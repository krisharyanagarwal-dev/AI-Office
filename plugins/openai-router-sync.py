#!/usr/bin/env python3
"""
Synchronous wrapper for the OpenAI Model Router

Provides synchronous API for dispatcher integration.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx

MODEL_ROUTER_URL = os.environ.get("MODEL_ROUTER_URL", "http://127.0.0.1:8081")


class ModelRouterSync:
    def __init__(self, base_url: str = MODEL_ROUTER_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=httpx.Timeout(60.0))

    def list_models(self) -> list[dict]:
        """List all available models."""
        url = f"{self.base_url}/v1/models"
        response = self.client.get(url)
        if response.status_code == 200:
            return response.json().get("data", [])
        return []

    def health(self) -> dict:
        """Check router health."""
        url = f"{self.base_url}/health"
        response = self.client.get(url)
        if response.status_code == 200:
            return response.json()
        return {"status": "unreachable"}

    def chat(
        self,
        model: str,
        messages: Optional[list[dict]] = None,
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
    ) -> dict:
        """Send a chat completion request."""
        url = f"{self.base_url}/v1/chat/completions"

        if messages is None:
            messages = [{"role": "user", "content": prompt or "Hello"}]

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = {"Content-Type": "application/json"}

        response = self.client.post(url, json=payload, headers=headers)
        return response.json()

    def close(self):
        """Close the HTTP client."""
        self.client.close()


def route_to_model(model_alias: str, task: str, max_tokens: Optional[int] = None) -> dict:
    """Route a task through the model router and return results."""
    client = ModelRouterSync()
    try:
        messages = [{"role": "user", "content": task}]
        result = client.chat(model_alias, messages=messages, max_tokens=max_tokens or 8192)
        return {
            "success": True,
            "model": model_alias,
            "backend": result.get("object", "chat_completion"),
            "choices": result.get("choices", []),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "model": model_alias,
        }
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync OpenAI Model Router Client")
    parser.add_argument("--model", "-m", default="qwen", help="Model to use (alias)")
    parser.add_argument("--prompt", "-p", required=True, help="User prompt")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max tokens")

    args = parser.parse_args()

    result = route_to_model(args.model, args.prompt, args.max_tokens)
    print(json.dumps(result, indent=2))