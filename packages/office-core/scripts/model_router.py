#!/usr/bin/env python3
"""
office-core Model Router Service
Runs on mini :8081 - Single entry point for all model calls
Routes to: MLX (local), NIM (cloud), Free-harness (fallback)
"""

import os
import sys
import json
import yaml
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add parent to path for observability imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from observability import setup_json_logging, update_model_router_backend_health, record_model_router_request

# Setup structured JSON logging
logger = setup_json_logging("model-router")

CONFIG_PATH = Path("/Users/aryanagarwal/AI-Office/packages/office-core/model-router.yaml")

@dataclass
class Backend:
    name: str
    type: str
    endpoint: str
    models: List[str]
    priority: int
    enabled: bool
    config: Dict

@dataclass
class RoutingRule:
    name: str
    condition: str
    backend: str
    fallback: Optional[str]

class ModelRouter:
    def __init__(self):
        self.backends: Dict[str, Backend] = {}
        self.rules: List[RoutingRule] = []
        self.aliases: Dict[str, str] = {}
        self.health: Dict[str, Dict] = {}
        self.load_config()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    
    def load_config(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        
        for b in config.get("backends", []):
            self.backends[b["name"]] = Backend(
                name=b["name"],
                type=b["type"],
                endpoint=b["endpoint"],
                models=b.get("models", []),
                priority=b.get("priority", 0),
                enabled=b.get("enabled", True),
                config=b.get("config", {})
            )
        
        for r in config.get("routing_rules", []):
            self.rules.append(RoutingRule(
                name=r["name"],
                condition=r["condition"],
                backend=r["backend"],
                fallback=r.get("fallback")
            ))
        
        self.aliases = config.get("aliases", {})
        logger.info(f"Loaded {len(self.backends)} backends, {len(self.rules)} rules, {len(self.aliases)} aliases")
    
    def resolve_model(self, model: str) -> str:
        """Resolve alias to actual model name."""
        return self.aliases.get(model, model)
    
    def select_backend(self, model: str) -> Optional[Backend]:
        """Select backend based on routing rules."""
        resolved = self.resolve_model(model)
        
        for rule in self.rules:
            if rule.condition == "true":
                backend = self.backends.get(rule.backend)
                if backend and backend.enabled:
                    return backend
                if rule.fallback:
                    fb = self.backends.get(rule.fallback)
                    if fb and fb.enabled:
                        return fb
                continue
            
            # Check if model in backend's models
            backend = self.backends.get(rule.backend)
            if backend and backend.enabled and resolved in backend.models:
                return backend
            if rule.fallback:
                fb = self.backends.get(rule.fallback)
                if fb and fb.enabled and resolved in fb.models:
                    return fb
        
        # Default: highest priority enabled backend
        enabled = [b for b in self.backends.values() if b.enabled]
        if enabled:
            return max(enabled, key=lambda b: b.priority)
        return None
    
    async def health_check(self, backend: Backend) -> bool:
        """Check backend health."""
        try:
            if backend.type == "mlx":
                url = f"{backend.endpoint}/v1/models"
            elif backend.type == "nim":
                url = f"{backend.endpoint}/v1/models"
            else:
                url = f"{backend.endpoint}/v1/models"
            
            response = await self.client.get(url, timeout=10.0)
            healthy = response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed for {backend.name}: {e}")
            healthy = False
        
        # Track consecutive failures
        if backend.name not in self.health:
            self.health[backend.name] = {"failures": 0, "healthy": True, "last_check": time.time()}
        
        if healthy:
            self.health[backend.name]["failures"] = 0
            self.health[backend.name]["healthy"] = True
        else:
            self.health[backend.name]["failures"] += 1
            if self.health[backend.name]["failures"] >= 3:
                self.health[backend.name]["healthy"] = False
        
        self.health[backend.name]["last_check"] = time.time()
        
        # Update Prometheus metrics
        failures = self.health[backend.name]["failures"]
        update_model_router_backend_health(backend.name, backend.type, healthy, failures)
        
        return healthy
    
    async def route_request(self, model: str, payload: Dict) -> httpx.Response:
        """Route request to appropriate backend."""
        resolved_model = self.resolve_model(model)
        backend = self.select_backend(model)
        
        if not backend:
            raise HTTPException(503, "No available backend")
        
        # Check health
        if not self.health.get(backend.name, {}).get("healthy", True):
            # Try fallback
            for rule in self.rules:
                if rule.backend == backend.name and rule.fallback:
                    fb = self.backends.get(rule.fallback)
                    if fb and fb.enabled and self.health.get(fb.name, {}).get("healthy", True):
                        backend = fb
                        break
        
        # Prepare request
        url = f"{backend.endpoint}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        
        # Add API key if needed
        if "api_key_env" in backend.config:
            api_key = os.environ.get(backend.config["api_key_env"])
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        
        # Modify payload for backend
        request_payload = dict(payload)
        request_payload["model"] = resolved_model
        
        # Apply backend-specific config
        if "max_tokens" in backend.config:
            request_payload.setdefault("max_tokens", backend.config["max_tokens"])
        
        timeout = backend.config.get("timeout", 180)
        
        logger.info(f"Routing {model} -> {backend.name} ({backend.type}) at {backend.endpoint}")
        
        # Record Prometheus metric
        record_model_router_request(backend.name, resolved_model)
        
        try:
            response = await self.client.post(
                url,
                json=request_payload,
                headers=headers,
                timeout=timeout
            )
            return response
        except httpx.TimeoutException:
            raise HTTPException(504, f"Backend {backend.name} timeout")
        except Exception as e:
            logger.error(f"Backend {backend.name} error: {e}")
            raise HTTPException(502, f"Backend error: {e}")

# FastAPI app
router = ModelRouter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Model router starting up")
    # Initial health checks
    for backend in router.backends.values():
        if backend.enabled:
            await router.health_check(backend)
    yield
    # Shutdown
    await router.client.aclose()
    logger.info("Model router shutting down")

app = FastAPI(title="office-core Model Router", lifespan=lifespan)

class ChatRequest(BaseModel):
    model: str
    messages: List[Dict]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: bool = False

@app.get("/health")
async def health():
    """Health endpoint."""
    backend_status = {}
    for name, health in router.health.items():
        backend_status[name] = {
            "healthy": health.get("healthy", True),
            "failures": health.get("failures", 0),
            "last_check": health.get("last_check", 0)
        }
    return {
        "status": "ok",
        "backends": backend_status,
        "backends_configured": len(router.backends),
        "rules": len(router.rules)
    }

@app.get("/v1/models")
async def list_models():
    """List available models."""
    models = []
    for backend in router.backends.values():
        if backend.enabled:
            for model in backend.models:
                models.append({
                    "id": model,
                    "object": "model",
                    "owned_by": backend.name,
                    "backend": backend.name,
                    "type": backend.type
                })
    return {"object": "list", "data": models}

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, background_tasks: BackgroundTasks):
    """Route chat completion request."""
    try:
        response = await router.route_request(request.model, request.model_dump(exclude_none=True))
        
        if request.stream:
            async def stream_response():
                async for chunk in response.aiter_bytes():
                    yield chunk
            return StreamingResponse(stream_response(), media_type="text/event-stream")
        else:
            return response.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Request failed: {e}")
        raise HTTPException(500, str(e))

@app.get("/metrics")
async def metrics():
    """Prometheus metrics."""
    lines = []
    lines.append("# HELP model_router_backend_healthy Backend health status")
    lines.append("# TYPE model_router_backend_healthy gauge")
    for name, health in router.health.items():
        lines.append(f'model_router_backend_healthy{{backend="{name}"}} {1 if health.get("healthy", True) else 0}')
    
    lines.append("# HELP model_router_backend_failures Consecutive failures")
    lines.append("# TYPE model_router_backend_failures counter")
    for name, health in router.health.items():
        lines.append(f'model_router_backend_failures{{backend="{name}"}} {health.get("failures", 0)}')
    
    return "\n".join(lines)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)