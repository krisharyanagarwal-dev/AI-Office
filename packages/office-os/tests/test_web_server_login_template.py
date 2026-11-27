"""Tests for the login page template.

The login page is served verbatim — it never goes through ``str.format`` — so
every CSS and JS brace in it must already be a literal brace. The template
carried doubled CSS braces and quadrupled JS braces (leftovers from a
``str.format`` convention the endpoint does not use) plus chart scripts with a
missing closing brace, so the page's stylesheet and charts broke silently.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

OFFICE_OS_ROOT = (Path(__file__).resolve().parents[3] / "packages" / "office-os")
sys.path.insert(0, str(OFFICE_OS_ROOT))

web_server = pytest.importorskip("core.web_server")


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.OfficeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script[^>]*>([\s\S]*?)</script>", html)


def _styles(html: str) -> list[str]:
    return re.findall(r"<style[^>]*>([\s\S]*?)</style>", html)


def test_login_page_styles_and_scripts_have_no_escaped_braces(server):
    html = _get(f"{server}/login")

    for css in _styles(html):
        assert "{{" not in css, "stylesheet carries format-escaped braces"
        assert "}}" not in css, "stylesheet carries format-escaped braces"
    for script in _scripts(html):
        assert "{{{{" not in script, "script carries double-escaped braces"
        assert "{{" not in script, "script carries format-escaped braces"


def test_login_script_blocks_are_valid_javascript(server, tmp_path):
    html = _get(f"{server}/login")
    scripts = [script for script in _scripts(html) if script.strip()]
    assert scripts, "the login page renders no scripts"

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    for index, code in enumerate(scripts):
        path = tmp_path / f"script-{index}.js"
        path.write_text(code)
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"script {index} does not parse: {result.stderr[-400:]}"


def test_login_stylesheet_braces_are_balanced(server):
    html = _get(f"{server}/login")
    styles = _styles(html)
    assert styles, "the login page renders no stylesheet"

    for css in styles:
        assert css.count("{") == css.count("}"), "stylesheet has unbalanced braces"
        assert "{{" not in css