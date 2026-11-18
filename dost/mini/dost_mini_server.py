#!/usr/bin/env python3
"""
Dost on the Mac mini — built on the shared chat_core.

Serves pet_page.html on 127.0.0.1:8787 with the full chat surface:
  /api/chat (blocking), /api/chat/stream (SSE), /api/history, /api/clear,
  /api/branch, /api/voice-status, /api/greet, /api/models, /api/health.

Brain: local MLX Qwen 9B (:11434) with NVIDIA NIM fallback (:4200).
No API keys stored here — the mini's key manager holds them.
Stdlib only, runs on /usr/bin/python3 (3.9). Localhost only. Paper-safe.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))           # mini: chat_core alongside server
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))    # laptop dev: chat_core in parent dir
from chat_core import Handler, ChatStore, DostChatServer, chunk_text  # noqa: E402

HOST = "127.0.0.1"
PORT = int(os.environ.get("DOST_PORT", "8787"))
NAME = os.environ.get("DOST_USER_NAME", "Aryan")

# Page: shared laptop page, copied to this directory at deploy time.
PAGE = Path(__file__).resolve().parent / "pet_page.html"

LOCAL = os.environ.get("DOST_LOCAL_URL", "http://127.0.0.1:11434/v1/chat/completions")
NIM = os.environ.get("DOST_NIM_URL", "http://127.0.0.1:4200/v1/chat/completions")

MAX_TEXT = 2000

# id -> (label, provider label, url, model)
MODELS = {
    "local:qwen2.5:7b": ("Local Qwen 9B (MLX)", "Mini", LOCAL, "qwen2.5:7b"),
    "nim:mistralai/mistral-large-4-1t-a52b": ("Mistral Large 4", "NVIDIA", NIM, "mistralai/mistral-large-4-1t-a52b"),
    "nim:nvidia/nemotron-3-ultra-550b-a55b": ("Nemotron 3 Ultra", "NVIDIA", NIM, "nvidia/nemotron-3-ultra-550b-a55b"),
    "nim:nvidia/nemotron-3.5-lightning-30b-a3b": ("Nemotron 3.5 Lightning", "NVIDIA", NIM, "nvidia/nemotron-3.5-lightning-30b-a3b"),
}
DOST_MODEL = os.environ.get("DOST_MODEL", "nim:nvidia/nemotron-3.5-lightning-30b-a3b")
DOST_FALLBACK = "local:qwen2.5:7b"

CHAT_DIR = Path.home() / ".dost_mini" / "chat"


def call(model_id, messages, max_tokens=700, timeout=120):
    """Call one model via its OpenAI-compatible endpoint."""
    label, _, url, model = MODELS[model_id]
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": 0.5, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer dost-mini"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        text = (data["choices"][0]["message"].get("content") or "").strip()
        if "```" in text:
            text = text.split("```", 1)[1].strip()
        return {"id": model_id, "label": label, "reply": text or "(empty answer)",
                "ms": int((time.time() - start) * 1000), "error": None}
    except Exception as e:  # noqa: BLE001
        msg = e.read().decode("utf-8", "replace")[:160] if isinstance(e, urllib.error.HTTPError) else str(e)[:160]
        return {"id": model_id, "label": label, "reply": "", "ms": int((time.time() - start) * 1000),
                "error": "{0}: {1}".format(type(e).__name__, msg)}


def clean_history(history):
    out = []
    for h in (history or [])[-12:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            out.append({"role": h["role"], "content": str(h["content"])[:4000]})
    return out


def dost_reply(text, history=None):
    """Try primary model, then fallback. Blocking."""
    for mid in (DOST_MODEL, DOST_FALLBACK):
        where = ("the local Qwen 9B model running on the mini itself"
                 if mid.startswith("local:")
                 else "{0}, which runs in NVIDIA's cloud".format(MODELS[mid][0]))
        system = PERSONA.format(NAME=NAME, model=where)
        ans = call(mid, [{"role": "system", "content": system}]
                   + clean_history(history) + [{"role": "user", "content": text}])
        if not ans["error"] and ans["reply"]:
            return ans["reply"]
    return "I can't reach any model right now. The mini's model services may be restarting; try again in a minute."


PERSONA = """You are Dost, a close, warm friend of {NAME}, running on their Mac mini.
Keep replies short (2-4 sentences) unless asked for detail. Match their language and energy.
No bullet lists or sign-offs unless asked. Be honest; say "I don't know" when you don't.
Remember what the person has told you across this conversation and refer back to it naturally.
If you're not sure about something, say so rather than guessing.

Facts about yourself (answer questions about yourself only from these):
- You are the Mac mini copy of Dost. Your brain is {model}.
- You can chat. You cannot see the laptop's research data, run research commands,
  audit systems, place trades, edit files, or control services.
- You remember past conversations in this chat window.
- The laptop has the full Dost (research, audit, OpenClaw). On the mini, the
  "Laptop Dost" page at http://127.0.0.1:18787 reaches it while the laptop is on.
- You are paper-only: nothing on this mini places live orders."""


class DostMiniHandler(Handler):
    PAGE = PAGE
    MODELS = MODELS
    NAME = NAME

    def greet(self):
        h = datetime.now().hour
        part = "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"
        return "{0}, {1}! Dost on the mini here. What's up?".format(part, NAME)

    def voice_status(self):
        return False

    def answer(self, text, history, backend):
        if backend not in MODELS:
            backend = DOST_MODEL
        if backend == DOST_MODEL:
            # dost_reply tries primary then fallback
            return dost_reply(text, history)
        ans = call(backend, [{"role": "system", "content": PERSONA.format(NAME=NAME, model="the mini's model")}]
                   + clean_history(history) + [{"role": "user", "content": text}])
        if ans["error"]:
            # try fallback
            ans = call(DOST_FALLBACK, [{"role": "system", "content": PERSONA.format(model="the mini's model")}]
                     + clean_history(history) + [{"role": "user", "content": text}])
            if ans["error"]:
                return "I can't reach any model right now. Try again in a minute."
        return ans["reply"]

    def stream_answer(self, text, history, backend):
        # No true token streaming on the mini (blocking model calls).
        # Return None so the base class chunks the blocking answer into SSE chunks.
        return None


def main():
    store = ChatStore(CHAT_DIR)
    server = DostChatServer((HOST, PORT), DostMiniHandler, store)
    print("Dost (mini) on http://{0}:{1}".format(HOST, PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
