"""
Provider Client - Direct API calls to free providers.
Bypasses OpenCode's full agent framework (~53K input tokens → ~3K).
Each provider maps to its native OpenAI-compatible endpoint.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import threading

_ENV_FILE = Path.home() / ".env"
_env_file_cache: Dict[str, str] = {}
_env_file_mtime = None


def _key_from_env_file(name: str) -> str:
    """Read one variable from ~/.env. The last non-empty assignment wins, so an
    empty placeholder line after a real key cannot blank it out."""
    global _env_file_mtime
    try:
        mtime = _ENV_FILE.stat().st_mtime
    except OSError:
        return ""
    if mtime != _env_file_mtime:
        parsed = {}
        try:
            for line in _ENV_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                if value:
                    parsed[key.strip()] = value
        except OSError:
            return ""
        _env_file_cache.clear()
        _env_file_cache.update(parsed)
        _env_file_mtime = mtime
    return _env_file_cache.get(name, "")


class ProviderClient:
    """Direct chat completions client for free providers.

    Supported providers and their endpoints:
    - nvidia_key1:  https://integrate.api.nvidia.com/v1/chat/completions (key: NVIDIA_API_KEY)
    - nvidia_key2:  same endpoint (key: NVIDIA_API_KEY_FALLBACK)
    - nvidia_key3:  same endpoint (key: NVIDIA_API_KEY_FALLBACK3)
    - nvidia_key4:  same endpoint (key: NVIDIA_API_KEY_FALLBACK4)
    - google:       https://generativelanguage.googleapis.com/v1beta/openai/chat/completions (key: GEMINI_API_KEY)
    - openrouter:   https://openrouter.ai/api/v1/chat/completions (key: OPENROUTER_API_KEY)
    """
    ENDPOINTS = {
        "nvidia_key1":  "https://integrate.api.nvidia.com/v1/chat/completions",
        "nvidia_key2":  "https://integrate.api.nvidia.com/v1/chat/completions",
        "nvidia_key3":  "https://integrate.api.nvidia.com/v1/chat/completions",
        "nvidia_key4":  "https://integrate.api.nvidia.com/v1/chat/completions",
        "google":       "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "openrouter":   "https://openrouter.ai/api/v1/chat/completions",
    }

    KEY_NAMES = {
        "nvidia_key1":  "NVIDIA_API_KEY",
        "nvidia_key2":  "NVIDIA_API_KEY_FALLBACK",
        "nvidia_key3":  "NVIDIA_API_KEY_FALLBACK2",
        "nvidia_key4":  "NVIDIA_API_KEY_FALLBACK3",
        "google":       "GEMINI_API_KEY",
        "openrouter":   "OPENROUTER_API_KEY",
    }

    # Per-priority curl timeout in seconds
    TIMEOUT_BY_PRIORITY = {
        "low":      120,
        "normal":   180,
        "high":     300,
        "critical": 300,
    }

    class PoolUnavailable(RuntimeError):
        """Raised when a provider pool is temporarily unavailable (timeout/rate-limit)."""
        pass

    class DailyQuotaExceeded(RuntimeError):
        """Raised when a provider's daily quota is exhausted."""
        pass

    def __init__(self, pool_name: str, model: str):
        self.pool_name = pool_name
        self.model = model
        self.endpoint = self.ENDPOINTS.get(pool_name)
        self.key_name = self.KEY_NAMES.get(pool_name)
        if self.endpoint is None:
            raise ValueError(f"Unknown provider pool: {pool_name}. Available: {list(self.ENDPOINTS.keys())}")
        if self.key_name is None:
            raise ValueError(f"No API key env var for pool: {pool_name}. Available: {list(self.KEY_NAMES.keys())}")
        # launchd starts the orchestrator without the shell's exports, so fall
        # back to ~/.env (mode 600) rather than copying secrets into a plist.
        self.api_key = os.environ.get(self.key_name, "") or _key_from_env_file(self.key_name)
        if not self.api_key:
            raise ValueError(f"Missing env var {self.key_name} for pool {pool_name}")
        # Resolve hostname to IP via dig (system resolver is broken for some
        # providers; dig uses its own resolver and works). Cache per instance.
        self._resolve_ip = self._resolve_host()

    def _resolve_host(self):
        """Resolve endpoint hostname to IP using dig. Returns None on failure."""
        from urllib.parse import urlparse
        try:
            hostname = urlparse(self.endpoint).hostname
        except Exception:
            return None
        try:
            result = subprocess.run(
                ["dig", "+short", "+time=2", "+tries=1", hostname],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and "." in line:
                        return line
        except Exception:
            pass
        return None

    def complete(self, prompt: str, max_tokens: int = 4096, temperature: float = 0.0,
                 priority: str = "normal", timeout: Optional[int] = None) -> str:
        """Send a single chat completion request. Returns raw text response.

        API keys are passed via a temp curl config file (--config) so they never
        appear on the command line where `ps aux` could expose them.

        Raises PoolUnavailable on curl timeout (exit 28) so the router can
        cool down the pool and route to another provider.
        """
        # Priority-based timeout
        # An explicit timeout wins (autopilot uses a short one so a slow pool
        # is skipped quickly); otherwise it follows the task priority.
        timeout = timeout or self.TIMEOUT_BY_PRIORITY.get(priority, self.TIMEOUT_BY_PRIORITY["normal"])

        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()

        # Write curl config (headers incl. secret API key) to a temp file.
        # curl config supports: header = "...", url = "...", data = "..."
        # One file per thread (workers run concurrently and would otherwise
        # share and delete each other's config), created owner-only.
        tmp_cfg = Path(f"/tmp/oc_curl_{os.getpid()}_{threading.get_ident()}.cfg")
        try:
            fd = os.open(tmp_cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(f"url = \"{self.endpoint}\"\n")
                f.write(f'header = "Authorization: Bearer {self.api_key}"\n')
                f.write('header = "Content-Type: application/json"\n')
            cmd = [
                "curl", "-s", "-m", str(timeout),
                "--config", str(tmp_cfg),
                "--data-binary", payload,
            ]
            # Use --resolve with dig-resolved IP to bypass broken system DNS
            if self._resolve_ip:
                from urllib.parse import urlparse
                hostname = urlparse(self.endpoint).hostname
                port = urlparse(self.endpoint).port or 443
                cmd.insert(4, "--resolve")
                cmd.insert(5, f"{hostname}:{port}:{self._resolve_ip}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        finally:
            try:
                tmp_cfg.unlink()
            except OSError:
                pass

        # curl exit code 28 = operation timeout, 6 = couldn't resolve host,
        # 7 = failed to connect → treat all as pool failure for failover
        if result.returncode in (28, 6, 7):
            raise self.PoolUnavailable(f"curl exit {result.returncode} on {self.pool_name}")

        if result.returncode != 0:
            raise RuntimeError(f"curl failed (exit {result.returncode}): {result.stderr}")

        out = result.stdout.strip()
        if not out:
            raise RuntimeError("Empty response from provider")

        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            # Some providers return NDJSON (OpenCode-style). Collect text parts.
            text_parts = []
            for line in out.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict) and entry.get("type") == "text":
                        text_parts.append(entry.get("part", {}).get("text", ""))
                except json.JSONDecodeError:
                    pass
            response = "".join(text_parts).strip()
            if not response:
                raise RuntimeError(f"Unparseable response: {out[:200]}")
            return response

        if "error" in d:
            raise RuntimeError(f"Provider error: {d['error']}")

        # Handle choices[0].message.content (standard OpenAI-compatible)
        try:
            msg = d["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning_content") or ""
            if content:
                # Strip reasoning blocks from model responses
                content = self._strip_reasoning(content)
                if content.strip():
                    # Log token usage if the provider reports it
                    usage = d.get("usage", {})
                    if usage:
                        self._log_token_usage(usage)
                    return content.strip()
        except (KeyError, IndexError, TypeError):
            pass

        raise RuntimeError(f"No content in response: {out[:200]}")

    def _log_token_usage(self, usage: dict):
        """Log token usage to a file for tracking free-tier consumption."""
        try:
            log_path = Path("/Users/aryanagarwal/office-os/logs/token_usage.jsonl")
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pool": self.pool_name,
                "model": self.model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Never fail a task because of logging

    @staticmethod
    def _strip_reasoning(text: str) -> str:
        """Strip reasoning/thinking blocks from model responses.

        Some models (Nemotron, DeepSeek) put chain-of-thought reasoning in the
        content field alongside or instead of the actual answer. This removes
        common reasoning delimiters to extract just the answer.
        """
        import re

        # Remove <thinking>...</thinking> blocks
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove <|start_header_id|>...<|end_header_id|> blocks (Llama-style)
        text = re.sub(r"<\|start_header_id\|>.*?<\|end_header_id\|>", "", text, flags=re.DOTALL)

        # Remove text between ∴ markers (Nemotron-style)
        text = re.sub(r"∴.*?∴", "", text, flags=re.DOTALL)

        # Remove leading reasoning lines (common model patterns)
        reasoning_starts = [
            r"^\s*\*\*Thinking:\*\*.*?\n",
            r"^\s*\*\*thinking:\*\*.*?\n",
            r"^\s*Here's? a thinking process:.*?\n",
            r"^\s*Here's? my thinking:.*?\n",
            r"^\s*Let me think.*?\n",
            r"^\s*I need to think.*?\n",
        ]
        for pattern in reasoning_starts:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

        # Remove trailing reasoning artifacts
        text = re.sub(r"\*\*Reasoning:\*\*.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r"\*\*Analysis:\*\*.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)

        # Remove Nemotron-style numbered reasoning chains at start of text:
        #   1. **Analyze User Input:**
        #      ...
        #   2. **Identify the Core Conflict/Request:**
        #      ...
        # Detect 2+ consecutive numbered sections at start with bold headers
        numbered_reasoning_re = re.compile(
            r"(?ms)^\d+\.\s*\*\*.*?\n(?:\s{0,3}[-*•].*?\n|\s{0,3}[^\n]*?\n?)*",
        )
        matches = list(numbered_reasoning_re.finditer(text))
        if len(matches) >= 2 and matches[0].start() == 0:
            text = text[matches[-1].end():].strip()

        return text.strip()

    def _log_token_usage(self, usage: dict):
        """Log token usage to a file for tracking free-tier consumption."""
        try:
            log_path = Path("/Users/aryanagarwal/office-os/logs/token_usage.jsonl")
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pool": self.pool_name,
                "model": self.model,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Never fail a task because of logging


def make_client(pool_name: str, model: str) -> ProviderClient:
    """Factory: create a ProviderClient for the given pool and model."""
    return ProviderClient(pool_name, model)