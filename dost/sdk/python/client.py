"""Dost Client - Python SDK for THE CLAUDE COMPANY API.

Provides :class:`DostClient`, a dependency-free HTTP client built on
``urllib.request`` for interacting with the Dost fleet API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .models import Debate, Finding, Task, Workspace


class DostError(Exception):
    """Base exception for Dost SDK errors."""


class DostAPIError(DostError):
    """Raised when the Dost API returns an HTTP error response."""

    def __init__(self, status: int, message: str, body: Optional[str] = None):
        self.status = status
        self.body = body
        super().__init__(f"Dost API error {status}: {message}")


class DostClient:
    """Client for interacting with THE CLAUDE COMPANY Dost API.

    All communication happens over HTTP using the standard library
    ``urllib.request``; no external dependencies are required.

    Parameters
    ----------
    api_key:
        API key used for bearer authentication.
    base_url:
        Base URL of the Dost API. Defaults to ``http://127.0.0.1:8083``.
    timeout:
        Request timeout in seconds.
    """

    def __init__(self, api_key: str, base_url: str = "http://127.0.0.1:8083", timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Send an HTTP request and return the parsed JSON body."""
        from urllib.parse import urlencode

        url = self.base_url + path
        if params:
            query = urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url += "?" + query

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise DostAPIError(exc.code, body_text, body_text)
        except urllib.error.URLError as exc:
            raise DostError(f"Request failed: {exc}")

        if not raw:
            return None
        return json.loads(raw)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def dispatch(
        self,
        prompt: str,
        agent_id: Optional[str] = None,
        priority: str = "normal",
        parent_task_id: Optional[str] = None,
        chain: Optional[dict] = None,
    ) -> dict:
        """Submit a prompt to the fleet.

        POST /tasks/dispatch
        """
        body: Dict[str, Any] = {"prompt": prompt, "priority": priority}
        if agent_id is not None:
            body["agent_id"] = agent_id
        if parent_task_id is not None:
            body["parent_task_id"] = parent_task_id
        if chain is not None:
            body["chain"] = chain
        return self._request("POST", "/tasks/dispatch", body=body)

    def debate(self, prompt: str, agents: Optional[list] = None) -> dict:
        """Start a debate.

        POST /debates
        """
        body: Dict[str, Any] = {"prompt": prompt}
        if agents is not None:
            body["agents"] = agents
        return self._request("POST", "/debates", body=body)

    def get_task(self, task_id: str) -> dict:
        """Get task details.

        GET /tasks/{task_id}
        """
        return self._request("GET", f"/tasks/{task_id}")

    def get_tasks(self, workspace_id: Optional[str] = None) -> list:
        """List tasks, optionally filtered by workspace.

        GET /tasks
        """
        params: Dict[str, Any] = {}
        if workspace_id is not None:
            params["workspace_id"] = workspace_id
        return self._request("GET", "/tasks", params=params)

    def get_findings(self, workspace_id: Optional[str] = None) -> list:
        """Get findings, optionally filtered by workspace.

        GET /findings
        """
        params: Dict[str, Any] = {}
        if workspace_id is not None:
            params["workspace_id"] = workspace_id
        return self._request("GET", "/findings", params=params)

    def get_synthesis(self) -> dict:
        """Get synthesis report.

        GET /synthesis
        """
        return self._request("GET", "/synthesis")

    def health_check(self) -> dict:
        """Check fleet health.

        GET /health
        """
        return self._request("GET", "/health")
