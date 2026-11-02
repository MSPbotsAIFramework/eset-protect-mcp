"""Security policy tools: read policies, read/assign/unassign policy
assignments to a device or group (Product design Goals; no policy authoring).

Confirmed against the live ESET Connect "policy-management" Swagger spec
(dev-leg lookup, see docs/tickets/PRD-21230.md "Self-test"): assignments are
filtered by `target.deviceUuid` / `target.deviceGroupUuid` (not bare
`deviceUuid`/`groupUuid`), the assign request/response body wraps a single
`assignment` object whose `target` is `{"deviceUuid": ...}` or
`{"deviceGroupUuid": ...}`, and `eset_get_policy` unwraps a
`{"policy": {...}}` envelope. The external tool parameter names
(`device_uuid`/`group_uuid`) are unchanged -- only the wire-level field names
differ, exactly the kind of fix the design's Open questions anticipated.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from eset_protect_mcp.api_client import EsetConnectClient
from eset_protect_mcp.errors import ToolError, map_status_code, run_tool_safely
from eset_protect_mcp.pagination import build_page, clamp_limit, extract_list, has_more_page, serialize, trim_item
from eset_protect_mcp.regions import ApiDomain

ClientFactory = Callable[[], Awaitable[EsetConnectClient]]

_DOMAIN = ApiDomain.POLICY_MANAGEMENT


async def _list_policies(client_factory: ClientFactory, limit: int | None) -> str:
    client = await client_factory()
    response = await client.request(
        "GET", "/v2/policies", domain=_DOMAIN, params={"pageSize": clamp_limit(limit)}
    )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to list policies")
    payload = response.json()
    items = extract_list(payload, "policies")
    return serialize(build_page(items, has_more_page(payload)))


async def _get_policy(client_factory: ClientFactory, policy_uuid: str) -> str:
    client = await client_factory()
    response = await client.request("GET", f"/v2/policies/{policy_uuid}", domain=_DOMAIN)
    if response.status_code == 404:
        raise map_status_code(404, f"Policy {policy_uuid} not found")
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to get policy")
    payload = response.json()
    policy = payload.get("policy", payload) if isinstance(payload, dict) else payload
    return serialize(trim_item(policy))


async def _list_policy_assignments(
    client_factory: ClientFactory,
    device_uuid: str | None,
    group_uuid: str | None,
    limit: int | None,
) -> str:
    client = await client_factory()
    params: dict[str, Any] = {"pageSize": clamp_limit(limit)}
    if device_uuid:
        params["target.deviceUuid"] = device_uuid
    if group_uuid:
        params["target.deviceGroupUuid"] = group_uuid
    response = await client.request(
        "GET", "/v2/policy-assignments", domain=_DOMAIN, params=params
    )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to list policy assignments")
    payload = response.json()
    items = extract_list(payload, "assignments")
    return serialize(build_page(items, has_more_page(payload)))


def _require_exactly_one_target(device_uuid: str | None, group_uuid: str | None) -> None:
    targets = [t for t in (device_uuid, group_uuid) if t]
    if len(targets) != 1:
        raise ToolError(
            "invalid_argument",
            "Exactly one of device_uuid or group_uuid is required (not both, not neither)",
        )


async def _assign_policy(
    client_factory: ClientFactory,
    policy_uuid: str,
    device_uuid: str | None,
    group_uuid: str | None,
) -> str:
    _require_exactly_one_target(device_uuid, group_uuid)
    client = await client_factory()
    target = {"deviceUuid": device_uuid} if device_uuid else {"deviceGroupUuid": group_uuid}
    body = {"assignment": {"policyUuid": policy_uuid, "target": target}}
    response = await client.request(
        "POST", "/v2/policy-assignments", domain=_DOMAIN, json_body=body
    )
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to assign policy")
    payload = response.json() if response.content else {}
    assignment = payload.get("assignment", payload) if isinstance(payload, dict) else payload
    return serialize(trim_item(assignment)) if assignment else serialize({"status": "assigned"})


async def _unassign_policy(client_factory: ClientFactory, assignment_uuid: str) -> str:
    client = await client_factory()
    response = await client.request(
        "DELETE", f"/v2/policy-assignments/{assignment_uuid}", domain=_DOMAIN
    )
    if response.status_code == 404:
        raise map_status_code(404, f"Policy assignment {assignment_uuid} not found")
    if response.status_code >= 400:
        raise map_status_code(response.status_code, "Failed to unassign policy")
    return serialize({"assignmentUuid": assignment_uuid, "status": "unassigned"})


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_list_policies(limit: int | None = None) -> str:
        """List the security policies defined for this tenant.

        Args:
            limit: Max policies to return (default 50, hard cap 200).
        """

        return await run_tool_safely(_list_policies(client_factory, limit))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_get_policy(policy_uuid: str) -> str:
        """Get one security policy by its ESET Connect policy UUID.

        Args:
            policy_uuid: The policy's ESET Connect UUID.
        """

        return await run_tool_safely(_get_policy(client_factory, policy_uuid))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def eset_list_policy_assignments(
        device_uuid: str | None = None,
        group_uuid: str | None = None,
        limit: int | None = None,
    ) -> str:
        """List which policies are assigned to which devices or groups.

        Args:
            device_uuid: Restrict to assignments on this device, if set.
            group_uuid: Restrict to assignments on this group, if set.
            limit: Max assignments to return (default 50, hard cap 200).
        """

        return await run_tool_safely(
            _list_policy_assignments(client_factory, device_uuid, group_uuid, limit)
        )

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def eset_assign_policy(
        policy_uuid: str,
        device_uuid: str | None = None,
        group_uuid: str | None = None,
    ) -> str:
        """Assign a security policy to exactly one device or one group.
        Exactly one of device_uuid/group_uuid is required; no wildcard or
        "all devices" targets are accepted.

        Args:
            policy_uuid: The policy's ESET Connect UUID.
            device_uuid: The target device's UUID (exclusive with group_uuid).
            group_uuid: The target group's UUID (exclusive with device_uuid).
        """

        return await run_tool_safely(
            _assign_policy(client_factory, policy_uuid, device_uuid, group_uuid)
        )

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def eset_unassign_policy(assignment_uuid: str) -> str:
        """Remove a policy assignment by its ESET Connect assignment UUID.

        Args:
            assignment_uuid: The policy assignment's ESET Connect UUID.
        """

        return await run_tool_safely(_unassign_policy(client_factory, assignment_uuid))
