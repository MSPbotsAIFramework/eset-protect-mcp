"""Structured, credential-safe logging helpers (Tech design "Observability";
SOP §6/§11/§14 "logging & sensitive data").

Every line is one key=value record carrying a correlation id (so lines from
one incoming request can be grouped), the active tool name, and -- for lines
describing an ESET Connect call -- that call's path, status code, latency,
and mapped error code. Never: the JWT, the Authorization header, or the raw
Username/Password credentials -- those never reach this module; callers only
ever pass it the request path, status code, and the already-built params /
json_body (which never carry credentials; see api_client.py).
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

logger = logging.getLogger("eset_protect_mcp")

_request_id_var: ContextVar[str | None] = ContextVar("eset_request_id", default=None)
_tool_name_var: ContextVar[str | None] = ContextVar("eset_tool_name", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def request_scope(request_id: str) -> Iterator[None]:
    """Bind a correlation id for the lifetime of one incoming HTTP request."""

    token = _request_id_var.set(request_id)
    try:
        yield
    finally:
        _request_id_var.reset(token)


@contextmanager
def tool_scope(tool_name: str) -> Iterator[None]:
    """Bind the active tool name for the lifetime of one tool invocation."""

    token = _tool_name_var.set(tool_name)
    try:
        yield
    finally:
        _tool_name_var.reset(token)


def _summarize_args(params: dict[str, Any] | None, json_body: dict[str, Any] | None) -> str:
    """A short, non-sensitive rendering of a call's own arguments.

    ``params``/``json_body`` never carry credentials -- those only ever live
    in the ``Authorization`` header built separately (api_client.py) -- so
    it is safe to render them as-is; still bounded in length as a precaution
    against an unexpectedly large payload ending up in a log line.
    """

    merged: dict[str, Any] = {**(params or {}), **(json_body or {})}
    if not merged:
        return "-"
    return str(merged)[:200]


def log_api_call(
    *,
    domain: str,
    path: str,
    status_code: int,
    latency_ms: float,
    error_code: str | None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> None:
    """One structured line per ESET Connect call (Tech design "Observability").

    ``status_code`` is ``0`` for a network-level failure (timeout / connection
    error) that never produced an HTTP response. Logged at WARNING when
    ``error_code`` is set, INFO otherwise, so error rate is filterable by
    level alone without parsing the line.
    """

    fields = (
        f"request_id={_request_id_var.get() or '-'} "
        f"tool={_tool_name_var.get() or '-'} "
        f"domain={domain} path={path} status={status_code} "
        f"latency_ms={latency_ms:.1f} error_code={error_code or '-'} "
        f"args={_summarize_args(params, json_body)}"
    )
    if error_code:
        logger.warning("eset_connect_call %s", fields)
    else:
        logger.info("eset_connect_call %s", fields)


def log_unexpected_error(exc: Exception) -> None:
    """One structured line for a tool failure that never reached ESET Connect
    (e.g. a response-parsing bug) -- errors.py's defensive last resort.
    """

    logger.warning(
        "eset_tool_unexpected_error request_id=%s tool=%s exception_type=%s",
        _request_id_var.get() or "-",
        _tool_name_var.get() or "-",
        type(exc).__name__,
    )
