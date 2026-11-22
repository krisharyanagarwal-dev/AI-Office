#!/usr/bin/env python3
"""
HUD v2 - FastAPI Dashboard for office-core
Port: 4747
NO SPA catch-all - explicit routes only
"""

import asyncio
import json
import os
import psutil
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

# Configuration
OFFICE_CORE_API = os.getenv("OFFICE_CORE_API", "http://127.0.0.1:8080")
HUD_PORT = int(os.getenv("HUD_PORT", "4747"))
HUD_HOST = os.getenv("HUD_HOST", "127.0.0.1")

# Combined portfolio feed path
COMBINED_PORTFOLIO_PATH = os.getenv(
    "COMBINED_PORTFOLIO_PATH",
    "/Users/aryanagarwal/trading/openalice/ui/public/combined_portfolio.json"
)

# Prometheus metrics
REQUEST_COUNT = Counter("hud_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("hud_request_duration_seconds", "Request latency", ["method", "endpoint"])
TASKS_COUNT = Gauge("hud_tasks_total", "Total tasks", ["status"])
AGENTS_COUNT = Gauge("hud_agents_total", "Total agents", ["enabled"])
MODELS_COUNT = Gauge("hud_model_routes_total", "Total model routes", ["enabled"])
LAUNCHD_COUNT = Gauge("hud_launchd_jobs_total", "Total launchd jobs", ["enabled"])
SYSTEM_MEMORY = Gauge("hud_system_memory_bytes", "System memory usage", ["type"])
SYSTEM_DISK = Gauge("hud_system_disk_bytes", "System disk usage", ["type", "mount"])
GIT_STATUS = Gauge("hud_git_status", "Git repo status", ["repo", "status"])

# SSE event queue
event_queues: List[asyncio.Queue] = []


async def broadcast_event(event_type: str, data: dict):
    """Broadcast event to all connected SSE clients."""
    event_data = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    for queue in event_queues[:]:
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            event_queues.remove(queue)


async def collect_system_metrics():
    """Collect and update system metrics."""
    # Memory
    mem = psutil.virtual_memory()
    SYSTEM_MEMORY.labels(type="total").set(mem.total)
    SYSTEM_MEMORY.labels(type="available").set(mem.available)
    SYSTEM_MEMORY.labels(type="used").set(mem.used)
    SYSTEM_MEMORY.labels(type="percent").set(mem.percent)

    # Disk
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            SYSTEM_DISK.labels(type="total", mount=partition.mountpoint).set(usage.total)
            SYSTEM_DISK.labels(type="used", mount=partition.mountpoint).set(usage.used)
            SYSTEM_DISK.labels(type="free", mount=partition.mountpoint).set(usage.free)
            SYSTEM_DISK.labels(type="percent", mount=partition.mountpoint).set((usage.used / usage.total) * 100)
        except PermissionError:
            pass

    # Git status for key repos
    repos = {
        "office-core": "/Users/aryanagarwal/AI-Office/packages/office-core",
        "AI-Office": "/Users/aryanagarwal/AI-Office",
    }
    for name, path in repos.items():
        try:
            result = subprocess.run(
                ["git", "-C", path, "status", "--porcelain"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                changes = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
                GIT_STATUS.labels(repo=name, status="clean" if changes == 0 else "dirty").set(1 if changes == 0 else 0)
                GIT_STATUS.labels(repo=name, status="changes").set(changes)
        except Exception:
            pass


async def fetch_office_core_data():
    """Fetch data from office-core API and update gauges."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            # Tasks
            resp = await client.get(f"{OFFICE_CORE_API}/tasks")
            if resp.status_code == 200:
                data = resp.json()
                tasks = data.get("tasks", [])
                by_status = {}
                for t in tasks:
                    by_status[t.get("status", "unknown")] = by_status.get(t.get("status", "unknown"), 0) + 1
                for status, count in by_status.items():
                    TASKS_COUNT.labels(status=status).set(count)

            # Agents
            resp = await client.get(f"{OFFICE_CORE_API}/agents")
            if resp.status_code == 200:
                data = resp.json()
                agents = data.get("agents", [])
                enabled = sum(1 for a in agents if a.get("enabled"))
                disabled = len(agents) - enabled
                AGENTS_COUNT.labels(enabled="true").set(enabled)
                AGENTS_COUNT.labels(enabled="false").set(disabled)

            # Models
            resp = await client.get(f"{OFFICE_CORE_API}/models")
            if resp.status_code == 200:
                data = resp.json()
                routes = data.get("routes", [])
                enabled = sum(1 for r in routes if r.get("enabled"))
                disabled = len(routes) - enabled
                MODELS_COUNT.labels(enabled="true").set(enabled)
                MODELS_COUNT.labels(enabled="false").set(disabled)

            # Launchd
            resp = await client.get(f"{OFFICE_CORE_API}/launchd")
            if resp.status_code == 200:
                data = resp.json()
                jobs = data.get("jobs", [])
                enabled = sum(1 for j in jobs if j.get("enabled"))
                disabled = len(jobs) - enabled
                LAUNCHD_COUNT.labels(enabled="true").set(enabled)
                LAUNCHD_COUNT.labels(enabled="false").set(disabled)

        except Exception as e:
            print(f"Error fetching office-core data: {e}")


async def metrics_collector():
    """Background task to collect metrics periodically."""
    while True:
        await collect_system_metrics()
        await fetch_office_core_data()
        await broadcast_event("metrics", {"timestamp": datetime.utcnow().isoformat()})
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    # Startup
    collector_task = asyncio.create_task(metrics_collector())
    yield
    # Shutdown
    collector_task.cancel()
    try:
        await collector_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="HUD v2",
    description="office-core Dashboard",
    version="2.0.0",
    lifespan=lifespan,
)

# Templates and static files
import os
from jinja2 import Environment, FileSystemLoader

template_dir = os.path.join(os.path.dirname(__file__), "templates")

# Create Jinja2 environment with cache disabled
jinja_env = Environment(
    loader=FileSystemLoader(template_dir),
    auto_reload=True,
    cache_size=0,  # Disable cache completely
    enable_async=False,
)

# Simple template renderer
async def render_template(template_name: str, context: dict) -> str:
    """Render template asynchronously."""
    template = jinja_env.get_template(template_name)
    return template.render(**context)

app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Health endpoint ---
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "hud-v2", "timestamp": datetime.utcnow().isoformat()}


# --- API Proxies to office-core ---
@app.get("/api/tasks")
async def api_tasks(status: Optional[str] = None, assignee: Optional[str] = None, limit: int = 100):
    """Proxy to office-core /tasks endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        params = {"limit": limit}
        if status:
            params["status"] = status
        if assignee:
            params["assignee"] = assignee
        resp = await client.get(f"{OFFICE_CORE_API}/tasks", params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="office-core API error")
        return resp.json()


@app.get("/api/agents")
async def api_agents(enabled_only: bool = False):
    """Proxy to office-core /agents endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        params = {"enabled_only": "true" if enabled_only else "false"}
        resp = await client.get(f"{OFFICE_CORE_API}/agents", params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="office-core API error")
        return resp.json()


@app.get("/api/models")
async def api_models(enabled_only: bool = False):
    """Proxy to office-core /models endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        params = {"enabled_only": "true" if enabled_only else "false"}
        resp = await client.get(f"{OFFICE_CORE_API}/models", params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="office-core API error")
        return resp.json()


@app.get("/api/launchd")
async def api_launchd(enabled_only: bool = False):
    """Proxy to office-core /launchd endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        params = {"enabled_only": "true" if enabled_only else "false"}
        resp = await client.get(f"{OFFICE_CORE_API}/launchd", params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="office-core API error")
        return resp.json()


@app.get("/api/combined-portfolio")
async def api_combined_portfolio():
    """Fetch combined portfolio data with fundamentals."""
    try:
        path = Path(COMBINED_PORTFOLIO_PATH)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Combined portfolio file not found")
        data = json.loads(path.read_text())
        return data
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid JSON in combined portfolio file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading combined portfolio: {str(e)}")


@app.get("/api/health")
async def api_health():
    """System health - combines office-core health with local system info."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        office_core_health = {"status": "unknown"}
        try:
            resp = await client.get(f"{OFFICE_CORE_API}/health")
            office_core_health = resp.json()
        except Exception:
            office_core_health = {"status": "unreachable"}

    # Local system health
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu_percent = psutil.cpu_percent(interval=0.1)

    return {
        "office_core": office_core_health,
        "system": {
            "memory": {
                "total": mem.total,
                "available": mem.available,
                "used": mem.used,
                "percent": mem.percent,
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": (disk.used / disk.total) * 100,
            },
            "cpu_percent": cpu_percent,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


# --- SSE Endpoint ---
@app.get("/events")
async def events(request: Request):
    """Server-Sent Events stream for real-time updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    event_queues.append(queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"
        finally:
            if queue in event_queues:
                event_queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Prometheus Metrics ---
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type="text/plain")


# --- Main Dashboard ---
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard HTML page."""
    html = await render_template("index.html", {"request": request})
    return HTMLResponse(content=html)


# --- Explicit 404 for any undefined route (NO catch-all) ---
# FastAPI automatically returns 404 for undefined routes
# We explicitly ensure no catch-all route exists


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HUD_HOST, port=HUD_PORT)