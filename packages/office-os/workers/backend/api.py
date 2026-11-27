#!/usr/bin/env python3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "office-core"))
"""
office-core API Server
FastAPI on :8080 - REST API for tasks, agents, models, launchd
"""

import sys
import uuid
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn

from db import (
    list_tasks, get_task, create_task, update_task, delete_task,
    list_agents, get_agent, upsert_agent, delete_agent,
    list_model_routes, get_model_route, upsert_model_route, delete_model_route,
    list_launchd_jobs, get_launchd_job, upsert_launchd_job, delete_launchd_job,
    init_db
)

from observability import setup_json_logging

# Setup structured JSON logging
logger = setup_json_logging("office-core-api")

# Import observability module
from observability import (
    observability_lifespan,
    metrics_endpoint,
    event_broadcaster,
    sse_event_generator,
    health_checker,
    collect_all_metrics,
    record_api_request,
    record_api_request_duration,
    TASKS_CREATED,
    TASKS_UPDATED,
    TASKS_DELETED,
)

init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with observability."""
    async with observability_lifespan(app):
        yield


app = FastAPI(
    title="office-core API",
    version="1.0.0",
    lifespan=lifespan
)


# --- Request middleware for metrics and logging ---
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    record_api_request(request.method, request.url.path, response.status_code)
    record_api_request_duration(request.method, request.url.path, duration)
    
    # Log request
    logger.info(
        "HTTP request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "client_ip": request.client.host if request.client else None,
        }
    )
    
    return response


# Task models
class TaskCreate(BaseModel):
    title: str
    description: str = ""
    priority: int = 0
    assignee: Optional[str] = None
    source: str = "api"
    tags: str = ""
    depends_on: List[str] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    assignee: Optional[str] = None
    tags: Optional[str] = None
    depends_on: Optional[List[str]] = None


# Agents
class AgentCreate(BaseModel):
    name: str
    type: str
    model: Optional[str] = None
    tools: List[str] = []
    policy: dict = {}
    launchd_label: Optional[str] = None
    health_endpoint: Optional[str] = None
    schedule: Optional[str] = None
    enabled: bool = True


# Models
class ModelRouteCreate(BaseModel):
    name: str
    backend: str
    endpoint: str
    models: List[str] = []
    priority: int = 0
    enabled: bool = True
    config: dict = {}


# Launchd
class LaunchdJobCreate(BaseModel):
    label: str
    agent_name: str
    program: List[str]
    working_directory: Optional[str] = None
    environment: dict = {}
    run_at_load: bool = True
    keep_alive: bool = True
    throttle_interval: int = 30
    start_calendar_interval: Optional[dict] = None
    standard_out_path: Optional[str] = None
    standard_error_path: Optional[str] = None
    process_type: str = "Background"
    enabled: bool = True


# --- Health endpoint (aggregated) ---
@app.get("/health")
async def health():
    """Aggregated health check for all office-core dependencies."""
    return await health_checker.check_all()


# --- Prometheus Metrics ---
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return metrics_endpoint()


# --- SSE Events ---
@app.get("/events")
async def events(request: Request):
    """Server-Sent Events stream for real-time HUD updates."""
    queue = await event_broadcaster.add_connection()
    return StreamingResponse(
        sse_event_generator(request, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Tasks ---
@app.get("/tasks")
def get_tasks(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0
):
    tasks = list_tasks(status=status, assignee=assignee, source=source, limit=limit, offset=offset)
    return {"tasks": tasks, "count": len(tasks)}


@app.post("/tasks")
async def create_task_endpoint(task: TaskCreate):
    task_id = str(uuid.uuid4())[:8]
    create_task(
        id=task_id, title=task.title, description=task.description,
        priority=task.priority, assignee=task.assignee,
        source=task.source, tags=task.tags, depends_on=task.depends_on
    )
    
    # Record metric
    TASKS_CREATED.labels(source=task.source).inc()
    
    # Broadcast event
    await event_broadcaster.broadcast_task_event("task_created", task_id, {
        "title": task.title,
        "assignee": task.assignee,
        "source": task.source,
        "priority": task.priority,
    })
    
    return {"id": task_id, "status": "created"}


@app.get("/tasks/{task_id}")
def get_task_endpoint(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.patch("/tasks/{task_id}")
async def update_task_endpoint(task_id: str, update: TaskUpdate):
    updates = update.model_dump(exclude_unset=True)
    if update_task(task_id, **updates):
        # Record metric
        if "status" in updates:
            TASKS_UPDATED.labels(status=updates["status"]).inc()
        
        # Broadcast event
        await event_broadcaster.broadcast_task_event("task_updated", task_id, updates)
        
        return {"status": "updated"}
    raise HTTPException(404, "Task not found")


@app.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    if delete_task(task_id):
        # Record metric
        TASKS_DELETED.inc()
        
        # Broadcast event
        await event_broadcaster.broadcast_task_event("task_deleted", task_id, {})
        
        return {"status": "deleted"}
    raise HTTPException(404, "Task not found")


# --- Agents ---
@app.get("/agents")
def get_agents(enabled_only: bool = False):
    agents = list_agents(enabled_only=enabled_only)
    return {"agents": agents}


@app.post("/agents")
async def create_agent(agent: AgentCreate):
    upsert_agent(
        name=agent.name, type=agent.type, model=agent.model,
        tools=agent.tools, policy=agent.policy,
        launchd_label=agent.launchd_label,
        health_endpoint=agent.health_endpoint,
        schedule=agent.schedule, enabled=agent.enabled
    )
    
    # Broadcast event
    await event_broadcaster.broadcast_agent_event("agent_created", agent.name, {
        "type": agent.type,
        "model": agent.model,
        "enabled": agent.enabled,
    })
    
    return {"status": "created"}


@app.get("/agents/{name}")
def get_agent_endpoint(name: str):
    agent = get_agent(name)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@app.patch("/agents/{name}")
async def update_agent_endpoint(name: str, agent: AgentCreate):
    # Get current agent to check for changes
    current = get_agent(name)
    if not current:
        raise HTTPException(404, "Agent not found")
    
    upsert_agent(
        name=agent.name, type=agent.type, model=agent.model,
        tools=agent.tools, policy=agent.policy,
        launchd_label=agent.launchd_label,
        health_endpoint=agent.health_endpoint,
        schedule=agent.schedule, enabled=agent.enabled
    )
    
    # Broadcast event with changes
    changes = {}
    for field in ["type", "model", "enabled", "tools", "policy", "health_endpoint", "schedule"]:
        new_val = getattr(agent, field, None)
        old_val = current.get(field)
        if new_val != old_val:
            changes[field] = {"old": old_val, "new": new_val}
    
    await event_broadcaster.broadcast_agent_event("agent_updated", name, {"changes": changes})
    
    return {"status": "updated"}


@app.delete("/agents/{name}")
async def delete_agent_endpoint(name: str):
    if delete_agent(name):
        await event_broadcaster.broadcast_agent_event("agent_deleted", name, {})
        return {"status": "deleted"}
    raise HTTPException(404, "Agent not found")


# --- Models ---
@app.get("/models")
def get_models(enabled_only: bool = False):
    routes = list_model_routes(enabled_only=enabled_only)
    return {"routes": routes}


@app.post("/models")
async def create_model_route(route: ModelRouteCreate):
    upsert_model_route(
        name=route.name, backend=route.backend, endpoint=route.endpoint,
        models=route.models, priority=route.priority,
        enabled=route.enabled, config=route.config
    )
    
    await event_broadcaster.broadcast_model_event("model_route_created", route.name, {
        "backend": route.backend,
        "endpoint": route.endpoint,
        "models": route.models,
        "enabled": route.enabled,
    })
    
    return {"status": "created"}


@app.patch("/models/{name}")
async def update_model_route_endpoint(name: str, route: ModelRouteCreate):
    current = get_model_route(name)
    if not current:
        raise HTTPException(404, "Model route not found")
    
    upsert_model_route(
        name=route.name, backend=route.backend, endpoint=route.endpoint,
        models=route.models, priority=route.priority,
        enabled=route.enabled, config=route.config
    )
    
    await event_broadcaster.broadcast_model_event("model_route_updated", name, {
        "backend": route.backend,
        "endpoint": route.endpoint,
        "models": route.models,
        "enabled": route.enabled,
    })
    
    return {"status": "updated"}


@app.delete("/models/{name}")
async def delete_model_route_endpoint(name: str):
    if delete_model_route(name):
        await event_broadcaster.broadcast_model_event("model_route_deleted", name, {})
        return {"status": "deleted"}
    raise HTTPException(404, "Model route not found")


# --- Launchd ---
@app.get("/launchd")
def get_launchd(enabled_only: bool = False):
    jobs = list_launchd_jobs(enabled_only=enabled_only)
    return {"jobs": jobs}


@app.post("/launchd")
async def create_launchd(job: LaunchdJobCreate):
    upsert_launchd_job(
        label=job.label, agent_name=job.agent_name, program=job.program,
        working_directory=job.working_directory, environment=job.environment,
        run_at_load=job.run_at_load, keep_alive=job.keep_alive,
        throttle_interval=job.throttle_interval,
        start_calendar_interval=job.start_calendar_interval,
        standard_out_path=job.standard_out_path,
        standard_error_path=job.standard_error_path,
        process_type=job.process_type, enabled=job.enabled
    )
    
    await event_broadcaster.broadcast_launchd_event("launchd_job_created", job.label, {
        "agent_name": job.agent_name,
        "program": job.program,
        "enabled": job.enabled,
    })
    
    return {"status": "created"}


@app.patch("/launchd/{label}")
async def update_launchd_endpoint(label: str, job: LaunchdJobCreate):
    current = get_launchd_job(label)
    if not current:
        raise HTTPException(404, "Launchd job not found")
    
    upsert_launchd_job(
        label=job.label, agent_name=job.agent_name, program=job.program,
        working_directory=job.working_directory, environment=job.environment,
        run_at_load=job.run_at_load, keep_alive=job.keep_alive,
        throttle_interval=job.throttle_interval,
        start_calendar_interval=job.start_calendar_interval,
        standard_out_path=job.standard_out_path,
        standard_error_path=job.standard_error_path,
        process_type=job.process_type, enabled=job.enabled
    )
    
    await event_broadcaster.broadcast_launchd_event("launchd_job_updated", label, {
        "agent_name": job.agent_name,
        "enabled": job.enabled,
    })
    
    return {"status": "updated"}


@app.delete("/launchd/{label}")
async def delete_launchd_endpoint(label: str):
    if delete_launchd_job(label):
        await event_broadcaster.broadcast_launchd_event("launchd_job_deleted", label, {})
        return {"status": "deleted"}
    raise HTTPException(404, "Launchd job not found")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)