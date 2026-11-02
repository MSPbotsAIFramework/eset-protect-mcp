from __future__ import annotations

import json

import httpx
import respx

from eset_protect_mcp import api_client as api_client_module
from eset_protect_mcp.errors import run_tool_safely
from eset_protect_mcp.server import build_mcp, get_client
from eset_protect_mcp.tools.detections import _list_detections, _resolve_detection
from eset_protect_mcp.tools.devices import _get_device, _list_devices
from eset_protect_mcp.tools.policies import _assign_policy, _unassign_policy

TOKEN_URL = "https://eu.business-account.iam.eset.systems/oauth/token"
DEVICES_URL = "https://eu.device-management.eset.systems/v1/devices"
DETECTIONS_URL = "https://eu.incident-management.eset.systems/v2/detections"
POLICY_ASSIGNMENTS_URL = "https://eu.policy-management.eset.systems/v2/policy-assignments"


def _mock_token():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "tok"}))


async def test_tools_list_snapshot():
    mcp = build_mcp()
    tools = await mcp.list_tools()
    names = {t.name for t in tools}

    assert names == {
        "eset_list_device_groups",
        "eset_list_devices",
        "eset_get_device",
        "eset_list_detections",
        "eset_get_detection",
        "eset_resolve_detection",
        "eset_list_policies",
        "eset_get_policy",
        "eset_list_policy_assignments",
        "eset_assign_policy",
        "eset_unassign_policy",
    }
    assert len(tools) == 11
    for tool in tools:
        assert tool.description is not None
        assert len(tool.description) <= 500, f"{tool.name} description too long"


@respx.mock
async def test_list_devices_default_limit_and_has_more(set_credentials):
    set_credentials()
    _mock_token()
    page = [{"deviceUuid": f"d{i}", "name": f"Device {i}"} for i in range(50)]
    route = respx.get(DEVICES_URL).mock(
        return_value=httpx.Response(200, json={"devices": page, "nextPageToken": "page-2"})
    )

    result = await run_tool_safely(_list_devices(get_client, None, None))
    data = json.loads(result)

    assert "error" not in data
    assert len(data["items"]) == 50
    assert data["has_more"] is True
    # Default limit (50) is sent as the real server-side pageSize param.
    assert route.calls.last.request.url.params["pageSize"] == "50"


@respx.mock
async def test_list_devices_limit_clamped_to_hard_cap(set_credentials):
    set_credentials()
    _mock_token()
    page = [{"deviceUuid": f"d{i}"} for i in range(200)]
    route = respx.get(DEVICES_URL).mock(
        return_value=httpx.Response(200, json={"devices": page, "nextPageToken": ""})
    )

    result = await run_tool_safely(_list_devices(get_client, None, 9999))
    data = json.loads(result)

    assert "error" not in data
    assert len(data["items"]) == 200
    assert data["has_more"] is False
    # A limit above the hard cap must not be rejected, and the effective
    # pageSize sent upstream is clamped to 200, not the requested 9999.
    assert route.calls.last.request.url.params["pageSize"] == "200"


@respx.mock
async def test_get_device_not_found_maps_to_error_envelope(set_credentials):
    set_credentials()
    _mock_token()
    respx.get(f"{DEVICES_URL}/missing-uuid").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )

    result = await run_tool_safely(_get_device(get_client, "missing-uuid"))
    data = json.loads(result)

    assert data["error"]["code"] == "not_found"
    assert data["error"]["retryable"] is False


@respx.mock
async def test_list_detections_empty_result_is_not_an_error(set_credentials):
    set_credentials()
    _mock_token()
    respx.get(DETECTIONS_URL).mock(
        return_value=httpx.Response(200, json={"detections": [], "nextPageToken": ""})
    )

    result = await run_tool_safely(
        _list_detections(get_client, "resolved", "high", None, None)
    )
    data = json.loads(result)

    assert "error" not in data
    assert data == {"items": [], "has_more": False}


@respx.mock
async def test_resolve_already_resolved_detection_does_not_raise(set_credentials):
    set_credentials()
    _mock_token()
    respx.post(
        "https://eu.incident-management.eset.systems/v2/detections/det-1:resolve"
    ).mock(return_value=httpx.Response(409, json={"message": "already resolved"}))

    result = await run_tool_safely(_resolve_detection(get_client, "det-1", None))
    data = json.loads(result)

    assert "error" not in data
    assert data == {"detectionUuid": "det-1", "status": "already_resolved"}


@respx.mock(assert_all_called=False)
async def test_assign_policy_requires_explicit_target(set_credentials):
    set_credentials()
    # Deliberately no route registered for /v2/policy-assignments: if
    # client-side validation did not run first, the attempted outbound call
    # would surface as upstream_error (unmocked request), not invalid_argument.
    result = await run_tool_safely(
        _assign_policy(get_client, "policy-1", device_uuid=None, group_uuid=None)
    )
    data = json.loads(result)

    assert data["error"]["code"] == "invalid_argument"


@respx.mock
async def test_unassign_policy_not_found_maps_to_error_envelope(set_credentials):
    set_credentials()
    _mock_token()
    respx.delete(f"{POLICY_ASSIGNMENTS_URL}/assign-missing").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )

    result = await run_tool_safely(_unassign_policy(get_client, "assign-missing"))
    data = json.loads(result)

    assert data["error"]["code"] == "not_found"
    assert data["error"]["retryable"] is False


@respx.mock
async def test_rate_limited_retry_then_success(set_credentials, monkeypatch):
    set_credentials()
    _mock_token()

    async def fast_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api_client_module.asyncio, "sleep", fast_sleep)

    responses = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"devices": [{"deviceUuid": "d1"}], "nextPageToken": ""}),
    ]
    respx.get(DEVICES_URL).mock(side_effect=responses)

    result = await run_tool_safely(_list_devices(get_client, None, None))
    data = json.loads(result)

    assert "error" not in data
    assert data["items"] == [{"deviceUuid": "d1"}]


@respx.mock
async def test_rate_limited_exhausted_maps_to_error_envelope(set_credentials, monkeypatch):
    set_credentials()
    _mock_token()

    async def fast_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api_client_module.asyncio, "sleep", fast_sleep)

    respx.get(DEVICES_URL).mock(
        side_effect=lambda request: httpx.Response(429, headers={"Retry-After": "0"})
    )

    result = await run_tool_safely(_list_devices(get_client, None, None))
    data = json.loads(result)

    assert data["error"]["code"] == "rate_limited"
    assert data["error"]["retryable"] is True
