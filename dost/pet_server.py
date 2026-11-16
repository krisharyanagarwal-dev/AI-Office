#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost pet. A local chat companion you can text or talk to.

Serves a small page on 127.0.0.1 with a pet that reacts to you. Text goes to
dost_respond. Voice uses the browser's built-in speech (mic in, voice out), so
no extra keys or audio tools are needed.

Run:  python3 pet_server.py            then open http://127.0.0.1:8787
Paper only. Localhost only.
"""
from __future__ import annotations

import json
import os
import sys
import threading
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
NODE_BIN = "/Users/aryanagarwal/.nvm/versions/node/v26.13.0/bin"
OPENCLAW = NODE_BIN + "/openclaw"
OPENCLAW_SESSION = "dost-pet"  # one continuous chat with OpenClaw


def openclaw_reply(text: str) -> str:
    """Send one message through the OpenClaw gateway and return the reply text."""
    import subprocess
    try:
        proc = subprocess.run(
            [OPENCLAW, "agent", "--session-id", OPENCLAW_SESSION, "--json", "-m", text],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "PATH": NODE_BIN + ":/usr/bin:/bin:/usr/local/bin"},
        )
    except subprocess.TimeoutExpired:
        return "OpenClaw took too long to answer. Try again."
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return "OpenClaw did not answer. Check that the gateway is running."
    if data.get("status") != "ok":
        return f"OpenClaw reported: {data.get('summary', 'an error')}"
    parts = (data.get("result") or {}).get("payloads") or []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
    return "\n\n".join(texts) or "OpenClaw replied with nothing."


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
        else:
            self._json(404, {"error": "not found"})

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
            self._json(502, {"error": f"could not transcribe: {result.get('error')}"})
            return
        self._json(200, {"text": (result.get("text") or "").strip()})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/listen":
            try:
                self._listen()
            except Exception as e:
                self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})
            return
        if self.path.split("?", 1)[0] != "/api/chat":
            self._json(404, {"error": "not found"})
            return
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
        try:
            if backend == "compare":
                ids = payload.get("models") if isinstance(payload.get("models"), list) else None
                self._json(200, {"answers": models.compare(text, ids)})
                return
            if ":" in backend:  # provider:model picked in the window
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
            self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})

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
