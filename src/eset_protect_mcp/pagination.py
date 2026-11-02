"""Pagination and response trimming (SOP §2.5).

Confirmed against the live Swagger specs (dev-leg lookup, see
docs/tickets/PRD-21230.md "Self-test"): ESET Connect's device/detection/
policy list endpoints DO support server-side pagination (`pageSize` /
`pageToken`, `nextPageToken` in the response) -- the help-center prose the
product design relied on just didn't document it. So the service requests
`pageSize=<clamped limit>` directly and treats a non-empty `nextPageToken` as
`has_more`, rather than fetching everything and slicing client-side as first
planned; the hard cap and field trimming below are still applied on this
side since ESET's own `pageSize` max (99999) is far above our token-economy
cap (SOP §2.5 wants <= 200).
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_LIMIT = 50
HARD_CAP_LIMIT = 200
MAX_RESPONSE_CHARS = 20_000

# Keys that look internal/audit-only rather than agent-relevant. The exact
# ESET Connect field names are unconfirmed (Open questions); this is a
# defensive denylist, not an assumption that these keys exist.
_AUDIT_LIKE_SUBSTRINGS = (
    "internal",
    "audit",
    "etag",
    "revision",
    "createdby",
    "modifiedby",
    "lastmodifiedby",
)


def extract_list(payload: Any, key: str) -> list[dict[str, Any]]:
    """Pull a list out of an ESET Connect response whose exact wrapper shape
    is unconfirmed (Open questions): accepts a bare JSON array, ``{key: [...]}``,
    or a generic ``{"items": [...]}`` wrapper.
    """

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get(key), list):
            return payload[key]
        if isinstance(payload.get("items"), list):
            return payload["items"]
    return []


def clamp_limit(limit: int | None) -> int:
    """Default to DEFAULT_LIMIT; clamp anything above HARD_CAP_LIMIT, never reject it (AC4)."""

    if limit is None or limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, HARD_CAP_LIMIT)


def trim_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if not any(marker in key.lower() for marker in _AUDIT_LIKE_SUBSTRINGS)
    }


def has_more_page(payload: Any) -> bool:
    """True if the response's `nextPageToken` says there is another page."""

    return isinstance(payload, dict) and bool(payload.get("nextPageToken"))


def build_page(items: list[dict[str, Any]], has_more: bool) -> dict[str, Any]:
    """Field-trim a server-paginated page and wrap it in the {"items","has_more"} envelope."""

    return {"items": [trim_item(item) for item in items], "has_more": has_more}


def paginate(items: list[dict[str, Any]], limit: int | None) -> dict[str, Any]:
    """Client-side fallback: apply the limit cap and field trimming or.

    Used only where ESET Connect has no server-side pageSize for a given
    call (none identified for the v1 tool set, but kept as a safety net).
    """

    effective_limit = clamp_limit(limit)
    trimmed = [trim_item(item) for item in items]
    page = trimmed[:effective_limit]
    has_more = len(trimmed) > effective_limit
    return {"items": page, "has_more": has_more}


def serialize(payload: dict[str, Any]) -> str:
    """Compact, non-ASCII-escaping JSON serialization with a character cap (SOP §2.5)."""

    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(text) <= MAX_RESPONSE_CHARS:
        return text

    # Only list-shaped payloads are expected to need truncation; drop items
    # from the tail until it fits, and flag has_more.
    if "items" in payload and isinstance(payload["items"], list):
        items = list(payload["items"])
        truncated = dict(payload)
        while items:
            items.pop()
            truncated["items"] = items
            truncated["has_more"] = True
            text = json.dumps(truncated, separators=(",", ":"), ensure_ascii=False)
            if len(text) <= MAX_RESPONSE_CHARS:
                return text
        truncated["items"] = []
        return json.dumps(truncated, separators=(",", ":"), ensure_ascii=False)

    # Non-list payload too large to truncate structurally -- return as-is;
    # this should not happen for the single-resource "get" tools in v1 given
    # the field trimming above.
    return text
