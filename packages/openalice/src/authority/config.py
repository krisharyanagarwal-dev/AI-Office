import os
from dataclasses import dataclass

_LOOPBACK_OK = ("127.0.0.1", "::1", "localhost")


@dataclass(frozen=True)
class Config:
    database_url: str
    api_token: str
    bind_host: str
    bind_port: int
    lease_ttl_seconds: int


def load_config() -> Config:
    host = os.environ.get("AUTHORITY_BIND_HOST", "127.0.0.1")
    if host not in _LOOPBACK_OK:
        raise ValueError(f"bind host must be loopback, got {host!r}")
    token = os.environ.get("AUTHORITY_API_TOKEN", "")
    if not token:
        raise ValueError("AUTHORITY_API_TOKEN is required")
    return Config(
        database_url=os.environ["DATABASE_URL"],
        api_token=token,
        bind_host=host,
        bind_port=int(os.environ.get("AUTHORITY_BIND_PORT", "4810")),
        lease_ttl_seconds=int(os.environ.get("LEASE_TTL_SECONDS", "90")),
    )
