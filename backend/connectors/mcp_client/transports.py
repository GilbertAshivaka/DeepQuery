"""MCP transports — stdio (local subprocess) and HTTP/SSE (remote).

Because every connector (public or SDK-built) is an MCP server, a single set of
transports reaches all of them. This module normalizes a connector's registered
endpoint into a stream pair the `ClientSession` drives, regardless of transport.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from mcp import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from core.config import settings

# Transports Deep Query speaks. stdio for local/self-hosted connectors; sse and
# streamable http for remote (ecosystem) servers.
STDIO = "stdio"
SSE = "sse"
HTTP = "http"
SUPPORTED_TRANSPORTS = {STDIO, SSE, HTTP}

# Settings whose values are secrets. A stdio connector subprocess inherits the
# parent environment (so it can resolve PATH, OS dirs, and — on Windows — Docker
# Desktop's CLI-plugin lookup), but DeepQuery's own secrets are stripped first so a
# connector never sees our API keys, DB/redis creds, JWT secret, or the credential
# encryption key. Matched on field name (key/secret/password/token), plus the
# credential-bearing URLs that don't fit that pattern.
_SECRET_HINTS = ("key", "secret", "password", "token")
_DENIED_ENV = {
    name.upper()
    for name in type(settings).model_fields
    if any(h in name.lower() for h in _SECRET_HINTS)
}
_DENIED_ENV |= {"DATABASE_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "AGENT_REDIS_URL"}


def _stdio_env(overrides: Optional[dict[str, str]]) -> dict[str, str]:
    """Parent environment with DeepQuery's secrets removed, then the connector's own
    env layered on. Inheriting the parent env (minus secrets) is what lets stdio
    servers like `docker mcp` / npx-based servers actually start — the MCP SDK's
    default is a minimal env that breaks PATH/plugin resolution."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in _DENIED_ENV}
    if overrides:
        env.update(overrides)
    return env


@dataclass
class TransportConfig:
    """How to reach one connector."""

    name: str
    transport: str = STDIO
    # stdio
    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    env: Optional[dict[str, str]] = None
    # sse / http
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None

    def __post_init__(self) -> None:
        if self.transport not in SUPPORTED_TRANSPORTS:
            raise ValueError(
                f"unsupported transport {self.transport!r}; expected one of {sorted(SUPPORTED_TRANSPORTS)}"
            )
        if self.transport == STDIO and not self.command:
            raise ValueError(f"stdio connector {self.name!r} requires a command")
        if self.transport in (SSE, HTTP) and not self.url:
            raise ValueError(f"{self.transport} connector {self.name!r} requires a url")

    @classmethod
    def from_registry(cls, *, name: str, transport: str, endpoint: str | dict[str, Any]) -> "TransportConfig":
        """Build from a registry row. `endpoint` is JSON: stdio uses
        {"command","args","env"}; sse/http use {"url","headers"}."""
        data = json.loads(endpoint) if isinstance(endpoint, str) else dict(endpoint)
        return cls(
            name=name,
            transport=transport,
            command=data.get("command"),
            args=list(data.get("args", [])),
            env=data.get("env"),
            url=data.get("url"),
            headers=data.get("headers"),
        )


@asynccontextmanager
async def open_streams(config: TransportConfig) -> AsyncIterator[tuple[Any, Any]]:
    """Open a (read_stream, write_stream) pair for the connector's transport."""
    if config.transport == STDIO:
        params = StdioServerParameters(
            command=config.command, args=config.args, env=_stdio_env(config.env)
        )
        async with stdio_client(params) as (read, write):
            yield read, write
    elif config.transport == SSE:
        async with sse_client(url=config.url, headers=config.headers) as (read, write):
            yield read, write
    elif config.transport == HTTP:
        # streamable http yields a third value (a session-id getter) we don't need here.
        async with streamablehttp_client(url=config.url, headers=config.headers) as (read, write, _):
            yield read, write
    else:  # pragma: no cover - guarded in __post_init__
        raise ValueError(f"unsupported transport {config.transport!r}")
