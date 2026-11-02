from __future__ import annotations

import pytest

from eset_protect_mcp import server
from eset_protect_mcp.auth import JwtCache
from eset_protect_mcp.regions import Region
from eset_protect_mcp.server import Credentials, _credentials_var


@pytest.fixture(autouse=True)
def reset_jwt_cache(monkeypatch):
    """Each test gets its own JWT cache so a token issued by one test's mock
    can never satisfy another test's cache-hit/cache-miss assertions.
    """

    monkeypatch.setattr(server, "_jwt_cache", JwtCache())
    yield


@pytest.fixture
def set_credentials():
    """Push Credentials into the request ContextVar for the duration of a test,
    mirroring what the credential middleware does per-request.
    """

    tokens = []

    def _set(username: str = "user1", password: str = "pass1", region: Region = Region.EU):
        token = _credentials_var.set(Credentials(username=username, password=password, region=region))
        tokens.append(token)
        return token

    yield _set

    # pytest-asyncio may run this fixture's setup and the test body in
    # different asyncio Contexts, which makes contextvars.Token.reset()
    # raise ValueError("created in a different Context"). That's harmless
    # here -- just clear the var directly instead of resetting the token.
    for token in tokens:
        try:
            _credentials_var.reset(token)
        except ValueError:
            _credentials_var.set(None)
