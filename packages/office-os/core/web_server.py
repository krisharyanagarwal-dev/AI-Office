"""
Office OS Web Server - Localhost web UI using Python stdlib http.server.
No installs. Access at http://localhost:8083
User-based: login required, each user sees only their own tasks.
"""
import glob
import json
import os
import sys
import uuid
import time
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")
from core.hive import Hive
from core.router import ProviderRouter
from agents.god_agent import GodAgent

sys.path.insert(0, "/Users/aryanagarwal/AI-Office/dost")
from workspace import (
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
from billing.meter import get_usage_summary, get_current_month_cost
from billing.plans import get_plan, calculate_monthly_cost

OFFICE_ROOT = Path("/Users/aryanagarwal/AI-Office/packages/office-os")
CONFIG_DIR = OFFICE_ROOT / "config"

# Qwen autonomous worker directories
QWEN_DIR = Path("/Users/aryanagarwal/.openclaw/autonomous-qwen")
TASK_QUEUE_DIR = QWEN_DIR / "queue"
QWEN_RESULT_DIR = QWEN_DIR / "results"
os.makedirs(TASK_QUEUE_DIR, exist_ok=True)
os.makedirs(QWEN_RESULT_DIR, exist_ok=True)

# Hive tasks directory (Office OS)
HIVE_DIR = str(OFFICE_ROOT / "tasks")

# JEV dispatcher log & kill switch (used by the public /dashboard route)
JEV_LOG = "/Users/aryanagarwal/.openclaw/jev-dispatcher.log"
KILL_SWITCH_PATH = "/Users/aryanagarwal/AI-Office/packages/_archive/openalice-fleet/state/trader_killswitch_status.json"

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
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #0f0f0f; color: #e0e0e0; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 2rem; width: 100%; max-width: 400px; }}
        h1 {{ margin-top: 0; font-size: 1.25rem; color: #10b981; }}
        .form-group {{ margin-bottom: 1rem; }}
        .form-group label {{ display: block; margin-bottom: 0.25rem; font-size: 0.85rem; color: #94a3b8; }}
        .form-group input {{ width: 100%; background: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; padding: 0.5rem; color: #e0e0e0; font-family: inherit; }}
        .btn {{ background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: 600; width: 100%; }}
        .btn:hover {{ background: #2563eb; }}
        .users {{ margin-top: 1rem; font-size: 0.8rem; color: #64748b; }}
        .users div {{ margin-bottom: 0.25rem; }}
    </style>
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
</body>
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
    </div>

    <div class="card">
        <h3>Organisation</h3>
        {org_html}
    </div>

    <div class="card">
        <h3>Latest Results (Your Tasks)</h3>
        {result_html}
    </div>

    <p style="margin-top: 1rem; color: #64748b; font-size: 0.8rem;">
        Office OS — Zero Claude Tokens — Free Models Only — http://localhost:8083
    </p>
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
    </style>
</head>
<body>
    <header>
        <h1><span class="dot"></span> JEV Dispatcher Dashboard</h1>
        <div>
            <a href="/metrics" class="btn secondary">/metrics (JSON)</a>
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
        <div class="card">
            <h3>💰 Cost (Today)</h3>
            <div class="kv"><span class="label">Cost units used</span><span class="value mono cost-badge {cost_class}">{cost_units_today}</span></div>
            <div class="kv"><span class="label">Net value</span><span class="value mono">{net_value_today}</span></div>
            <div class="kv"><span class="label">Tasks completed</span><span class="value mono">{tasks_completed_today}</span></div>
            <div class="kv"><span class="label">Debate calls</span><span class="value mono">{debate_calls_today}</span></div>
            <div class="kv"><span class="label">Voice dispatches</span><span class="value mono">{voice_dispatches_today}</span></div>
        </div>
        <div class="card">
            <h3>🧩 Findings</h3>
            <div class="findings-grid">
                <div class="finding-stat"><div class="num">{findings_confirmed}</div><div class="lbl">Confirmed</div></div>
                <div class="finding-stat"><div class="num">{findings_contested}</div><div class="lbl">Contested</div></div>
                <div class class="finding-stat"><div class="num">{findings_pending}</div><div class="lbl">Pending</div></div>
                <div class="finding-stat"><div class="num">{findings_needs_review}</div><div class="lbl">Needs Review</div></div>
                <div class="finding-stat"><div class="num">{findings_total}</div><div class="lbl">Total</div></div>
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
        <h3>🧩 Recent Dost Tasks (last 10)</h3>
        {dost_rows}
    </div>

    <div class="card">
        <h3>📡 Activity Feed (last 10)</h3>
        {activity_rows}
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

        # Count JEV tasks in Hive
        jev_created = 0
        jev_done = 0
        try:
            for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
                try:
                    with open(hive_file) as f:
                        t = json.load(f)
                    if t.get("metadata", {}).get("source") == "jev-cloud-orchestrator":
                        jev_created += 1
                        if t.get("status") == "done":
                            jev_done += 1
                except Exception:
                    pass
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
        now = time.time()
        CYCLE_WINDOW_SEC = 24 * 60 * 60  # per-cycle = last 24 hours
        MIN_WINDOW_SEC = 60

        jev_created_total = 0
        jev_done_total = 0
        jev_errors_total = 0
        jev_created_cycle = 0
        jev_done_cycle = 0
        jev_errors_cycle = 0
        jev_tasks_per_min = 0

        try:
            for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
                try:
                    with open(hive_file) as f:
                        t = json.load(f)
                    if t.get("metadata", {}).get("source") != "jev-cloud-orchestrator":
                        continue

                    # Lifetime counts
                    jev_created_total += 1
                    if t.get("status") == "done":
                        jev_done_total += 1
                    if t.get("status") == "error":
                        jev_errors_total += 1

                    # Per-cycle counts (last 24h)
                    ts = t.get("updated_at") or t.get("created_at")
                    if ts:
                        try:
                            task_time = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
                            age_sec = now - task_time
                            if age_sec <= CYCLE_WINDOW_SEC:
                                jev_created_cycle += 1
                                if t.get("status") == "done":
                                    jev_done_cycle += 1
                                if t.get("status") == "error":
                                    jev_errors_cycle += 1
                            if age_sec <= MIN_WINDOW_SEC:
                                jev_tasks_per_min += 1
                        except ValueError:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        jev_calls_today = jev_created_cycle  # per-cycle calls

        # Provider pool status from router
        pool_status = {}
        try:
            sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")
            from core.router import ProviderRouter
            router = ProviderRouter()
            pool_status = router.status()
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
            },
            "ollama": {
                "available": ollama_ok,
                "model": "hauhaucs/qwen3.5-9b-uncensored-aggressive",
            },
            "provider_pools": pool_status,
            "free_ceiling": {
                "calls_per_day_ceiling": 288000,
                "calls_today": jev_calls_today,
                "headroom_pct": round((1 - jev_calls_today / 288000) * 100, 1) if jev_calls_today < 288000 else 0,
            },
        }

    def _serve_metrics(self):
        """System metrics endpoint - aggregates Qwen, JEV, and Ollama health."""
        payload = self._build_metrics_payload()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

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

        # --- Cost panel: today's cost_units from office_pnl.json ---
        cost_units_today = 0
        net_value_today = 0
        tasks_completed_today = 0
        debate_calls_today = 0
        voice_dispatches_today = 0
        cost_class = "cost-ok"
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            pnl_path = Path("/Users/aryanagarwal/.openclaw/office_pnl.json")
            if pnl_path.exists():
                pnl = json.loads(pnl_path.read_text())
                if isinstance(pnl, list):
                    for t in pnl:
                        created = t.get("created_at", "")
                        if not created.startswith(today_str):
                            continue
                        cost = t.get("cost_units", 0)
                        cost_units_today += cost
                        net_value_today += t.get("net_value", 0)
                        if t.get("status") == "done":
                            tasks_completed_today += 1
                        if t.get("source") == "debate":
                            debate_calls_today += 1
                        md = t.get("metadata", {}) or {}
                        if md.get("voice_dispatch"):
                            voice_dispatches_today += 1
                    if cost_units_today > 100:
                        cost_class = "cost-bad"
                    elif cost_units_today > 50:
                        cost_class = "cost-warn"
        except Exception:
            pass

        # --- Findings panel: counts from findings.json ---
        findings_confirmed = 0
        findings_contested = 0
        findings_pending = 0
        findings_needs_review = 0
        findings_total = 0
        try:
            findings_path = Path("/Users/aryanagarwal/Documents/polymarket/research/findings.json")
            if findings_path.exists():
                findings_data = json.loads(findings_path.read_text())
                findings_list = findings_data.get("findings", [])
                findings_total = len(findings_list)
                for f in findings_list:
                    vs = f.get("verification_status", "missing")
                    if vs == "confirmed":
                        findings_confirmed += 1
                    elif vs == "contested":
                        findings_contested += 1
                    elif vs == "pending":
                        findings_pending += 1
                    elif vs == "needs-review":
                        findings_needs_review += 1
        except Exception:
            pass

        # --- Activity feed: last 10 dost tasks with source type ---
        activity_rows = ""
        try:
            activity_tasks = []
            for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
                try:
                    with open(hive_file) as f:
                        t = json.load(f)
                    if t.get("metadata", {}).get("source") == "dost":
                        activity_tasks.append(t)
                except Exception:
                    pass
            activity_tasks.sort(key=lambda x: x.get("updated_at", "") or x.get("created_at", ""), reverse=True)
            for t in activity_tasks[:10]:
                md = t.get("metadata", {}) or {}
                if md.get("voice_dispatch"):
                    source_class = "source-voice"
                    source_label = "voice"
                    source_icon = "🎤"
                elif md.get("debate"):
                    source_class = "source-debate"
                    source_label = "debate"
                    source_icon = "🗣️"
                else:
                    source_class = "source-dost"
                    source_label = "dost"
                    source_icon = "📋"
                ts = t.get("updated_at", "") or t.get("created_at", "")
                time_str = ts[11:16] if len(ts) >= 16 else ts
                activity_rows += f"""
                <div class="activity-item">
                    <div>
                        <span class="activity-source {source_class}">{source_icon} {source_label}</span>
                        <span class="task-agent">{escape(t.get('agent_id', '?'))}</span><br>
                        <span class="task-title">{escape(t.get('title', '?'))[:80]}</span>
                    </div>
                    <div>
                        <span class="activity-time">{escape(time_str)}</span><br>
                        <span class="status-badge status-{t.get('status', 'pending')}">{escape(t.get('status', 'pending'))}</span>
                    </div>
                </div>
                """
            if not activity_rows:
                activity_rows = '<div class="empty">No activity yet.</div>'
        except Exception as e:
            activity_rows = f'<div class="empty">Error reading activity: {escape(str(e))}</div>'

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
            dost_tasks = []
            for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
                try:
                    with open(hive_file) as f:
                        t = json.load(f)
                    if t.get("metadata", {}).get("source") == "dost":
                        dost_tasks.append(t)
                except Exception:
                    pass
            dost_tasks.sort(key=lambda x: x.get("updated_at", "") or x.get("created_at", ""), reverse=True)
            for t in dost_tasks[:10]:
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
            # Findings panel
            findings_confirmed=findings_confirmed,
            findings_contested=findings_contested,
            findings_pending=findings_pending,
            findings_needs_review=findings_needs_review,
            findings_total=findings_total,
            # Activity feed
            activity_rows=activity_rows,
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
            findings_path = Path("/Users/aryanagarwal/Documents/polymarket/research/findings.json")
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
            sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")
            sys.path.insert(0, "/Users/aryanagarwal/AI-Office/dost")
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
            HIVE_DIR = Path("/Users/aryanagarwal/AI-Office/packages/office-os/tasks")
            tasks = []
            if HIVE_DIR.exists():
                for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
                    try:
                        with open(hive_file) as f:
                            task = json.load(f)
                        if (task.get("metadata") or {}).get("source") == "dost":
                            tasks.append(task)
                    except Exception:
                        continue
                tasks.sort(key=lambda x: x.get("updated_at", "") or x.get("created_at", ""), reverse=True)
                tasks = tasks[:20]
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

        lines = [
            "Dost Doctor — System Health Check",
            "",
            f"Dispatcher: reachable, {jev.get('tasks_done',0)}/{jev.get('tasks_created',0)} tasks done ({jev.get('completion_rate',0):.0f}%)",
            f"Error rate: {jev.get('error_rate_total',0):.1f}%",
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

        # Cost cap
        try:
            pnl_path = Path("/Users/aryanagarwal/.openclaw/office_pnl.json")
            if pnl_path.exists():
                pnl = json.loads(pnl_path.read_text())
                if isinstance(pnl, list):
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    today_cost = sum(t.get("cost_units",0) for t in pnl if t.get("created_at","").startswith(today))
                    lines.append(f"")
                    lines.append(f"Today's cost: {today_cost} units")
                    if today_cost > 100:
                        lines.append(f"  ⚠ COST CAP EXCEEDED (100 units)")
                    elif today_cost > 50:
                        lines.append(f"  ⚠ Approaching cap")
        except Exception:
            pass

        # Findings
        try:
            findings_path = Path("/Users/aryanagarwal/Documents/polymarket/research/findings.json")
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
        sys.path.insert(0, "/Users/aryanagarwal/AI-Office/packages/office-os")
        sys.path.insert(0, "/Users/aryanagarwal/AI-Office/dost")
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
            HIVE_DIR = Path("/Users/aryanagarwal/AI-Office/packages/office-os/tasks")
            tasks = []
            if HIVE_DIR.exists():
                for hive_file in glob.glob(os.path.join(HIVE_DIR, "*.json")):
                    try:
                        with open(hive_file) as f:
                            task = json.load(f)
                        if (task.get("metadata") or {}).get("source") == "dost":
                            tasks.append(task)
                    except Exception:
                        continue
                tasks.sort(key=lambda x: x.get("updated_at", "") or x.get("created_at", ""), reverse=True)
                tasks = tasks[:30]
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
    lock_path = "/Users/aryanagarwal/AI-Office/packages/office-os/logs/web_server.lock"
    if not acquire_lock(lock_path):
        print("[web_server] Another instance is already running. Exiting.")
        return
    try:
        server = HTTPServer(("127.0.0.1", port), OfficeHandler)
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
