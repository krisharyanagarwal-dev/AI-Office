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
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/Users/aryanagarwal/AI-Office/office-os")
from core.hive import Hive
from core.router import ProviderRouter
from agents.god_agent import GodAgent

OFFICE_ROOT = Path("/Users/aryanagarwal/AI-Office/office-os")
CONFIG_DIR = OFFICE_ROOT / "config"

# Qwen autonomous worker directories
QWEN_DIR = Path("/Users/aryanagarwal/.openclaw/autonomous-qwen")
TASK_QUEUE_DIR = QWEN_DIR / "queue"
QWEN_RESULT_DIR = QWEN_DIR / "results"
os.makedirs(TASK_QUEUE_DIR, exist_ok=True)
os.makedirs(QWEN_RESULT_DIR, exist_ok=True)

# Hive tasks directory (Office OS)
HIVE_DIR = str(OFFICE_ROOT / "tasks")

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
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._do_login()
        elif parsed.path == "/task":
            self._create_task()
        elif parsed.path == "/qwen/task":
            self._create_qwen_task()
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

    def _serve_metrics(self):
        """System metrics endpoint - aggregates Qwen, JEV, and Ollama health."""
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

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "service": "office-web-metrics",
            "status": "ok",
            "qwen": qwen_metrics,
            "jev": {
                "tasks_created": jev_created,
                "tasks_done": jev_done,
                "completion_rate": round(jev_done / jev_created * 100, 1) if jev_created > 0 else 0,
            },
            "ollama": {
                "available": ollama_ok,
                "model": "hauhaucs/qwen3.5-9b-uncensored-aggressive",
            },
        }).encode())

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
    lock_path = "/Users/aryanagarwal/office-os/logs/web_server.lock"
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
