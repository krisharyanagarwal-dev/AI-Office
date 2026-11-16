"""
Dost model hub: talk to one chosen model, or ask several at once and compare.

Every model here is reached through an OpenAI-compatible chat endpoint using the
keys already in ~/.env (Groq, NVIDIA, DeepInfra), plus local Ollama when it is
running. Paper-safe: this only sends prompts and returns text.
"""
from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from openai_components import FALLBACK_ENDPOINTS, _curl_chat

# Chat models checked against each provider's /models list on 2026-11-17.
CURATED = {
    "groq": [
        ("openai/gpt-oss-120b", "GPT-OSS 120B"),
        ("openai/gpt-oss-20b", "GPT-OSS 20B"),
        ("qwen/qwen3.8-27b", "Qwen 3.8 27B"),
    ],
    "nvidia": [
        ("mistralai/mistral-large-4-1t-a52b", "Mistral Large 4"),
        ("nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra"),
        ("nvidia/nemotron-3.5-lightning-30b-a3b", "Nemotron 3.5 Lightning"),
    ],
    # DeepInfra left out: the account has no balance ("You need positive balance").
    # DeepSeek V4.1 Flash on NVIDIA left out: timed out after 60 s twice.
}
PROVIDER_LABEL = {"groq": "Groq", "nvidia": "NVIDIA", "deepinfra": "DeepInfra", "ollama": "Local"}
OLLAMA = "http://127.0.0.1:11434"
SYSTEM = ("You are Dost, a warm and honest friend. Keep answers short and clear unless "
          "asked for detail. If you do not know something, say so.")


def _endpoints() -> dict:
    return {name: (url, key) for name, url, key, _ in FALLBACK_ENDPOINTS
            if key and "{" not in url}


def _ollama_models() -> list:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", []) if "embed" not in m["name"]]
    except Exception:
        return []


def list_models() -> list:
    """Models you can pick right now. id format: provider:model."""
    out = []
    eps = _endpoints()
    for provider, models in CURATED.items():
        if provider not in eps:
            continue
        for model, label in models:
            out.append({"id": f"{provider}:{model}", "label": label,
                        "provider": PROVIDER_LABEL[provider]})
    for m in _ollama_models():
        out.append({"id": f"ollama:{m}", "label": m, "provider": "Local"})
    return out


def _clean_history(history) -> list:
    msgs = []
    for h in (history or [])[-12:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:4000]})
    return msgs


def ask_model(model_id: str, text: str, history=None) -> dict:
    """Send one prompt to one model. Returns {id, label, reply, ms, error}."""
    start = time.time()
    provider, _, model = model_id.partition(":")
    label = next((m["label"] for m in list_models() if m["id"] == model_id), model)
    messages = [{"role": "system", "content": SYSTEM}] + _clean_history(history) + \
               [{"role": "user", "content": text}]
    payload = {"model": model, "messages": messages, "temperature": 0.5, "max_tokens": 900}
    if provider == "ollama":
        url, key = OLLAMA + "/v1/chat/completions", "ollama"
    else:
        ep = _endpoints().get(provider)
        if not ep:
            return {"id": model_id, "label": label, "reply": "", "ms": 0,
                    "error": f"no key for {provider}"}
        url, key = ep
    try:
        result = _curl_chat(url, key, payload)
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    ms = int((time.time() - start) * 1000)
    if not result.get("ok"):
        return {"id": model_id, "label": label, "reply": "", "ms": ms,
                "error": str(result.get("error", "failed"))[:200]}
    reply = (result.get("text") or "").strip()
    if "</think>" in reply:  # drop visible reasoning blocks
        reply = reply.split("</think>", 1)[1].strip()
    return {"id": model_id, "label": label, "reply": reply or "(empty answer)", "ms": ms, "error": None}


def compare(text: str, model_ids=None, limit: int = 6) -> list:
    """Ask several models the same prompt at once. Default: every available model."""
    available = [m["id"] for m in list_models()]
    if not model_ids:
        model_ids = list(available)
    model_ids = [m for m in model_ids if m in available][:limit]
    with ThreadPoolExecutor(max_workers=max(1, len(model_ids))) as pool:
        return list(pool.map(lambda mid: ask_model(mid, text), model_ids))
