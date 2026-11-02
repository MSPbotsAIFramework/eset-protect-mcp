"""OAuth2 password-grant auth against ESET Connect, with a credential-bound,
expiring JWT cache (Tech design §7 / "Decisions made by DEV01").

SOP §3.4 forbids cross-request caching of tenant-derived data *unless* the
cache key is bound to the credential and the entry expires -- this is that
one allowed exception. The cache is in-process memory only, keyed by a hash
of the credential (never the raw username/password), and is never written to
disk, logged, or returned to the MCP caller.

Endpoint confirmed against the live ESET Connect "business-account" (OAuth)
Swagger spec (dev-leg Swagger lookup, see docs/tickets/PRD-21230.md
"Self-test"): the token endpoint is ``POST /oauth/token`` on the
business-account.iam host, not ``/v1/oauth-provider/token`` on the resource
gateway host as first assumed -- the latter 301-redirects to the Swagger UI,
which would otherwise surface as an opaque JSON-parse failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

import httpx

from eset_protect_mcp.errors import ToolError
from eset_protect_mcp.regions import ApiDomain, Region, domain_host

TOKEN_PATH = "/oauth/token"

# ESET's token response includes its own `expires_in` (observed 3600s via the
# live Swagger example); fall back to that example value if the field is ever
# missing, and always leave a 5-minute safety margin so a token never expires
# mid-flight on a long-running tool call.
_DEFAULT_EXPIRES_IN_SECONDS = 3600
_SAFETY_MARGIN_SECONDS = 5 * 60


def _cache_key(username: str, region: Region) -> str:
    return hashlib.sha256(f"{username}:{region.value}".encode("utf-8")).hexdigest()


class JwtCache:
    """In-process, credential-fingerprinted, expiring JWT cache.

    One instance is shared across requests within a running server process;
    each entry is isolated by its credential+region hash, so no tenant can
    ever observe another tenant's cached token. The same token is valid
    across all ESET Connect resource hosts for that region (see regions.py).
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _get_fresh(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        token, expires_at = entry
        if expires_at <= time.monotonic():
            return None
        return token

    async def get_or_authenticate(
        self,
        *,
        username: str,
        password: str,
        region: Region,
        client: httpx.AsyncClient,
    ) -> str:
        key = _cache_key(username, region)
        cached = self._get_fresh(key)
        if cached is not None:
            return cached

        async with self._lock_for(key):
            # Re-check: another concurrent caller for the same credential may
            # have already refreshed it while we waited on the lock.
            cached = self._get_fresh(key)
            if cached is not None:
                return cached

            token, expires_in = await self._authenticate(
                username=username, password=password, region=region, client=client
            )
            ttl = max(0, expires_in - _SAFETY_MARGIN_SECONDS)
            self._entries[key] = (token, time.monotonic() + ttl)
            return token

    def invalidate(self, *, username: str, region: Region) -> None:
        self._entries.pop(_cache_key(username, region), None)

    @staticmethod
    async def _authenticate(
        *,
        username: str,
        password: str,
        region: Region,
        client: httpx.AsyncClient,
    ) -> tuple[str, int]:
        host = domain_host(region, ApiDomain.AUTH)
        try:
            response = await client.post(
                f"https://{host}{TOKEN_PATH}",
                data={
                    "grant_type": "password",
                    "username": username,
                    "password": password,
                },
            )
        except httpx.TimeoutException as exc:
            raise ToolError("upstream_error", f"ESET Connect auth timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ToolError("upstream_error", f"ESET Connect auth request failed: {exc}") from exc

        if response.status_code >= 400:
            # ESET's OAuth token endpoint returns 400 (not 401) for bad
            # credentials, body `{"error": "unauthorized_client", ...}`
            # (confirmed live, see docs/tickets/PRD-21230.md "Self-test") --
            # unlike the resource APIs' 400, this call site's 400 always
            # means an auth problem, never a parameter-validation one.
            if response.status_code in (400, 401, 403):
                raise ToolError("unauthorized", "ESET Connect rejected the API user credentials")
            raise ToolError(
                "upstream_error",
                f"ESET Connect auth returned HTTP {response.status_code}",
            )

        body = response.json()
        token = body.get("access_token")
        if not token:
            raise ToolError("upstream_error", "ESET Connect auth response had no access_token")
        expires_in = body.get("expires_in") or _DEFAULT_EXPIRES_IN_SECONDS
        return token, int(expires_in)
