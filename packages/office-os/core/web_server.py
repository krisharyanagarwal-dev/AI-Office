"""
Office OS Web Server - Localhost web UI using Python stdlib http.server.
No installs. Access at http://localhost:8083
User-based: login required, each user sees only their own tasks.
"""
import glob
import json
import logging
import os
import sys
import uuid
import time
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "office-os"))
from core.hive import Hive
from core.router import ProviderRouter
from agents.god_agent import GodAgent

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "dost"))
# `workspace` and `activity_feed` moved into the `collab` subpackage in
# ec37280d ("group 36 modules into 7 subpackages"). The bare imports below
# stopped resolving, so this module died at import time with
# "ModuleNotFoundError: No module named 'workspace'" and the launchd job
# crash-looped (109 runs, exit 1) instead of serving anything. The sibling
# callers were updated in the same refactor -- dost/dost.py and
# dost/setup_wizard.py both use `from collab.workspace import ...` -- and this
# one was missed.
from collab.workspace import (
    workspace_exists,
    get_workspace,
    can_access_workspace,
    can_edit_workspace,
    list_workspaces,
    workspace_tasks_dir,
    workspace_findings_dir,
    create_workspace,
    DEFAULT_WORKSPACE_ID,
)
from billing.meter import get_usage_summary, get_current_month_cost, workspace_pnl_dir
from billing.plans import get_plan, calculate_monthly_cost

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "dost"))
from collab.activity_feed import get_activity_feed
from memory_pkg.unified import get_unified_memory

OFFICE_ROOT = (Path(__file__).resolve().parents[3] / "packages" / "office-os")
CONFIG_DIR = OFFICE_ROOT / "config"


def advisory_cost_cap_limit():
    """Daily synthetic cost ceiling from office.json; None when not configured."""
    try:
        cfg = json.loads((CONFIG_DIR / "office.json").read_text())
        cap = (cfg.get("cost_cap") or {}) if isinstance(cfg, dict) else {}
        value = cap.get("daily_units")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = int(value)
        return value if value > 0 else None
    except Exception:
        return None


def _daily_ledger_cost(pnl_path: Path) -> int:
    """Cost booked in the ledger's local day.

    office_pnl.json entries are stamped with local wall-clock time, so the day
    key used to sum them must be local too. A UTC key reads the previous
    local day's spend as "today" for part of every local day.
    """
    pnl = json.loads(pnl_path.read_text())
    if not isinstance(pnl, list):
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(
        t.get("cost_units", 0)
        for t in pnl
        if isinstance(t, dict) and str(t.get("created_at", "")).startswith(today)
    )


def _workspace_pnl_costs(pnl_dir: Path) -> dict:
    """Aggregate the workspace P&L entries by local day.

    Entries are stamped with local wall-clock time, so the day keys used to
    bucket them must be local too.
    """
    stats = {
        "cost_units_today": 0,
        "net_value_today": 0,
        "tasks_completed_today": 0,
        "debate_calls_today": 0,
        "voice_dispatches_today": 0,
        "cost_per_agent": {},
        "cost_per_type": {},
        "cost_yesterday": 0,
    }
    if not pnl_dir.exists():
        return stats

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    for f in sorted(pnl_dir.iterdir()):
        if f.suffix != ".json":
            continue
        try:
            raw = json.loads(f.read_text())
        except Exception:
            continue
        entries = raw if isinstance(raw, list) else [raw]
        for t in entries:
            if not isinstance(t, dict):
                continue
            created = t.get("created_at", "")
            day = created[:10] if created else ""
            cost = int(t.get("cost_units", 0) or 0)
            agent = t.get("agent_id", "unknown")
            mtype = t.get("metric_type", "task")
            if day == today_str:
                stats["cost_units_today"] += cost
                stats["net_value_today"] += int(t.get("net_value", 0) or 0)
                per_agent = stats["cost_per_agent"]
                per_agent[agent] = per_agent.get(agent, 0) + cost
                per_type = stats["cost_per_type"]
                per_type[mtype] = per_type.get(mtype, 0) + cost
                if t.get("status") == "done":
                    stats["tasks_completed_today"] += 1
                if t.get("source") == "debate":
                    stats["debate_calls_today"] += 1
                md = t.get("metadata", {}) or {}
                if md.get("voice_dispatch"):
                    stats["voice_dispatches_today"] += 1
            elif day == yesterday_str:
                stats["cost_yesterday"] += cost
    return stats

# Qwen autonomous worker directories
QWEN_DIR = (Path.home() / ".openclaw" / "autonomous-qwen")
TASK_QUEUE_DIR = QWEN_DIR / "queue"
QWEN_RESULT_DIR = QWEN_DIR / "results"
os.makedirs(TASK_QUEUE_DIR, exist_ok=True)
os.makedirs(QWEN_RESULT_DIR, exist_ok=True)

# Hive tasks directory (Office OS)
HIVE_DIR = str(OFFICE_ROOT / "tasks")

# JEV dispatcher log & kill switch (used by the public /dashboard route)
JEV_LOG = str(Path.home() / ".openclaw" / "jev-dispatcher.log")
KILL_SWITCH_PATH = str(Path(__file__).resolve().parents[3] / "packages" / "_archive" / "openalice-fleet" / "state" / "trader_killswitch_status.json")

# Stock bot metrics file (written by all_stocks_bot.py after each run)
STOCKS_METRICS_FILE = (Path.home() / ".openclaw" / "stocks_metrics.json")

# Load users
with open(CONFIG_DIR / "users.json") as f:
    USERS_CONFIG = json.load(f)

USERS = USERS_CONFIG["users"]
SESSIONS = USERS_CONFIG.get("sessions", {})
SESSION_TIMEOUT = USERS_CONFIG.get("session_timeout_sec", 86400)


def save_sessions():
    USERS_CONFIG["sessions"] = SESSIONS
    with open(CONFIG_DIR / "users.json", "w") as f:
        json.dump(USERS_CONFIG, f, indent=2)


def create_session(user_id):
    sid = str(uuid.uuid4())[:16]
    SESSIONS[sid] = {
        "user_id": user_id,
        "created_at": time.time(),
    }
    save_sessions()
    return sid


def get_current_user(cookie_header):
    if not cookie_header:
        return None, None
    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith("office_session="):
            sid = cookie.split("=", 1)[1]
            session = SESSIONS.get(sid)
            if session and (time.time() - session.get("created_at", 0)) < SESSION_TIMEOUT:
                return session["user_id"], sid
    return None, None


def require_login(handler_method):
    def wrapper(self, *args, **kwargs):
        user_id, sid = get_current_user(self.headers.get("Cookie", ""))
        if not user_id:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        self.current_user = user_id
        self.current_sid = sid
        return handler_method(self, *args, **kwargs)
    return wrapper


class RateLimiter:
    """In-memory rate limiter tracking requests per API key per minute.

    Each API key gets a fixed 60-second window. Requests are counted per key;
    once the count exceeds the key's limit, further requests are rejected until
    the window resets.
    """

    def __init__(self, default_limit: int = 60):
        self.default_limit = default_limit
        self._limits = {}   # api_key -> custom limit (int)
        self._buckets = {}  # api_key -> {"count": int, "reset": float}

    def set_limit(self, api_key: str, limit: int):
        """Configure a custom per-minute limit for a specific API key."""
        self._limits[api_key] = int(limit)

    def check(self, api_key: str) -> dict:
        """Return rate limit status for *api_key*.

        Returns: {"limit", "remaining", "reset", "allowed", "retry_after"}.
        """
        now = time.time()
        limit = self._limits.get(api_key, self.default_limit)
        bucket = self._buckets.get(api_key)
        if bucket is None or now >= bucket["reset"]:
            bucket = {"count": 0, "reset": now + 60}
            self._buckets[api_key] = bucket
        bucket["count"] += 1
        remaining = max(0, limit - bucket["count"])
        allowed = bucket["count"] <= limit
        retry_after = max(0, int(bucket["reset"] - now)) if not allowed else 0
        return {
            "limit": limit,
            "remaining": remaining,
            "reset": int(bucket["reset"]),
            "allowed": allowed,
            "retry_after": retry_after,
        }


RATE_LIMITER = RateLimiter()


# Simple HTML template - CSS braces doubled to escape Python .format()
LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Office OS - Login</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #0f0f0f; color: #e0e0e0; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 2rem; width: 100%; max-width: 400px; }
        h1 { margin-top: 0; font-size: 1.25rem; color: #10b981; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.25rem; font-size: 0.85rem; color: #94a3b8; }
        .form-group input { width: 100%; background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.5rem; color: #e0e0e0; font-family: inherit; }
        .btn { background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: 600; width: 100%; }
        .btn:hover { background: #2563eb; }
        .users { margin-top: 1rem; font-size: 0.8rem; color: #64748b; }
        .users div { margin-bottom: 0.25rem; }
    </style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="card">
        <h1>🏢 Office OS Login</h1>
        <form method="POST" action="/login">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required placeholder="aryan or demo">
            </div>
            <button class="btn" type="submit">Sign in</button>
        </form>
        <div class="users">
            <div>• aryan (owner)</div>
            <div>• demo (user)</div>
        </div>
    </div>

    <script>
    // Chart.js charts
    const charts = {};

    function initCharts() {
        // Fetch metrics
        fetch('/metrics')
            .then(r => r.json())
            .then(data => {
                const jev = data.jev || {};
                const pools = data.provider_pools || {};

                // Completion rate chart
                const completionCtx = document.getElementById('completionChart');
                if (completionCtx) {
                    charts.completion = new Chart(completionCtx.getContext('2d'), {
                        type: 'gauge',
                        data: {
                            labels: ['Completion Rate'],
                            datasets: [{
                                data: [Math.min(100, jev.completion_rate || 0)],
                                backgroundColor: '#10b981',
                                borderColor: '#ffffff',
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                title: { display: true, text: 'Task Completion Rate (%)' }
                            },
                            scales: {
                                y: { min: 0, max: 100 }
                            }
                        }
                    });
                }

                // Error rate chart
                const errorCtx = document.getElementById('errorChart');
                if (errorCtx) {
                    charts.error = new Chart(errorCtx.getContext('2d'), {
                        type: 'gauge',
                        data: {
                            labels: ['Error Rate (%)'],
                            datasets: [{
                                data: [Math.min(100, jev.error_rate || 0)],
                                backgroundColor: '#ef4444',
                                borderColor: '#ffffff',
                                borderWidth: 2
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                title: { display: true, text: 'Error Rate (%)' }
                            },
                            scales: { y: { min: 0, max: 100 } }
                        }
                    });
                }

                // Pool status chart
                const poolCtx = document.getElementById('poolChart');
                if (poolCtx && pools) {
                    const poolNames = Object.keys(pools);
                    const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                    charts.pools = new Chart(poolCtx.getContext('2d'), {
                        type: 'bar',
                        data: {
                            labels: poolNames.map(p => p.split('_')[0]),
                            datasets: [{
                                label: 'Pool Status',
                                data: poolValues,
                                backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                            }]
                        },
                        options: {
                            responsive: true,
                            scales: {
                                y: { min: 0, max: 1, ticks: { display: false } }
                            },
                            plugins: {
                                legend: { display: false },
                                title: { display: true, text: 'Provider Pool Status' }
                            }
                        }
                    });
                }
            })
            .catch(err => console.error('Failed to load metrics:', err));
        }

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};
                    
                    // Update completion chart
                    if (charts.completion) {
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }
                    
                    // Update error chart
                    if (charts.error) {
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }
                })
                .catch(() => {});
        }, 30000);
    </script>

    <script>
        // Chart.js charts
        const charts = {};

        function initCharts() {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    // Completion rate chart
                    const completionCtx = document.getElementById('costChart');
                    if (completionCtx && !charts.completion) {
                        charts.completion = new Chart(completionCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Completion Rate'],
                                datasets: [{
                                    data: [Math.min(100, jev.completion_rate || 0)],
                                    backgroundColor: '#10b981',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Task Completion Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Error rate chart
                    const errorCtx = document.getElementById('errorChart');
                    if (errorCtx && !charts.error) {
                        charts.error = new Chart(errorCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Error Rate (%)'],
                                datasets: [{
                                    data: [Math.min(100, jev.error_rate || 0)],
                                    backgroundColor: '#ef4444',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Error Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Pool status chart
                    const poolCtx = document.getElementById('poolChart');
                    if (poolCtx && pools && !charts.pools) {
                        const poolNames = Object.keys(pools);
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools = new Chart(poolCtx.getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: poolNames.map(p => p.split('_')[0]),
                                datasets: [{
                                    label: 'Pool Status',
                                    data: poolValues,
                                    backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                                }]
                            },
                            options: {
                                responsive: true,
                                scales: {
                                    y: { min: 0, max: 1, ticks: { display: false } }
                                },
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Provider Pool Status' }
                                }
                            }
                        });
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};
                    
                    if (charts.completion) {
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }
                    
                    if (charts.error) {
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }
                    
                    if (charts.pools && pools) {
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools.data.datasets[0].data = poolValues;
                        charts.pools.update();
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }, 30000);
    </script>

    <script>
        // Chart.js charts
        const charts = {};

        function initCharts() {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    // Completion rate chart
                    const completionCtx = document.getElementById('costChart');
                    if (completionCtx && !charts.completion) {
                        charts.completion = new Chart(completionCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Completion Rate'],
                                datasets: [{
                                    data: [Math.min(100, jev.completion_rate || 0)],
                                    backgroundColor: '#10b981',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Task Completion Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Error rate chart
                    const errorCtx = document.getElementById('errorChart');
                    if (errorCtx && !charts.error) {
                        charts.error = new Chart(errorCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Error Rate (%)'],
                                datasets: [{
                                    data: [Math.min(100, jev.error_rate || 0)],
                                    backgroundColor: '#ef4444',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Error Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Pool status chart
                    const poolCtx = document.getElementById('poolChart');
                    if (poolCtx && pools && !charts.pools) {
                        const poolNames = Object.keys(pools);
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools = new Chart(poolCtx.getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: poolNames.map(p => p.split('_')[0]),
                                datasets: [{
                                    label: 'Pool Status',
                                    data: poolValues,
                                    backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                                }]
                            },
                            options: {
                                responsive: true,
                                scales: {
                                    y: { min: 0, max: 1, ticks: { display: false } }
                                },
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Provider Pool Status' }
                                }
                            }
                        });
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    if (charts.completion) {
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }

                    if (charts.error) {
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }

                    if (charts.pools && pools) {
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools.data.datasets[0].data = poolValues;
                        charts.pools.update();
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }, 30000);
    </script>

    <script>
        // Chart.js charts
        const charts = {};

        function initCharts() {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    // Completion rate chart
                    const completionCtx = document.getElementById('costChart');
                    if (completionCtx && !charts.completion) {
                        charts.completion = new Chart(completionCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Completion Rate'],
                                datasets: [{
                                    data: [Math.min(100, jev.completion_rate || 0)],
                                    backgroundColor: '#10b981',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Task Completion Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Error rate chart
                    const errorCtx = document.getElementById('errorChart');
                    if (errorCtx && !charts.error) {
                        charts.error = new Chart(errorCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Error Rate (%)'],
                                datasets: [{
                                    data: [Math.min(100, jev.error_rate || 0)],
                                    backgroundColor: '#ef4444',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Error Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Pool status chart
                    const poolCtx = document.getElementById('poolChart');
                    if (poolCtx && pools && !charts.pools) {
                        const poolNames = Object.keys(pools);
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools = new Chart(poolCtx.getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: poolNames.map(p => p.split('_')[0]),
                                datasets: [{
                                    label: 'Pool Status',
                                    data: poolValues,
                                    backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                                }]
                            },
                            options: {
                                responsive: true,
                                scales: {
                                    y: { min: 0, max: 1, ticks: { display: false } }
                                },
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Provider Pool Status' }
                                }
                            }
                        });
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    if (charts.completion) {
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }

                    if (charts.error) {
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }

                    if (charts.pools && pools) {
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools.data.datasets[0].data = poolValues;
                        charts.pools.update();
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }, 30000);
    </script>

    <script>
        // Chart.js charts
        const charts = {};

        function initCharts() {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    // Completion rate chart
                    const completionCtx = document.getElementById('costChart');
                    if (completionCtx && !charts.completion) {
                        charts.completion = new Chart(completionCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Completion Rate'],
                                datasets: [{
                                    data: [Math.min(100, jev.completion_rate || 0)],
                                    backgroundColor: '#10b981',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Task Completion Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Error rate chart
                    const errorCtx = document.getElementById('errorChart');
                    if (errorCtx && !charts.error) {
                        charts.error = new Chart(errorCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Error Rate (%)'],
                                datasets: [{
                                    data: [Math.min(100, jev.error_rate || 0)],
                                    backgroundColor: '#ef4444',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Error Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Pool status chart
                    const poolCtx = document.getElementById('poolChart');
                    if (poolCtx && pools && !charts.pools) {
                        const poolNames = Object.keys(pools);
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools = new Chart(poolCtx.getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: poolNames.map(p => p.split('_')[0]),
                                datasets: [{
                                    label: 'Pool Status',
                                    data: poolValues,
                                    backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                                }]
                            },
                            options: {
                                responsive: true,
                                scales: {
                                    y: { min: 0, max: 1, ticks: { display: false } }
                                },
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Provider Pool Status' }
                                }
                            }
                        });
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    if (charts.completion) {
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }

                    if (charts.error) {
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }

                    if (charts.pools && pools) {
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools.data.datasets[0].data = poolValues;
                        charts.pools.update();
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }, 30000);
    </script>

    <script>
        // Chart.js charts
        const charts = {};

        function initCharts() {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    // Completion rate chart
                    const completionCtx = document.getElementById('costChart');
                    if (completionCtx && !charts.completion) {
                        charts.completion = new Chart(completionCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Completion Rate'],
                                datasets: [{
                                    data: [Math.min(100, jev.completion_rate || 0)],
                                    backgroundColor: '#10b981',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Task Completion Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Error rate chart
                    const errorCtx = document.getElementById('errorChart');
                    if (errorCtx && !charts.error) {
                        charts.error = new Chart(errorCtx.getContext('2d'), {
                            type: 'gauge',
                            data: {
                                labels: ['Error Rate (%)'],
                                datasets: [{
                                    data: [Math.min(100, jev.error_rate || 0)],
                                    backgroundColor: '#ef4444',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Error Rate (%)' }
                                },
                                scales: {
                                    y: { min: 0, max: 100 }
                                }
                            }
                        });
                    }

                    // Pool status chart
                    const poolCtx = document.getElementById('poolChart');
                    if (poolCtx && pools && !charts.pools) {
                        const poolNames = Object.keys(pools);
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools = new Chart(poolCtx.getContext('2d'), {
                            type: 'bar',
                            data: {
                                labels: poolNames.map(p => p.split('_')[0]),
                                datasets: [{
                                    label: 'Pool Status',
                                    data: poolValues,
                                    backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                                }]
                            },
                            options: {
                                responsive: true,
                                scales: {
                                    y: { min: 0, max: 1, ticks: { display: false } }
                                },
                                plugins: {
                                    legend: { display: false },
                                    title: { display: true, text: 'Provider Pool Status' }
                                }
                            }
                        });
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {
                    const jev = data.jev || {};
                    const pools = data.provider_pools || {};

                    if (charts.completion) {
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }

                    if (charts.error) {
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }

                    if (charts.pools && pools) {
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools.data.datasets[0].data = poolValues;
                        charts.pools.update();
                    }
                })
                .catch(err => console.error('Failed to load metrics:', err));
        }, 30000);
    </script>
</body>
</html>
</html>"""

def _org_rows():
    """One row per office system from logs/org_state.json (written by the orchestrator)."""
    from core.orchestrator import ORG_STATE_PATH, load_org_digest
    try:
        doc = json.loads(ORG_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return f'<div class="empty">{escape(load_org_digest())}</div>'
    rows = ""
    for s in doc.get("systems", []):
        cls = "status-ok" if s.get("ok") else "status-cooldown"
        label = "OK" if s.get("ok") else "PROBLEM"
        problem = escape(s["problems"][0]) if s.get("problems") else ""
        rows += f"""
            <div class="provider">
                <span class="provider-name">{escape(s.get('name', '?'))}</span>
                <span><span class="status-badge {cls}">{label}</span></span>
                <span style="font-size:0.8rem;color:#64748b">{escape(s.get('summary', ''))} {problem}</span>
            </div>
            """
    rows += f'<div style="font-size:0.75rem;color:#64748b">Surveyed {escape(doc.get("generated_at", "?"))}</div>'
    return rows


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Office OS - Agent Fleet</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
        h1 {{ font-size: 1.5rem; margin: 0; display: flex; align-items: center; gap: 0.5rem; }}
        h1 .dot {{ width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .user-bar {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.5rem 1rem; font-size: 0.85rem; }}
        .user-bar .user-name {{ font-weight: 600; color: #10b981; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
        .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; }}
        .card h3 {{ margin-top: 0; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 0.75rem; }}
        .provider {{ display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid #2a2a2a; }}
        .provider:last-child {{ border-bottom: none; }}
        .provider-name {{ font-family: monospace; font-size: 0.85rem; }}
        .task {{ display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid #2a2a2a; }}
        .task:last-child {{ border-bottom: none; }}
        .task-id {{ font-family: monospace; font-size: 0.8rem; color: #64748b; }}
        .task-agent {{ font-size: 0.85rem; color: #cbd5e1; }}
        .task-title {{ font-size: 0.9rem; }}
        .status-badge {{ font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; font-weight: 600; }}
        .status-done {{ background: #10b981; color: white; }}
        .status-failed {{ background: #ef4444; color: white; }}
        .status-in_progress {{ background: #f59e0b; color: white; }}
        .status-pending {{ background: #64748b; color: white; }}
        .status-assigned {{ background: #3b82f6; color: white; }}
        .status-up {{ background: #10b981; color: white; }}
        .status-cooling {{ background: #f59e0b; color: white; }}
        .status-down {{ background: #ef4444; color: white; }}
        .sparkline {{ display: flex; align-items: flex-end; gap: 4px; height: 40px; margin-top: 0.5rem; }}
        .spark-bar {{ width: 6px; border-radius: 2px; }}
        .spark-bar-up {{ background: #10b981; }}
        .spark-bar-down {{ background: #ef4444; }}
        .spark-bar-idle {{ background: #2a2a2a; }}
        .spark-bar-cooling {{ background: #f59e0b; }}
        .spark-label {{ font-size: 0.65rem; color: #94a3b8; text-align: center; margin-top: 0.25rem; }}
        .spark-value {{ font-size: 0.7rem; font-family: monospace; color: #e0e0e0; }}
        .cooldown-timer {{ font-size: 0.7rem; color: #f59e0b; font-family: monospace; }}
        .result-card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-top: 1rem; }}
        .result-card pre {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; font-family: monospace; white-space: pre-wrap; }}
        .form-group {{ margin-bottom: 1rem; }}
        .form-group label {{ display: block; margin-bottom: 0.25rem; font-size: 0.85rem; color: #94a3b8; }}
        .form-group input, .form-group textarea, .form-group select {{ width: 100%; background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.5rem; color: #e0e0e0; font-family: inherit; }}
        .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: 600; }}
        .btn:hover {{ background: #2563eb; }}
        .refresh {{ margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }}
        .empty {{ color: #64748b; font-style: italic; }}
        .logout {{ color: #94a3b8; text-decoration: none; font-size: 0.85rem; }}
        .logout:hover {{ color: #e0e0e0; }}
        .qwen-card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-top: 1rem; }}
        .qwen-status {{ display: flex; justify-content: space-between; font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.75rem; }}
        .qwen-status .ok {{ color: #10b981; }}
        .qwen-status .bad {{ color: #ef4444; }}
        .qwen-form {{ display: flex; gap: 0.5rem; margin-top: 0.75rem; }}
        .qwen-form input[type="text"] {{ flex: 1; background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.5rem; color: #e0e0e0; font-family: inherit; }}
        .qwen-result {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; font-family: monospace; white-space: pre-wrap; margin-top: 0.75rem; }}
        .dispatch-form {{ display: flex; flex-direction: column; gap: 0.5rem; }}
        .dispatch-row {{ display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; }}
        .dispatch-btn {{ background: #10b981; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 0.85rem; }}
        .dispatch-btn:hover {{ background: #059669; }}
        .dispatch-btn.secondary {{ background: #2a2a2a; }}
        .dispatch-btn.secondary:hover {{ background: #3a3a3a; }}
        .dispatch-result {{ font-size: 0.75rem; margin-top: 0.5rem; min-height: 1.2rem; }}
        .quick-dispatch {{ display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.5rem; }}
    </style>
</head>
<body>
    <header>
        <h1><span class="dot"></span> Office OS — Agent Fleet</h1>
        <div>
            <a href="/task" class="btn" style="margin-right: 0.5rem;">+ New Task</a>
            <a href="/qwen" class="btn" style="margin-right: 0.5rem; background: #10b981;">Qwen Agent</a>
            <span class="user-bar">Signed in as <span class="user-name">{user_name}</span> ({user_role})</span>
            <a href="/logout" class="logout">Sign out</a>
        </div>
    </header>
    <div class="refresh">
        <button class="btn" onclick="location.reload()">Refresh</button>
        <span style="color: #64748b; font-size: 0.85rem;">http://localhost:8083</span>
    </div>

    <!-- Qwen Card -->
    <div class="qwen-card">
        <h3>🧠 Qwen3.5-9B Autonomous Agent</h3>
        <div class="qwen-status">
            <span id="qwen-status" class="qwen-status ok">● Checking...</span>
            <span>Pending: <span id="qwen-pending">-</span> | Completed: <span id="qwen-completed">-</span></span>
        </div>
        <form id="qwen-form" class="qwen-form">
            <input type="text" id="qwen-prompt" placeholder="Ask Qwen3.5-9B..." required />
            <button type="submit" class="btn">Send</button>
        </form>
        <div id="qwen-result" class="qwen-result"></div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Provider Pools</h3>
            {provider_html}
        </div>
        <div class="card">
            <h3>Your Tasks</h3>
            {task_html}
        </div>
        <div class="card">
            <h3>⚡ Dispatch Task</h3>
            <form id="dispatch-form" class="dispatch-form">
                <label style="font-size:0.75rem;color:#94a3b8">Prompt</label>
                <input type="text" id="dispatch-prompt" placeholder="e.g. What is the fleet completion rate?" required />
                <div class="dispatch-row">
                    <select id="dispatch-agent">
                        <option value="strategy-advisor">Strategy Advisor</option>
                        <option value="cost-analyst">Cost Analyst</option>
                        <option value="risk-manager">Risk Manager</option>
                        <option value="general-assistant">General Assistant</option>
                    </select>
                    <select id="dispatch-priority">
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                        <option value="low">Low</option>
                    </select>
                    <button type="submit" class="dispatch-btn">Dispatch</button>
                </div>
                <div class="quick-dispatch">
                    <button type="button" class="dispatch-btn secondary" onclick="quickDispatch('What is the fleet completion rate?')">Fleet Completion</button>
                    <button type="button" class="dispatch-btn secondary" onclick="quickDispatch('Show me pending findings')">Pending Findings</button>
                    <button type="button" class="dispatch-btn secondary" onclick="quickDispatch('What is the cost summary?')">Cost Summary</button>
                </div>
                <div id="dispatch-result" class="dispatch-result"></div>
            </form>
        </div>
    </div>

    <div class="card">
        <h3>Organisation</h3>
        {org_html}
    </div>

    <div class="card">
        <h3>🏥 Provider Health</h3>
        <div class="sparkline">{sparkline_html}</div>
        <div class="small">Green = up · Red = down/cooling · Dim = idle</div>
    </div>
    <div class="card">
        <h3>📊 Cost Trend</h3>
        <div class="chart-container">
            <div class="chart-title">Daily Cost Units</div>
            <div class="chart-canvas"><canvas id="costChart"></canvas></div>
        </div>
        </div>
        <div class="card">
            <h3>📊 Task Completion Trend</h3>
            <div class="chart-container">
                <div class="chart-title">Tasks Completed Over Time</div>
                <div class="chart-canvas"><canvas id="taskChart"></canvas></div>
            </div>
        </div>
        <div class="card">
            <h3>🧩 Recent Dost Tasks (last 10)</h3>
            {dost_rows}
        </div>

    <p style="margin-top: 1rem; color: #64748b; font-size: 0.8rem;">
        Office OS — Zero Claude Tokens — Free Models Only — http://localhost:8083
    </p>
    <script>
        function quickDispatch(prompt) {{
            document.getElementById('dispatch-prompt').value = prompt;
            document.getElementById('dispatch-form').dispatchEvent(new Event('submit'));
        }}
        document.getElementById('dispatch-form').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const prompt = document.getElementById('dispatch-prompt').value;
            const agent = document.getElementById('dispatch-agent').value;
            const priority = document.getElementById('dispatch-priority').value;
            if (!prompt) return;
            const resultDiv = document.getElementById('dispatch-result');
            resultDiv.textContent = 'Dispatching...';
            resultDiv.style.color = '#f59e0b';
            try {{
                const resp = await fetch('/api/task', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                    body: 'prompt=' + encodeURIComponent(prompt) + '&agent_id=' + encodeURIComponent(agent) + '&priority=' + encodeURIComponent(priority)
                }});
                const data = await resp.json();
                if (data.ok) {{
                    resultDiv.textContent = 'Dispatched: ' + data.task_id;
                    resultDiv.style.color = '#10b981';
                }} else {{
                    resultDiv.textContent = 'Error: ' + (data.error || 'unknown');
                    resultDiv.style.color = '#ef4444';
                }}
            }} catch (err) {{
                resultDiv.textContent = 'Error: ' + err.message;
                resultDiv.style.color = '#ef4444';
            }}
        }});
    </script>
</body>
</html>"""


# Public dashboard template (no login required) for the /dashboard route.
# CSS braces are doubled to escape Python .format().
DASHBOARD_PUBLIC_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="30">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JEV Dispatcher Dashboard — Office OS</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
        h1 {{ font-size: 1.5rem; margin: 0; display: flex; align-items: center; gap: 0.5rem; }}
        h1 .dot {{ width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .user-bar {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.5rem 1rem; font-size: 0.85rem; color: #94a3b8; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
        .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; }}
        .card h3 {{ margin-top: 0; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 0.75rem; }}
        .kv {{ display: flex; justify-content: space-between; padding: 0.45rem 0; border-bottom: 1px solid #2a2a2a; font-size: 0.9rem; }}
        .kv:last-child {{ border-bottom: none; }}
        .kv .label {{ color: #94a3b8; }}
        .kv .value {{ font-family: monospace; color: #e0e0e0; }}
        .status-locked {{ color: #10b981; font-weight: 700; }}
        .status-off {{ color: #ef4444; font-weight: 700; }}
        .tier {{ display: flex; justify-content: space-between; padding: 0.45rem 0; border-bottom: 1px solid #2a2a2a; font-size: 0.9rem; }}
        .tier:last-child {{ border-bottom: none; }}
        .tier-a {{ color: #10b981; font-weight: 700; }}
        .tier-b {{ color: #f59e0b; font-weight: 700; }}
        .tier-c {{ color: #ef4444; font-weight: 700; }}
        .task {{ display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid #2a2a2a; }}
        .task:last-child {{ border-bottom: none; }}
        .task-id {{ font-family: monospace; font-size: 0.8rem; color: #64748b; }}
        .task-agent {{ font-size: 0.85rem; color: #cbd5e1; }}
        .task-title {{ font-size: 0.9rem; }}
        .status-badge {{ font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; font-weight: 600; }}
        .status-done {{ background: #10b981; color: white; }}
        .status-in_progress {{ background: #f59e0b; color: white; }}
        .status-pending {{ background: #64748b; color: white; }}
        .status-failed {{ background: #ef4444; color: white; }}
        .status-error {{ background: #ef4444; color: white; }}
        .result-card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-top: 1rem; }}
        .result-card pre {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; font-family: monospace; white-space: pre-wrap; }}
        .refresh {{ margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }}
        .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: 600; text-decoration: none; }}
        .btn:hover {{ background: #2563eb; }}
        .btn.secondary {{ background: #2a2a2a; }}
        .empty {{ color: #64748b; font-style: italic; }}
        .logout {{ color: #94a3b8; text-decoration: none; font-size: 0.85rem; }}
        .logout:hover {{ color: #e0e0e0; }}
        .mono {{ font-family: monospace; font-size: 0.85rem; }}
        .small {{ font-size: 0.8rem; color: #94a3b8; }}
        .ok {{ color: #10b981; }}
        .cost-badge {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }}
        .cost-ok {{ background: #10b981; color: white; }}
        .cost-warn {{ background: #f59e0b; color: white; }}
        .cost-bad {{ background: #ef4444; color: white; }}
        .sparkline {{ display: flex; align-items: flex-end; gap: 2px; height: 40px; margin-top: 0.5rem; }}
        .spark-bar {{ width: 6px; background: #3b82f6; border-radius: 2px; }}
        .spark-bar.up {{ background: #10b981; }}
        .spark-bar.down {{ background: #ef4444; }}
        .spark-bar.idle {{ background: #2a2a2a; }}
        .findings-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 0.5rem; }}
        .finding-stat {{ background: #151515; border: 1px solid #2a2a2a; border-radius: 6px; padding: 0.75rem; text-align: center; }}
        .finding-stat .num {{ font-size: 1.5rem; font-family: monospace; font-weight: 700; }}
        .finding-stat .lbl {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; }}
        .activity-item {{ display: flex; justify-content: space-between; padding: 0.45rem 0; border-bottom: 1px solid #2a2a2a; font-size: 0.85rem; }}
        .activity-item:last-child {{ border-bottom: none; }}
        .activity-time {{ color: #64748b; font-size: 0.75rem; }}
        .activity-source {{ font-family: monospace; font-size: 0.75rem; }}
        .source-voice {{ color: #10b981; }}
        .source-debate {{ color: #f59e0b; }}
        .source-dost {{ color: #3b82f6; }}
        /* Activity feed panel */
        .activity-feed {{ display: grid; gap: 0.5rem; }}
        .activity-item {{ display: flex; justify-content: space-between; align-items: baseline; padding: 0.5rem 0.75rem; border: 1px solid #2a2a2a; border-radius: 6px; background: #151515; font-size: 0.85rem; }}
        .activity-item:hover {{ border-color: #3b82f6; }}
        .activity-item .act-time {{ color: #64748b; font-size: 0.75rem; font-family: monospace; }}
        .activity-item .act-actor {{ color: #cbd5e1; font-size: 0.8rem; }}
        .activity-item .act-action {{ color: #e0e0e0; font-weight: 600; }}
        .activity-item .act-target {{ color: #94a3b8; font-size: 0.8rem; }}
        .activity-item .act-type {{ font-size: 0.7rem; padding: 0.1rem 0.45rem; border-radius: 4px; font-weight: 700; text-transform: uppercase; }}
        .activity-type-dispatch {{ background: #3b82f6; color: white; }}
        .activity-type-debate {{ background: #f59e0b; color: white; }}
        .activity-type-finding {{ background: #10b981; color: white; }}
        .activity-type-cost-alert {{ background: #ef4444; color: white; }}
        .activity-type-system {{ background: #8b5cf6; color: white; }}
        .activity-legend {{ display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.75rem; color: #94a3b8; }}
        .activity-legend .leg {{ display: flex; align-items: center; gap: 0.3rem; }}
        .activity-breakdown {{ display: flex; gap: 0.75rem; flex-wrap: wrap; margin-top: 0.5rem; }}
        .activity-breakdown .stat {{ background: #151515; border: 1px solid #2a2a2a; border-radius: 6px; padding: 0.6rem 0.9rem; text-align: center; }}
        .activity-breakdown .stat .num {{ font-size: 1.3rem; font-family: monospace; font-weight: 700; }}
        .activity-breakdown .stat .lbl {{ font-size: 0.68rem; color: #94a3b8; text-transform: uppercase; }}
        .activity-empty {{ color: #64748b; font-style: italic; text-align: center; padding: 1rem; }}
        .findings-panel {{ margin-top: 0.75rem; }}
        .finding-status {{ display: inline-block; font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 4px; font-weight: 600; text-transform: uppercase; }}
        .finding-confirmed {{ background: #10b981; color: white; }}
        .finding-contested {{ background: #f59e0b; color: white; }}
        .finding-pending {{ background: #64748b; color: white; }}
        .finding-skipped {{ background: #94a3b8; color: white; }}
        .findings-panel .finding-item {{ display: flex; justify-content: space-between; padding: 0.45rem 0; border-bottom: 1px solid #2a2a2a; font-size: 0.85rem; }}
        .findings-panel .finding-item:last-child {{ border-bottom: none; }}
        .findings-panel .finding-claim {{ font-family: monospace; font-size: 0.8rem; color: #cbd5e1; max-width: 420px; }}
        .findings-panel .finding-agent {{ color: #94a3b8; font-size: 0.75rem; }}
        .findings-panel .finding-date {{ color: #64748b; font-size: 0.75rem; font-family: monospace; }}
        .findings-panel .agent-breakdown {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }}
        .findings-panel .agent-chip {{ background: #151515; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.3rem 0.6rem; font-size: 0.75rem; color: #cbd5e1; }}
        .findings-panel .tier-c-review {{ border: 1px solid #ef4444; background: #2a0a0a; border-radius: 6px; padding: 0.75rem; margin-top: 0.75rem; }}
        .findings-panel .tier-c-title {{ color: #ef4444; font-weight: 700; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
        .findings-panel .tier-c-item {{ display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid #3a1a1a; font-size: 0.85rem; }}
        .findings-panel .tier-c-item:last-child {{ border-bottom: none; }}
        .cost-panel {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; }}
        .cost-per-agent {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
        .cost-per-agent th, .cost-per-agent td {{ padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid #2a2a2a; }}
        .cost-per-agent th {{ color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; }}
        .cost-per-agent tr:last-child td {{ border-bottom: none; }}
        .cost-trend {{ display: flex; gap: 1rem; }}
        .cost-trend .stat {{ background: #151515; border: 1px solid #2a2a2a; border-radius: 6px; padding: 0.75rem; flex: 1; }}
        .cost-trend .stat .num {{ font-size: 1.25rem; font-family: monospace; font-weight: 700; }}
        .cost-trend .stat .lbl {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; }}
        .chart-container {{ position: relative; height: 200px; margin-bottom: 1rem; }}
        .chart-title {{ font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 0.5rem; }}
        .chart-canvas {{ width: 100%; height: 200px; }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <header>
        <h1><span class="dot"></span> JEV Dispatcher Dashboard</h1>
        <div>
            <a href="/metrics" class="btn secondary">/metrics (JSON)</a>
            <a href="/health/ops/ui" class="btn secondary">/health/ops (UI)</a>
            <span class="user-bar">http://localhost:8083/dashboard</span>
            <a href="/logout" class="logout">Sign out</a>
        </div>
    </header>
    <div class="refresh">
        <button class="btn" onclick="location.reload()">Refresh</button>
        <span class="small">Auto-refresh every 30s · Fleet status · Kill switch · Dost tasks · Synthesis · Cost · Findings · Activity</span>
    </div>

    <div class="card">
        <h3>🔒 Kill Switch</h3>
        <div class="kv"><span class="label">Verdict</span><span class="value status-locked">{kill_verdict}</span></div>
        <div class="kv"><span class="label">Live orders allowed</span><span class="value status-off">{kill_live}</span></div>
        <div class="kv"><span class="label">Mode</span><span class="value">Paper-only · Tier C human-only · No live orders</span></div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>📊 Fleet Status (JEV)</h3>
            <div class="kv"><span class="label">Tasks created (cycle)</span><span class="value mono">{jev_created}</span></div>
            <div class="kv"><span class="label">Tasks done (cycle)</span><span class="value mono">{jev_done}</span></div>
            <div class="kv"><span class="label">Completion rate</span><span class="value mono">{completion_rate}%</span></div>
            <div class="kv"><span class="label">Error rate</span><span class="value mono">{error_rate}%</span></div>
            <div class="kv"><span class="label">Calls today</span><span class="value mono">{calls_today}</span></div>
            <div class="kv"><span class="label">Tasks per min</span><span class="value mono">{tasks_per_min}</span></div>
        </div>
        <div class="card">
            <h3>🎯 Autonomy Tiers</h3>
            <div class="tier"><span class="label">Tier A — autonomous</span><span class="value tier-a">{tier_a}</span></div>
            <div class="tier"><span class="label">Tier B — gated</span><span class="value tier-b">{tier_b}</span></div>
            <div class="tier"><span class="label">Tier C — human-only</span><span class="value tier-c">{tier_c}</span></div>
            <div class="kv"><span class="label">Provider pools available</span><span class="value mono ok">{pools_available}/{pools_total}</span></div>
            <div class="kv"><span class="label">Free-tier headroom</span><span class="value mono">{headroom_pct}%</span></div>
        </div>
        <div class="card cost-panel">
            <h3>💰 Cost (Today)</h3>
            <div class="cost-section">
                <h4 style="margin:0 0 0.5rem 0;font-size:0.8rem;color:#94a3b8;text-transform:uppercase;">Per Agent</h4>
                <table class="cost-per-agent">
                    <thead><tr><th>Agent</th><th>Cost units</th></tr></thead>
                    <tbody>{cost_per_agent_rows}</tbody>
                </table>
            </div>
            <div class="cost-section">
                <h4 style="margin:0 0 0.5rem 0;font-size:0.8rem;color:#94a3b8;text-transform:uppercase;">Per Task Type</h4>
                <table class="cost-per-agent">
                    <thead><tr><th>Type</th><th>Cost units</th></tr></thead>
                    <tbody>{cost_per_type_rows}</tbody>
                </table>
            </div>
            <div class="cost-trend">
                {trend_html}
                <div class="kv"><span class="label">Headroom remaining</span><span class="value mono">{cost_headroom_pct}%</span></div>
            </div>
        </div>
        <div class="card">
            <h3>🧩 Findings</h3>
            <div class="findings-grid">
                <div class="finding-stat"><div class="num">{findings_confirmed}</div><div class="lbl">Confirmed</div></div>
                <div class="finding-stat"><div class="num">{findings_contested}</div><div class="lbl">Contested</div></div>
                <div class="finding-stat"><div class="num">{findings_pending}</div><div class="lbl">Pending</div></div>
                <div class="finding-stat"><div class="num">{findings_skipped}</div><div class="lbl">Skipped</div></div>
                <div class="finding-stat"><div class="num">{findings_total}</div><div class="lbl">Total</div></div>
            </div>
            <div class="findings-panel">
                <div style="margin-bottom:0.5rem;">
                    <strong style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase">Recent findings (last 10)</strong>
                    {findings_recent_html}
                </div>
                <div style="margin-top:0.75rem;margin-bottom:0.5rem;">
                    <strong style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase">By agent</strong>
                    <div class="agent-breakdown">{findings_agent_html}</div>
                </div>
                <div class="tier-c-review">
                    <div class="tier-c-title">⚠ Pending — needs Tier C review</div>
                    {findings_tier_c_html}
                </div>
            </div>
        </div>
        <div class="card">
            <h3>⚡ Dispatch Task</h3>
            <form id="dispatch-form" style="display:flex;flex-direction:column;gap:0.5rem;">
                <label style="font-size:0.75rem;color:#94a3b8">Send a prompt to the fleet:</label>
                <input type="text" id="dispatch-prompt" placeholder="e.g. What is the fleet status?" style="background:#0f0f0f;border:1px solid #2a2a2a;border-radius:4px;padding:0.5rem;color:#e0e0e0;font-family:inherit;font-size:0.85rem;" />
                <div style="display:flex;gap:0.5rem;">
                    <button type="submit" class="btn" style="padding:0.5rem 1rem;font-size:0.85rem;">Dispatch</button>
                    <button type="button" class="btn secondary" onclick="quickDispatch('What is the current fleet completion rate and error rate?')" style="padding:0.5rem 1rem;font-size:0.75rem;">Fleet Status</button>
                    <button type="button" class="btn secondary" onclick="quickDispatch('Show me pending findings needing review')" style="padding:0.5rem 1rem;font-size:0.75rem;">Findings Review</button>
                </div>
                <div id="dispatch-result" style="font-size:0.75rem;color:#10b981;margin-top:0.5rem;"></div>
            </form>
        </div>
    </div>

        <div class="card">
            <h3>🏥 Provider Health</h3>
            <div class="sparkline">{sparkline_html}</div>
            <div class="small">Green = up · Red = down/cooling · Dim = idle</div>
        </div>
        <div class="card">
            <h3>📊 Cost Trend</h3>
            <div class="chart-container">
                <div class="chart-title">Daily Cost Units</div>
                <div class="chart-canvas"><canvas id="costChart"></canvas></div>
            </div>
        </div>
        <div class="card">
            <h3>📊 Task Completion Trend</h3>
            <div class="chart-container">
                <div class="chart-title">Tasks Completed Over Time</div>
                <div class="chart-canvas"><canvas id="taskChart"></canvas></div>
            </div>
        </div>
        <div class="card">
            <h3>🧩 Recent Dost Tasks (last 10)</h3>
            {dost_rows}
        </div>

    <div class="card">
        <h3>📡 Activity Feed</h3>
        {activity_panel}
    </div>

    <div class="card">
        <h3>🧠 Synthesis Panel</h3>
        <div class="result-card"><pre>{synthesis}</pre></div>
        <p class="small">Last synthesis line from jev-dispatcher.log.</p>
    </div>

    <p style="margin-top: 1rem; color: #64748b; font-size: 0.8rem;">
        JEV Dispatcher — Paper-only · Kill switch LOCKED · Free tiers only · http://localhost:8083/dashboard
    </p>
    <script>
        function quickDispatch(prompt) {{
            document.getElementById('dispatch-prompt').value = prompt;
            document.getElementById('dispatch-form').dispatchEvent(new Event('submit'));
        }}
        document.getElementById('dispatch-form').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const prompt = document.getElementById('dispatch-prompt').value;
            if (!prompt) return;
            const resultDiv = document.getElementById('dispatch-result');
            resultDiv.textContent = 'Dispatching...';
            resultDiv.style.color = '#f59e0b';
            try {{
                const resp = await fetch('/api/task', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                    body: 'prompt=' + encodeURIComponent(prompt) + '&agent_id=strategy-advisor&priority=normal'
                }});
                const data = await resp.json();
                if (data.ok) {{
                    resultDiv.textContent = 'Dispatched: ' + data.task_id;
                    resultDiv.style.color = '#10b981';
                }} else {{
                    resultDiv.textContent = 'Error: ' + (data.error || 'unknown');
                    resultDiv.style.color = '#ef4444';
                }}
            }} catch (err) {{
                resultDiv.textContent = 'Error: ' + err.message;
                resultDiv.style.color = '#ef4444';
            }}
        }});
    </script>

    <script>
        // Chart.js charts
        const charts = {{}};

        function initCharts() {{
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {{
                    const jev = data.jev || {{}};
                    const pools = data.provider_pools || {{}};

                    // Completion rate chart
                    const completionCtx = document.getElementById('costChart');
                    if (completionCtx && !charts.completion) {{
                        charts.completion = new Chart(completionCtx.getContext('2d'), {{
                            type: 'gauge',
                            data: {{
                                labels: ['Completion Rate'],
                                datasets: [{{
                                    data: [Math.min(100, jev.completion_rate || 0)],
                                    backgroundColor: '#10b981',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                ]
                            }},
                            options: {{
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {{
                                    legend: {{ display: false }},
                                    title: {{ display: true, text: 'Task Completion Rate (%)' }}
                                }},
                                scales: {{
                                    y: {{ min: 0, max: 100 }}
                                }}
                            }}
                        }});
                    }}

                    // Error rate chart
                    const errorCtx = document.getElementById('errorChart');
                    if (errorCtx && !charts.error) {{
                        charts.error = new Chart(errorCtx.getContext('2d'), {{
                            type: 'gauge',
                            data: {{
                                labels: ['Error Rate (%)'],
                                datasets: [{{
                                    data: [Math.min(100, jev.error_rate || 0)],
                                    backgroundColor: '#ef4444',
                                    borderColor: '#ffffff',
                                    borderWidth: 2
                                ]
                            }},
                            options: {{
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {{
                                    legend: {{ display: false }},
                                    title: {{ display: true, text: 'Error Rate (%)' }}
                                }},
                                scales: {{
                                    y: {{ min: 0, max: 100 }}
                                }}
                            }}
                        }});
                    }}

                    // Pool status chart
                    const poolCtx = document.getElementById('poolChart');
                    if (poolCtx && pools && !charts.pools) {{
                        const poolNames = Object.keys(pools);
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools = new Chart(poolCtx.getContext('2d'), {{
                            type: 'bar',
                            data: {{
                                labels: poolNames.map(p => p.split('_')[0]),
                                datasets: [{{
                                    label: 'Pool Status',
                                    data: poolValues,
                                    backgroundColor: poolValues.map(v => v === 1 ? '#10b981' : (v === 0.5 ? '#f59e0b' : '#ef4444'))
                                }}]
                            }},
                            options: {{
                                responsive: true,
                                scales: {{
                                    y: {{ min: 0, max: 1, ticks: {{ display: false }} }}
                                }},
                                plugins: {{
                                    legend: {{ display: false }},
                                    title: {{ display: true, text: 'Provider Pool Status' }}
                                }}
                            }}
                        }});
                    }}
                }})
                .catch(err => console.error('Failed to load metrics:', err));
        }}

        // Initialize charts when page loads
        document.addEventListener('DOMContentLoaded', initCharts);
        // Refresh charts every 30 seconds
        setInterval(() => {{
            fetch('/metrics')
                .then(r => r.json())
                .then(data => {{
                    const jev = data.jev || {{}};
                    const pools = data.provider_pools || {{}};

                    if (charts.completion) {{
                        charts.completion.data.datasets[0].data = [Math.min(100, jev.completion_rate || 0)];
                        charts.completion.update();
                    }}

                    if (charts.error) {{
                        charts.error.data.datasets[0].data = [Math.min(100, jev.error_rate || 0)];
                        charts.error.update();
                    }}

                    if (charts.pools && pools) {{
                        const poolValues = pools.map(p => p.available ? 1 : (p.cooldown_remaining > 0 ? 0.5 : 0));
                        charts.pools.data.datasets[0].data = poolValues;
                        charts.pools.update();
                    }}
                }})
                .catch(err => console.error('Failed to load metrics:', err));
        }}, 30000);
    </script>
</body>
</html>"""

TASK_RESULT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task {task_id} - Office OS</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
        a {{ color: #3b82f6; }}
        .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
        .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; font-size: 0.85rem; color: #94a3b8; margin-bottom: 1rem; }}
        .meta div {{ background: #151515; padding: 0.75rem; border-radius: 4px; }}
        .meta .label {{ font-size: 0.7rem; text-transform: uppercase; color: #64748b; margin-bottom: 0.25rem; }}
        .meta .value {{ font-family: monospace; }}
        pre {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; font-family: monospace; white-space: pre-wrap; }}
        .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
        .btn.secondary {{ background: #2a2a2a; }}
        .error {{ color: #ef4444; }}
    </style>
</head>
<body>
    <a href="/" class="btn secondary">← Back to dashboard</a>
    <h1>Task {task_id}</h1>
    <div class="meta">
        <div><span class="label">Title</span><div class="value">{title}</div></div>
        <div><span class="label">Agent</span><div class="value">{agent}</div></div>
        <div><span class="label">Status</span><div class="value">{status}</div></div>
        <div><span class="label">Priority</span><div class="value">{priority}</div></div>
        <div><span class="label">Pool</span><div class="value">{pool}</div></div>
        <div><span class="label">Model</span><div class="value">{model}</div></div>
    </div>

    {error_html}

    <div class="card">
        <h3 style="margin-top:0">Result</h3>
        <pre>{result}</pre>
    </div>
</body>
</html>"""


def escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


HIVE_METRICS_CACHE_TTL_SEC = 30
HIVE_METRICS_PERSIST_INTERVAL_SEC = 60
HIVE_METRICS_REFRESH_INTERVAL_SEC = 30
HIVE_METRICS_STATE_FILE = str(OFFICE_ROOT / "state" / "hive_metrics.json")
_HIVE_METRICS_CACHE: dict = {}
_HIVE_METRICS_FILE_STATE: dict = {}
_HIVE_METRICS_STATE_LOADED_PATH = None
_HIVE_METRICS_LAST_PERSIST_TS = 0.0
_HIVE_METRICS_LAST_PERSIST_PATH = None
_HIVE_METRICS_REFRESH_RUNNING = False
_HIVE_METRICS_LOCK = threading.Lock()
_HIVE_METRICS_SCAN_LOCK = threading.Lock()


def _empty_hive_metrics() -> dict:
    return {
        "tasks_created_total": 0,
        "tasks_done_total": 0,
        "errors_total": 0,
        "tasks_created": 0,
        "tasks_done": 0,
        "errors_cycle": 0,
        "tasks_per_min": 0,
    }


def _load_hive_metrics_state() -> bool:
    """Load the persisted aggregate and per-file index from disk."""
    global _HIVE_METRICS_FILE_STATE, _HIVE_METRICS_STATE_LOADED_PATH
    path = str(HIVE_METRICS_STATE_FILE)
    try:
        raw = json.loads(Path(path).read_text())
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        _HIVE_METRICS_STATE_LOADED_PATH = path
        return False

    aggregate = raw.get("aggregate")
    files = raw.get("files")
    if not isinstance(aggregate, dict) or not isinstance(files, dict):
        _HIVE_METRICS_STATE_LOADED_PATH = path
        return False

    data = _empty_hive_metrics()
    for key in data:
        value = aggregate.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            data[key] = value
    try:
        ts = float(raw.get("ts") or 0.0)
    except (TypeError, ValueError):
        ts = 0.0

    _HIVE_METRICS_CACHE["ts"] = ts
    _HIVE_METRICS_CACHE["data"] = data
    _HIVE_METRICS_CACHE["ready"] = True
    _HIVE_METRICS_FILE_STATE = dict(files)
    _HIVE_METRICS_STATE_LOADED_PATH = path
    return True


def _ensure_hive_metrics_state_loaded() -> None:
    if _HIVE_METRICS_STATE_LOADED_PATH != str(HIVE_METRICS_STATE_FILE):
        _load_hive_metrics_state()


def _save_hive_metrics_state(data: dict) -> None:
    global _HIVE_METRICS_LAST_PERSIST_TS, _HIVE_METRICS_LAST_PERSIST_PATH
    try:
        path = Path(HIVE_METRICS_STATE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps({"ts": time.time(), "aggregate": data, "files": _HIVE_METRICS_FILE_STATE})
        )
        tmp.replace(path)
        _HIVE_METRICS_LAST_PERSIST_TS = time.time()
        _HIVE_METRICS_LAST_PERSIST_PATH = str(path)
    except Exception:
        pass


def _refresh_hive_metrics() -> dict:
    """Rescan the hive and return the fresh aggregate.

    Only files whose mtime/size changed are re-read, so a refresh over a
    hive with thousands of tasks costs a directory listing plus a handful of
    parses instead of re-reading everything.
    """
    global _HIVE_METRICS_FILE_STATE

    with _HIVE_METRICS_SCAN_LOCK:
        _ensure_hive_metrics_state_loaded()
        now = time.time()

        CYCLE_WINDOW_SEC = 24 * 60 * 60  # per-cycle = last 24 hours
        MIN_WINDOW_SEC = 60

        state = dict(_HIVE_METRICS_FILE_STATE)
        seen = set()
        changed = False

        try:
            hive_files = glob.glob(os.path.join(HIVE_DIR, "*.json"))
        except Exception:
            hive_files = []

        for hive_file in hive_files:
            name = os.path.basename(hive_file)
            seen.add(name)
            try:
                stat = os.stat(hive_file)
            except OSError:
                continue

            previous = state.get(name)
            if (
                isinstance(previous, list)
                and len(previous) >= 6
                and previous[0] == stat.st_mtime_ns
                and previous[1] == stat.st_size
            ):
                continue

            try:
                with open(hive_file) as f:
                    task = json.load(f)
            except Exception:
                continue
            if not isinstance(task, dict):
                continue

            is_jev = task.get("metadata", {}).get("source") == "jev-cloud-orchestrator"
            is_dost = (task.get("metadata") or {}).get("source") == "dost"
            status = task.get("status")
            if not isinstance(status, str):
                status = ""
            raw_ts = task.get("updated_at") or task.get("created_at")
            task_time = None
            if raw_ts:
                try:
                    task_time = time.mktime(time.strptime(raw_ts, "%Y-%m-%dT%H:%M:%SZ"))
                except (TypeError, ValueError):
                    task_time = None
            state[name] = [
                stat.st_mtime_ns,
                stat.st_size,
                1 if is_jev else 0,
                status,
                task_time,
                task if is_dost else None,
            ]
            changed = True

        for name in list(state.keys()):
            if name not in seen:
                del state[name]
                changed = True

        created_total = 0
        done_total = 0
        errors_total = 0
        created_cycle = 0
        done_cycle = 0
        errors_cycle = 0
        tasks_per_min = 0

        for entry in state.values():
            if not isinstance(entry, list) or len(entry) < 5:
                continue
            _, _, is_jev, status, task_time = entry[:5]
            if not is_jev:
                continue
            created_total += 1
            if status == "done":
                done_total += 1
            if status == "error":
                errors_total += 1
            if task_time is not None:
                age_sec = now - task_time
                if age_sec <= CYCLE_WINDOW_SEC:
                    created_cycle += 1
                    if status == "done":
                        done_cycle += 1
                    if status == "error":
                        errors_cycle += 1
                if age_sec <= MIN_WINDOW_SEC:
                    tasks_per_min += 1

        data = {
            "tasks_created_total": created_total,
            "tasks_done_total": done_total,
            "errors_total": errors_total,
            "tasks_created": created_cycle,
            "tasks_done": done_cycle,
            "errors_cycle": errors_cycle,
            "tasks_per_min": tasks_per_min,
        }

        _HIVE_METRICS_FILE_STATE = state
        _HIVE_METRICS_CACHE["ts"] = now
        _HIVE_METRICS_CACHE["data"] = data
        _HIVE_METRICS_CACHE["ready"] = True
        if changed and (
            now - _HIVE_METRICS_LAST_PERSIST_TS >= HIVE_METRICS_PERSIST_INTERVAL_SEC
            or _HIVE_METRICS_LAST_PERSIST_PATH != str(HIVE_METRICS_STATE_FILE)
        ):
            _save_hive_metrics_state(data)
        return data


def _run_hive_metrics_refresh() -> None:
    global _HIVE_METRICS_REFRESH_RUNNING
    try:
        _refresh_hive_metrics()
    except Exception:
        pass
    finally:
        with _HIVE_METRICS_LOCK:
            _HIVE_METRICS_REFRESH_RUNNING = False


def _schedule_hive_metrics_refresh() -> bool:
    """Start a hive refresh in the background; only one runs at a time."""
    global _HIVE_METRICS_REFRESH_RUNNING
    with _HIVE_METRICS_LOCK:
        if _HIVE_METRICS_REFRESH_RUNNING:
            return False
        _HIVE_METRICS_REFRESH_RUNNING = True
    threading.Thread(target=_run_hive_metrics_refresh, daemon=True).start()
    return True


def _hive_metrics_refresher_loop(stop_event: threading.Event, interval_sec: float) -> None:
    """Keep the hive aggregate current without waiting for a request."""
    while not stop_event.is_set():
        try:
            _schedule_hive_metrics_refresh()
        except Exception:
            pass
        stop_event.wait(interval_sec)


def _start_hive_metrics_refresher(
    interval_sec: float = HIVE_METRICS_REFRESH_INTERVAL_SEC,
) -> threading.Event:
    """Start the background refresher. Setting the returned event stops it."""
    stop_event = threading.Event()
    threading.Thread(
        target=_hive_metrics_refresher_loop,
        args=(stop_event, interval_sec),
        name="hive-metrics-refresher",
        daemon=True,
    ).start()
    return stop_event


def _hive_task_metrics() -> dict:
    """Return the last-known hive aggregate without waiting for a scan.

    The scan itself is expensive on a hive with thousands of tasks, so it
    runs in the background and readers get the previous aggregate straight
    away.
    """
    _ensure_hive_metrics_state_loaded()
    cached = _HIVE_METRICS_CACHE.get("data")
    if not isinstance(cached, dict):
        cached = _empty_hive_metrics()
        _HIVE_METRICS_CACHE["data"] = cached
    if time.time() - _HIVE_METRICS_CACHE.get("ts", 0.0) >= HIVE_METRICS_CACHE_TTL_SEC:
        _schedule_hive_metrics_refresh()
    return cached


def _recent_dost_tasks(limit: int = 20) -> list:
    """Return the most recent dost tasks from the background-maintained index.

    The refresher already visits every task file, so the request path reads the
    index it keeps instead of opening the whole hive on every request.
    """
    _ensure_hive_metrics_state_loaded()
    tasks = []
    for entry in _HIVE_METRICS_FILE_STATE.values():
        if not isinstance(entry, list) or len(entry) < 6:
            continue
        task = entry[5]
        if not isinstance(task, dict):
            continue
        if (task.get("metadata") or {}).get("source") != "dost":
            continue
        tasks.append(task)
    tasks.sort(key=lambda t: t.get("updated_at", "") or t.get("created_at", ""), reverse=True)
    return tasks[:limit]


class OfficeHandler(BaseHTTPRequestHandler):
    current_user = None
    current_sid = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Rate limit API endpoints
        if path.startswith("/api/") and not self._check_rate_limit():
            return

        if path == "/login":
            self._serve_login()
        elif path == "/logout":
            self._do_logout()
        elif path == "/":
            self._serve_dashboard()
        elif path.startswith("/task/"):
            task_id = path.split("/task/")[1]
            self._serve_task_result(task_id)
        elif path == "/qwen":
            self._serve_qwen_page()
        elif path.startswith("/qwen/result/"):
            task_id = path.split("/qwen/result/")[1]
            self._get_qwen_result(task_id)
        elif path == "/qwen/status":
            self._qwen_status()
        elif path == "/metrics":
            self._serve_metrics()
        elif path == "/dashboard":
            self._serve_dashboard_public()
        elif path == "/api/findings":
            self._serve_api_findings()
        elif path == "/api/synthesis":
            self._serve_api_synthesis()
        elif path == "/api/tasks":
            self._serve_api_tasks()
        elif path == "/api/metrics":
            self._serve_api_metrics()
        elif path == "/api/workspaces":
            self._serve_api_workspaces()
        elif path.startswith("/api/workspaces/"):
            self._serve_api_workspace_detail()
        elif path == "/doctor":
            self._serve_doctor_page()
        elif path == "/review":
            self._serve_review_page()
        elif path == "/results":
            self._serve_results_page()
        elif path == "/health":
            self._serve_health()
        elif path == "/health/dispatcher":
            self._serve_health_dispatcher()
        elif path == "/health/providers":
            self._serve_health_providers()
        elif path == "/health/ops":
            self._serve_health_ops()
        elif path == "/health/ops/ui":
            self._serve_health_ops_page()
        elif path == "/api/health":
            self._serve_health()
        elif path == "/events":
            self._serve_sse_events()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)

        # Rate limit API endpoints
        if parsed.path.startswith("/api/") and not self._check_rate_limit():
            return

        if parsed.path == "/login":
            self._do_login()
        elif parsed.path == "/task":
            self._create_task()
        elif parsed.path == "/qwen/task":
            self._create_qwen_task()
        elif parsed.path == "/api/task":
            self._serve_dashboard_task()
        elif parsed.path == "/api/workspaces":
            self._create_api_workspace()
        elif parsed.path == "/api/stocks":
            self._serve_stocks_metrics()
        else:
            self.send_error(404)

    # ---------- auth ----------
    def _serve_login(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(LOGIN_TEMPLATE.encode("utf-8"))

    def _do_login(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        params = parse_qs(body)
        username = params.get("username", [""])[0]

        if username in USERS:
            sid = create_session(username)
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"office_session={sid}; Path=/; HttpOnly; Max-Age={SESSION_TIMEOUT}")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><p>Invalid username. <a href='/login'>Try again</a>.</p></body></html>")

    def _do_logout(self):
        cookie = self.headers.get("Cookie", "")
        for c in cookie.split(";"):
            c = c.strip()
            if c.startswith("office_session="):
                sid = c.split("=", 1)[1]
                if sid in SESSIONS:
                    del SESSIONS[sid]
                    save_sessions()
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()

    # ---------- stock bot metrics ----------
    def _serve_stocks_metrics(self):
        """Receive stock bot run results and persist them to STOCKS_METRICS_FILE."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "invalid json"}).encode("utf-8"))
            return

        STOCKS_METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STOCKS_METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))

    # ---------- workspace auth context ----------
    def _workspace_context(self):
        """Extract workspace context from X-Workspace-ID and X-User-Email headers."""
        workspace_id = self.headers.get("X-Workspace-ID", "").strip() or None
        email = self.headers.get("X-User-Email", "").strip() or None
        return workspace_id, email

    def _validate_workspace_access(self, workspace_id, email):
        """Verify workspace exists and user has access. Returns (workspace_dict, error_response_bool)."""
        if not workspace_id:
            return None, False  # no workspace context -> allowed (default workspace)
        if not workspace_exists(workspace_id):
            self._send_json({"error": f"Workspace not found: {workspace_id}"}, status=404)
            return None, True
        if email and not can_access_workspace(workspace_id, email):
            self._send_json({"error": f"No access to workspace: {workspace_id}"}, status=403)
            return None, True
        ws = get_workspace(workspace_id)
        return ws, False

    def _require_workspace_edit(self, workspace_id, email):
        """Verify workspace exists and user can edit. Returns True if OK, sends error otherwise."""
        if not workspace_id:
            self._send_json({"error": "X-Workspace-ID header required"}, status=400)
            return False
        if not workspace_exists(workspace_id):
            self._send_json({"error": f"Workspace not found: {workspace_id}"}, status=404)
            return False
        if email and not can_edit_workspace(workspace_id, email):
            self._send_json({"error": f"No edit access to workspace: {workspace_id}"}, status=403)
            return False
        return True

    def _api_key(self) -> str:
        """Identify the caller by API key: X-API-Key header, Bearer token, else 'anonymous'."""
        key = self.headers.get("X-API-Key", "").strip()
        if key:
            return key
        auth = self.headers.get("Authorization", "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return "anonymous"

    def _check_rate_limit(self) -> bool:
        """Enforce per-API-key rate limiting for API endpoints.

        Returns True if the request may proceed. On limit exceeded, sends a
        429 Too Many Requests with a Retry-After header and returns False.
        """
        status = RATE_LIMITER.check(self._api_key())
        self._rate_limit_status = status
        if not status["allowed"]:
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", str(status["retry_after"]))
            self.send_header("X-RateLimit-Limit", str(status["limit"]))
            self.send_header("X-RateLimit-Remaining", "0")
            self.send_header("X-RateLimit-Reset", str(status["reset"]))
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Too Many Requests",
                "message": "Rate limit exceeded.",
                "retry_after": status["retry_after"],
            }).encode())
            return False
        return True

    # ---------- dashboard ----------
    @require_login
    def _serve_dashboard(self):
        user_id = self.current_user
        user_info = USERS.get(user_id, {})
        user_name = user_info.get("name", user_id)
        user_role = user_info.get("role", "user")

        router = ProviderRouter()
        provider_status = router.status()

        provider_rows = ""
        for name, s in provider_status.items():
            mark_class = "status-ok" if s["available"] else "status-cooldown"
            mark_text = "OK" if s["available"] else f"COOLDOWN {s['cooldown_remaining']:.0f}s"
            models = ", ".join(m.split("/")[-1] for m in s["models"][:2])
            provider_rows += f"""
            <div class="provider">
                <span class="provider-name">{escape(name)}</span>
                <span><span class="status-badge {mark_class}">{mark_text}</span> tier={escape(s['tier'])}</span>
                <span style="font-size:0.8rem;color:#64748b">{escape(models)}</span>
            </div>
            """

        # Provider health: sparkline + status badge + model names + cooldown timers
        provider_health_html = ""
        for name, s in provider_status.items():
            available = s.get("available", False)
            cd = s.get("cooldown_remaining", 0)
            tier = s.get("tier", "?")
            models = s.get("models", [])
            model_short = ", ".join(m.split("/")[-1] for m in models[:2]) if models else "?"

            if available and cd == 0:
                status_text = "UP"
                status_class = "status-up"
                bar_class = "spark-bar-up"
                bar_title = "UP"
            elif cd > 0:
                status_text = f"COOLING {cd:.0f}s"
                status_class = "status-cooling"
                bar_class = "spark-bar-cooling"
                bar_title = f"COOLING {cd:.0f}s"
            else:
                status_text = "DOWN"
                status_class = "status-down"
                bar_class = "spark-bar-idle"
                bar_title = "DOWN"

            # Simple 8-point sparkline history: current + 7 recent samples (all current status)
            history = [1 if (available and cd == 0) else (0.5 if cd > 0 else 0)] * 8
            max_h = max(history) if max(history) > 0 else 1
            bars = ""
            for val in history:
                h = int(40 * val / max_h)
                if val >= 1:
                    bcls = "spark-bar-up"
                elif val > 0:
                    bcls = "spark-bar-cooling"
                else:
                    bcls = "spark-bar-idle"
                bars += f'<div class="spark-bar {bcls}" style="height:{h}px;" title="{bar_title}"></div>'

            cd_html = f'<div class="cooldown-timer">{cd:.0f}s remaining</div>' if cd > 0 else ""

            provider_health_html += f"""
            <div class="provider" style="padding:0.5rem 0;">
                <div style="font-size:0.8rem;color:#94a3b8">{escape(name.split('_')[-1])}</div>
                <div>{bars}</div>
                <div class="spark-label">{model_short[:14]}</div>
                <span class="status-badge {status_class}">{status_text}</span>
                <span style="font-size:0.8rem;color:#64748b">{escape(models[0].split('/')[-1] if models else '?')}</span>
                {cd_html}
            </div>
            """

        if not provider_health_html:
            provider_health_html = '<div class="empty">No provider data.</div>'

        hive = Hive()
        task_rows = ""
        statuses = ["pending", "assigned", "in_progress", "done", "failed"]
        any_tasks = False
        for status in statuses:
            tasks = hive.list_tasks(status=status, user_id=user_id)
            if tasks:
                any_tasks = True
                badge_class = f"status-{status}"
                for t in tasks:
                    agent = escape(t.get("agent_id", "unassigned"))
                    title = escape(t["title"])
                    pool = escape(t.get("assigned_pool", "-"))
                    task_rows += f"""
                    <div class="task">
                        <span class="task-id">{escape(t['id'])}</span>
                        <div>
                            <span class="status-badge {badge_class}">{status}</span>
                            <span class="task-agent">{agent}</span><br>
                            <span class="task-title">{title}</span>
                        </div>
                        <span style="font-size:0.8rem;color:#64748b">{pool}</span>
                    </div>
                    """
        if not any_tasks:
            task_rows = '<div class="empty">No tasks yet. Create your first task below.</div>'

        done_tasks = hive.list_tasks(status="done", user_id=user_id)
        result_rows = ""
        if done_tasks:
            for t in done_tasks[-5:]:
                agent = escape(t.get("agent_id", "?"))
                title = escape(t["title"])
                result = (t.get("result") or "")[:200].replace("\n", " ")
                result_rows += f"""
                <div class="task">
                    <span class="task-id">{escape(t['id'])}</span>
                    <div>
                        <span class="task-agent">{agent}</span><br>
                        <span class="task-title">{title}</span>
                    </div>
                    <a href="/task/{escape(t['id'])}" style="color:#3b82f6;text-decoration:none">View result</a>
                </div>
                """
        else:
            result_rows = '<div class="empty">No completed tasks yet.</div>'

        html = DASHBOARD_TEMPLATE.format(
            provider_html=provider_rows,
            task_html=task_rows,
            result_html=result_rows,
            org_html=_org_rows(),
            provider_health_html=provider_health_html,
            user_name=escape(user_name),
            user_role=escape(user_role),
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    @require_login
    def _serve_task_result(self, task_id):
        hive = Hive()
        task = hive.get_task(task_id, user_id=self.current_user)

        if not task:
            self.send_error(404, "Task not found or not accessible")
            return

        result = task.get("result") or "No result available."
        error = task.get("error") or ""

        error_html = f'''<div class="card">
            <h3 style="margin-top:0">Error</h3>
            <pre class="error">{escape(task['error'])}</pre>
        </div>''' if error else ""

        html = TASK_RESULT_TEMPLATE.format(
            task_id=task_id,
            title=escape(task["title"]),
            agent=escape(task.get("agent_id", "?")),
            status=escape(task["status"]),
            priority=escape(task.get("priority", "normal")),
            pool=escape(task.get("assigned_pool", "-")),
            model=escape(task.get("assigned_model", "-")),
            result=escape(result),
            error_html=error_html,
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    @require_login
    def _create_task(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        params = parse_qs(body)

        title = params.get("title", [""])[0]
        desc = params.get("description", [""])[0]
        agent_id = params.get("agent_id", ["principal-architect"])[0]
        priority = params.get("priority", ["normal"])[0]

        hive = Hive()
        router = ProviderRouter()
        god = GodAgent(hive, router)
        result = god.create_task(title, desc, agent_id=agent_id, priority=priority, user_id=self.current_user)

        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    @require_login
    def _serve_dashboard_task(self):
        """Dashboard task trigger — writes a dost task file from a button click."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        params = parse_qs(body)

        prompt = params.get("prompt", [""])[0]
        agent_id = params.get("agent_id", ["strategy-advisor"])[0]
        priority = params.get("priority", ["normal"])[0]

        if not prompt:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "No prompt provided"}).encode())
            return

        import uuid
        task_id = f"jev-{uuid.uuid4().hex[:8]}"
        task = {
            "id": task_id,
            "title": f"Dashboard: {prompt[:60]}",
            "description": prompt,
            "status": "pending",
            "agent_id": agent_id,
            "priority": priority,
            "user_id": self.current_user,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata": {
                "tier": "pro",
                "source": "dost",
                "web_dispatch": True,
                "qwen_task_id": f"jev-exec-dost-{task_id[:8]}",
            },
            "result": None,
            "error": None,
        }
        try:
            HIVE_DIR.mkdir(parents=True, exist_ok=True)
            task_path = HIVE_DIR / f"{task_id}.json"
            task_path.write_text(json.dumps(task, indent=2))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "task_id": task_id, "message": "Task submitted to fleet"}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    @require_login
    def _serve_qwen_page(self):
        user_id = self.current_user
        user_info = USERS.get(user_id, {})
        user_name = user_info.get("name", user_id)
        user_role = user_info.get("role", "user")

        # Check Qwen status
        ollama_ok = False
        pending = 0
        completed = 0
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                d = json.loads(resp.read())
                models = [m.get("name", "") for m in d.get("models", [])]
                ollama_ok = any("qwen3.5-9b" in m for m in models)
        except Exception:
            ollama_ok = False

        try:
            pending = len([f for f in os.listdir(TASK_QUEUE_DIR) if f.endswith(".json")])
        except Exception:
            pending = 0
        try:
            completed = len([f for f in os.listdir(QWEN_RESULT_DIR) if f.endswith(".result")])
        except Exception:
            completed = 0

        status_class = "ok" if ollama_ok else "bad"
        status_text = "Ollama Online" if ollama_ok else "Ollama Offline"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Qwen3.5-9B — Office OS</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
        h1 {{ font-size: 1.5rem; margin: 0; display: flex; align-items: center; gap: 0.5rem; }}
        h1 .dot {{ width: 8px; height: 8px; background: #10b981; border-radius: 50%; }}
        .nav {{ display: flex; gap: 0.5rem; }}
        .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; text-decoration: none; }}
        .btn.secondary {{ background: #2a2a2a; }}
        .btn:hover {{ opacity: 0.9; }}
        .qwen-card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1.5rem; max-width: 800px; }}
        .qwen-status {{ display: flex; justify-content: space-between; font-size: 0.85rem; color: #94a3b8; margin-bottom: 1rem; }}
        .qwen-status .ok {{ color: #10b981; }}
        .qwen-status .bad {{ color: #ef4444; }}
        .qwen-form {{ display: flex; gap: 0.5rem; margin-bottom: 1rem; }}
        .qwen-form input[type="text"] {{ flex: 1; background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.75rem; color: #e0e0e0; font-family: inherit; font-size: 0.9rem; }}
        .qwen-result {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; font-family: monospace; white-space: pre-wrap; margin-top: 0.75rem; }}
        .loading {{ color: #64748b; font-style: italic; }}
        .empty {{ color: #64748b; font-style: italic; }}
        .logout {{ color: #94a3b8; text-decoration: none; font-size: 0.85rem; }}
        .logout:hover {{ color: #e0e0e0; }}
    </style>
</head>
<body>
    <header>
        <h1><span class="dot"></span> Qwen3.5-9B</h1>
        <div class="nav">
            <a href="/" class="btn secondary">← Dashboard</a>
            <span class="user-bar">Signed in as <span class="user-name">{user_name}</span> ({user_role})</span>
            <a href="/logout" class="logout">Sign out</a>
        </div>
    </header>
    <div class="qwen-card">
        <div class="qwen-status">
            <span id="qwen-status" class="qwen-status {'ok' if ollama_ok else 'bad'}">● {status_text}</span>
            <span>Pending: <span id="qwen-pending">{pending}</span> | Completed: <span id="qwen-completed">{completed}</span></span>
        </div>
        <form id="qwen-form" class="qwen-form">
            <input type="text" id="qwen-prompt" placeholder="Ask Qwen3.5-9B..." required />
            <button type="submit" class="btn">Send</button>
        </form>
        <div id="qwen-result" class="qwen-result"></div>
    </div>
    <script>
        // Poll Qwen status every 10 seconds
        async function pollStatus() {{
            try {{
                const resp = await fetch('/qwen/status');
                const data = await resp.json();
                document.getElementById('qwen-status').textContent = data.ollama_ok ? '● Ollama Online' : '● Ollama Offline';
                document.getElementById('qwen-status').className = 'qwen-status ' + (data.ollama_ok ? 'ok' : 'bad');
                document.getElementById('qwen-pending').textContent = data.pending_tasks;
                document.getElementById('qwen-completed').textContent = data.completed_tasks;
            }} catch {{ /* silent */ }}
        }}
        setInterval(pollStatus, 10000);
        pollStatus();

        // Handle form submission
        document.getElementById('qwen-form').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const prompt = document.getElementById('qwen-prompt').value;
            const taskId = 'qwen-' + Date.now();
            const resultDiv = document.getElementById('qwen-result');
            resultDiv.textContent = 'Processing...';

            try {{
                const submitResp = await fetch('/qwen/task', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ prompt: prompt, id: taskId }})
                }});
                const submitData = await submitResp.json();
                if (submitData.status !== 'queued') {{
                    resultDiv.textContent = 'Error: ' + (submitData.error || 'unknown');
                    return;
                }}

                // Poll for result
                let attempts = 0;
                const maxAttempts = 60; // 5 minutes
                while (attempts < maxAttempts) {{
                    await new Promise(r => setTimeout(r, 5000));
                    const resultResp = await fetch('/qwen/result/' + taskId);
                    if (resultResp.status === 200) {{
                        const resultData = await resultResp.json();
                        resultDiv.textContent = resultData.response || JSON.stringify(resultData);
                        return;
                    }}
                    attempts++;
                }}
                resultDiv.textContent = 'Task still processing. Check back later.';
            }} catch (err) {{
                resultDiv.textContent = 'Error: ' + err.message;
            }}
        }});
    </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    # ---------- Qwen autonomous tasks ----------
    @require_login
    def _create_qwen_task(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
            prompt = data.get("prompt", "")
            task_id = data.get("id", f"qwen-{uuid.uuid4().hex[:8]}")
        except json.JSONDecodeError:
            prompt = body.strip()
            task_id = f"qwen-{uuid.uuid4().hex[:8]}"

        if not prompt:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "No prompt provided"}).encode())
            return

        # Write task file for the autonomous worker to pick up
        task_file = os.path.join(TASK_QUEUE_DIR, f"{task_id}.json")
        with open(task_file, "w") as f:
            f.write(prompt)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "queued", "task_id": task_id, "file": task_file}).encode())

    @require_login
    def _get_qwen_result(self, task_id):
        result_file = os.path.join(QWEN_RESULT_DIR, f"{task_id}.result")
        if os.path.exists(result_file):
            with open(result_file, "r") as f:
                result = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(result.encode())
        else:
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "processing", "task_id": task_id}).encode())

    @require_login
    def _qwen_status(self):
        # Check Ollama availability
        ollama_ok = False
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                d = json.loads(resp.read())
                models = [m.get("name", "") for m in d.get("models", [])]
                ollama_ok = any("qwen3.5-9b" in m for m in models)
        except Exception:
            ollama_ok = False

        # Count pending tasks
        pending = len([f for f in os.listdir(TASK_QUEUE_DIR) if f.endswith(".json")]) if os.path.isdir(TASK_QUEUE_DIR) else 0
        completed = len([f for f in os.listdir(QWEN_RESULT_DIR) if f.endswith(".result")]) if os.path.isdir(QWEN_RESULT_DIR) else 0

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "ollama_available": ollama_ok,
            "model": "hauhaucs/qwen3.5-9b-uncensored-aggressive",
            "pending_tasks": pending,
            "completed_tasks": completed,
            "worker_running": True
        }).encode())

    def _build_metrics_payload(self):
        """Aggregate Qwen, JEV, and Ollama health into a metrics dict (shared by /metrics and /dashboard)."""
        # Qwen API metrics
        qwen_metrics = {"pending_tasks": 0, "completed_tasks": 0, "ollama_available": False}
        try:
            req = urllib.request.Request("http://127.0.0.1:18790/metrics")
            with urllib.request.urlopen(req, timeout=5) as resp:
                qwen_metrics = json.loads(resp.read())
        except Exception:
            pass

        # Ollama status
        ollama_ok = False
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                d = json.loads(resp.read())
                models = [m.get("name", "") for m in d.get("models", [])]
                ollama_ok = any("qwen3.5-9b" in m for m in models)
        except Exception:
            pass

        # JEV throughput metrics: per-cycle (last 24h) counts, tasks/min, error rate
        hive_metrics = _hive_task_metrics()
        jev_created_total = hive_metrics["tasks_created_total"]
        jev_done_total = hive_metrics["tasks_done_total"]
        jev_errors_total = hive_metrics["errors_total"]
        jev_created_cycle = hive_metrics["tasks_created"]
        jev_done_cycle = hive_metrics["tasks_done"]
        jev_errors_cycle = hive_metrics["errors_cycle"]
        jev_tasks_per_min = hive_metrics["tasks_per_min"]
        jev_data_ready = bool(_HIVE_METRICS_CACHE.get("ready"))
        jev_data_age_sec = round(max(0.0, time.time() - _HIVE_METRICS_CACHE.get("ts", 0.0)), 1)

        jev_calls_today = jev_created_cycle  # per-cycle calls

        # Provider pool status from router
        pool_status = {}
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "office-os"))
            from core.router import ProviderRouter
            router = ProviderRouter()
            pool_status = router.status()
        except Exception:
            pass

        # Stock bot metrics: last run results from all_stocks_bot.py
        stocks_metrics = {}
        try:
            if STOCKS_METRICS_FILE.exists():
                with open(STOCKS_METRICS_FILE) as f:
                    stocks_metrics = json.load(f)
        except Exception:
            pass

        return {
            "service": "office-web-metrics",
            "status": "ok",
            "qwen": qwen_metrics,
            "jev": {
                # Per-cycle (last 24h) metrics — primary
                "tasks_created": jev_created_cycle,
                "tasks_done": jev_done_cycle,
                "completion_rate": round(jev_done_cycle / jev_created_cycle * 100, 1) if jev_created_cycle > 0 else 0,
                "tasks_per_min": round(jev_tasks_per_min, 1),
                "calls_today": jev_calls_today,
                "error_rate": round(jev_errors_cycle / jev_created_cycle * 100, 1) if jev_created_cycle > 0 else 0,
                # Lifetime totals — supplementary
                "tasks_created_total": jev_created_total,
                "tasks_done_total": jev_done_total,
                "error_rate_total": round(jev_errors_total / jev_created_total * 100, 1) if jev_created_total > 0 else 0,
                # Provenance of the hive aggregate — false means the counters are
                # a cold-start placeholder, not a measured value.
                "data_ready": jev_data_ready,
                "data_age_sec": jev_data_age_sec,
            },
            "ollama": {
                "available": ollama_ok,
                "model": "hauhaucs/qwen3.5-9b-uncensored-aggressive",
            },
            "stocks": stocks_metrics,
            "provider_pools": pool_status,
            "free_ceiling": {
                "calls_per_day_ceiling": 288000,
                "calls_today": jev_calls_today,
                "headroom_pct": round((1 - jev_calls_today / 288000) * 100, 1) if jev_calls_today < 288000 else 0,
            },
        }

    def _serve_metrics(self):
        """System metrics endpoint - aggregates Qwen, JEV, and Ollama health."""
        result = {}

        def _build():
            result["payload"] = self._build_metrics_payload()

        t = threading.Thread(target=_build, daemon=True)
        t.start()
        t.join(timeout=8)
        if t.is_alive():
            payload = {
                "service": "office-web-metrics",
                "status": "degraded",
                "error": "metrics build timed out",
            }
        else:
            payload = result.get(
                "payload",
                {
                    "service": "office-web-metrics",
                    "status": "error",
                    "error": "metrics build failed",
                },
            )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    # ---------- health checks ----------
    def _check_dispatcher(self):
        """Is the JEV dispatcher reachable? (http://localhost:8083/metrics)"""
        detail = {}
        url = "http://localhost:8083/metrics"
        reachable = False
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                detail["status_code"] = resp.getcode()
                reachable = resp.getcode() == 200
        except Exception as e:
            detail["error"] = str(e)
        # Supplemental context: pid file + log freshness
        pid_path = (Path.home() / ".openclaw" / "jev-dispatcher.pid")
        log_path = Path(JEV_LOG)
        try:
            detail["pid"] = int(pid_path.read_text().strip())
        except (OSError, ValueError, FileNotFoundError):
            pass
        detail["log_exists"] = log_path.exists()
        try:
            detail["log_age_sec"] = int(time.time() - log_path.stat().st_mtime)
        except OSError:
            detail["log_age_sec"] = None
        if reachable:
            return {"status": "healthy", "reachable": True, **detail}
        if detail.get("pid") or log_path.exists():
            return {"status": "degraded", "reachable": False, **detail}
        return {"status": "unhealthy", "reachable": False, **detail}

    def _check_providers(self):
        """Are provider pools available?"""
        detail = {}
        try:
            router = ProviderRouter()
            pools = router.status()
            available = sum(1 for p in pools.values() if p.get("available"))
            total = len(pools)
            detail["pools"] = {
                name: {
                    "available": p.get("available"),
                    "tier": p.get("tier"),
                    "cooldown_remaining": round(p.get("cooldown_remaining", 0), 1),
                }
                for name, p in pools.items()
            }
        except Exception as e:
            return {"status": "unhealthy", "available": 0, "total": 0, "error": str(e), **detail}
        if total == 0:
            return {"status": "unhealthy", "available": 0, "total": 0, **detail}
        if available == total:
            return {"status": "healthy", "available": available, "total": total, **detail}
        if available > 0:
            return {"status": "degraded", "available": available, "total": total, **detail}
        return {"status": "unhealthy", "available": 0, "total": total, **detail}

    def _check_findings_store(self):
        """Is the findings store accessible?"""
        paths = [(Path.home() / "Documents" / "polymarket" / "research" / "findings.json")]
        try:
            paths.append(workspace_findings_dir(DEFAULT_WORKSPACE_ID))
        except Exception:
            pass
        accessible = []
        for p in paths:
            try:
                if p.is_file():
                    json.loads(p.read_text())  # must be valid JSON
                    accessible.append(str(p))
                elif p.is_dir():
                    accessible.append(str(p))
            except Exception:
                continue
        if accessible:
            return {"status": "healthy", "accessible": True, "paths": accessible}
        return {"status": "unhealthy", "accessible": False, "paths": []}

    def _check_office_pnl(self):
        """Is office_pnl.json accessible?"""
        pnl_path = (Path.home() / ".openclaw" / "office_pnl.json")
        try:
            data = json.loads(pnl_path.read_text())
            count = len(data) if isinstance(data, list) else (1 if isinstance(data, dict) else 0)
            return {
                "status": "healthy",
                "accessible": True,
                "path": str(pnl_path),
                "entries": count,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "accessible": False,
                "path": str(pnl_path),
                "error": str(e),
            }

    def _serve_health(self):
        """GET /health (and /api/health) - aggregate health check."""
        checks = {
            "dispatcher": self._check_dispatcher(),
            "providers": self._check_providers(),
            "findings_store": self._check_findings_store(),
            "office_pnl": self._check_office_pnl(),
        }
        statuses = [c.get("status") for c in checks.values()]
        if all(s == "healthy" for s in statuses):
            overall = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"
        payload = {
            "status": overall,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._send_json(payload)

    def _serve_health_dispatcher(self):
        """GET /health/dispatcher - detailed dispatcher status."""
        check = self._check_dispatcher()
        payload = {
            "endpoint": "/health/dispatcher",
            "check": check,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            lines = Path(JEV_LOG).read_text().splitlines()
            payload["log_tail"] = lines[-5:] if lines else []
        except Exception:
            payload["log_tail"] = []
        try:
            payload["kill_switch"] = json.loads(Path(KILL_SWITCH_PATH).read_text())
        except Exception:
            payload["kill_switch"] = None
        status = 200 if check["status"] == "healthy" else 503
        self._send_json(payload, status=status)

    def _serve_health_providers(self):
        """GET /health/providers - detailed provider pool health."""
        check = self._check_providers()
        payload = {
            "endpoint": "/health/providers",
            "check": check,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._send_json(payload)

    def _serve_health_ops(self):
        """GET /health/ops - self-healing observability.

        Returns per-service heartbeat snapshots (status, last_run, error_count,
        last_error), recent healing actions, failed-over pool routing
        preferences, trading fleet state, remediation-history metrics, and
        remediation-failure alerts persisted by FleetSelfHealing.
        """
        try:
            memory = get_unified_memory()
            heartbeats = memory.get_preference("service_heartbeats", {}) or {}
            healing_actions = memory.get_preference("last_healing_actions", []) or []
            failed_over_pools = memory.get_preference("failed_over_pools", []) or []
            healing_alerts = memory.get_preference("healing_alerts", []) or []
            trading_fleet = memory.get_preference("trading_fleet", {}) or {}
            consecutive_failures = memory.get_preference("consecutive_failures", {}) or {}
        except Exception as e:
            heartbeats = {}
            healing_actions = []
            failed_over_pools = []
            healing_alerts = []
            trading_fleet = {}
            consecutive_failures = {}
            error = str(e)
        else:
            error = None

        # Remediation-history metrics computed from the persisted action log.
        by_type: dict[str, int] = {}
        by_outcome = {"success": 0, "failure": 0, "unknown": 0}
        for a in healing_actions:
            atype = a.get("type", "unknown")
            by_type[atype] = by_type.get(atype, 0) + 1
            if a.get("success") is True:
                by_outcome["success"] += 1
            elif a.get("success") is False:
                by_outcome["failure"] += 1
            else:
                by_outcome["unknown"] += 1

        # Alert summary: total alerts, escalated count, breakdown by type.
        alert_by_type: dict[str, int] = {}
        escalated = 0
        for a in healing_alerts:
            atype = a.get("action_type", "unknown")
            alert_by_type[atype] = alert_by_type.get(atype, 0) + 1
            if a.get("escalated"):
                escalated += 1

        payload = {
            "endpoint": "/health/ops",
            "services": heartbeats,
            "failed_over_pools": sorted(failed_over_pools),
            "recent_healing_actions": healing_actions[-20:],
            "recent_healing_alerts": healing_alerts[-20:],
            "trading_fleet": trading_fleet,
            "remediation_metrics": {
                "total_actions": len(healing_actions),
                "by_type": by_type,
                "by_outcome": by_outcome,
                "active_consecutive_failures": consecutive_failures,
            },
            "alert_summary": {
                "total": len(healing_alerts),
                "escalated": escalated,
                "by_type": alert_by_type,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            payload["error"] = error
        self._send_json(payload)

    def _serve_health_ops_page(self):
        """GET /health/ops/ui - self-healing observability dashboard (HTML)."""
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            memory = get_unified_memory()
            heartbeats = memory.get_preference("service_heartbeats", {}) or {}
            healing_actions = memory.get_preference("last_healing_actions", []) or []
            failed_over_pools = memory.get_preference("failed_over_pools", []) or []
            pool_scale_factors = memory.get_preference("pool_scale_factors", {}) or {}
            trading_fleet = memory.get_preference("trading_fleet", {}) or {}
            consecutive_failures = memory.get_preference("consecutive_failures", {}) or {}
            healing_alerts = memory.get_preference("healing_alerts", []) or []
        except Exception as e:
            heartbeats = {}
            healing_actions = []
            failed_over_pools = []
            pool_scale_factors = {}
            trading_fleet = {}
            consecutive_failures = {}
            healing_alerts = []
            error = str(e)
        else:
            error = None

        # Service heartbeat rows
        service_rows = ""
        if heartbeats:
            for name, hb in sorted(heartbeats.items()):
                status = hb.get("status", "unknown")
                status_class = "ok" if status == "healthy" else ("warn" if status == "degraded" else "err")
                service_rows += f"""
                    <tr>
                        <td>{escape(str(name))}</td>
                        <td class="{status_class}">{escape(str(status))}</td>
                        <td class="mono">{escape(str(hb.get('last_run', '-')))}</td>
                        <td class="mono">{escape(str(hb.get('error_count', '-')))}</td>
                        <td>{escape(str(hb.get('last_error', '-')))}</td>
                    </tr>
                """
        else:
            service_rows = '<tr><td colspan="5" class="empty">No service heartbeats recorded.</td></tr>'

        # Pool scale factor rows
        scale_rows = ""
        if pool_scale_factors:
            for name, factor in sorted(pool_scale_factors.items()):
                scale_rows += f"""
                    <tr><td>{escape(str(name))}</td><td class="mono">{escape(str(factor))}</td></tr>
                """
        else:
            scale_rows = '<tr><td colspan="2" class="empty">No pool scale factors recorded.</td></tr>'

        # Healing action rows
        action_rows = ""
        if healing_actions:
            for a in healing_actions[-20:]:
                ok = a.get("success")
                cls = "ok" if ok is True else ("err" if ok is False else "neutral")
                result = "✓" if ok is True else ("✗" if ok is False else "–")
                action_rows += f"""
                    <tr>
                        <td class="mono">{escape(str(a.get('timestamp', '')))}</td>
                        <td>{escape(str(a.get('type', '')))}</td>
                        <td>{escape(str(a.get('target', '')))}</td>
                        <td>{escape(str(a.get('reason', '')))}</td>
                        <td class="{cls}">{result}</td>
                    </tr>
                """
        else:
            action_rows = '<tr><td colspan="5" class="empty">No healing actions recorded.</td></tr>'

        fop_items = ", ".join(escape(str(p)) for p in sorted(failed_over_pools)) or "None"

        # Trading fleet summary rows
        tf_rows = ""
        if trading_fleet:
            for name in ("fleet_health_ok", "fleet_agents_alive", "fleet_agents_expected",
                         "fleet_agents_dead", "fleet_checks_failing"):
                series = trading_fleet.get(name, {})
                for label, value in series.items():
                    tf_rows += f"""
                        <tr>
                            <td class="mono">{escape(str(name))}</td>
                            <td class="mono">{escape(str(label))}</td>
                            <td class="mono">{escape(str(value))}</td>
                        </tr>
                    """
        else:
            tf_rows = '<tr><td colspan="3" class="empty">No trading fleet metrics recorded.</td></tr>'

        # Remediation metric rows
        rm_by_type = ""
        rm_total = len(healing_actions)
        rm_success = sum(1 for a in healing_actions if a.get("success") is True)
        rm_failure = sum(1 for a in healing_actions if a.get("success") is False)
        rm_types: dict[str, int] = {}
        for a in healing_actions:
            atype = a.get("type", "unknown")
            rm_types[atype] = rm_types.get(atype, 0) + 1
        for atype, count in sorted(rm_types.items()):
            rm_by_type += f"""
                <tr>
                    <td class="mono">{escape(str(atype))}</td>
                    <td class="mono">{escape(str(count))}</td>
                </tr>
            """
        if not rm_by_type:
            rm_by_type = '<tr><td colspan="2" class="empty">No remediation actions recorded.</td></tr>'

        # Cooldown / consecutive failure rows
        cf_rows = ""
        if consecutive_failures:
            for key, count in sorted(consecutive_failures.items()):
                cf_rows += f"""
                <tr>
                    <td class="mono">{escape(str(key))}</td>
                    <td class="mono {'err' if count >= 3 else 'neutral'}">{escape(str(count))}</td>
                </tr>
                """
        else:
            cf_rows = '<tr><td colspan="2" class="empty">No active cooldown failures.</td></tr>'

        # Alert rows (recent, escalated highlighted)
        alert_rows = ""
        for a in healing_alerts[-20:]:
            cls = "err" if a.get("escalated") else "neutral"
            alert_rows += f"""
                <tr>
                    <td class="mono">{escape(str(a.get('timestamp', '')))}</td>
                    <td>{escape(str(a.get('action_type', '')))}</td>
                    <td class="mono">{escape(str(a.get('target', '')))}</td>
                    <td class="mono">{escape(str(a.get('consecutive_failures', 0)))}</td>
                    <td class="{cls}">{'ESCALATED' if a.get('escalated') else 'failed'}</td>
                    <td>{escape(str(a.get('reason', ''))[:120])}</td>
                </tr>
            """
        if not alert_rows:
            alert_rows = '<tr><td colspan="6" class="empty">No remediation-failure alerts.</td></tr>'

        alert_total = len(healing_alerts)
        alert_escalated = sum(1 for a in healing_alerts if a.get("escalated"))

        error_box = (
            f'<div class="card" style="border-color:#ef4444">'
            f'<p style="color:#ef4444;margin:0">Error reading memory: {escape(error)}</p></div>'
            if error else ""
        )

        html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Dost Ops — Self-Healing Dashboard</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
                a {{ color: #3b82f6; }}
                .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
                .btn.secondary {{ background: #2a2a2a; }}
                .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
                table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
                th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #2a2a2a; }}
                th {{ color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; }}
                tr:last-child td {{ border-bottom: none; }}
                .mono {{ font-family: monospace; }}
                .ok {{ color: #10b981; }}
                .err {{ color: #ef4444; }}
                .warn {{ color: #f59e0b; }}
                .neutral {{ color: #94a3b8; }}
                .empty {{ color: #64748b; }}
                .kv {{ display: flex; gap: 1.5rem; margin-bottom: 0.5rem; }}
                .kv .label {{ color: #94a3b8; font-size: 0.8rem; }}
                .refresh {{ display: flex; gap: 0.5rem; align-items: center; margin-bottom: 1rem; }}
                .small {{ color: #64748b; font-size: 0.75rem; }}
                h1 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin: 0 0 1rem 0; }}
                h2 {{ font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin: 1rem 0 0.5rem 0; }}
            </style>
        </head>
        <body>
            <a href="/" class="btn secondary">← Dashboard</a>
            <a href="/health/ops" class="btn secondary">JSON endpoint</a>
            <button class="btn" onclick="location.reload()">Refresh</button>
            <h1>Ops — Self-Healing Observability</h1>
            {error_box}
            <div class="refresh"><span class="small">Auto-refresh every 30s · {len(heartbeats)} services · {len(failed_over_pools)} failed-over pools · {len(healing_actions)} healing actions</span></div>
            <script>setTimeout(() => location.reload(), 30000);</script>

            <h2>Services</h2>
            <table>
                <thead><tr><th>Service</th><th>Status</th><th>Last run</th><th>Errors</th><th>Last error</th></tr></thead>
                <tbody>{service_rows}</tbody>
            </table>

            <h2>Routing</h2>
            <div class="kv"><span class="label">Failed-over pools</span><span class="mono">{fop_items}</span></div>
            <table>
                <thead><tr><th>Pool</th><th>Scale factor</th></tr></thead>
                <tbody>{scale_rows}</tbody>
            </table>

            <h2>Recent healing actions</h2>
            <table>
                <thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Reason</th><th>Result</th></tr></thead>
                <tbody>{action_rows}</tbody>
            </table>

            <h2>Trading fleet (OpenAlice)</h2>
            <div class="kv">
                <span class="label">Total actions</span><span class="mono">{rm_total}</span>
                <span class="label">Succeeded</span><span class="mono ok">{rm_success}</span>
                <span class="label">Failed</span><span class="mono err">{rm_failure}</span>
            </div>
            <table>
                <thead><tr><th>Metric</th><th>Label</th><th>Value</th></tr></thead>
                <tbody>{tf_rows}</tbody>
            </table>

            <h2>Remediation history</h2>
            <table>
                <thead><tr><th>Action type</th><th>Count</th></tr></thead>
                <tbody>{rm_by_type}</tbody>
            </table>

            <h2>Active cooldowns (consecutive failures)</h2>
            <table>
                <thead><tr><th>Action key</th><th>Consecutive failures</th></tr></thead>
                <tbody>{cf_rows}</tbody>
            </table>

            <h2>Remediation-failure alerts (last 20)</h2>
            <div class="kv">
                <span class="label">Total</span><span class="mono">{alert_total}</span>
                <span class="label">Escalated</span><span class="mono {'err' if alert_escalated else 'neutral'}">{alert_escalated}</span>
            </div>
            <table>
                <thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Consecutive</th><th>Severity</th><th>Reason</th></tr></thead>
                <tbody>{alert_rows}</tbody>
            </table>
            <div class="kv"><span class="label">Generated</span><span class="mono">{escape(timestamp)}</span></div>
        </body>
        </html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_sse_events(self):
        """GET /events - Server-Sent Events stream for real-time metrics."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        import queue
        import threading

        # Create a queue for this connection
        event_queue = queue.Queue()

        # Background thread to push metrics updates
        def metrics_pusher():
            last_metrics = None
            while True:
                try:
                    # Build metrics payload (same as /api/metrics)
                    payload = self._build_metrics_payload()
                    if payload != last_metrics:
                        data = json.dumps(payload)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last_metrics = payload
                    time.sleep(5)  # Push every 5 seconds
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                except Exception:
                    time.sleep(5)

        pusher_thread = threading.Thread(target=metrics_pusher, daemon=True)
        pusher_thread.start()

        # Keep connection alive until client disconnects
        try:
            while pusher_thread.is_alive():
                time.sleep(1)
        except Exception:
            pass

    def build_activity_panel_html(self, workspace_id: str = "default") -> str:
        """Build the activity feed panel HTML from workspace activity JSONL logs.

        Shows: recent activity (last 10), activity by type breakdown, and recent
        user actions. Reads from ~/.openclaw/workspaces/{workspace_id}/activity/.
        """
        try:
            activities = get_activity_feed(workspace_id, limit=50) or []
        except Exception:
            activities = []

        # Classify each activity into a type badge.
        def classify(a):
            action = (a.get("action") or "").lower()
            target_type = (a.get("target_type") or "").lower()
            if "dispatch" in action or target_type == "dispatch":
                return "dispatch"
            if "debate" in action or target_type == "debate":
                return "debate"
            if "finding" in action or target_type == "finding":
                return "finding"
            if "cost" in action or "alert" in action or "spike" in action:
                return "cost-alert"
            return "system"

        # Recent activity (last 10)
        recent = activities[:10]
        recent_rows = ""
        if recent:
            for a in recent:
                atype = classify(a)
                ts = a.get("timestamp", "")
                time_str = ts[11:16] if len(ts) >= 16 else ts
                actor = escape(a.get("actor_email", "?"))
                action = escape(a.get("action", "?"))
                target = escape(f'{a.get("target_type", "?")}:{a.get("target_id", "?")}')
                recent_rows += f"""
                <div class="activity-item">
                    <div class="act-time">{escape(time_str)}</div>
                    <div>
                        <span class="act-actor">{actor}</span>
                        <span class="act-action">{action}</span>
                        <span class="act-target">{target}</span>
                    </div>
                    <span class="act-type activity-type-{atype}">{atype}</span>
                </div>
                """
        else:
            recent_rows = '<div class="activity-empty">No recent activity.</div>'

        # Activity by type breakdown
        type_counts = {}
        for a in activities:
            atype = classify(a)
            type_counts[atype] = type_counts.get(atype, 0) + 1
        type_order = ["dispatch", "debate", "finding", "cost-alert", "system"]
        type_labels = {
            "dispatch": "Dispatch",
            "debate": "Debate",
            "finding": "Finding",
            "cost-alert": "Cost Alert",
            "system": "System",
        }
        breakdown_rows = ""
        for atype in type_order:
            count = type_counts.get(atype, 0)
            breakdown_rows += f"""
            <div class="stat">
                <div class="num">{count}</div>
                <div class="lbl">{type_labels[atype]}</div>
            </div>
            """

        # Recent user actions (who did what, when) - last 10
        user_rows = ""
        if recent:
            for a in recent:
                ts = a.get("timestamp", "")
                time_str = ts[11:16] if len(ts) >= 16 else ts
                actor = escape(a.get("actor_email", "?"))
                action = escape(a.get("action", "?"))
                target = escape(f'{a.get("target_type", "?")}:{a.get("target_id", "?")}')
                user_rows += f"""
                <div class="activity-item">
                    <div class="act-time">{escape(time_str)}</div>
                    <div>
                        <span class="act-actor">{actor}</span>
                        <span class="act-action">{action}</span>
                        <span class="act-target">{target}</span>
                    </div>
                    <span class="act-type activity-type-{classify(a)}">{classify(a)}</span>
                </div>
                """
        else:
            user_rows = '<div class="activity-empty">No user actions yet.</div>'

        panel = f"""
        <div class="activity-feed">
            <div class="activity-legend">
                {''.join(f'<span class="leg"><span class="act-type activity-type-{t}">{t}</span> {type_labels[t]}</span>' for t in type_order)}
            </div>
            <div class="activity-breakdown">{breakdown_rows}</div>
            <h4 style="margin:0.5rem 0 0.25rem 0;font-size:0.8rem;color:#94a3b8;text-transform:uppercase">Recent Activity (last 10)</h4>
            {recent_rows}
            <h4 style="margin:1rem 0 0.25rem 0;font-size:0.8rem;color:#94a3b8;text-transform:uppercase">Recent User Actions</h4>
            {user_rows}
        </div>
        """
        return panel

    def _serve_dashboard_public(self):
        """Public HTML dashboard (no login): fleet status, autonomy tiers, kill switch, dost tasks, synthesis."""
        payload = self._build_metrics_payload()
        jev = payload.get("jev", {})
        pools = payload.get("provider_pools", {})
        free = payload.get("free_ceiling", {})

        pools_available = sum(1 for p in pools.values() if p.get("available"))
        pools_total = len(pools)

        # Kill switch: LOCKED, live_orders_allowed: false
        kill_verdict = "UNKNOWN"
        try:
            with open(KILL_SWITCH_PATH) as f:
                ks = json.load(f)
            kill_verdict = ks.get("verdict", "UNKNOWN")
        except Exception:
            pass

        # Autonomy tiers (from dispatcher knowledge)
        tier_a, tier_b, tier_c = 13, 12, 7

        # --- Cost panel: per-agent, per-type, trend, headroom from workspace pnl ---
        cost_class = "cost-ok"

        try:
            cost_stats = _workspace_pnl_costs(workspace_pnl_dir("default"))
        except Exception:
            cost_stats = _workspace_pnl_costs(Path("/nonexistent"))
        cost_units_today = cost_stats["cost_units_today"]
        net_value_today = cost_stats["net_value_today"]
        tasks_completed_today = cost_stats["tasks_completed_today"]
        debate_calls_today = cost_stats["debate_calls_today"]
        voice_dispatches_today = cost_stats["voice_dispatches_today"]
        cost_per_agent = cost_stats["cost_per_agent"]
        cost_per_type = cost_stats["cost_per_type"]
        cost_yesterday = cost_stats["cost_yesterday"]

        # Cost per agent rows
        cost_per_agent_rows = ""
        for agent, cost in sorted(cost_per_agent.items(), key=lambda x: -x[1]):
            cost_per_agent_rows += f"""
                <tr><td>{escape(agent)}</td><td class="mono">{cost}</td></tr>
            """
        if not cost_per_agent_rows:
            cost_per_agent_rows = '<tr><td colspan="2" class="empty">No agent costs today.</td></tr>'

        # Cost per task type rows (dispatch, debate, voice, history first, then any others)
        type_order = ["dispatch", "debate", "voice", "history"]
        cost_per_type_rows = ""
        for mtype in type_order:
            if mtype in cost_per_type:
                cost_per_type_rows += f"""
                    <tr><td>{escape(mtype)}</td><td class="mono">{cost_per_type[mtype]}</td></tr>
                """
        for mtype in sorted(cost_per_type.keys()):
            if mtype not in type_order:
                cost_per_type_rows += f"""
                    <tr><td>{escape(mtype)}</td><td class="mono">{cost_per_type[mtype]}</td></tr>
                """
        if not cost_per_type_rows:
            cost_per_type_rows = '<tr><td colspan="2" class="empty">No task-type costs today.</td></tr>'

        # Trend today vs yesterday
        if cost_yesterday > 0:
            trend_pct = round((cost_units_today - cost_yesterday) / cost_yesterday * 100, 1)
            trend_dir = "up" if cost_units_today >= cost_yesterday else "down"
            trend_arrow = "▲" if cost_units_today >= cost_yesterday else "▼"
            trend_html = f"""
                <div class="kv"><span class="label">Today</span><span class="value mono">{cost_units_today}</span></div>
                <div class="kv"><span class="label">Yesterday</span><span class="value mono">{cost_yesterday}</span></div>
                <div class="kv"><span class="label">Change</span><span class="value mono {trend_dir}">{trend_arrow} {abs(trend_pct)}%</span></div>
            """
        else:
            trend_html = f"""
                <div class="kv"><span class="label">Today</span><span class="value mono">{cost_units_today}</span></div>
                <div class="kv"><span class="label">Yesterday</span><span class="value mono">0</span></div>
                <div class="kv"><span class="label">Change</span><span class="value mono">—</span></div>
            """

        # Headroom percentage remaining (cost-based, from workspace plan)
        cost_headroom_pct = 100
        try:
            mc = get_current_month_cost("default")
            month_cost = int(mc.get("cost_units", 0) or 0)
            plan = get_plan("default")
            plan_limit = int(plan.get("plan", {}).get("monthly_cost_units", 500))
            if plan_limit > 0:
                cost_headroom_pct = round(max(plan_limit - month_cost, 0) / plan_limit * 100, 1)
        except Exception:
            pass

        if cost_units_today > 100:
            cost_class = "cost-bad"
        elif cost_units_today > 50:
            cost_class = "cost-warn"

        # --- Findings panel: counts from workspace findings store ---
        findings_confirmed = 0
        findings_contested = 0
        findings_pending = 0
        findings_skipped = 0
        findings_total = 0
        findings_list = []
        try:
            findings_dir = workspace_findings_dir(DEFAULT_WORKSPACE_ID)
            if findings_dir.exists():
                for f in sorted(findings_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    if f.suffix == ".json":
                        try:
                            findings_list.append(json.loads(f.read_text()))
                        except Exception:
                            continue
                findings_total = len(findings_list)
                for f in findings_list:
                    vs = f.get("verification_status", "missing")
                    if vs == "confirmed":
                        findings_confirmed += 1
                    elif vs == "contested":
                        findings_contested += 1
                    elif vs == "pending":
                        findings_pending += 1
                    elif vs == "skipped":
                        findings_skipped += 1
        except Exception:
            pass

        # Recent findings (last 10): agent, claim preview, date, verification status
        findings_recent_html = ""
        try:
            recent = sorted(findings_list, key=lambda x: x.get("date", ""), reverse=True)[:10]
            if recent:
                for f in recent:
                    agent = escape(f.get("agent", "?"))
                    claim = escape(str(f.get("claim", ""))[:90])
                    date = f.get("date", "")
                    date_str = date[11:16] if len(date) >= 16 else date
                    vs = f.get("verification_status", "missing")
                    vs_class = f"finding-{vs}" if vs in ("confirmed", "contested", "pending", "skipped") else "finding-status"
                    findings_recent_html += f"""
                    <div class="finding-item">
                        <div>
                            <div class="finding-claim">{claim}</div>
                            <div><span class="finding-agent">{agent}</span> <span class="finding-date">{escape(date_str)}</span></div>
                        </div>
                        <span class="finding-status {vs_class}">{escape(vs)}</span>
                    </div>
                    """
            else:
                findings_recent_html = '<div class="empty">No recent findings.</div>'
        except Exception as e:
            findings_recent_html = f'<div class="empty">Error reading findings: {escape(str(e))}</div>'

        # Findings by agent breakdown
        findings_agent_html = ""
        try:
            agent_counts = {}
            for f in findings_list:
                a = f.get("agent", "unknown")
                agent_counts[a] = agent_counts.get(a, 0) + 1
            if agent_counts:
                for a, c in sorted(agent_counts.items(), key=lambda x: -x[1]):
                    findings_agent_html += f'<span class="agent-chip">{escape(a)}: {c}</span>'
            else:
                findings_agent_html = '<div class="empty">No agents.</div>'
        except Exception as e:
            findings_agent_html = f'<div class="empty">Error: {escape(str(e))}</div>'

        # Pending findings needing Tier C review (highlighted in red)
        findings_tier_c_html = ""
        try:
            tier_c = [f for f in findings_list if f.get("verification_status") == "pending"]
            if tier_c:
                for f in tier_c[:10]:
                    agent = escape(f.get("agent", "?"))
                    claim = escape(str(f.get("claim", ""))[:90])
                    date = f.get("date", "")
                    date_str = date[11:16] if len(date) >= 16 else date
                    findings_tier_c_html += f"""
                    <div class="tier-c-item">
                        <div>
                            <div class="finding-claim">{claim}</div>
                            <div><span class="finding-agent">{agent}</span> <span class="finding-date">{escape(date_str)}</span></div>
                        </div>
                        <span class="finding-status finding-pending">Pending</span>
                    </div>
                    """
            else:
                findings_tier_c_html = '<div class="empty">No pending findings awaiting Tier C review.</div>'
        except Exception as e:
            findings_tier_c_html = f'<div class="empty">Error: {escape(str(e))}</div>'

        # --- Activity feed panel: recent activity, type breakdown, user actions ---
        activity_panel = self.build_activity_panel_html(workspace_id="default")

        # --- Provider health sparkline: up/down per pool ---
        sparkline_html = ""
        try:
            for pname, pinfo in pools.items():
                avail = pinfo.get("available", False)
                cd = pinfo.get("cooldown_remaining", 0)
                tier = pinfo.get("tier", "?")
                models = pinfo.get("models", [])
                model_short = models[0].split("/")[-1] if models else "?"
                if avail and cd == 0:
                    bar_class = "spark-bar up"
                    bar_title = "UP"
                elif cd > 0:
                    bar_class = "spark-bar down"
                    bar_title = f"COOLING {cd:.0f}s"
                else:
                    bar_class = "spark-bar idle"
                    bar_title = "IDLE"
                height = 30 if (avail and cd == 0) else (15 if cd > 0 else 8)
                sparkline_html += f"""
                <div style="display:flex;flex-direction:column;align-items:center;gap:4px;width:70px;">
                    <div class="spark-bar {bar_class}" style="height:{height}px;" title="{pname} ({tier}): {bar_title}"></div>
                    <div class="activity-time" style="font-size:0.65rem">{escape(pname.split('_')[-1])}</div>
                    <div class="activity-time" style="font-size:0.6rem">{model_short[:12]}</div>
                </div>
                """
            if not sparkline_html:
                sparkline_html = '<div class="empty">No provider data.</div>'
        except Exception:
            sparkline_html = '<div class="empty">Provider data unavailable.</div>'

        # Recent dost tasks (last 10, source=="dost") with status and result preview
        dost_rows = ""
        try:
            for t in _recent_dost_tasks(10):
                result = t.get("result")
                if not isinstance(result, str):
                    result = str(result) if result else ""
                preview = result.replace("\n", " ")[:120] if result else "(no result yet)"
                status = t.get("status", "pending")
                dost_rows += f"""
                <div class="task">
                    <span class="task-id">{escape(t.get('id', '?'))}</span>
                    <div>
                        <span class="status-badge status-{status}">{escape(status)}</span>
                        <span class="task-agent">{escape(t.get('agent_id', '?'))}</span><br>
                        <span class="task-title">{escape(t.get('title', '?'))}</span>
                    </div>
                    <span style="font-size:0.8rem;color:#64748b">{escape(preview)}</span>
                </div>
                """
            if not dost_rows:
                dost_rows = '<div class="empty">No dost tasks found.</div>'
        except Exception as e:
            dost_rows = f'<div class="empty">Error reading dost tasks: {escape(str(e))}</div>'

        # Synthesis panel: last synthesis output from jev-dispatcher.log
        synthesis = "No synthesis output found in log."
        try:
            with open(JEV_LOG) as f:
                log_lines = f.readlines()
            for line in reversed(log_lines):
                if "Synthesis:" in line:
                    synthesis = line.strip()
                    break
        except Exception:
            pass

        html = DASHBOARD_PUBLIC_TEMPLATE.format(
            kill_verdict=escape(kill_verdict),
            kill_live="false",
            tier_a=tier_a,
            tier_b=tier_b,
            tier_c=tier_c,
            jev_created=jev.get("tasks_created", 0),
            jev_done=jev.get("tasks_done", 0),
            completion_rate=jev.get("completion_rate", 0),
            error_rate=jev.get("error_rate", 0),
            calls_today=jev.get("calls_today", 0),
            tasks_per_min=jev.get("tasks_per_min", 0),
            pools_available=pools_available,
            pools_total=pools_total,
            headroom_pct=free.get("headroom_pct", 0),
            # Cost panel
            cost_units_today=cost_units_today,
            net_value_today=net_value_today,
            tasks_completed_today=tasks_completed_today,
            debate_calls_today=debate_calls_today,
            voice_dispatches_today=voice_dispatches_today,
            cost_class=cost_class,
            cost_per_agent_rows=cost_per_agent_rows,
            cost_per_type_rows=cost_per_type_rows,
            trend_html=trend_html,
            cost_headroom_pct=cost_headroom_pct,
            # Findings panel
            findings_confirmed=findings_confirmed,
            findings_contested=findings_contested,
            findings_pending=findings_pending,
            findings_skipped=findings_skipped,
            findings_total=findings_total,
            findings_recent_html=findings_recent_html,
            findings_agent_html=findings_agent_html,
            findings_tier_c_html=findings_tier_c_html,
            # Activity feed panel
            activity_panel=activity_panel,
            # Provider health sparkline
            sparkline_html=sparkline_html,
            dost_rows=dost_rows,
            synthesis=escape(synthesis),
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_api_findings(self):
        """API endpoint: return all findings with optional workspace_id filter."""
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        workspace_id = qs.get("workspace_id", [None])[0]
        user_id, _ = get_current_user(self.headers.get("Cookie", ""))
        email = self.headers.get("X-User-Email", "").strip() or user_id

        if workspace_id:
            ws, errored = self._validate_workspace_access(workspace_id, email)
            if errored:
                return
            findings_dir = workspace_findings_dir(workspace_id)
            findings = []
            if findings_dir.exists():
                for f in sorted(findings_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    if f.suffix == ".json":
                        try:
                            findings.append(json.loads(f.read_text()))
                        except Exception:
                            continue
            self._send_json({"workspace_id": workspace_id, "findings": findings, "total": len(findings)})
            return

        try:
            findings_path = (Path.home() / "Documents" / "polymarket" / "research" / "findings.json")
            if findings_path.exists():
                data = json.loads(findings_path.read_text())
                findings = data.get("findings", [])
            else:
                findings = []
        except Exception:
            findings = []
        self._send_json({"findings": findings, "total": len(findings)})

    def _serve_api_synthesis(self):
        """API endpoint: return synthesis detail."""
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "office-os"))
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "dost"))
            from dost import synthesis_detail
            text = synthesis_detail()
        except Exception as e:
            text = f"Error generating synthesis: {e}"
        self._send_json({"synthesis": text})

    def _serve_api_tasks(self):
        """API endpoint: return recent dost tasks with optional workspace_id filter."""
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        workspace_id = qs.get("workspace_id", [None])[0]
        user_id, _ = get_current_user(self.headers.get("Cookie", ""))
        email = self.headers.get("X-User-Email", "").strip() or user_id

        if workspace_id:
            ws, errored = self._validate_workspace_access(workspace_id, email)
            if errored:
                return
            tasks_dir = workspace_tasks_dir(workspace_id)
            tasks = []
            if tasks_dir.exists():
                for f in sorted(tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    if f.suffix == ".json":
                        try:
                            tasks.append(json.loads(f.read_text()))
                        except Exception:
                            continue
            self._send_json({"workspace_id": workspace_id, "tasks": tasks, "total": len(tasks)})
            return

        try:
            tasks = _recent_dost_tasks(20)
        except Exception:
            tasks = []
        self._send_json({"tasks": tasks, "total": len(tasks)})

    # ---------- workspace API endpoints ----------

    def _serve_api_workspaces(self):
        """GET /api/workspaces - list all workspaces (requires auth)."""
        user_id, _ = get_current_user(self.headers.get("Cookie", ""))
        if not user_id:
            self._send_json({"error": "Authentication required"}, status=401)
            return
        workspaces = list_workspaces()
        self._send_json({"workspaces": workspaces, "total": len(workspaces)})

    def _serve_api_workspace_detail(self):
        """GET /api/workspaces/{workspace_id} and sub-routes (/tasks, /findings, /metrics)."""
        user_id, _ = get_current_user(self.headers.get("Cookie", ""))
        if not user_id:
            self._send_json({"error": "Authentication required"}, status=401)
            return

        workspace_id, email = self._workspace_context()
        # Prefer path segment, fall back to header
        path = urlparse(self.path).path
        prefix = "/api/workspaces/"
        remainder = path[len(prefix):]
        parts = [p for p in remainder.split("/") if p]
        path_workspace_id = parts[0] if parts else None
        sub_route = parts[1] if len(parts) > 1 else None

        ws_id = path_workspace_id or workspace_id
        if not ws_id:
            self._send_json({"error": "Workspace ID required"}, status=400)
            return

        ws, errored = self._validate_workspace_access(ws_id, email or user_id)
        if errored:
            return

        if sub_route == "tasks":
            self._serve_workspace_tasks(ws_id, email or user_id)
        elif sub_route == "findings":
            self._serve_workspace_findings(ws_id, email or user_id)
        elif sub_route == "metrics":
            self._serve_workspace_metrics(ws_id, email or user_id)
        elif sub_route == "usage":
            self._serve_workspace_usage(ws_id, email or user_id)
        elif sub_route == "cost":
            self._serve_workspace_cost(ws_id, email or user_id)
        elif sub_route == "plan":
            self._serve_workspace_plan(ws_id, email or user_id)
        else:
            self._send_json({"workspace": ws})

    def _serve_workspace_tasks(self, workspace_id, email):
        """List tasks for a workspace."""
        tasks_dir = workspace_tasks_dir(workspace_id)
        tasks = []
        if tasks_dir.exists():
            for f in sorted(tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.suffix == ".json":
                    try:
                        tasks.append(json.loads(f.read_text()))
                    except Exception:
                        continue
        self._send_json({"workspace_id": workspace_id, "tasks": tasks, "total": len(tasks)})

    def _serve_workspace_findings(self, workspace_id, email):
        """List findings for a workspace."""
        findings_dir = workspace_findings_dir(workspace_id)
        findings = []
        if findings_dir.exists():
            for f in sorted(findings_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.suffix == ".json":
                    try:
                        findings.append(json.loads(f.read_text()))
                    except Exception:
                        continue
        self._send_json({"workspace_id": workspace_id, "findings": findings, "total": len(findings)})

    def _serve_workspace_metrics(self, workspace_id, email):
        """Get metrics for a workspace."""
        tasks_dir = workspace_tasks_dir(workspace_id)
        findings_dir = workspace_findings_dir(workspace_id)
        task_count = 0
        finding_count = 0
        if tasks_dir.exists():
            task_count = len([f for f in tasks_dir.iterdir() if f.suffix == ".json"])
        if findings_dir.exists():
            finding_count = len([f for f in findings_dir.iterdir() if f.suffix == ".json"])
        self._send_json({
            "workspace_id": workspace_id,
            "task_count": task_count,
            "finding_count": finding_count,
        })

    def _serve_workspace_usage(self, workspace_id, email):
        """GET /api/workspaces/{workspace_id}/usage - usage summary.

        Query params: metric_type (optional), start_date (optional), end_date (optional)
        Returns: {"workspace_id", "period", "total_cost_units", "by_type", "by_day"}
        """
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        metric_type = qs.get("metric_type", [None])[0]
        start_date = qs.get("start_date", [None])[0]
        end_date = qs.get("end_date", [None])[0]
        summary = get_usage_summary(
            workspace_id,
            metric_type=metric_type,
            start_date=start_date,
            end_date=end_date,
        )
        self._send_json(summary)

    def _serve_workspace_cost(self, workspace_id, email):
        """GET /api/workspaces/{workspace_id}/cost - current month cost and projection.

        Returns: {"workspace_id", "current_month_cost", "plan", "headroom", "projected_monthly"}
        """
        cost = calculate_monthly_cost(workspace_id)
        self._send_json(cost)

    def _serve_workspace_plan(self, workspace_id, email):
        """GET /api/workspaces/{workspace_id}/plan - plan details.

        Returns: {"workspace_id", "plan": {...}, "features": [...]}
        """
        plan = get_plan(workspace_id)
        self._send_json(plan)

    def _create_api_workspace(self):
        """POST /api/workspaces - create a new workspace."""
        user_id, _ = get_current_user(self.headers.get("Cookie", ""))
        if not user_id:
            self._send_json({"error": "Authentication required"}, status=401)
            return

        workspace_id, email = self._workspace_context()
        if not email:
            self._send_json({"error": "X-User-Email header required"}, status=400)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            data = {}
        name = data.get("name", f"Workspace for {email}")
        plan = data.get("plan", "starter")

        if not self._require_workspace_edit(None, email):
            return

        ws = create_workspace(name=name, owner_email=email, plan=plan)
        self._send_json({"workspace": ws}, status=201)

    def _serve_api_metrics(self):
        """GET /api/metrics - system metrics with optional workspace_id filter."""
        workspace_id, email = self._workspace_context()
        if workspace_id:
            ws, errored = self._validate_workspace_access(workspace_id, email)
            if errored:
                return
        payload = self._build_metrics_payload()
        if workspace_id:
            payload["workspace_id"] = workspace_id
            # Include cost information for the workspace
            try:
                current_month = get_current_month_cost(workspace_id)
                payload["current_month_cost"] = current_month["cost_units"]
                payload["cost_by_type"] = current_month.get("by_type", {})
            except Exception:
                payload["current_month_cost"] = 0
                payload["cost_by_type"] = {}
        self._send_json(payload)

    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        rate = getattr(self, "_rate_limit_status", None)
        if rate:
            self.send_header("X-RateLimit-Limit", str(rate["limit"]))
            self.send_header("X-RateLimit-Remaining", str(rate["remaining"]))
            self.send_header("X-RateLimit-Reset", str(rate["reset"]))
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _serve_doctor_page(self):
        """Doctor page — system health check board."""
        payload = self._build_metrics_payload()
        jev = payload.get("jev", {})
        pools = payload.get("provider_pools", {})
        free = payload.get("free_ceiling", {})

        pools_available = sum(1 for p in pools.values() if p.get("available"))
        pools_total = len(pools)

        error_rate = jev.get("error_rate")
        error_rate_total = jev.get("error_rate_total")
        if isinstance(error_rate, (int, float)) and isinstance(error_rate_total, (int, float)):
            error_line = (
                f"Error rate: {error_rate:.1f}% in the last 24h (all-time {error_rate_total:.1f}%)"
            )
        else:
            error_line = "Error rate: unavailable"

        lines = [
            "Dost Doctor — System Health Check",
            "",
            f"Dispatcher: reachable, {jev.get('tasks_done',0)}/{jev.get('tasks_created',0)} tasks done ({jev.get('completion_rate',0):.0f}%)",
            error_line,
            f"Calls today: {jev.get('calls_today',0)}",
            f"Provider pools: {pools_available}/{pools_total} available",
            f"Free-tier headroom: {free.get('headroom_pct',0):.0f}%",
            "",
            "Provider details:",
        ]
        for pname, pinfo in pools.items():
            avail = pinfo.get("available", False)
            cd = pinfo.get("cooldown_remaining", 0)
            status = "UP" if (avail and cd == 0) else f"COOLING {cd:.0f}s" if cd > 0 else "DOWN"
            lines.append(f"  {pname}: {status} (tier={pinfo.get('tier','?')})")

        # Cost cap (advisory; threshold comes from office.json)
        try:
            pnl_path = (Path.home() / ".openclaw" / "office_pnl.json")
            cap_limit = advisory_cost_cap_limit()
            if pnl_path.exists():
                today_cost = _daily_ledger_cost(pnl_path)
                lines.append(f"")
                lines.append(f"Today's cost: {today_cost} units")
                if cap_limit is None:
                    lines.append(f"  ⚠ No cost cap configured")
                elif today_cost > cap_limit:
                    lines.append(f"  ⚠ COST CAP EXCEEDED ({cap_limit} units, advisory)")
                elif today_cost > cap_limit * 0.8:
                    lines.append(f"  ⚠ Approaching cap ({cap_limit} units)")
        except Exception:
            pass

        # Findings
        try:
            findings_path = (Path.home() / "Documents" / "polymarket" / "research" / "findings.json")
            if findings_path.exists():
                data = json.loads(findings_path.read_text())
                findings = data.get("findings", [])
                vs = {}
                for f in findings:
                    s = f.get("verification_status", "missing")
                    vs[s] = vs.get(s, 0) + 1
                lines.append(f"")
                lines.append(f"Findings: {len(findings)} total")
                for s, c in sorted(vs.items()):
                    lines.append(f"  {s}: {c}")
        except Exception:
            pass

        board = "\n".join(lines)
        html_lines = []
        for line in board.split("\n"):
            if "⚠" in line or "EXCEEDED" in line:
                html_lines.append(f'<div style="color:#ef4444">{escape(line)}</div>')
            elif line.startswith("  ") and "UP" in line:
                html_lines.append(f'<div style="color:#10b981">{escape(line)}</div>')
            elif line.startswith("  ") and "COOLING" in line:
                html_lines.append(f'<div style="color:#f59e0b">{escape(line)}</div>')
            elif line.startswith("  ") and "DOWN" in line:
                html_lines.append(f'<div style="color:#ef4444">{escape(line)}</div>')
            elif line == "":
                html_lines.append('<div></div>')
            else:
                html_lines.append(f'<div>{escape(line)}</div>')
        content = "\n".join(html_lines)
        html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Dost Doctor — Health Check</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
                a {{ color: #3b82f6; }}
                .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
                .btn.secondary {{ background: #2a2a2a; }}
                .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
                pre {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; font-family: monospace; white-space: pre-wrap; }}
            </style>
        </head>
        <body>
            <a href="/" class="btn secondary">← Dashboard</a>
            <a href="/doctor?refresh=1" class="btn">Refresh</a>
            <h1>Doctor — System Health Check</h1>
            <div class="card">
                <pre>{content}</pre>
            </div>
        </body>
        </html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_review_page(self):
        """Tier C review page — findings review board."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "office-os"))
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "dost"))
        from dost import synthesis_detail
        try:
            text = synthesis_detail()
        except Exception as e:
            text = f"Error generating synthesis: {e}"
        html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Tier C Review — Findings</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
                a {{ color: #3b82f6; }}
                .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
                .btn.secondary {{ background: #2a2a2a; }}
                .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
                pre {{ background: #000; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; font-family: monospace; white-space: pre-wrap; }}
            </style>
        </head>
        <body>
            <a href="/" class="btn secondary">← Dashboard</a>
            <a href="/review?refresh=1" class="btn">Refresh</a>
            <h1>Tier C Review — Findings Board</h1>
            <div class="card">
                <pre>{escape(text)}</pre>
            </div>
            <p style="color:#94a3b8; font-size:0.8rem">Use `python3 dost.py --review 'index:action'` to confirm/contest/skip/delete findings.</p>
        </body>
        </html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_results_page(self):
        """Results page — recent dispatch results."""
        try:
            tasks = _recent_dost_tasks(30)
        except Exception:
            tasks = []
        rows = ""
        for t in tasks:
            md = t.get("metadata") or {}
            result = t.get("result") or {}
            preview = ""
            if isinstance(result, dict):
                preview = result.get("preview", "") or result.get("text", "") or ""
            elif isinstance(result, str):
                preview = result
            preview = escape(str(preview)[:120])
            rows += f"""
            <div style="padding:0.5rem 0; border-bottom:1px solid #2a2a2a;">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-family:monospace; font-size:0.8rem; color:#64748b">{escape(t.get('id','?'))}</span>
                    <span style="font-size:0.85rem; color:#cbd5e1">{escape(t.get('agent_id','?'))}</span>
                </div>
                <div style="font-size:0.9rem">{escape(t.get('title','?'))}</div>
                <div style="font-size:0.75rem; color:#64748b; margin-top:0.25rem">{preview}</div>
            </div>
            """
        if not rows:
            rows = '<div style="color:#64748b; font-style:italic">No results yet.</div>'
        html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Results — Dost Dispatch History</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }}
                a {{ color: #3b82f6; }}
                .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
                .btn.secondary {{ background: #2a2a2a; }}
                .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
            </style>
        </head>
        <body>
            <a href="/" class="btn secondary">← Dashboard</a>
            <a href="/results?refresh=1" class="btn">Refresh</a>
            <h1>Results — Recent Dispatch History</h1>
            <div class="card">
                {rows}
            </div>
        </body>
        </html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def acquire_lock(lock_path: str) -> bool:
    """Try to acquire a lock file. Returns True if we got it, False if already held."""
    lock = Path(lock_path)
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            os.kill(pid, 0)
            return False
        except (ValueError, OSError, ProcessLookupError):
            lock.unlink(missing_ok=True)
    try:
        lock.write_text(str(os.getpid()))
        return True
    except OSError:
        return False


def release_lock(lock_path: str):
    """Remove the lock file if we hold it."""
    try:
        Path(lock_path).unlink(missing_ok=True)
    except OSError:
        pass


def run(port=8083):
    lock_path = str(Path(__file__).resolve().parents[3] / "packages" / "office-os" / "logs" / "web_server.lock")
    if not acquire_lock(lock_path):
        print("[web_server] Another instance is already running. Exiting.")
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), OfficeHandler)
        _start_hive_metrics_refresher()
        print(f"Office OS web server running at http://localhost:{port}")
        print("Users: aryan (owner), demo (user)")
        print("Press Ctrl+C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nWeb server stopped.")
            server.server_close()
    finally:
        release_lock(lock_path)


if __name__ == "__main__":
    run()
