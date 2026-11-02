# eset-protect-mcp

MCP server for [ESET PROTECT](https://www.eset.com/int/business/protect-platform/) endpoint
security and EDR data, built against **ESET Connect** -- the REST gateway ESET documents as
the integration surface in front of ESET PROTECT, ESET Inspect, and ESET Cloud Office
Security (`help.eset.com/eset_connect/en-US/eset_apis.html`).

It gives an Agent read access to a tenant's managed devices and device groups, read + resolve
access to EDR detections, and read + assign/unassign access to security policies, scoped to
one region (`eu` / `de` / `us` / `ca` / `jpn`) per the Header credentials below.

- Transport: MCP Streamable HTTP (`POST /mcp`), stateless, one container serving multiple
  tenants concurrently.
- Stack: Python 3.12, [FastMCP](https://github.com/modelcontextprotocol/python-sdk), `httpx`.
- License: Apache-2.0. Copyright MSPbots.ai.

---

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

Every `/mcp` request must carry the tenant's ESET Connect API User credentials and region.
There is no environment-variable fallback -- a request missing any of these gets HTTP 401.

| Header | Required | Meaning | Where to obtain |
|---|---|---|---|
| `X-Eset-Username` | Yes | ESET Connect API User username | ESET PROTECT/Inspect console → create an API User account ([create_api_user_account](https://help.eset.com/eset_connect/en-US/create_api_user_account.html)) |
| `X-Eset-Password` | Yes | ESET Connect API User password | Same API User account |
| `X-Eset-Region` | Yes | One of `eu`, `de`, `us`, `ca`, `jpn` -- must match the region hosting the tenant's ESET PROTECT/Inspect/Cloud Office Security server | Known by the tenant admin; ESET does not publish a region-discovery endpoint |

Credentials are read per-request only (never logged, never cached on disk). A JWT obtained via
ESET's OAuth2 password grant is cached in-process for up to 55 minutes, keyed by a hash of the
username + region -- never by the raw credential, and never shared across tenants.

## Tools (11)

| Tool | Resource | Semantics |
|---|---|---|
| `eset_list_device_groups` | Devices | read-only |
| `eset_list_devices` | Devices | read-only |
| `eset_get_device` | Devices | read-only |
| `eset_list_detections` | Detections | read-only |
| `eset_get_detection` | Detections | read-only |
| `eset_resolve_detection` | Detections | destructive (marks a detection resolved) |
| `eset_list_policies` | Policies | read-only |
| `eset_get_policy` | Policies | read-only |
| `eset_list_policy_assignments` | Policies | read-only |
| `eset_assign_policy` | Policies | destructive (assigns a policy to one device or group) |
| `eset_unassign_policy` | Policies | destructive (removes a policy assignment) |

Device lifecycle writes (move/rename/create/delete), ESET Inspect EDR rule/exclusion authoring,
and the other ESET public APIs (MSP Administrator 2, Hub, Secure Authentication, Threat
Intelligence) are out of scope for this first version -- see
`docs/tickets/PRD-21230.md` for the full product design, non-goals, and the rationale behind
each choice.

## Running locally

```bash
uv sync
uv run python -m eset_protect_mcp
# in another shell, with a real or placeholder ESET Connect API User:
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'X-Eset-Username: your_username' \
  -H 'X-Eset-Password: your_password' \
  -H 'X-Eset-Region: eu' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`GET /health` is a pure local liveness probe and never calls ESET Connect.

## Testing

```bash
uv sync
uv run pytest
```

Unit tests mock ESET Connect (no network). Manual end-to-end verification against a real
ESET Connect API User account is not possible in CI/CD for this ticket (no trial tenant
available); see `docs/tickets/PRD-21230.ac.json` for the test cases marked accordingly.
