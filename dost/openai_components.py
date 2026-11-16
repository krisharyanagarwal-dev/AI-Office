#!/usr/bin/env python3
"""
THE CLAUDE COMPANY — OpenAI Components Integration

Uses OpenAI's API components (chat completions, Whisper STT, TTS) where an
OpenAI key is available, and falls back to OpenAI-compatible endpoints
(Groq, NVIDIA NIM, DeepInfra, Cloudflare) when it is not.

The dost uses these for the language/reasoning/voice layer, while our six
departments + verification gates remain the truth engine.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _read_env_file() -> dict:
    env = {}
    p = Path.home() / ".env"
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


_ENV = _read_env_file()


def get_key(name: str) -> Optional[str]:
    return os.environ.get(name) or _ENV.get(name) or None


OPENAI_API_KEY = get_key("OPENAI_API_KEY")
OPENAI_BASE_URL = get_key("OPENAI_BASE_URL") or "https://api.openai.com/v1"

# OpenAI-compatible fallback endpoints (already configured in this stack)
# Each entry: (name, chat/completions URL, API key, default model)
FALLBACK_ENDPOINTS = [
    ("groq", "https://api.groq.com/openai/v1/chat/completions", get_key("GROQ_API_KEY"), "openai/gpt-oss-20b"),
    ("nvidia", "https://integrate.api.nvidia.com/v1/chat/completions", get_key("NVIDIA_API_KEY"), "openai/gpt-oss-20b"),
    ("deepinfra", "https://api.deepinfra.com/v1/openai/chat/completions", get_key("DEEPINFRA_API_KEY"), "openai/gpt-oss-20b"),
    ("cloudflare", "https://api.cloudflare.com/client/v4/accounts/{}/ai/v1", get_key("CLOUDFLARE_API_KEY"), "@cf/openai/gpt-oss-120b"),
]


def chat_completion(messages: list[dict], model: str = "gpt-4o-mini",
                    temperature: float = 0.3, max_tokens: int = 1000) -> dict:
    """
    OpenAI chat completions component. Returns {"text": str, "provider": str, "model": str}.
    Tries OpenAI first, then OpenAI-compatible fallbacks with provider-appropriate models.
    """
    # Try OpenAI directly
    if OPENAI_API_KEY:
        try:
            result = _curl_chat(OPENAI_BASE_URL + "/chat/completions",
                                OPENAI_API_KEY, {"model": model, "messages": messages,
                                                 "temperature": temperature, "max_tokens": max_tokens})
            if result.get("ok"):
                return {"text": result["text"], "provider": "openai", "model": model}
        except Exception:
            pass  # fall through to fallbacks

    # Try OpenAI-compatible fallbacks with their native models
    for name, url, key, fallback_model in FALLBACK_ENDPOINTS:
        if not key:
            continue
        if name == "cloudflare" and "{" in url:
            continue
        try:
            payload = {"model": fallback_model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}
            result = _curl_chat(url, key, payload)
            if result.get("ok"):
                return {"text": result["text"], "provider": name, "model": fallback_model}
        except Exception:
            continue

    return {
        "text": "(No LLM provider available. Set OPENAI_API_KEY or GROQ_API_KEY/NVIDIA_API_KEY/DEEPINFRA_API_KEY.)",
        "provider": "none",
        "model": model,
    }


def _curl_chat(url: str, key: str, payload: dict) -> dict:
    """POST chat/completions via curl. Returns {ok, text} or {ok: False, error}."""
    tmp = Path(tempfile.mkstemp(suffix=".json")[1])
    tmp.write_text(json.dumps(payload))
    try:
        proc = subprocess.run(
            ["curl", "-s", "-X", "POST", url,
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "--data-binary", f"@{tmp}",
             "--max-time", "60"],
            capture_output=True, text=True, timeout=70,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": f"curl exit {proc.returncode}: {proc.stderr[:200]}"}
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"non-JSON response: {proc.stdout[:200]}"}

        # OpenAI / OpenAI-compatible format
        choices = data.get("choices")
        if choices and len(choices) > 0:
            msg = choices[0].get("message", {})
            text = msg.get("content", "")
            return {"ok": True, "text": text}

        # Cloudflare format: {result: {response: "..."}}
        result = data.get("result")
        if isinstance(result, dict) and result.get("response"):
            return {"ok": True, "text": result["response"]}

        return {"ok": False, "error": f"unexpected format: {proc.stdout[:300]}"}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 2. Whisper STT component (speech-to-text)
# ---------------------------------------------------------------------------

def speech_to_text(audio_path: str, model: str = "whisper-1") -> dict:
    """
    OpenAI Whisper STT component. Transcribes an audio file.
    Falls back: if no OpenAI key, returns a helpful error (no free Whisper
    equivalent in the fallback pool). User can paste text instead.
    """
    if not OPENAI_API_KEY:
        return {
            "ok": False,
            "error": "Whisper STT requires OPENAI_API_KEY. No free Whisper equivalent in fallback pool.",
            "text": "",
        }

    proc = subprocess.run(
        ["curl", "-s", "-X", "POST", OPENAI_BASE_URL + "/audio/transcriptions",
         "-H", f"Authorization: Bearer {OPENAI_API_KEY}",
         "-F", f"file=@{audio_path}",
         "-F", f"model={model}",
         "--max-time", "120"],
        capture_output=True, text=True, timeout=130,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": f"curl exit {proc.returncode}", "text": ""}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"non-JSON: {proc.stdout[:200]}", "text": ""}

    if data.get("text"):
        return {"ok": True, "text": data["text"], "provider": "openai-whisper"}
    return {"ok": False, "error": data.get("error", {}).get("message", "unknown error"), "text": ""}


# ---------------------------------------------------------------------------
# 3. TTS component (text-to-speech)
# ---------------------------------------------------------------------------

def text_to_speech(text: str, model: str = "tts-1", voice: str = "alloy",
                   output_path: str | None = None) -> dict:
    """
    OpenAI TTS component. Generates an MP3 from text.
    Falls back: if no OpenAI key, returns error (no free TTS in fallback pool).
    """
    if not OPENAI_API_KEY:
        return {
            "ok": False,
            "error": "TTS requires OPENAI_API_KEY. No free TTS equivalent in fallback pool.",
            "path": "",
        }

    if output_path is None:
        output_path = str(Path(tempfile.mkstemp(suffix=".mp3")[1]))

    proc = subprocess.run(
        ["curl", "-s", "-X", "POST", OPENAI_BASE_URL + "/audio/speech",
         "-H", f"Authorization: Bearer {OPENAI_API_KEY}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"model": model, "voice": voice, "input": text}),
         "--output", output_path,
         "--max-time", "120"],
        capture_output=True, text=True, timeout=130,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": f"curl exit {proc.returncode}", "path": ""}
    if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
        return {"ok": True, "path": output_path, "provider": "openai-tts"}
    return {"ok": False, "error": proc.stderr[:300] or proc.stdout[:300], "path": ""}


# ---------------------------------------------------------------------------
# 4. Dost reasoning layer — uses chat_completion to think before dispatching
# ---------------------------------------------------------------------------

def dost_reason(user_message: str, context: str = "") -> dict:
    """
    OpenAI reasoning component for the dost.
    Given a user message + context, decide:
      - which department to route to
      - whether to execute a research command directly
      - what plain-language response to give
    Returns a dict with routing decision + reasoning.
    """
    system = (
        "You are the reasoning layer of THE CLAUDE COMPANY's dost. "
        "Departments: research (NSE hypothesis/backtest/gate/holdout/calibrate/report), "
        "trading (paper backtests, forward sim, cost models), fleet (32 agents, paper-only, "
        "Tier C blocked), ops (P&L, provider health, dashboards), upgrade (self-upgrade), "
        "assistant (code, write, analyze, strategize). "
        "Research commands: report, register, gate, holdout, calibrate, all. "
        "Boundaries: paper-only, kill switch LOCKED, no live orders, cost-honest, "
        "no curve-fitting, Tier C human-only. "
        "Respond in JSON: {\"department\": str, \"command\": str|null, \"reasoning\": str, "
        "\"direct_response\": str|null}. If the user wants a research pipeline command run, "
        "set command to that command. Otherwise null."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Context: {context}\n\nUser: {user_message}"},
    ]
    result = chat_completion(messages, model="gpt-4o-mini", temperature=0.2, max_tokens=600)
    try:
        decision = json.loads(result["text"])
    except (json.JSONDecodeError, KeyError):
        # Fallback: route to assistant, no command
        decision = {
            "department": "assistant",
            "command": None,
            "reasoning": result["text"][:300],
            "direct_response": None,
        }
    decision["_provider"] = result.get("provider", "none")
    decision["_model"] = result.get("model", "unknown")
    return decision


# ---------------------------------------------------------------------------
# 5. Provider health check
# ---------------------------------------------------------------------------

def provider_health() -> dict:
    """Report which OpenAI/OpenAI-compatible components are available."""
    return {
        "openai_chat": bool(OPENAI_API_KEY),
        "openai_whisper": bool(OPENAI_API_KEY),
        "openai_tts": bool(OPENAI_API_KEY),
        "fallbacks_available": [
            name for name, _, key, _ in FALLBACK_ENDPOINTS if key
        ],
        "base_url": OPENAI_BASE_URL,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        print(json.dumps(provider_health(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "chat":
        msg = sys.argv[2] if len(sys.argv) > 2 == 2 else "hello"
        r = dost_reason(msg)
        print(json.dumps(r, indent=2))
    else:
        print("Usage: python openai_components.py health | chat \"message\"")