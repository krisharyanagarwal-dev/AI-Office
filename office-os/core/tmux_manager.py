"""
TMUX Manager - session management for Office OS agents.
Borrowed from agent-deck (tmux TUI patterns) and openrig (tmux worktrees).
Each agent runs in its own tmux session with an OpenCode CLI subprocess.
"""
import os
import subprocess
from pathlib import Path


class TMuxManager:
    def __init__(self, socket_path="/tmp/office-os-tmux"):
        self.socket_path = socket_path
        os.makedirs(os.path.dirname(socket_path), exist_ok=True)

    def _run(self, *args, check=True):
        """Run a tmux command."""
        cmd = ["tmux", "-L", "office-os", "-S", self.socket_path] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"tmux {' '.join(args)} failed: {result.stderr}")
        return result

    def session_exists(self, session_name):
        result = self._run("has-session", "-t", session_name, check=False)
        return result.returncode == 0

    def create_session(self, session_name, working_dir=None, command=None):
        """Create a new tmux session, optionally running a command."""
        if self.session_exists(session_name):
            return True

        cmd = ["new-session", "-d", "-s", session_name]
        if working_dir:
            cmd += ["-c", working_dir]
        self._run(*cmd)

        if command:
            self.send_keys(session_name, command + "\n")

        return True

    def send_keys(self, session_name, keys):
        """Send keystrokes to a tmux session."""
        self._run("send-keys", "-t", session_name, keys)

    def capture_pane(self, session_name):
        """Capture the visible contents of a tmux pane."""
        result = self._run("capture-pane", "-t", session_name, "-p")
        return result.stdout

    def kill_session(self, session_name):
        """Kill a tmux session."""
        self._run("kill-session", "-t", session_name, check=False)

    def list_sessions(self):
        """List all office-os tmux sessions."""
        result = self._run("list-sessions", "-F", "#{session_name}", check=False)
        if not result.stdout.strip():
            return []
        return [s.strip() for s in result.stdout.strip().split("\n")]

    def attach(self, session_name):
        """Print instructions to attach to a session."""
        print(f"Attach: tmux -L office-os -S {self.socket_path} attach -t {session_name}")
