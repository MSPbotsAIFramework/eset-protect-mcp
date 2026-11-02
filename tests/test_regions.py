from __future__ import annotations

import time

import httpx
import respx

from eset_protect_mcp.auth import JwtCache, _cache_key
from eset_protect_mcp.regions import ApiDomain, Region, domain_host, parse_region

TOKEN_URL = "https://eu.business-account.iam.eset.systems/oauth/token"


def test_domain_host_mapping():
    assert domain_host(Region.EU, ApiDomain.AUTH) == "eu.business-account.iam.eset.systems"
    assert (
        domain_host(Region.JPN, ApiDomain.DEVICE_MANAGEMENT)
        == "jpn.device-management.eset.systems"
    )
    assert (
        domain_host(Region.US, ApiDomain.INCIDENT_MANAGEMENT)
        == "us.incident-management.eset.systems"
    )
    assert (
        domain_host(Region.CA, ApiDomain.POLICY_MANAGEMENT)
        == "ca.policy-management.eset.systems"
    )


def test_parse_region_rejects_invalid():
    assert parse_region("eu") is Region.EU
    assert parse_region("EU") is Region.EU
    assert parse_region("mars") is None


@respx.mock
async def test_jwt_cache_hit_skips_token_call():
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    )
    cache = JwtCache()
    async with httpx.AsyncClient() as http_client:
        first = await cache.get_or_authenticate(
            username="user1", password="pw", region=Region.EU, client=http_client
        )
        second = await cache.get_or_authenticate(
            username="user1", password="pw", region=Region.EU, client=http_client
        )

    assert first == second == "tok-1"
    assert token_route.call_count == 1


@respx.mock
async def test_jwt_cache_miss_after_expiry_reauths():
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "tok-2", "expires_in": 3600}),
        ]
    )
    cache = JwtCache()
    async with httpx.AsyncClient() as http_client:
        first = await cache.get_or_authenticate(
            username="user1", password="pw", region=Region.EU, client=http_client
        )
        # Force the cached entry into an expired state rather than waiting
        # out the real ~55-minute TTL.
        key = _cache_key("user1", Region.EU)
        token, _expires_at = cache._entries[key]
        cache._entries[key] = (token, time.monotonic() - 1)

        second = await cache.get_or_authenticate(
            username="user1", password="pw", region=Region.EU, client=http_client
        )

    assert first == "tok-1"
    assert second == "tok-2"
    assert token_route.call_count == 2
