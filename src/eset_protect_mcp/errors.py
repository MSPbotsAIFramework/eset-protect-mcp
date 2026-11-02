"""Fixed error-code vocabulary and status-code mapping (SOP §4.2).

Tools never raise; every failure is returned as a JSON string envelope
``{"error": {"code", "message", "retryable"}}`` so the calling agent can
branch on ``code`` and decide whether ``retryable`` warrants another try.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Awaitable, Literal

from eset_protect_mcp.logging_utils import log_unexpected_error, tool_scope

ErrorCode = Literal[
    "not_configured",
    "unauthorized",
    "not_found",
    "invalid_argument",
    "rate_limited",
    "upstream_error",
]

# code -> default retryable flag (SOP §4.2 table)
_DEFAULT_RETRYABLE: dict[ErrorCode, bool] = {
    "not_configured": False,
    "unauthorized": False,
    "not_found": False,
    "invalid_argument": False,
    "rate_limited": True,
    "upstream_error": True,
}


@dataclass
class ToolError(Exception):
    """Carries a structured error envelope through the tool layer."""

    code: ErrorCode
    message: str
    retryable: bool | None = None

    def __post_init__(self) -> None:
        if self.retryable is None:
            self.retryable = _DEFAULT_RETRYABLE[self.code]

    def to_json(self) -> str:
        return json.dumps(
            {
                "error": {
                    "code": self.code,
                    "message": self.message,
                    "retryable": self.retryable,
                }
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )


def error_envelope(code: ErrorCode, message: str, retryable: bool | None = None) -> str:
    """Build the JSON string error envelope directly (no exception)."""

    return ToolError(code=code, message=message, retryable=retryable).to_json()


async def run_tool_safely(tool_name: str, coro: Awaitable[str]) -> str:
    """Every tool body is wrapped in this: tools never raise (SOP §4.1), they
    return the error envelope as a normal string result instead.

    ``tool_name`` binds the active-tool context (logging_utils.tool_scope) so
    every structured log line emitted while ``coro`` runs -- in particular
    api_client.py's per-call log -- carries it (Tech design "Observability").
    """

    with tool_scope(tool_name):
        try:
            return await coro
        except ToolError as exc:
            return exc.to_json()
        except Exception as exc:  # pragma: no cover - defensive last resort
            # Never echo the raw exception text here: it could be an httpx
            # error that embeds request details. Keep the message generic.
            log_unexpected_error(exc)
            return error_envelope(
                "upstream_error", f"Unexpected error: {type(exc).__name__}"
            )


def map_status_code(status_code: int, message: str) -> ToolError:
    """Map an ESET Connect HTTP status code to the fixed error vocabulary."""

    if status_code in (401, 403):
        return ToolError("unauthorized", message)
    if status_code == 404:
        return ToolError("not_found", message)
    if status_code in (400, 422):
        return ToolError("invalid_argument", message)
    if status_code == 429:
        return ToolError("rate_limited", message)
    if status_code >= 500:
        return ToolError("upstream_error", message)
    # Any other unexpected status is still an upstream problem, not ours.
    return ToolError("upstream_error", message)
