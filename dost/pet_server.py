#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — Dost pet server. A local chat companion you can text or talk to.

Built on the shared chat_core.Handler. Serves a small page on 127.0.0.1:8787 with:
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
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chat_core import Handler, ChatStore, DostChatServer, chunk_text  # noqa: E402
from dost import MEMORY, companion_respond, dost_greeting  # noqa: E402
from openai_components import speech_to_text, get_key  # noqa: E402
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


def openclaw_reply(text: str) -> str:
    """Placeholder for the openclaw backend — not wired up."""
    return "(openclaw backend not available — try a different model.)"


class PetHandler(Handler):
    PAGE = PAGE
    NAME = MEMORY.profile.get("name", "there")
    MODELS = {}  # populated dynamically via list_models()

    # ---- voice -------------------------------------------------------------
    def voice_status(self):
        return bool(get_key("GROQ_API_KEY") or get_key("OPENAI_API_KEY"))

    def greet(self):
        return dost_greeting()

    def listen(self):
        """Receive audio clip and transcribe via STT."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_AUDIO:
            return {"ok": False, "error": "audio missing or too large"}
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
        return result

    # ---- models -------------------------------------------------------------
    def list_models(self):
        return models.list_models()

    def compare_models(self, text, history):
        return models.compare(text)

    # ---- answers ------------------------------------------------------------
    def answer(self, text, history, backend):
        if ":" in backend:
            ans = models.ask_model(backend, text, history)
            if ans["error"]:
                return f"{ans['label']}: {ans['error']}"
            return ans["reply"]
        if backend == "openclaw":
            return openclaw_reply(text)
        # default: dost companion
        with MODEL_LOCK:
            return companion_respond(text)

    def stream_answer(self, text, history, backend):
        """Yield SSE chunks. Each chunk is str or dict {type, text, label, ms}."""
        if ":" in backend:
            ans = models.ask_model(backend, text, history)
            if ans["error"]:
                yield {"type": "error", "error": f"{ans['label']}: {ans['error']}"}
                return
            reply = ans["reply"]
            label = ans["label"]
            ms = ans.get("ms", 0)
        elif backend == "openclaw":
            reply = openclaw_reply(text)
            label = None
            ms = 0
        else:
            with MODEL_LOCK:
                reply = companion_respond(text)
            label = None
            ms = 0

        for chunk in chunk_text(reply):
            if label:
                yield {"type": "model", "text": chunk, "label": label, "ms": ms}
            else:
                yield {"type": "text", "text": chunk}


def main() -> None:
    store = ChatStore(CHAT_DIR)
    server = DostChatServer((HOST, PORT), PetHandler, store)
    print(f"Dost pet running at http://{HOST}:{PORT}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
