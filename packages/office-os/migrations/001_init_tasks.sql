-- office-core task database schema
-- Version 1: Initial schema

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, failed, cancelled, blocked
    priority INTEGER DEFAULT 0,              -- higher = more urgent
    assignee TEXT,                           -- agent name or 'human'
    source TEXT,                             -- origin: cli, api, hud, scheduler, webhook
    tags TEXT,                               -- comma-separated
    depends_on TEXT,                         -- JSON array of task IDs
    metadata TEXT,                           -- JSON blob for extensibility
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    failed_at TIMESTAMP,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC);

-- Task events log (append-only, for audit/history)
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,   -- created, started, completed, failed, updated, assigned, blocked, unblocked
    payload TEXT,               -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id);
CREATE INDEX IF NOT EXISTS idx_task_events_type ON task_events(event_type);

-- Agent registry
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    type TEXT NOT NULL,              -- llm, script, daemon, bridge, monitor
    model TEXT,                      -- model name or 'none'
    tools TEXT,                      -- JSON array of tool names
    policy TEXT,                     -- JSON: permissions, limits, timeouts
    launchd_label TEXT,              -- e.g., com.aryan.office-core.agent-name
    health_endpoint TEXT,            -- HTTP endpoint for health checks
    schedule TEXT,                   -- cron or interval (e.g., "*/5 * * * *", "30s")
    enabled BOOLEAN DEFAULT 1,
    metadata TEXT,                   -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Model router config
CREATE TABLE IF NOT EXISTS model_routes (
    name TEXT PRIMARY KEY,
    backend TEXT NOT NULL,           -- mlx, nim, free-harness, ollama, openai, anthropic
    endpoint TEXT NOT NULL,          -- URL
    models TEXT,                     -- JSON array of model names this route serves
    priority INTEGER DEFAULT 0,      -- higher = preferred
    enabled BOOLEAN DEFAULT 1,
    config TEXT,                     -- JSON: api_key, timeout, max_tokens, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Launchd job definitions (generated from agents)
CREATE TABLE IF NOT EXISTS launchd_jobs (
    label TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    program TEXT NOT NULL,           -- Full command with args (JSON array)
    working_directory TEXT,
    environment TEXT,                -- JSON object
    run_at_load BOOLEAN DEFAULT 1,
    keep_alive BOOLEAN DEFAULT 1,
    throttle_interval INTEGER DEFAULT 30,
    start_calendar_interval TEXT,    -- JSON for calendar intervals
    standard_out_path TEXT,
    standard_error_path TEXT,
    process_type TEXT,               -- Background, Standard, Adaptive
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_name) REFERENCES agents(name)
);

-- System state / key-value
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trigger to update updated_at
CREATE TRIGGER IF NOT EXISTS update_tasks_timestamp
AFTER UPDATE ON tasks
BEGIN
    UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_agents_timestamp
AFTER UPDATE ON agents
BEGIN
    UPDATE agents SET updated_at = CURRENT_TIMESTAMP WHERE name = NEW.name;
END;

CREATE TRIGGER IF NOT EXISTS update_model_routes_timestamp
AFTER UPDATE ON model_routes
BEGIN
    UPDATE model_routes SET updated_at = CURRENT_TIMESTAMP WHERE name = NEW.name;
END;

CREATE TRIGGER IF NOT EXISTS update_launchd_jobs_timestamp
AFTER UPDATE ON launchd_jobs
BEGIN
    UPDATE launchd_jobs SET updated_at = CURRENT_TIMESTAMP WHERE label = NEW.label;
END;