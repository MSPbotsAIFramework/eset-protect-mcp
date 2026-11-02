"""EDR detection tools: read + the one explicit write action named by the
ticket's wording ("manage ... EDR data") -- resolving a detection.

Confirmed against the live ESET Connect "incident-management" Swagger spec
(dev-leg lookup, see docs/tickets/PRD-21230.md "Self-test"): `/v2/detections`
supports `pageSize`/`pageToken` but no `status`/`severity`/`deviceUuid`
filter params -- those are applied client-side on the fetched page below,
against the Detection object's own `resolved` (bool), `severityLevel`
(enum), and `device.uuid` fields. This can miss matches on a later page;
ESET Connect has no detections search endpoint for this ticket's v2
generation to filter across the full result set (documented limitation, not
a bug -- see docs/tickets/PRD-21230.md "Self-test" / Risks). `eset_get_detection`
unwraps a `{"detection": {...}}` envelope.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from eset_protect_mcp.api_client import EsetConnectClient
from eset_protect_mcp.errors import map_status_code, run_tool_safely
from eset_protect_mcp.pagination import build_page, clamp_limit, extract_list, has_more_page, serialize, trim_item
from eset_protect_mcp.regions import ApiDomain

ClientFactory = Callable[[], Awaitable[EsetConnectClient]]

_DOMAIN = ApiDomain.INCIDENT_MANAGEMENT

_RESOLVED_STATUS_WORDS = {"resolved", "closed"}
_OPEN_STATUS_WORDS = {"open", "unresolved", "active"}


def _matches_filters(
    item: dict[str, Any], status: str | None, severity: str | None, device_uuid: str | None
) -> bool:
    if status:
        wanted = status.strip().lower()
        resolved = item.get("resolved")
        if wanted in _RESOLVED_STATUS_WORDS and resolved is not True:
            return False
        if wanted in _OPEN_STATUS_WORDS and resolved is not False:
            return False
    if severity:
        level = str(item.get("severityLevel") or "").lower()
        if level != severity.strip().lower():
            return False
    if device_uuid:
        device = item.get("device") or {}
        if not isinstance(device, dict) or device.get("uuid") != device_uuid:
            return False
    return True


async def _list_detections(
    client_factory: ClientFactory,
    status: str | None,
    severity: str | None,
    device_uuid: str | None,
    limit: int | None,
) -> str:
    client = await client_factory()
    response = await client.request(
        "GET", "/v2/detections", domain=_DOMAIN, params={"pageSize": clamp_limit(limit)}
    )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to list detections")
    payload = response.json()
    items = extract_list(payload, "detections")
    # A filter matching nothing is a normal empty result, not not_found (AC6).
    filtered = [i for i in items if _matches_filters(i, status, severity, device_uuid)]
    return serialize(build_page(filtered, has_more_page(payload)))


async def _get_detection(client_factory: ClientFactory, detection_uuid: str) -> str:
    client = await client_factory()
    response = await client.request(
        "GET", f"/v2/detections/{detection_uuid}", domain=_DOMAIN
    )
    if response.status_code == 404:
        raise map_status_code(404, f"Detection {detection_uuid} not found")
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to get detection")
    payload = response.json()
    detection = payload.get("detection", payload) if isinstance(payload, dict) else payload
    return serialize(trim_item(detection))


async def _resolve_detection(
    client_factory: ClientFactory, detection_uuid: str, note: str | None
) -> str:
    client = await client_factory()
    body: dict[str, Any] = {"note": note} if note else {}
    response = await client.request(
        "POST",
        f"/v2/detections/{detection_uuid}:resolve",
        domain=_DOMAIN,
        json_body=body or None,
    )
    if response.status_code == 404:
        raise map_status_code(404, f"Detection {detection_uuid} not found")
    if response.status_code == 409:
        # ESET's documented error codes for this endpoint don't list 409, but
        # re-resolving an already-resolved detection is not a failure from
        # the agent's point of view if it ever occurs -- echo the current
        # state as a structured success rather than raising (AC7).
        return serialize(
            {"detectionUuid": detection_uuid, "status": "already_resolved"}
        )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to resolve detection")
    return serialize({"detectionUuid": detection_uuid, "status": "resolved"})


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_list_detections(
        status: str | None = None,
        severity: str | None = None,
        device_uuid: str | None = None,
        limit: int | None = None,
    ) -> str:
        """List EDR detections for this tenant, optionally filtered.

        Args:
            status: Restrict to this detection status, if set.
            severity: Restrict to this severity, if set.
            device_uuid: Restrict to detections on this device, if set.
            limit: Max detections to return (default 50, hard cap 200).
        """

        return await run_tool_safely(
            "eset_list_detections",
            _list_detections(client_factory, status, severity, device_uuid, limit),
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_get_detection(detection_uuid: str) -> str:
        """Get one EDR detection by its ESET Connect detection UUID.

        Args:
            detection_uuid: The detection's ESET Connect UUID.
        """

        return await run_tool_safely(
            "eset_get_detection", _get_detection(client_factory, detection_uuid)
        )

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def eset_resolve_detection(detection_uuid: str, note: str | None = None) -> str:
        """Mark an EDR detection as resolved. Resolving an already-resolved
        detection succeeds and echoes the current state; it is not an error.

        Args:
            detection_uuid: The detection's ESET Connect UUID.
            note: Optional free-text note to attach to the resolution.
        """

        return await run_tool_safely(
            "eset_resolve_detection", _resolve_detection(client_factory, detection_uuid, note)
        )
