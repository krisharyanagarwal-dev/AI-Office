#!/usr/bin/env python3
"""
Dost on the Mac mini - a self-contained pet server for the 24/7 box.

Serves the same pet page as the laptop (pet_page.html next to this file) on
127.0.0.1:8787, but its brain is the mini's own model services:
  * local  - the MLX Qwen 9B behind the Ollama shim on :11434
  * NVIDIA - free NIM models through the mini's key manager on :4200
No API keys are stored here: the key manager holds them. Stdlib only, so it
runs on the mini's /usr/bin/python3 (3.9). Localhost only. Paper-safe: it only
sends prompts and returns text.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("DOST_PORT", "8787"))
PAGE = Path(__file__).resolve().parent / "pet_page.html"
LOCAL = os.environ.get("DOST_LOCAL_URL", "http://127.0.0.1:11434/v1/chat/completions")
NIM = os.environ.get("DOST_NIM_URL", "http://127.0.0.1:4200/v1/chat/completions")
NAME = os.environ.get("DOST_USER_NAME", "Aryan")
MAX_TEXT = 2000

# id -> (label, provider label, url, model)
MODELS = {
    "local:qwen2.5:7b": ("Local Qwen 9B (MLX)", "Mini", LOCAL, "qwen2.5:7b"),
    "nim:openai/gpt-oss-20b": ("GPT-OSS 20B", "NVIDIA", NIM, "openai/gpt-oss-20b"),
    "nim:mistralai/mistral-large-4-1t-a52b": ("Mistral Large 4", "NVIDIA", NIM, "mistralai/mistral-large-4-1t-a52b"),
    "nim:nvidia/nemotron-3-ultra-550b-a55b": ("Nemotron 3 Ultra", "NVIDIA", NIM, "nvidia/nemotron-3-ultra-550b-a55b"),
    "nim:nvidia/nemotron-3.5-lightning-30b-a3b": ("Nemotron 3.5 Lightning", "NVIDIA", NIM, "nvidia/nemotron-3.5-lightning-30b-a3b"),
}
DOST_MODEL = os.environ.get("DOST_MODEL", "nim:nvidia/nemotron-3.5-lightning-30b-a3b")  # ~1 s replies
DOST_FALLBACK = "local:qwen2.5:7b"

PERSONA = f"""You are Dost, a close, warm friend of {NAME}, running on their Mac mini.
Keep replies short (2-4 sentences) unless asked for detail. Match their language and energy.
No bullet lists or sign-offs unless asked. Be honest; say "I don't know" when you don't.
Facts about yourself (answer questions about yourself only from these):
- You are the Mac mini copy of Dost. Your brain is {{model}}.
- You can chat. You cannot see the laptop's research data, run research commands,
  audit systems, place trades, edit files, or control services.
- The laptop has the full Dost (research, audit, OpenClaw). On the mini, the
  "Laptop Dost" page at http://127.0.0.1:18787 reaches it while the laptop is on."""


def call(model_id: str, messages: list, max_tokens: int = 700, timeout: int = 120) -> dict:
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
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        return {"id": model_id, "label": label, "reply": text or "(empty answer)",
                "ms": int((time.time() - start) * 1000), "error": None}
    except Exception as e:  # network, HTTP, JSON
        msg = e.read().decode("utf-8", "replace")[:160] if isinstance(e, urllib.error.HTTPError) else str(e)[:160]
        return {"id": model_id, "label": label, "reply": "", "ms": int((time.time() - start) * 1000),
                "error": f"{type(e).__name__}: {msg}"}


def clean_history(history) -> list:
    out = []
    for h in (history or [])[-12:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            out.append({"role": h["role"], "content": str(h["content"])[:4000]})
    return out


def dost_reply(text: str, history=None) -> str:
    for mid in (DOST_MODEL, DOST_FALLBACK):
        where = ("the local Qwen 9B model running on the mini itself" if mid.startswith("local:")
                 else f"{MODELS[mid][0]}, which runs in NVIDIA's cloud; the mini only sends it your messages")
        system = PERSONA.format(model=where)
        ans = call(mid, [{"role": "system", "content": system}] + clean_history(history)
                   + [{"role": "user", "content": text}])
        if not ans["error"]:
            return ans["reply"]
    return "I can't reach any model right now. The mini's model services may be restarting; try again in a minute."


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/greet":
            h = datetime.now().hour
            part = "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"
            self._json(200, {"reply": f"{part}, {NAME}! Dost on the mini here. What's up?"})
        elif path == "/api/models":
            self._json(200, {"models": [{"id": k, "label": v[0], "provider": v[1]} for k, v in MODELS.items()]})
        elif path == "/health":
            self._json(200, {"status": "ok", "brain": DOST_MODEL})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/listen":
            self._json(501, {"error": "voice is not set up on the mini yet; type instead"})
            return
        if path != "/api/chat":
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
                ids = [m for m in (payload.get("models") or MODELS.keys()) if m in MODELS]
                msgs = [{"role": "user", "content": text}]
                with ThreadPoolExecutor(max_workers=len(ids) or 1) as pool:
                    answers = list(pool.map(lambda m: call(m, msgs), ids))
                self._json(200, {"answers": answers})
            elif backend in MODELS:
                ans = call(backend, clean_history(payload.get("history")) + [{"role": "user", "content": text}])
                if ans["error"]:
                    self._json(502, {"error": f"{ans['label']}: {ans['error']}"})
                else:
                    self._json(200, {"reply": ans["reply"], "label": ans["label"], "ms": ans["ms"]})
            elif backend == "openclaw":
                self._json(200, {"reply": "OpenClaw lives on the laptop. Open Laptop Dost on the mini to use it."})
            else:
                self._json(200, {"reply": dost_reply(text, payload.get("history"))})
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {str(e)[:160]}"})

    def log_message(self, format, *args):  # noqa: A002
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Dost (mini) on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
