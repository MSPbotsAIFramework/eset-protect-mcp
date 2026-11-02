"""FastMCP factory, credential middleware, and the outer Starlette app.

Three Headers carry the tenant's ESET Connect identity on every request
(Tech design §5): ``X-Eset-Username``, ``X-Eset-Password``, ``X-Eset-Region``.
The middleware below is the service's one and only place that reads them; it
stores them in a ``ContextVar`` for the duration of the request (SOP §3.3)
and resets it in a ``finally`` block so nothing can leak between concurrent
requests from different tenants.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from eset_protect_mcp.api_client import EsetConnectClient, get_http_client
from eset_protect_mcp.auth import JwtCache
from eset_protect_mcp.errors import ToolError
from eset_protect_mcp.regions import VALID_REGIONS, Region, parse_region
from eset_protect_mcp.tools import detections, devices, policies

HEADER_USERNAME = "X-Eset-Username"
HEADER_PASSWORD = "X-Eset-Password"
HEADER_REGION = "X-Eset-Region"

MCP_MOUNT_PREFIX = "/mcp"

SERVICE_INSTRUCTIONS = (
    "Manage ESET PROTECT / ESET Inspect / ESET Cloud Office Security endpoint "
    "security data for one tenant via the ESET Connect gateway API. Three "
    "resource families: devices (the managed endpoints and their groups), "
    "detections (EDR findings, read and resolve), and policies (security "
    "policy definitions and their assignment to devices/groups). A typical "
    "EDR-triage flow: eset_list_detections to find open findings, "
    "eset_get_detection for detail, eset_resolve_detection once handled. A "
    "typical policy flow: eset_list_policies, then eset_assign_policy or "
    "eset_unassign_policy against a specific device or group. All tools "
    "require the tenant's ESET Connect API User credentials and region via "
    "request headers; there is no cross-tenant or cross-region access."
)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    region: Region


_credentials_var: ContextVar[Credentials | None] = ContextVar(
    "eset_credentials", default=None
)

# One process-wide, credential-fingerprinted, expiring JWT cache (SOP §3.4's
# documented exception; see auth.py).
_jwt_cache = JwtCache()


def get_credentials() -> Credentials:
    creds = _credentials_var.get()
    if creds is None:
        # The middleware already rejects any /mcp request missing Headers, so
        # this only fires if a tool is invoked outside that path (e.g. a bug).
        raise ToolError("not_configured", "No ESET Connect credentials in request context")
    return creds


async def get_client() -> EsetConnectClient:
    """Build a per-call ESET Connect client bound to this request's credentials."""

    creds = get_credentials()
    token = await _jwt_cache.get_or_authenticate(
        username=creds.username,
        password=creds.password,
        region=creds.region,
        client=get_http_client(),
    )
    return EsetConnectClient(region=creds.region, token=token)


def _missing_headers(request: Request) -> list[str]:
    missing = []
    if not request.headers.get(HEADER_USERNAME):
        missing.append(HEADER_USERNAME)
    if not request.headers.get(HEADER_PASSWORD):
        missing.append(HEADER_PASSWORD)
    if not request.headers.get(HEADER_REGION):
        missing.append(HEADER_REGION)
    return missing


async def _credential_middleware(request: Request, call_next):
    if not request.url.path.startswith(MCP_MOUNT_PREFIX):
        return await call_next(request)

    missing = _missing_headers(request)
    if missing:
        return JSONResponse(
            {
                "error": {
                    "code": "unauthorized",
                    "message": f"Missing required header(s): {', '.join(missing)}",
                    "missing_headers": missing,
                }
            },
            status_code=401,
        )

    region = parse_region(request.headers[HEADER_REGION])
    if region is None:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_argument",
                    "message": (
                        f"Invalid {HEADER_REGION}: {request.headers[HEADER_REGION]!r}; "
                        f"must be one of {VALID_REGIONS}"
                    ),
                }
            },
            status_code=400,
        )

    creds = Credentials(
        username=request.headers[HEADER_USERNAME],
        password=request.headers[HEADER_PASSWORD],
        region=region,
    )
    token = _credentials_var.set(creds)
    try:
        return await call_next(request)
    finally:
        _credentials_var.reset(token)


async def _health(_: Request) -> JSONResponse:
    # Pure local probe -- never calls ESET Connect (SOP §1.1).
    return JSONResponse({"status": "ok"})


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name="eset-protect-mcp",
        instructions=SERVICE_INSTRUCTIONS,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    devices.register(mcp, get_client)
    detections.register(mcp, get_client)
    policies.register(mcp, get_client)
    return mcp


def create_app() -> Starlette:
    mcp = build_mcp()
    mcp_asgi_app = mcp.streamable_http_app()

    app = Starlette(
        routes=[
            Route("/health", _health),
            Mount("/", app=mcp_asgi_app),
        ],
        middleware=[Middleware(BaseHTTPMiddleware, dispatch=_credential_middleware)],
        # The mounted MCP app's own lifespan manages its session manager;
        # Mount() does not propagate a sub-app's lifespan on its own, so it
        # must be wired to the outer app explicitly (SOP §7).
        lifespan=mcp_asgi_app.router.lifespan_context,
    )
    return app
