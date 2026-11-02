from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.requests import Request

from eset_protect_mcp.server import _credential_middleware, create_app, get_credentials


def _scope(headers: dict[str, str], path: str = "/mcp") -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }


async def test_missing_header_returns_401_with_header_names():
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert response.status_code == 401
    body = response.json()
    missing = body["error"]["missing_headers"]
    assert set(missing) == {"X-Eset-Username", "X-Eset-Password", "X-Eset-Region"}
    for name in missing:
        assert name in body["error"]["message"]


async def test_health_does_not_depend_on_upstream():
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # No credential headers at all, and ESET Connect is never reachable
        # from this process -- /health must still answer locally.
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_concurrent_requests_do_not_leak_context():
    observed: dict[str, str] = {}

    async def run(name: str, username: str, delay: float) -> None:
        request = Request(
            _scope(
                {
                    "X-Eset-Username": username,
                    "X-Eset-Password": "pw",
                    "X-Eset-Region": "eu",
                }
            )
        )

        async def call_next(_request: Request) -> None:
            # Yield control so the two concurrent requests interleave before
            # either reads the ContextVar back out.
            await asyncio.sleep(delay)
            observed[name] = get_credentials().username
            return None

        await _credential_middleware(request, call_next)

    await asyncio.gather(run("a", "alice", 0.05), run("b", "bob", 0.01))

    assert observed == {"a": "alice", "b": "bob"}
