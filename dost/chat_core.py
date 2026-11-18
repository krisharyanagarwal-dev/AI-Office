#!/usr/bin/env python3
"""
Shared Dost chat core: one HTTP surface for both the laptop and mini servers.

Stdlib only, Python 3.9-safe (no match statement, no runtime X | Y annotations).

Subclass Handler and override:
  PAGE          - path to pet_page.html (served at /)
  MODELS        - dict {id: (label, provider)} for /api/models
  NAME          - user name for greetings
  answer()      - blocking reply: (text, history, backend) -> str
  stream_answer() - SSE chunks: (text, history, backend) -> Iterator[str] | None
                  Return None to fall back to chunking answer().
  voice_status() -> bool
  greet() -> str

The base class handles all endpoints:
  /, /api/greet, /api/models, /api/health, /api/history, /api/clear,
  /api/branch, /api/voice-status, /api/chat, /api/chat/stream
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Optional


def chunk_text(text: str, max_chunk: int = 120) -> list:
    """Split text into sentence-sized chunks for SSE streaming."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list = []
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


class ChatStore:
    """Per-session JSON message store."""
    def __init__(self, directory):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, session_id="default"):
        return self.directory / (session_id + ".json")

    def load(self, session_id="default"):
        try:
            data = json.loads(self.path(session_id).read_text())
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save(self, messages, session_id="default"):
        with self._lock:
            self.path(session_id).write_text(json.dumps(messages, indent=2))

    def branches(self, session_id="default"):
        messages = self.load(session_id)
        branches = {}
        for m in messages:
            branches.setdefault(m.get("branch_id", "main"), []).append(m)
        return branches


class Handler(BaseHTTPRequestHandler):
    """Base chat handler. Subclass and override PAGE, MODELS, NAME, answer, etc."""

    PAGE = Path("pet_page.html")
    MODELS = {}
    NAME = "there"
    STORE = None  # set by DostChatServer before use

    # ---- overridable hooks ------------------------------------------------
    def answer(self, text, history, backend):
        raise NotImplementedError

    def stream_answer(self, text, history, backend):
        """Return an iterator of text chunks for SSE, or None if unsupported."""
        return None

    def voice_status(self):
        return False

    def greet(self):
        return "Hi, " + self.NAME + "!"

    def compare_models(self, text, history):
        """Default compare: run each model sequentially."""
        answers = []
        for mid, info in self.MODELS.items():
            try:
                reply = self.answer(text, history or [], mid)
                label = info[0] if isinstance(info, tuple) else str(info)
                answers.append({"label": label, "reply": reply, "error": None})
            except Exception:  # noqa: BLE001
                label = info[0] if isinstance(info, tuple) else str(info)
                answers.append({"label": label, "reply": "", "error": "provider unreachable"})
        return answers

    # ---- HTTP plumbing ----------------------------------------------------
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _get_query(self, key, default=""):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        return qs.get(key, [default])[0]

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(min(length, 65536)) or b"{}")

    def _persist(self, text, reply, session_id, branch_id):
        """Save a user+assistant turn to the session store."""
        store = self.__class__.STORE
        if store is None or not reply:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        messages = store.load(session_id)
        messages.append({"id": str(uuid.uuid4())[:8], "role": "user",
                         "content": text, "ts": ts, "branch_id": branch_id})
        messages.append({"id": str(uuid.uuid4())[:8], "role": "assistant",
                         "content": str(reply), "ts": ts, "branch_id": branch_id})
        store.save(messages, session_id)

    def log_message(self, format, *args):  # noqa: A002
        return

    # ---- GET --------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        store = self.__class__.STORE

        if path in ("/", "/index.html"):
            try:
                self._send(200, self.PAGE.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self._json(404, {"error": "page not found"})
        elif path == "/api/greet":
            self._json(200, {"reply": self.greet()})
        elif path == "/api/models":
            models = []
            for k, v in self.MODELS.items():
                if isinstance(v, tuple):
                    models.append({"id": k, "label": v[0], "provider": v[1] if len(v) > 1 else ""})
                else:
                    models.append({"id": k, "label": str(v), "provider": ""})
            self._json(200, {"models": models})
        elif path == "/api/health":
            self._json(200, {"status": "ok"})
        elif path == "/api/history":
            if store is None:
                self._json(500, {"error": "store not configured"})
                return
            self._json(200, {"messages": store.load(self._get_query("session_id", "default"))})
        elif path == "/api/voice-status":
            self._json(200, {"stt": self.voice_status()})
        else:
            self._json(404, {"error": "not found"})

    # ---- POST -------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        store = self.__class__.STORE

        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "bad request"})
            return

        text = str(payload.get("text", "")).strip()[:2000]
        session_id = str(payload.get("session_id", "default"))
        branch_id = str(payload.get("branch_id", "main"))

        if path == "/api/clear":
            if store is None:
                self._json(500, {"error": "store not configured"})
                return
            store.save([], session_id)
            self._json(200, {"ok": True, "session_id": session_id})
            return

        if path == "/api/branch":
            if store is None:
                self._json(500, {"error": "store not configured"})
                return
            from_msg = str(payload.get("from_message_id", ""))
            new_branch = str(payload.get("new_branch", "branch-" + uuid.uuid4().hex[:6]))
            messages = store.load(session_id)
            new_messages = []
            found = False
            for m in messages:
                new_messages.append(dict(m))
                if m.get("id") == from_msg:
                    found = True
                    break
            if not found and from_msg:
                self._json(400, {"error": "Reference message not found in branch."})
                return
            for m in new_messages:
                m["branch_id"] = new_branch
            all_messages = store.load(session_id)
            all_messages.extend(new_messages)
            store.save(all_messages, session_id)
            self._json(200, {"ok": True, "new_branch": new_branch, "messages": new_messages})
            return

        if path not in ("/api/chat", "/api/chat/stream"):
            self._json(404, {"error": "not found"})
            return

        if not text:
            self._json(400, {"error": "empty message"})
            return

        backend = str(payload.get("backend", "dost"))
        history = payload.get("history")

        # ---- non-streaming ------------------------------------------------
        if path == "/api/chat":
            try:
                if backend == "compare":
                    self._json(200, {"answers": self.compare_models(text, history)})
                    return
                reply = self.answer(text, history or [], backend)
                self._persist(text, reply, session_id, branch_id)
                self._json(200, {"reply": str(reply)})
            except Exception:  # noqa: BLE001
                self._json(500, {"error": "Dost couldn't answer right now. Try again."})
            return

        # ---- streaming SSE ------------------------------------------------
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def send_event(event_type, data):
            msg = "event: " + event_type + "\ndata: " + json.dumps(data) + "\n\n"
            self.wfile.write(msg.encode())
            self.wfile.flush()

        try:
            send_event("start", {"session_id": session_id, "branch_id": branch_id})
            reply = ""
            if backend == "compare":
                answers = self.compare_models(text, history)
                send_event("content", {"type": "compare", "answers": answers})
            else:
                stream = self.stream_answer(text, history or [], backend)
                if stream is None:
                    full = self.answer(text, history or [], backend)
                    stream = chunk_text(full)
                    reply = ""
                for chunk in stream:
                    reply = reply + chunk
                    send_event("content", {"type": "text", "text": chunk})
                    time.sleep(0.03)
            if store is not None:
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                messages = store.load(session_id)
                messages.append({"id": str(uuid.uuid4())[:8], "role": "user",
                                 "content": text, "ts": ts, "branch_id": branch_id})
                if reply:
                    messages.append({"id": str(uuid.uuid4())[:8], "role": "assistant",
                                     "content": reply, "ts": ts, "branch_id": branch_id})
                store.save(messages, session_id)
            send_event("done", {"message_id": str(uuid.uuid4())[:8], "reply": reply})
        except BrokenPipeError:
            pass
        except Exception:  # noqa: BLE001
            try:
                send_event("error", {"error": "Dost couldn't answer right now. Try again."})
            except BrokenPipeError:
                pass
        finally:
            try:
                self.wfile.flush()
            except BrokenPipeError:
                pass


class DostChatServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with Handler.STORE wired."""

    def __init__(self, server_address, handler_cls, store):
        handler_cls.STORE = store
        super(DostChatServer, self).__init__(server_address, handler_cls)
