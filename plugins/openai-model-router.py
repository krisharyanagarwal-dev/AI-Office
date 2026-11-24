#!/usr/bin/env python3
"""
OpenAI-Compatible Model Router Client

Provides a client interface to the office-core model-router service
Runs on localhost:8081 - Routes to MLX (local), NIM (cloud), Free-harness (fallback)

Usage:
    python openai-model-router.py --model qwen --prompt "Explain quantum computing"
    python openai-model-router.py --list-models
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx

MODEL_ROUTER_URL = os.environ.get("MODEL_ROUTER_URL", "http://127.0.0.1:8081")


class ModelRouterClient:
    def __init__(self, base_url: str = MODEL_ROUTER_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    async def list_models(self) -> list[dict]:
        """List all available models."""
        url = f"{self.base_url}/v1/models"
        response = await self.client.get(url)
        if response.status_code == 200:
            return response.json().get("data", [])
        return []

    async def health(self) -> dict:
        """Check router health."""
        url = f"{self.base_url}/health"
        response = await self.client.get(url)
        if response.status_code == 200:
            return response.json()
        return {"status": "unreachable"}

    async def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> dict:
        """Send a chat completion request."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = {"Content-Type": "application/json"}

        response = await self.client.post(url, json=payload, headers=headers)
        return response.json()

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


async def main():
    parser = argparse.ArgumentParser(description="OpenAI Model Router Client")
    parser.add_argument("--model", "-m", default="qwen", help="Model to use (alias)")
    parser.add_argument("--prompt", "-p", help="User prompt")
    parser.add_argument("--list-models", "-l", action="store_true", help="List available models")
    parser.add_argument("--health", action="store_true", help="Check router health")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max tokens")
    parser.add_argument("--temperature", type=float, default=0.7, help="Temperature")
    parser.add_argument("--url", default=MODEL_ROUTER_URL, help="Model router URL")

    args = parser.parse_args()

    client = ModelRouterClient(args.url)

    if args.list_models:
        models = await client.list_models()
        print(json.dumps(models, indent=2))
    elif args.health:
        health = await client.health()
        print(json.dumps(health, indent=2))
    elif args.prompt:
        messages = [{"role": "user", "content": args.prompt}]
        result = await client.chat(args.model, messages, args.max_tokens, args.temperature)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())