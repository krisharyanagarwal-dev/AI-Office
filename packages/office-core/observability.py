#!/usr/bin/env python3
"""
Observability module for office-core
Prometheus metrics, structured JSON logging, SSE events, health checks
"""

import asyncio
import json
import logging
import logging.handlers
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncGenerator

import httpx
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CollectorRegistry
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

# Add parent to path for db imports
sys.path.insert(0, str(Path(__file__).parent))
from db import (
    list_tasks, list_agents, list_model_routes, list_launchd_jobs,
    get_conn
)

# ============================================================================
# Prometheus Metrics
# ============================================================================

# Create a custom registry for office-core metrics
REGISTRY = CollectorRegistry()

# Task metrics
TASKS_TOTAL = Gauge(
    "office_core_tasks_total",
    "Total tasks by status",
    ["status"],
    registry=REGISTRY
)
TASKS_CREATED = Counter(
    "office_core_tasks_created_total",
    "Total tasks created",
    ["source"],
    registry=REGISTRY
)
TASKS_UPDATED = Counter(
    "office_core_tasks_updated_total",
    "Total tasks updated",
    ["status"],
    registry=REGISTRY
)
TASKS_DELETED = Counter(
    "office_core_tasks_deleted_total",
    "Total tasks deleted",
    registry=REGISTRY
)

# Agent metrics
AGENTS_TOTAL = Gauge(
    "office_core_agents_total",
    "Total agents by enabled status",
    ["enabled"],
    registry=REGISTRY
)
AGENT_HEALTH = Gauge(
    "office_core_agent_healthy",
    "Agent health status (1=healthy, 0=unhealthy)",
    ["agent_name"],
    registry=REGISTRY
)

# Model router metrics
MODEL_ROUTES_TOTAL = Gauge(
    "office_core_model_routes_total",
    "Total model routes by enabled status",
    ["enabled"],
    registry=REGISTRY
)
MODEL_ROUTER_BACKEND_HEALTHY = Gauge(
    "office_core_model_router_backend_healthy",
    "Model router backend health status",
    ["backend_name", "backend_type"],
    registry=REGISTRY
)
MODEL_ROUTER_BACKEND_FAILURES = Counter(
    "office_core_model_router_backend_failures_total",
    "Model router backend consecutive failures",
    ["backend_name"],
    registry=REGISTRY
)
MODEL_ROUTER_REQUESTS = Counter(
    "office_core_model_router_requests_total",
    "Model router requests routed",
    ["backend_name", "model"],
    registry=REGISTRY
)

# Launchd metrics
LAUNCHD_JOBS_TOTAL = Gauge(
    "office_core_launchd_jobs_total",
    "Total launchd jobs by enabled status",
    ["enabled"],
    registry=REGISTRY
)
LAUNCHD_JOB_STATUS = Gauge(
    "office_core_launchd_job_status",
    "Launchd job status (1=loaded/enabled, 0=disabled)",
    ["label", "agent_name"],
    registry=REGISTRY
)

# API metrics
API_REQUESTS = Counter(
    "office_core_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY
)
API_REQUEST_DURATION = Histogram(
    "office_core_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint"],
    registry=REGISTRY
)

# System metrics
DB_CONNECTIONS = Gauge(
    "office_core_db_connections_active",
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
        logging.getLogger("observability").error(f"Failed to collect task metrics: {e}")


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
        logging.getLogger("observability").error(f"Failed to collect agent metrics: {e}")


def collect_model_route_metrics():
    """Collect model route metrics from database."""
    try:
        routes = list_model_routes()
        enabled_count = sum(1 for r in routes if r.get("enabled"))
        disabled_count = len(routes) - enabled_count
        
        MODEL_ROUTES_TOTAL.labels(enabled="true").set(enabled_count)
        MODEL_ROUTES_TOTAL.labels(enabled="false").set(disabled_count)
    except Exception as e:
        logging.getLogger("observability").error(f"Failed to collect model route metrics: {e}")


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
        logging.getLogger("observability").error(f"Failed to collect launchd metrics: {e}")


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
# Structured JSON Logging
# ============================================================================

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": getattr(record, "service", "office-core"),
            "message": record.getMessage(),
            "fields": {}
        }
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in ["name", "msg", "args", "created", "filename", "funcName",
                          "levelname", "levelno", "lineno", "module", "msecs",
                          "message", "name", "pathname", "process", "processName",
                          "relativeCreated", "thread", "threadName", "exc_info",
                          "exc_text", "stack_info", "service", "taskName"]:
                log_entry["fields"][key] = value
        
        # Add exception info if present
        if record.exc_info:
            log_entry["fields"]["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


def setup_json_logging(service_name: str, log_dir: Optional[Path] = None) -> logging.Logger:
    """Setup structured JSON logging for a service with daily rotation."""
    if log_dir is None:
        log_dir = Path.home() / "AI-Office" / "packages" / "office-core" / "logs"
    
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{service_name}.log"
    
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # Clear existing handlers
    
    # File handler with JSON formatting and daily rotation
    # Keeps 30 days of logs
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setFormatter(JSONFormatter())
    file_handler.suffix = "%Y-%m-%d"
    logger.addHandler(file_handler)
    
    # Console handler with JSON formatting
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger


# ============================================================================
# SSE Event System
# ============================================================================

class EventBroadcaster:
    """Manages SSE connections and broadcasts events."""
    
    def __init__(self, max_queue_size: int = 100):
        self.queues: List[asyncio.Queue] = []
        self.max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
    
    async def add_connection(self) -> asyncio.Queue:
        """Add a new SSE connection and return its queue."""
        queue = asyncio.Queue(maxsize=self.max_queue_size)
        async with self._lock:
            self.queues.append(queue)
        return queue
    
    async def remove_connection(self, queue: asyncio.Queue):
        """Remove an SSE connection."""
        async with self._lock:
            if queue in self.queues:
                self.queues.remove(queue)
    
    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """Broadcast an event to all connected clients."""
        event_data = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        
        async with self._lock:
            for queue in self.queues[:]:
                try:
                    queue.put_nowait(event_data)
                except asyncio.QueueFull:
                    # Remove full queues
                    self.queues.remove(queue)
    
    async def broadcast_task_event(self, event_type: str, task_id: str, data: Dict[str, Any]):
        """Broadcast a task-related event."""
        await self.broadcast(event_type, {
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_agent_event(self, event_type: str, agent_name: str, data: Dict[str, Any]):
        """Broadcast an agent-related event."""
        await self.broadcast(event_type, {
            "agent_name": agent_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_model_event(self, event_type: str, backend_name: str, data: Dict[str, Any]):
        """Broadcast a model router backend event."""
        await self.broadcast(event_type, {
            "backend_name": backend_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_launchd_event(self, event_type: str, label: str, data: Dict[str, Any]):
        """Broadcast a launchd job event."""
        await self.broadcast(event_type, {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })


# Global event broadcaster instance
event_broadcaster = EventBroadcaster()


async def sse_event_generator(request: Request, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """Generate SSE events for a connection."""
    try:
        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
        
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield event
            except asyncio.TimeoutError:
                # Send heartbeat
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
    finally:
        await event_broadcaster.remove_connection(queue)


# ============================================================================
# Health Check Aggregation
# ============================================================================

class HealthChecker:
    """Aggregates health checks for all office-core dependencies."""
    
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
                        # Running now. The status column is the PREVIOUS exit
                        # (e.g. -15 after a kickstart), so it does not mean failed.
                        loaded_jobs.append(label)
                    elif status != 0 and pid == '-':
                        # Exited with non-zero = failed
                        failed_jobs.append(label)
                    elif pid == '-' and status == 0:
                        # Scheduled job not currently running = OK (not failed)
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
    logger = logging.getLogger("observability")
    logger.info("Observability module starting up")
    
    # Initial metrics collection
    await collect_all_metrics()
    
    yield
    
    # Shutdown
    logger.info("Observability module shutting down")
    await health_checker.close()