"""ESET Connect region + API-domain -> host mapping.

Confirmed against the live `servers` entries in ESET's own published Swagger
specs for each API family (fetched during this ticket's dev leg per the
design's Open questions -- see docs/tickets/PRD-21230.md "Self-test" for the
exact URLs and dates). ESET Connect is not one gateway host per region as
first assumed from the help-center prose; auth and each resource family are
separate per-region hosts under a shared ``eset.systems`` domain, except auth
which lives under ``iam.eset.systems``:

- Auth (OAuth2 token issuance): ``{region}.business-account.iam.eset.systems``
- Device management:            ``{region}.device-management.eset.systems``
- Incident management:          ``{region}.incident-management.eset.systems``
- Policy management:            ``{region}.policy-management.eset.systems``

A single JWT issued by the auth host is a bearer token accepted by all three
resource hosts (confirmed: an invalid bearer gets a uniform 401 "Token has
expired or is invalid" from each, not a host-specific auth scheme), so the
JWT cache stays keyed by username+region only, independent of which resource
domain a given tool call targets.
"""

from __future__ import annotations

from enum import Enum


class Region(str, Enum):
    EU = "eu"
    DE = "de"
    US = "us"
    CA = "ca"
    JPN = "jpn"


class ApiDomain(str, Enum):
    AUTH = "business-account.iam"
    DEVICE_MANAGEMENT = "device-management"
    INCIDENT_MANAGEMENT = "incident-management"
    POLICY_MANAGEMENT = "policy-management"


def domain_host(region: Region, domain: ApiDomain) -> str:
    return f"{region.value}.{domain.value}.eset.systems"


def parse_region(value: str) -> Region | None:
    """Case-insensitive parse; returns None for an invalid region string."""

    try:
        return Region(value.strip().lower())
    except ValueError:
        return None


VALID_REGIONS = ", ".join(r.value for r in Region)
