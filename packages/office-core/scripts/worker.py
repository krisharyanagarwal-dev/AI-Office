#!/usr/bin/env python3
"""
office-core Worker Daemon
Polls task database for assigned tasks and executes them.
"""

import os
import sys
import json
import time
import signal
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import (
    list_tasks, update_task, get_task,
    list_agents, get_agent,
    init_db
)
from observability import setup_json_logging

# Setup structured JSON logging for each worker role
_worker_loggers: Dict[str, logging.Logger] = {}

def get_worker_logger(role: str) -> logging.Logger:
    """Get or create a structured JSON logger for a worker role."""
    if role not in _worker_loggers:
        _worker_loggers[role] = setup_json_logging(f"worker.{role}")
    return _worker_loggers[role]

class Worker:
    def __init__(self, role: str, poll_interval: int = 30):
        self.role = role
        self.poll_interval = poll_interval
        self.running = False
        self.current_task: Optional[Dict] = None
        self.work_dir = Path.home() / "AI-Office" / "packages" / "office-core" / "workers" / role
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        # Create role-specific logger with structured JSON formatting
        self.logger = get_worker_logger(role)
        
        # Role-specific executors
        self.executors = {
            "backend": self._exec_backend,
            "frontend": self._exec_frontend,
            "infrastructure": self._exec_infrastructure,
            "ai-model": self._exec_ai_model,
            "automation": self._exec_automation,
            "qa": self._exec_qa,
            "security": self._exec_security,
            "research": self._exec_research,
            "auditor": self._exec_auditor,
        }
    
    def start(self):
        """Start the worker loop."""
        self.running = True
        self.logger.info("Worker starting", extra={"role": self.role})
        init_db()
        
        while self.running:
            try:
                self._poll_and_execute()
            except Exception as e:
                self.logger.error("Worker error", extra={"role": self.role, "error": str(e)})
            time.sleep(self.poll_interval)
        
        self.logger.info("Worker stopped", extra={"role": self.role})
    
    def stop(self):
        """Stop the worker."""
        self.running = False
    
    def _poll_and_execute(self):
        """Poll for pending tasks and execute one."""
        tasks = list_tasks(status="pending", assignee=self.role, limit=1)
        if not tasks:
            return
        
        task = tasks[0]
        task_id = task["id"]
        self.logger.info("Worker claimed task", extra={"role": self.role, "task_id": task_id, "title": task['title']})
        
        # Mark in progress
        update_task(task_id, status="in_progress")
        self.current_task = task
        
        try:
            # Execute based on role
            executor = self.executors.get(self.role)
            if executor:
                result = executor(task)
                update_task(task_id, status="completed", metadata=result)
                self.logger.info("Worker completed task", extra={"role": self.role, "task_id": task_id})
            else:
                self.logger.warning("Worker no executor for role", extra={"role": self.role})
                update_task(task_id, status="failed", error=f"No executor for role {self.role}")
        except Exception as e:
            self.logger.error("Worker task failed", extra={"role": self.role, "task_id": task_id, "error": str(e)})
            update_task(task_id, status="failed", error=str(e))
        finally:
            self.current_task = None
    
    # --- Role-specific executors ---
    
    def _exec_backend(self, task: Dict) -> Dict:
        """Execute backend tasks: API server, migrations, etc."""
        title = task["title"]
        
        if "API server" in title:
            return self._build_api_server()
        elif "Migrate tasks from office-os" in title:
            return self._migrate_office_os()
        elif "Migrate tasks from office-manager" in title:
            return self._migrate_office_manager()
        else:
            return {"status": "skipped", "reason": f"Unknown backend task: {title}"}
    
    def _build_api_server(self) -> Dict:
        """Create office-core API server (FastAPI)."""
        api_file = self.work_dir / "api.py"
        api_content = '''#!/usr/bin/env python3
"""
office-core API Server
FastAPI on :8080 - REST API for tasks, agents, models, launchd
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

from db import (
    list_tasks, get_task, create_task, update_task, delete_task,
    list_agents, get_agent, upsert_agent, delete_agent,
    list_model_routes, get_model_route, upsert_model_route,
    list_launchd_jobs, get_launchd_job, upsert_launchd_job,
    init_db
)

init_db()

app = FastAPI(title="office-core API", version="1.0.0")

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

@app.get("/health")
def health():
    return {"status": "ok", "service": "office-core-api"}

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
def create_task_endpoint(task: TaskCreate):
    import uuid
    task_id = str(uuid.uuid4())[:8]
    create_task(
        id=task_id, title=task.title, description=task.description,
        priority=task.priority, assignee=task.assignee,
        source=task.source, tags=task.tags, depends_on=task.depends_on
    )
    return {"id": task_id, "status": "created"}

@app.get("/tasks/{task_id}")
def get_task_endpoint(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task

@app.patch("/tasks/{task_id}")
def update_task_endpoint(task_id: str, update: TaskUpdate):
    updates = update.model_dump(exclude_unset=True)
    if update_task(task_id, **updates):
        return {"status": "updated"}
    raise HTTPException(404, "Task not found")

@app.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: str):
    if delete_task(task_id):
        return {"status": "deleted"}
    raise HTTPException(404, "Task not found")

# --- Agents ---
@app.get("/agents")
def get_agents(enabled_only: bool = False):
    agents = list_agents(enabled_only=enabled_only)
    return {"agents": agents}

@app.post("/agents")
def create_agent(agent: AgentCreate):
    upsert_agent(
        name=agent.name, type=agent.type, model=agent.model,
        tools=agent.tools, policy=agent.policy,
        launchd_label=agent.launchd_label,
        health_endpoint=agent.health_endpoint,
        schedule=agent.schedule, enabled=agent.enabled
    )
    return {"status": "created"}

@app.get("/agents/{name}")
def get_agent_endpoint(name: str):
    agent = get_agent(name)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent

# --- Models ---
@app.get("/models")
def get_models(enabled_only: bool = False):
    routes = list_model_routes(enabled_only=enabled_only)
    return {"routes": routes}

@app.post("/models")
def create_model_route(route: ModelRouteCreate):
    upsert_model_route(
        name=route.name, backend=route.backend, endpoint=route.endpoint,
        models=route.models, priority=route.priority,
        enabled=route.enabled, config=route.config
    )
    return {"status": "created"}

# --- Launchd ---
@app.get("/launchd")
def get_launchd(enabled_only: bool = False):
    jobs = list_launchd_jobs(enabled_only=enabled_only)
    return {"jobs": jobs}

@app.post("/launchd")
def create_launchd(job: LaunchdJobCreate):
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
    return {"status": "created"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
'''
        api_file.write_text(api_content)
        
        # Start API server in background
        subprocess.Popen(
            [sys.executable, str(api_file)],
            cwd=str(self.work_dir),
            stdout=open(self.work_dir / "api.out.log", "w"),
            stderr=open(self.work_dir / "api.err.log", "w")
        )
        time.sleep(2)
        
        # Verify
        import urllib.request
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5) as resp:
                if resp.status == 200:
                    return {"status": "success", "message": "API server running on :8080"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
        return {"status": "started", "message": "API server process launched"}
    
    def _migrate_office_os(self) -> Dict:
        """Migrate tasks from office-os/tasks."""
        import glob
        from pathlib import Path
        
        task_files = glob.glob("/Users/aryanagarwal/AI-Office/office-os/tasks/**/*", recursive=True)
        count = 0
        for tf in task_files:
            if tf.endswith((".json", ".md", ".txt", ".yaml", ".yml")):
                try:
                    with open(tf) as f:
                        content = f.read()
                    task_id = Path(tf).stem[:8]
                    from db import create_task
                    create_task(
                        id=task_id,
                        title=Path(tf).name,
                        description=content[:500],
                        source="office-os-migration",
                        metadata={"original_path": tf}
                    )
                    count += 1
                except Exception as e:
                    pass
        return {"status": "completed", "migrated": count}
    
    def _migrate_office_manager(self) -> Dict:
        """Migrate tasks from office-manager/collect."""
        import glob
        from pathlib import Path
        
        collect_files = glob.glob("/Users/aryanagarwal/AI-Office/office-manager/collect/**/*", recursive=True)
        count = 0
        for cf in collect_files:
            if cf.endswith((".json", ".md", ".txt", ".yaml", ".yml")):
                try:
                    with open(cf) as f:
                        content = f.read()
                    task_id = Path(cf).stem[:8]
                    from db import create_task
                    create_task(
                        id=task_id,
                        title=Path(cf).name,
                        description=content[:500],
                        source="office-manager-migration",
                        metadata={"original_path": cf}
                    )
                    count += 1
                except Exception as e:
                    pass
        return {"status": "completed", "migrated": count}
    
    def _exec_frontend(self, task: Dict) -> Dict:
        """Execute frontend tasks: HUD v2."""
        return {"status": "stubbed", "message": "Frontend task - implement HUD v2"}
    
    def _exec_infrastructure(self, task: Dict) -> Dict:
        """Execute infrastructure tasks: Prometheus, logging, tracing."""
        return {"status": "stubbed", "message": "Infrastructure task"}
    
    def _exec_ai_model(self, task: Dict) -> Dict:
        """Execute AI/model tasks."""
        return {"status": "stubbed", "message": "AI/Model task"}
    
    def _exec_automation(self, task: Dict) -> Dict:
        """Execute automation tasks: archiving."""
        return {"status": "stubbed", "message": "Automation task"}
    
    def _exec_qa(self, task: Dict) -> Dict:
        """Execute QA tasks."""
        return {"status": "stubbed", "message": "QA task"}
    
    def _exec_security(self, task: Dict) -> Dict:
        """Execute security tasks."""
        return {"status": "stubbed", "message": "Security task"}
    
    def _exec_research(self, task: Dict) -> Dict:
        """Execute research/documentation tasks."""
        title = task["title"]
        docs_dir = Path.home() / "AI-Office" / "packages" / "office-core" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        
        if "ARCHITECTURE" in title:
            doc_file = docs_dir / "OFFICE_CORE_ARCHITECTURE.md"
            doc_file.write_text("# Office Core Architecture\n\nDocumentation pending.\n")
        elif "AGENT_DEVELOPMENT" in title:
            doc_file = docs_dir / "AGENT_DEVELOPMENT_GUIDE.md"
            doc_file.write_text("# Agent Development Guide\n\nDocumentation pending.\n")
        elif "MODEL_ROUTER" in title:
            doc_file = docs_dir / "MODEL_ROUTER_CONFIG.md"
            doc_file.write_text("# Model Router Configuration\n\nDocumentation pending.\n")
        elif "LAUNCHD_MANAGEMENT" in title:
            doc_file = docs_dir / "LAUNCHD_MANAGEMENT.md"
            doc_file.write_text("# Launchd Management\n\nDocumentation pending.\n")
        else:
            return {"status": "skipped"}
        return {"status": "created", "file": str(doc_file)}
    
    def _exec_auditor(self, task: Dict) -> Dict:
        """Execute auditor tasks."""
        return {"status": "stubbed", "message": "Auditor task"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="office-core Worker")
    parser.add_argument("role", choices=[
        "backend", "frontend", "infrastructure", "ai-model",
        "automation", "qa", "security", "research", "auditor"
    ])
    parser.add_argument("--interval", type=int, default=30, help="Poll interval (seconds)")
    args = parser.parse_args()
    
    worker = Worker(args.role, args.interval)
    
    def signal_handler(sig, frame):
        worker.stop()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    worker.start()

if __name__ == "__main__":
    main()