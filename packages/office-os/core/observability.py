#!/usr/bin/env python3
"""
Observability module for office-os
Prometheus metrics, structured JSON logging, SSE events, health checks
Uses shared utilities from packages/shared
"""

import sys
from pathlib import Path

# Add shared package to path
SHARED_PATH = Path(__file__).parent.parent.parent / "shared" / "python"
sys.path.insert(0, str(SHARED_PATH))

import asyncio
import json
import logging
import logging.handlers
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, AsyncGenerator

import httpx
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CollectorRegistry
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

# Import from office-os db
sys.path.insert(0, str(Path(__file__).parent))
from database import (
    list_tasks, list_agents, list_model_routes, list_launchd_jobs,
    get_conn
)

# Import shared logging utilities
from structured_logging.structured import JSONFormatter as SharedJSONFormatter
from structured_logging.structured import setup_json_logging, get_logger
from structured_logging.sse import EventBroadcaster, sse_event_generator

# ============================================================================
# Prometheus Metrics
# ============================================================================

# Create a custom registry for office-os metrics
REGISTRY = CollectorRegistry()

# Task metrics
TASKS_TOTAL = Gauge(
    "office_os_tasks_total",
    "Total tasks by status",
    ["status"],
    registry=REGISTRY
)
TASKS_CREATED = Counter(
    "office_os_tasks_created_total",
    "Total tasks created",
    ["source"],
    registry=REGISTRY
)
TASKS_UPDATED = Counter(
    "office_os_tasks_updated_total",
    "Total tasks updated",
    ["status"],
    registry=REGISTRY
)
TASKS_DELETED = Counter(
    "office_os_tasks_deleted_total",
    "Total tasks deleted",
    registry=REGISTRY
)

# Agent metrics
AGENTS_TOTAL = Gauge(
    "office_os_agents_total",
    "Total agents by enabled status",
    ["enabled"],
    registry=REGISTRY
)
AGENT_HEALTH = Gauge(
    "office_os_agent_healthy",
    "Agent health status (1=healthy, 0=unhealthy)",
    ["agent_name"],
    registry=REGISTRY
)

# Model router metrics
MODEL_ROUTES_TOTAL = Gauge(
    "office_os_model_routes_total",
    "Total model routes by enabled status",
    ["enabled"],
    registry=REGISTRY
)
MODEL_ROUTER_BACKEND_HEALTHY = Gauge(
    "office_os_model_router_backend_healthy",
    "Model router backend health status",
    ["backend_name", "backend_type"],
    registry=REGISTRY
)
MODEL_ROUTER_BACKEND_FAILURES = Counter(
    "office_os_model_router_backend_failures_total",
    "Model router backend consecutive failures",
    ["backend_name"],
    registry=REGISTRY
)
MODEL_ROUTER_REQUESTS = Counter(
    "office_os_model_router_requests_total",
    "Model router requests routed",
    ["backend_name", "model"],
    registry=REGISTRY
)

# Launchd metrics
LAUNCHD_JOBS_TOTAL = Gauge(
    "office_os_launchd_jobs_total",
    "Total launchd jobs by enabled status",
    ["enabled"],
    registry=REGISTRY
)
LAUNCHD_JOB_STATUS = Gauge(
    "office_os_launchd_job_status",
    "Launchd job status (1=loaded/enabled, 0=disabled)",
    ["label", "agent_name"],
    registry=REGISTRY
)

# API metrics
API_REQUESTS = Counter(
    "office_os_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY
)
API_REQUEST_DURATION = Histogram(
    "office_os_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint"],
    registry=REGISTRY
)

# System metrics
DB_CONNECTIONS = Gauge(
    "office_os_db_connections_active",
    "Active database connections",
    registry=REGISTRY
)

# ============================================================================
# Metrics Collection Functions
# ============================================================================

def collect_task_metrics():
    """Collect task metrics from database."""
    try:
        tasks = list_tasks()
        by_status = {}
        for task in tasks:
            status = task.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        
        for status, count in by_status.items():
            TASKS_TOTAL.labels(status=status).set(count)
    except Exception as e:
        get_logger("observability").error(f"Failed to collect task metrics: {e}")


def collect_agent_metrics():
    """Collect agent metrics from database."""
    try:
        agents = list_agents()
        enabled_count = sum(1 for a in agents if a.get("enabled"))
        disabled_count = len(agents) - enabled_count
        
        AGENTS_TOTAL.labels(enabled="true").set(enabled_count)
        AGENTS_TOTAL.labels(enabled="false").set(disabled_count)
        
        # Individual agent health (placeholder - would need actual health checks)
        for agent in agents:
            # Default to healthy if enabled, unknown if disabled
            health = 1 if agent.get("enabled") else 0
            AGENT_HEALTH.labels(agent_name=agent.get("name", "unknown")).set(health)
    except Exception as e:
        get_logger("observability").error(f"Failed to collect agent metrics: {e}")


def collect_model_route_metrics():
    """Collect model route metrics from database."""
    try:
        routes = list_model_routes()
        enabled_count = sum(1 for r in routes if r.get("enabled"))
        disabled_count = len(routes) - enabled_count
        
        MODEL_ROUTES_TOTAL.labels(enabled="true").set(enabled_count)
        MODEL_ROUTES_TOTAL.labels(enabled="false").set(disabled_count)
    except Exception as e:
        get_logger("observability").error(f"Failed to collect model route metrics: {e}")


def collect_launchd_metrics():
    """Collect launchd job metrics from database."""
    try:
        jobs = list_launchd_jobs()
        enabled_count = sum(1 for j in jobs if j.get("enabled"))
        disabled_count = len(jobs) - enabled_count
        
        LAUNCHD_JOBS_TOTAL.labels(enabled="true").set(enabled_count)
        LAUNCHD_JOBS_TOTAL.labels(enabled="false").set(disabled_count)
        
        for job in jobs:
            status = 1 if job.get("enabled") else 0
            LAUNCHD_JOB_STATUS.labels(
                label=job.get("label", "unknown"),
                agent_name=job.get("agent_name", "unknown")
            ).set(status)
    except Exception as e:
        get_logger("observability").error(f"Failed to collect launchd metrics: {e}")


def update_model_router_backend_health(backend_name: str, backend_type: str, healthy: bool, failures: int = 0):
    """Update model router backend health metrics."""
    MODEL_ROUTER_BACKEND_HEALTHY.labels(
        backend_name=backend_name,
        backend_type=backend_type
    ).set(1 if healthy else 0)
    
    if failures > 0:
        MODEL_ROUTER_BACKEND_FAILURES.labels(backend_name=backend_name).inc(failures)


def record_model_router_request(backend_name: str, model: str):
    """Record a model router request."""
    MODEL_ROUTER_REQUESTS.labels(backend_name=backend_name, model=model).inc()


def record_api_request(method: str, endpoint: str, status: int):
    """Record an API request."""
    API_REQUESTS.labels(method=method, endpoint=endpoint, status=str(status)).inc()


def record_api_request_duration(method: str, endpoint: str, duration: float):
    """Record API request duration."""
    API_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)


async def collect_all_metrics():
    """Collect all metrics from database."""
    collect_task_metrics()
    collect_agent_metrics()
    collect_model_route_metrics()
    collect_launchd_metrics()


# ============================================================================
# Structured JSON Logging (using shared utilities)
# ============================================================================

# Re-export shared logging setup for backward compatibility
def setup_json_logging(service_name: str, log_dir: Optional[Path] = None) -> logging.Logger:
    """Setup structured JSON logging for a service with daily rotation.
    
    Uses shared logging utilities from packages/shared.
    """
    if log_dir is None:
        log_dir = Path.home() / "AI-Office" / "logs"
    
    return shared_setup_json_logging(service_name, log_dir)


def shared_setup_json_logging(service_name: str, log_dir: Path, level: int = logging.INFO,
                               console: bool = True, max_bytes: int = 10 * 1024 * 1024,
                               backup_count: int = 30) -> logging.Logger:
    """Shared JSON logging setup from packages/shared."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{service_name}.log"
    
    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    logger.handlers.clear()
    
    formatter = SharedJSONFormatter(service_name)
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    logger.propagate = False
    return logger


# ============================================================================
# SSE Event System (using shared utilities)
# ============================================================================

# Re-export shared SSE broadcaster
event_broadcaster = EventBroadcaster()


async def sse_event_generator(request: Request, queue: asyncio.Queue, 
                              heartbeat_interval: float = 30.0) -> AsyncGenerator[str, None]:
    """Generate SSE events for a connection. Uses shared implementation."""
    async for event in shared_sse_event_generator(request, queue, heartbeat_interval):
        yield event


async def shared_sse_event_generator(request: Request, queue: asyncio.Queue, 
                                     heartbeat_interval: float = 30.0) -> AsyncGenerator[str, None]:
    """Shared SSE event generator from packages/shared."""
    try:
        yield f"event: connected\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
        
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                yield event
            except asyncio.TimeoutError:
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
    finally:
        pass


# ============================================================================
# Health Check Aggregation
# ============================================================================

class HealthChecker:
    """Aggregates health checks for all office-os dependencies."""
    
    def __init__(self):
        self.model_router_url = "http://127.0.0.1:8081"
        self.mlx_url = "http://127.0.0.1:11434"
        self.nim_url = "http://127.0.0.1:4200"
        self.client = httpx.AsyncClient(timeout=10.0)
    
    async def check_database(self) -> Dict[str, Any]:
        """Check database connectivity."""
        try:
            conn = get_conn()
            conn.execute("SELECT 1").fetchone()
            return {"status": "healthy", "component": "database"}
        except Exception as e:
            return {"status": "unhealthy", "component": "database", "error": str(e)}
    
    async def check_model_router(self) -> Dict[str, Any]:
        """Check model router health."""
        try:
            resp = await self.client.get(f"{self.model_router_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": "healthy" if data.get("status") == "ok" else "degraded",
                    "component": "model_router",
                    "details": data
                }
            return {"status": "unhealthy", "component": "model_router", "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "unhealthy", "component": "model_router", "error": str(e)}
    
    async def check_mlx(self) -> Dict[str, Any]:
        """Check MLX server health."""
        try:
            resp = await self.client.get(f"{self.mlx_url}/v1/models")
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                return {
                    "status": "healthy",
                    "component": "mlx",
                    "models_count": len(models)
                }
            return {"status": "degraded", "component": "mlx", "error": "upstream offline (mini asleep)"}
        except Exception as e:
            return {"status": "degraded", "component": "mlx", "error": str(e)}
    
    async def check_nim(self) -> Dict[str, Any]:
        """Check NIM proxy health."""
        try:
            resp = await self.client.get(f"{self.nim_url}/v1/models")
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                return {
                    "status": "healthy",
                    "component": "nim",
                    "models_count": len(models)
                }
            return {"status": "degraded", "component": "nim", "error": "upstream offline (mini asleep)"}
        except Exception as e:
            return {"status": "degraded", "component": "nim", "error": str(e)}
    
    async def check_launchd_jobs(self) -> Dict[str, Any]:
        """Check launchd jobs status from database using launchctl list."""
        try:
            jobs = list_launchd_jobs(enabled_only=True)
            loaded_jobs = []
            failed_jobs = []
            
            # Get launchctl list output
            try:
                result = await asyncio.create_subprocess_exec(
                    "launchctl", "list",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate()
                lines = stdout.decode().strip().split('\n')[1:]  # Skip header
                
                # Parse launchctl list: PID status Label
                launchctl_status = {}
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 3:
                        pid, status, label = parts[0], parts[1], parts[2]
                        launchctl_status[label] = {'pid': pid, 'status': int(status) if status.lstrip('-').isdigit() else status}
            except Exception:
                launchctl_status = {}
            
            for job in jobs:
                label = job.get('label', '')
                if label:
                    info = launchctl_status.get(label, {})
                    pid = info.get('pid', '-')
                    status = info.get('status', -1)
                    
                    if pid != '-':
                        loaded_jobs.append(label)
                    elif status != 0 and pid == '-':
                        failed_jobs.append(label)
                    elif pid == '-' and status == 0:
                        loaded_jobs.append(label)
                    else:
                        failed_jobs.append(label)
            
            return {
                "status": "healthy" if not failed_jobs else "degraded",
                "component": "launchd",
                "enabled_count": len(jobs),
                "loaded_count": len(loaded_jobs),
                "failed_jobs": failed_jobs
            }
        except Exception as e:
            return {"status": "unhealthy", "component": "launchd", "error": str(e)}
    
    async def check_all(self) -> Dict[str, Any]:
        """Run all health checks."""
        checks = await asyncio.gather(
            self.check_database(),
            self.check_model_router(),
            self.check_mlx(),
            self.check_nim(),
            self.check_launchd_jobs(),
            return_exceptions=True
        )
        
        results = []
        overall_status = "healthy"
        
        for check in checks:
            if isinstance(check, Exception):
                results.append({"status": "unhealthy", "component": "unknown", "error": str(check)})
                overall_status = "unhealthy"
            else:
                results.append(check)
                if check.get("status") == "unhealthy":
                    overall_status = "unhealthy"
                elif check.get("status") == "degraded" and overall_status == "healthy":
                    overall_status = "degraded"
        
        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "checks": results
        }
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global health checker instance
health_checker = HealthChecker()


# ============================================================================
# Metrics Endpoint
# ============================================================================

def metrics_endpoint() -> Response:
    """Prometheus metrics endpoint."""
    # Collect latest metrics before serving
    collect_all_metrics()
    return Response(content=generate_latest(REGISTRY), media_type="text/plain")


# ============================================================================
# Lifespan Manager
# ============================================================================

@asynccontextmanager
async def observability_lifespan(app):
    """Lifespan handler for observability components."""
    # Startup
    logger = get_logger("observability")
    logger.info("Observability module starting up")
    
    # Initial metrics collection
    await collect_all_metrics()
    
    yield
    
    # Shutdown
    logger.info("Observability module shutting down")
    await health_checker.close()