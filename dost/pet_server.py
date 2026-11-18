#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost pet server. A local chat companion you can text or talk to.

Serves a small page on 127.0.0.1:8787 with:
  - SSE streaming chat (/api/chat/stream)
  - Server-side message persistence (~/.openclaw/dost_chat/)
  - Conversation branching (/api/branch)
  - Clear conversation (/api/clear)
  - Voice transcription (/api/listen) via Groq Whisper or OpenAI Whisper

Run:  python3 pet_server.py   then open http://127.0.0.1:8787
Paper only. Localhost only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dost import MEMORY, companion_respond  # noqa: E402
from openai_components import speech_to_text  # noqa: E402
import models  # noqa: E402

MAX_AUDIO = 15 * 1024 * 1024  # 15 MB voice clip limit
AUDIO_EXT = {
    "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav",
}

HOST = "127.0.0.1"
PORT = 8787
PAGE = Path(__file__).resolve().parent / "pet_page.html"
MODEL_LOCK = threading.Lock()  # one model call at a time
MAX_TEXT = 2000
CHUNK_DELAY = 0.03  # seconds between streamed chunks

# ---- Server-side chat persistence ------------------------------------------
CHAT_DIR = Path.home() / ".openclaw" / "dost_chat"
CHAT_DIR.mkdir(parents=True, exist_ok=True)


def _chat_path(session_id: str = "default") -> Path:
    return CHAT_DIR / f"{session_id}.json"


def _load_messages(session_id: str = "default") -> list:
    try:
        data = json.loads(_chat_path(session_id).read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_messages(messages: list, session_id: str = "default") -> None:
    _chat_path(session_id).write_text(json.dumps(messages, indent=2))


def _chunk_text(text: str, max_chunk: int = 120) -> list:
    """Break text into sentence-sized chunks for SSE streaming."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= max_chunk:
            current = (current + " " + sentence).strip() if current else sentence
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks or [text]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    # ---- GET ----------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/models":
            try:
                self._json(200, {"models": models.list_models()})
            except Exception as e:
                self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})
        elif path == "/api/greet":
            try:
                from datetime import datetime
                hour = datetime.now().hour
                part = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
                name = MEMORY.profile.get("name", "there")
                self._json(200, {"reply": f"{part}, {name}! Good to see you. What's on your mind?"})
            except Exception as e:  # never crash the page
                self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})
        elif path == "/api/history":
            session_id = self._get_query("session_id", "default")
            try:
                messages = _load_messages(session_id)
                self._json(200, {"messages": messages})
            except Exception as e:
                self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})
        elif path == "/api/voice-status":
            from openai_components import get_key
            has_stt = bool(get_key("GROQ_API_KEY") or get_key("OPENAI_API_KEY"))
            self._json(200, {"stt": has_stt})
        elif path == "/api/branches":
            session_id = self._get_query("session_id", "default")
            try:
                messages = _load_messages(session_id)
                branches = {}
                for m in messages:
                    bid = m.get("branch_id", "main")
                    branches.setdefault(bid, []).append(m)
                self._json(200, {"branches": branches})
            except Exception as e:
                self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})
        else:
            self._json(404, {"error": "not found"})

    def _get_query(self, key: str, default: str = "") -> str:
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        return qs.get(key, [default])[0]

    # ---- Voice --------------------------------------------------------------
    def _listen(self) -> None:
        """Receive a recorded voice clip from the page and return its transcript."""
        import tempfile
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_AUDIO:
            self._json(400, {"error": "audio missing or too large"})
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = AUDIO_EXT.get(ctype, ".webm")
        audio = self.rfile.read(length)
        fd, path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
            result = speech_to_text(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if not result.get("ok"):
            err = result.get("error", "unknown error")
            # Friendly, user-facing error — never raw exception text
            if "No STT provider" in err:
                self._json(502, {"error": "Voice transcription is not set up. Add GROQ_API_KEY or OPENAI_API_KEY to ~/.env, or use text instead."})
            else:
                self._json(502, {"error": f"Could not transcribe: {err}"})
            return
        self._json(200, {"text": (result.get("text") or "").strip()})

    # ---- POST ---------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/listen":
            try:
                self._listen()
            except Exception as e:
                self._json(500, {"error": "Voice transcription failed. Try again."})
            return
        if path == "/api/clear":
            session_id = self._get_json_field("session_id", "default")
            try:
                _save_messages([], session_id)
                self._json(200, {"ok": True, "session_id": session_id})
            except Exception as e:
                self._json(500, {"error": "Could not clear conversation. Try again."})
            return
        if path == "/api/branch":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "bad request"})
                return
            session_id = str(payload.get("session_id", "default"))
            from_branch = str(payload.get("from_branch", "main"))
            new_branch = str(payload.get("new_branch", f"branch-{uuid.uuid4().hex[:6]}"))
            from_message_id = str(payload.get("from_message_id", ""))
            try:
                messages = _load_messages(session_id)
                # Copy messages up to and including from_message_id into new branch
                new_messages = []
                found = False
                for m in messages:
                    new_messages.append(dict(m))
                    if m.get("id") == from_message_id:
                        found = True
                        break
                if not found and from_message_id:
                    self._json(400, {"error": "Reference message not found in branch."})
                    return
                # Update branch_id on copied messages
                for m in new_messages:
                    m["branch_id"] = new_branch
                # Append to existing messages (they carry their branch_id)
                all_messages = _load_messages(session_id)
                all_messages.extend(new_messages)
                _save_messages(all_messages, session_id)
                self._json(200, {"ok": True, "new_branch": new_branch, "messages": new_messages})
            except Exception as e:
                self._json(500, {"error": "Could not create branch. Try again."})
            return
        if path != "/api/chat" and path != "/api/chat/stream":
            self._json(404, {"error": "not found"})
            return

        # ---- Read request body ---------------------------------------------
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            text = str(payload.get("text", "")).strip()[:MAX_TEXT]
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "bad request"})
            return
        if not text:
            self._json(400, {"error": "empty message"})
            return

        backend = str(payload.get("backend", "dost"))
        session_id = str(payload.get("session_id", "default"))
        branch_id = str(payload.get("branch_id", "main"))

        # ---- Non-streaming /api/chat ---------------------------------------
        if path == "/api/chat":
            try:
                if backend == "compare":
                    self._json(200, {"answers": models.compare(text)})
                    return
                if ":" in backend:
                    ans = models.ask_model(backend, text, payload.get("history"))
                    if ans["error"]:
                        self._json(502, {"error": f"{ans['label']}: {ans['error']}"})
                    else:
                        self._json(200, {"reply": ans["reply"], "label": ans["label"], "ms": ans["ms"]})
                    return
                if backend == "openclaw":
                    reply = openclaw_reply(text)
                else:
                    with MODEL_LOCK:
                        reply = companion_respond(text)
                self._json(200, {"reply": str(reply)})
            except Exception as e:
                self._json(500, {"error": "Dost couldn't answer right now. Try again."})
            return

        # ---- Streaming /api/chat/stream (SSE) ------------------------------
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def send_event(event_type: str, data: dict) -> None:
            msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(msg.encode())
            self.wfile.flush()

        try:
            send_event("start", {"session_id": session_id, "branch_id": branch_id})

            reply = ""
            if backend == "compare":
                answers = models.compare(text)
                send_event("content", {"type": "compare", "answers": answers})
            elif ":" in backend:
                ans = models.ask_model(backend, text, payload.get("history"))
                if ans["error"]:
                    send_event("error", {"error": f"{ans['label']}: {ans['error']}"})
                else:
                    reply = ans["reply"]
                    for chunk in _chunk_text(reply):
                        send_event("content", {"type": "model", "label": ans["label"], "text": chunk, "ms": ans["ms"]})
                        time.sleep(CHUNK_DELAY)
            elif backend == "openclaw":
                reply = openclaw_reply(text)
                for chunk in _chunk_text(reply):
                    send_event("content", {"type": "text", "text": chunk})
                    time.sleep(CHUNK_DELAY)
            else:
                with MODEL_LOCK:
                    reply = companion_respond(text)
                for chunk in _chunk_text(reply):
                    send_event("content", {"type": "text", "text": chunk})
                    time.sleep(CHUNK_DELAY)

            # Persist to server-side history
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            messages = _load_messages(session_id)
            messages.append({"id": str(uuid.uuid4())[:8], "role": "user", "content": text, "ts": ts, "branch_id": branch_id})
            if reply:
                messages.append({"id": str(uuid.uuid4())[:8], "role": "assistant", "content": reply, "ts": ts, "branch_id": branch_id})
            _save_messages(messages, session_id)

            send_event("done", {"message_id": str(uuid.uuid4())[:8], "reply": reply})
        except BrokenPipeError:
            pass  # Client disconnected
        except Exception as e:
            try:
                send_event("error", {"error": "Dost couldn't answer right now. Try again."})
            except BrokenPipeError:
                pass
        finally:
            try:
                self.wfile.flush()
            except BrokenPipeError:
                pass

    def _get_json_field(self, key: str, default: str) -> str:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            return str(payload.get(key, default))
        except Exception:
            return default

    def log_message(self, format, *args):  # noqa: A002
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Dost pet running at http://{HOST}:{PORT}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
