"""Thin async REST wrapper over ESET Connect (SOP §5, §9 api_client.py role).

One ``httpx.AsyncClient`` is shared across requests for connection pooling;
nothing tenant-specific lives on it -- the bearer token and region are bound
per call via ``EsetConnectClient``, built fresh for each tool invocation from
that request's own credentials. The target host varies by API domain, not
just region (see regions.py) -- devices, detections, and policies each live
on their own per-region host -- so ``domain`` is a required argument on every
call rather than being fixed at construction time; the one JWT obtained for
a region is valid across all of that region's resource hosts.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from eset_protect_mcp.errors import ToolError, map_status_code
from eset_protect_mcp.logging_utils import log_api_call
from eset_protect_mcp.regions import ApiDomain, Region, domain_host

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
MAX_ATTEMPTS = 3  # initial attempt + up to 2 retries, for 429 / 5xx
TOTAL_BUDGET_SECONDS = 120.0
_DEFAULT_BACKOFF_SECONDS = 1.0

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=READ_TIMEOUT,
                pool=READ_TIMEOUT,
            )
        )
    return _client


async def aclose_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _parse_retry_after(value: str | None) -> float:
    if not value:
        return _DEFAULT_BACKOFF_SECONDS
    try:
        return max(0.0, float(value))
    except ValueError:
        # Retry-After may be an HTTP-date; not worth parsing for a bounded
        # backoff -- fall back to the default rather than block indefinitely.
        return _DEFAULT_BACKOFF_SECONDS


class EsetConnectClient:
    """Bound to one tenant's region + already-resolved JWT for one tool call."""

    def __init__(
        self,
        *,
        region: Region,
        token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._region = region
        self._token = token
        self._http = http_client or get_http_client()

    async def request(
        self,
        method: str,
        path: str,
        *,
        domain: ApiDomain,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Issue one logical call, retrying 429/5xx with backoff.

        Returns the final response regardless of status code -- callers map
        the status code to the fixed error vocabulary (errors.py). Network-
        level failures (timeout, connection error) raise httpx exceptions
        wrapped by the caller via errors.map_status_code's upstream_error path.
        """

        url = f"https://{domain_host(self._region, domain)}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
        started = time.monotonic()

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._http.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            except httpx.TimeoutException as exc:
                # status=0: a network-level failure, never reached ESET Connect
                # far enough to get an HTTP response.
                log_api_call(
                    domain=domain.value,
                    path=path,
                    status_code=0,
                    latency_ms=(time.monotonic() - started) * 1000,
                    error_code="upstream_error",
                    params=params,
                    json_body=json_body,
                )
                raise ToolError(
                    "upstream_error", f"ESET Connect request timed out: {method} {path}"
                ) from exc
            except httpx.HTTPError as exc:
                log_api_call(
                    domain=domain.value,
                    path=path,
                    status_code=0,
                    latency_ms=(time.monotonic() - started) * 1000,
                    error_code="upstream_error",
                    params=params,
                    json_body=json_body,
                )
                raise ToolError(
                    "upstream_error", f"ESET Connect request failed: {method} {path}: {exc}"
                ) from exc

            retryable_status = response.status_code == 429 or response.status_code >= 500
            remaining = deadline - time.monotonic()
            if retryable_status and attempt < MAX_ATTEMPTS and remaining > 0:
                if response.status_code == 429:
                    delay = _parse_retry_after(response.headers.get("Retry-After"))
                else:
                    delay = _DEFAULT_BACKOFF_SECONDS * (2 ** (attempt - 1))
                await asyncio.sleep(min(delay, remaining))
                continue

            error_code = (
                map_status_code(response.status_code, "").code
                if response.status_code >= 400
                else None
            )
            log_api_call(
                domain=domain.value,
                path=path,
                status_code=response.status_code,
                latency_ms=(time.monotonic() - started) * 1000,
                error_code=error_code,
                params=params,
                json_body=json_body,
            )
            return response
