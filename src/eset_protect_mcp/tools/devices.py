"""Device and device-group tools (read-only, Product design "Non-goals": no
device lifecycle writes in v1).

Paths and response shapes confirmed against the live ESET Connect
"device-management" Swagger spec (dev-leg lookup, see
docs/tickets/PRD-21230.md "Self-test"): device-group filtering is a separate
path (`/v1/device_groups/{groupUuid}/devices`), not a query param on
`/v1/devices`; `eset_get_device` unwraps a `{"device": {...}}` envelope.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from eset_protect_mcp.api_client import EsetConnectClient
from eset_protect_mcp.errors import map_status_code, run_tool_safely
from eset_protect_mcp.pagination import build_page, clamp_limit, extract_list, has_more_page, serialize, trim_item
from eset_protect_mcp.regions import ApiDomain

ClientFactory = Callable[[], Awaitable[EsetConnectClient]]

_DOMAIN = ApiDomain.DEVICE_MANAGEMENT


async def _list_device_groups(client_factory: ClientFactory, limit: int | None) -> str:
    client = await client_factory()
    response = await client.request(
        "GET", "/v1/device_groups", domain=_DOMAIN, params={"pageSize": clamp_limit(limit)}
    )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to list device groups")
    payload = response.json()
    groups = extract_list(payload, "deviceGroups")
    return serialize(build_page(groups, has_more_page(payload)))


async def _list_devices(
    client_factory: ClientFactory, group_uuid: str | None, limit: int | None
) -> str:
    client = await client_factory()
    path = f"/v1/device_groups/{group_uuid}/devices" if group_uuid else "/v1/devices"
    response = await client.request(
        "GET", path, domain=_DOMAIN, params={"pageSize": clamp_limit(limit)}
    )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to list devices")
    payload = response.json()
    items = extract_list(payload, "devices")
    return serialize(build_page(items, has_more_page(payload)))


async def _get_device(client_factory: ClientFactory, device_uuid: str) -> str:
    client = await client_factory()
    response = await client.request("GET", f"/v1/devices/{device_uuid}", domain=_DOMAIN)
    if response.status_code == 404:
        raise map_status_code(404, f"Device {device_uuid} not found")
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to get device")
    payload = response.json()
    device = payload.get("device", payload) if isinstance(payload, dict) else payload
    return serialize(trim_item(device))


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_list_device_groups(limit: int | None = None) -> str:
        """List the device groups ESET PROTECT manages for this tenant.

        Args:
            limit: Max groups to return (default 50, hard cap 200).
        """

        return await run_tool_safely(
            "eset_list_device_groups", _list_device_groups(client_factory, limit)
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_list_devices(group_uuid: str | None = None, limit: int | None = None) -> str:
        """List the endpoints (devices) ESET PROTECT manages for this tenant.

        Args:
            group_uuid: Restrict to devices in this device group, if set.
            limit: Max devices to return (default 50, hard cap 200).
        """

        return await run_tool_safely(
            "eset_list_devices", _list_devices(client_factory, group_uuid, limit)
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_get_device(device_uuid: str) -> str:
        """Get one device by its ESET Connect device UUID.

        Args:
            device_uuid: The device's ESET Connect UUID.
        """

        return await run_tool_safely("eset_get_device", _get_device(client_factory, device_uuid))
