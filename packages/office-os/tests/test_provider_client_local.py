"""
Local MLX pool support in ProviderClient.

The local MLX server on 127.0.0.1:11435 is an OpenAI-compatible endpoint with
no API key, no DNS lookup and a much slower token rate than the cloud pools,
so it needs its own timeout floor. These tests drive a real HTTP server on
loopback rather than mocking curl.
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.provider_client import ProviderClient

MLX_MODEL = "TheCluster/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-MLX-mxfp4"
LOCAL_POOL = "mlx_local"


class _Recorder(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.recorded.append({
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(body.decode()),
        })
        payload = json.dumps({"choices": [{"message": {"content": "local answer"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    server.recorded = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _local_client(port, model=MLX_MODEL):
    client = ProviderClient(LOCAL_POOL, model)
    client.endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
    return client


def test_local_pool_needs_no_api_key(monkeypatch):
    for name in ("NVIDIA_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = ProviderClient(LOCAL_POOL, MLX_MODEL)
    assert client.pool_name == LOCAL_POOL


def test_local_pool_does_not_resolve_dns():
    client = ProviderClient(LOCAL_POOL, MLX_MODEL)
    assert client._resolve_ip is None, "a loopback endpoint must not be sent through dig/--resolve"


def test_local_request_sends_no_authorization_header(local_server):
    client = _local_client(local_server.server_address[1])
    answer = client.complete("hello", max_tokens=16)
    assert answer == "local answer"
    assert local_server.recorded, "the local server received no request"
    assert local_server.recorded[0]["authorization"] is None, (
        "the keyless local pool must not send an Authorization header"
    )


def test_local_request_carries_the_requested_model(local_server):
    client = _local_client(local_server.server_address[1])
    client.complete("hello", max_tokens=16)
    assert local_server.recorded[0]["body"]["model"] == MLX_MODEL


def test_local_connection_refused_raises_pool_unavailable():
    client = _local_client(_closed_port())
    with pytest.raises(ProviderClient.PoolUnavailable):
        client.complete("hello", max_tokens=16, timeout=5)


def test_local_timeout_has_a_floor_above_the_cloud_default():
    client = ProviderClient(LOCAL_POOL, MLX_MODEL)
    assert client._effective_timeout("normal", None) >= 300
    assert client._effective_timeout("normal", 45) >= 300
    assert client._effective_timeout("low", None) >= 300


def test_cloud_timeout_is_not_floored(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = ProviderClient("google", "gemini-3.5-flash")
    assert client._effective_timeout("normal", 45) == 45
    assert client._effective_timeout("normal", None) == 180
