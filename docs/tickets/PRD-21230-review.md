# PRD-21230 · Code review

Status: frozen @ 16dfaf2

## Round 1 · 2026-11-02 · reviewed dev/PRD-21230 e6f49bc (base main be47d42)

Verdict: changes requested

### Findings

1. [must-fix] docs/tickets/PRD-21230.md:530,596 — The repo contains Chinese text, violating the
   vendor-mcp-development SOP's English-only rule (SOP §0.4: "all repo content is English: code,
   comments, tool descriptions, error messages, logs, docs, and commit messages all without Chinese"),
   which explicitly covers the committed ticket doc (SKILL.md: "the pipeline docs in the repo...like
   the rest of the repo's content, English only (SOP §0.4), no Chinese version"). Line 530 quotes
   `references/gates.md`'s Chinese section title (translated: "the repo's own declared tests"); line 596
   quotes "dev lock" (translated from Chinese). Re-running the
   scan the Self-test section itself specifies confirms this: `grep -rnP '[\x{4e00}-\x{9fff}]'
   --exclude-dir=.git --exclude-dir=.venv .` on `dev/PRD-21230` at `e6f49bc` returns these two hits — the
   Self-test's claim "No output (clean), run twice" does not hold for the frozen commit (the quotes were
   likely added in the `e6f49bc` "freeze design doc" commit, after the scan was last run). Fix: rephrase
   both references in English (e.g. "the repo's own tests" / "the dev-lock step") so the scan returns no
   output.

2. [must-fix] src/eset_protect_mcp/ (whole package) — No logging code exists anywhere in the
   implementation (`grep -rn "import logging\|getLogger\|print(" src` returns nothing), but the Tech
   design's own "Observability" section (docs/tickets/PRD-21230.md:341-343) commits to: "structured logs
   include tool name, a non-sensitive arg summary …, the ESET Connect path and status code, latency, and
   the mapped error code; never the JWT or raw credentials." This is also SOP §14 Checklist's explicit
   "logging & sensitive data" item (translated from Chinese): "structured logs carry a request-id;
   never print credentials / tokens / sensitive business data"
   (`reference/vendor-mcp-development-sop.md:484`). Right now there is nothing to redact in the first
   place because nothing is logged, which trivially satisfies the "never log credentials" half but fails
   the "structured logs for tool name / path / status / latency / error code" half outright — there would
   be no observability into this service's behavior in INT (tool call volume, latency, error rates by
   code) until this is added. Fix: add structured logging (tool name, path/domain, status code, latency,
   mapped error code) at the call boundary in `api_client.py`/`server.py`, matching what the Tech design
   already promises; never log the Username/Password headers or the JWT.

### Suggestions (not blocking)

3. [suggestion] src/eset_protect_mcp/tools/policies.py:178 (`eset_unassign_policy` registration) — The
   Tech design's "Idempotency & concurrency" section (docs/tickets/PRD-21230.md:324-329) explicitly
   distinguishes `eset_unassign_policy` as "naturally idempotent" from `eset_resolve_detection` /
   `eset_assign_policy`, which it says are deliberately "not annotated `idempotentHint`" — implying
   `eset_unassign_policy` was meant to carry `idempotentHint=True` alongside its existing
   `destructiveHint=True`. The code only sets `destructiveHint=True`. No AC or test depends on this
   annotation, so it is not blocking, but it is a one-line gap against the design's own stated intent.

4. [suggestion] src/eset_protect_mcp/auth.py:54-61 (`JwtCache._locks`) — Each distinct
   `sha256(username+region)` key gets its own `asyncio.Lock` entry that is never removed, even after the
   corresponding cache entry expires. In a long-running process serving many distinct tenants this dict
   grows without bound (one lock per tenant+region ever seen, not per currently-cached tenant). Low risk
   in practice (bounded by the number of distinct registered tenants actually calling this service), but
   worth a follow-up if tenant churn turns out to be high.

### What was verified independently (not just re-reading the Self-test claims)

- `uv sync && uv run pytest -v` on `e6f49bc`: 17/17 passed, matching the Self-test table exactly.
- `docker build --platform linux/amd64 -t eset-protect-mcp:review .`: succeeded.
- Container smoke test: `GET /health` → 200 `{"status":"ok"}`; `tools/list` with no headers → 401 listing
  all three missing header names; `tools/list` with placeholder headers → 200, 11 tools returned.
- Measured every tool's live `description` length from the running container (FastMCP does not dedent
  the raw docstring, so the wire value includes the literal `Args:` block and indentation): longest is
  `eset_assign_policy` at 416 chars, all 11 under the 500-char cap (AC1 holds in practice, not just in
  the `test_tools_list_snapshot` assertion).
- README "MSPbots Connector" section: byte-for-byte `diff` against
  `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` (71 lines) — exit 0.
- `git merge-base --is-ancestor e6f49bc origin/main` → not an ancestor (not yet merged); `BASE` in the
  `[DEV]` stub (`main @ be47d42`) matches `origin/main`'s current HEAD, so no re-sync is needed before
  merging once this round is fixed.
- Credential-isolation and JWT-cache tests (`test_concurrent_requests_do_not_leak_context`,
  `test_jwt_cache_hit_skips_token_call`, `test_jwt_cache_miss_after_expiry_reauths`) read and confirmed
  sound: real concurrency via `asyncio.gather`, real cache-expiry forcing, not mocked-out internals.
- Chinese-text scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`):
  2 hits, both in `docs/tickets/PRD-21230.md` (Finding 1).
- `grep -rn "import logging\|getLogger\|print(" src`: no output (Finding 2).

Not merged this round — see Finding 1 and 2 above. No gateway or platform repo is involved
(`Track: vendor-mcp`, single repo, `Release order: any`), so there is nothing else to stage.

### Fixes (round 1, applied on `dev/PRD-21230`)

Only the two must-fix items were addressed; the two suggestions (`eset_unassign_policy`
`idempotentHint`, `JwtCache._locks` pruning) were deliberately left untouched — they were marked
not-blocking and are out of scope for a review-fix round.

1. **Must-fix 1 (Chinese text)**: translated the two flagged quotes in `docs/tickets/PRD-21230.md`
   (lines 530, 596 at the time of the finding) from Chinese section-title fragments to their English
   equivalents ("the repo's own declared tests", "dev lock"), without changing anything else in that
   frozen document (no AC, conclusion, or Self-test result was touched). Re-running the scan also
   turned up two more hits this finding did not name: this review document (`PRD-21230-review.md`)
   itself quotes the Chinese SOP text verbatim as evidence for Finding 1 and Finding 2, which is the
   same violation in a different file. Translated those quotes too (meaning preserved, citation kept),
   since the English-only gate is repo-wide and a file this round itself edits cannot be left failing
   it. `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.pytest_cache .`
   now returns no output (exit 1).

2. **Must-fix 2 (no structured logging)**: added a new `src/eset_protect_mcp/logging_utils.py`
   (structured `key=value` logger named `eset_protect_mcp`, a per-request `request_id` ContextVar
   bound in `server.py`'s credential middleware, and a per-tool-call `tool_name` ContextVar bound by
   `errors.run_tool_safely`, which now takes the tool name as its first argument — every one of the
   11 `@mcp.tool` call sites in `tools/devices.py` / `tools/detections.py` / `tools/policies.py`, and
   the matching 9 direct calls in `tests/test_tools.py`, were updated to pass it). `api_client.py`'s
   `EsetConnectClient.request()` now logs one line per ESET Connect call (success, retried-then-final,
   or network failure) with: `request_id`, `tool`, `domain`, `path`, `status` (`0` for a network-level
   failure that never got a response), `latency_ms`, `error_code` (`-` on success, else the same code
   the tool's error envelope uses), and a non-sensitive `args` summary built only from the call's own
   `params`/`json_body` (which never carry credentials — those only ever live in the `Authorization`
   header built separately and are never passed to the logger). `errors.run_tool_safely`'s defensive
   last-resort branch (an exception that never reached ESET Connect) now also logs one line via
   `logging_utils.log_unexpected_error`. Verified independently with a throwaway script
   (`~/.claude/skills/mb-ticket-pipeline/scratch/PRD-21230/verify_logging.py`, not part of this repo):
   ran a 200 and a 404 tool call through `run_tool_safely` with a real `respx`-mocked JWT exchange
   using a deliberately distinctive fake password and JWT value, captured the emitted log records, and
   asserted the captured text contains `tool=`, `status=200`/`404`, `error_code=not_found`,
   `latency_ms=`, and a non-`-` `request_id=`, while asserting the fake password string, the fake JWT
   string, and the literal substring `Bearer` are all absent from every captured line — all assertions
   passed.

Gates re-run on the fixed commit (see `docs/tickets/PRD-21230.md` "Self-test" for the original table;
not re-duplicated there since the main document stays frozen — this round's results live here):

| Gate | Command | Result |
|---|---|---|
| Unit tests | `uv sync && uv run pytest -v` | **17 passed**, 0 failed, 0.19s — same 17 node IDs as round 1, all still green after the `run_tool_safely` signature change |
| Chinese-text scan | `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=.pytest_cache .` | No output (exit 1) |
| Container build | `sudo docker build --platform linux/amd64 -t eset-protect-mcp:review2 .` | `naming to docker.io/library/eset-protect-mcp:review2` — succeeded |
| Container smoke test | `docker run -p 18081:8080 ...` | `GET /health` → 200; `tools/list` no headers → 401 all three missing names; `tools/list` placeholder headers → 200, 11 tools listed — same shape as round 1 |
| README Connector section | `diff <(sed -n '1,71p' .../readme-connector-section.md) <(sed -n '19,89p' README.md)` | Exit 0 — byte-for-byte match, unchanged by this round |
| `gitleaks detect --source .` | — | `no leaks found` (5 commits scanned) |
| `git merge-base --is-ancestor <base> origin/main` | base recorded in the `[DEV]` stub is `main @ be47d42` | `origin/main` is still at `be47d42` — no re-sync needed before merge |

No test or AC was altered. No tool name, parameter, or error contract changed — this round is purely
the two must-fix items plus the one knock-on English-only fix in this file.

## Round 2 · 2026-11-02 · reviewed dev/PRD-21230 16dfaf2 (base main be47d42)

Verdict: approved

### Findings

No must-fix. Both Round 1 must-fix items are fixed; no new must-fix found in this round's diff
(`e6f49bc..16dfaf2`, 10 files changed: `api_client.py`, `errors.py`, `server.py`, new
`logging_utils.py`, the three `tools/*.py` call sites, `tests/test_tools.py`, the review doc itself,
and 2 lines of `docs/tickets/PRD-21230.md`).

1. [suggestion, carried over from Round 1, still not addressed] `src/eset_protect_mcp/tools/policies.py`
   (`eset_unassign_policy` registration) — still missing `idempotentHint` despite the Tech design
   calling it out as naturally idempotent. Not blocking; left untouched intentionally per the Round 1
   "Fixes" note.
2. [suggestion, carried over from Round 1, still not addressed] `src/eset_protect_mcp/auth.py:54-61`
   (`JwtCache._locks`) — still never pruned for expired cache keys. Not blocking.

### Verified independently (not just re-reading the Round 1 "Fixes" claims)

- **Must-fix 1 (Chinese text) is fixed**: `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git
  --exclude-dir=.venv --exclude-dir=.pytest_cache .` on `16dfaf2` — no output (confirmed clean; the two
  flagged lines in `docs/tickets/PRD-21230.md:530,596` now read "the repo's own declared tests" / "dev
  lock", and the review doc's own quotes of the SOP text were translated too, which Round 1's "Fixes"
  note already flagged as a knock-on fix within scope).
- **Must-fix 2 (no structured logging) is fixed, and credential-safe**: read `logging_utils.py` (new),
  the `api_client.py` call-boundary logging (`log_api_call` on every branch: timeout, other
  `httpx.HTTPError`, and the normal response path, each with `domain`/`path`/`status`/`latency_ms`/
  `error_code`/a non-sensitive `args` summary), `errors.py`'s `run_tool_safely(tool_name, coro)` +
  `tool_scope` binding, and `server.py`'s `request_scope` binding in the credential middleware. Traced
  the credential path end to end: `auth.py`'s `JwtCache._authenticate` posts the password-grant request
  via its own bare `httpx.AsyncClient.post(..., data={"username": ..., "password": ...})` call — it does
  **not** go through `EsetConnectClient.request()`/`log_api_call` at all, so the one place credentials
  are ever sent is structurally outside the new logging path. `api_client.py`'s `request()` only ever
  logs `params`/`json_body`, which are the tool's own business arguments (never the Header-derived
  credentials, which only ever reach the separately-built `Authorization` header). Confirmed all 11
  `@mcp.tool` call sites (`devices.py` x3, `detections.py` x3, `policies.py` x5) and all 9 direct
  `run_tool_safely(...)` call sites in `tests/test_tools.py` were updated to the new 2-arg signature
  (`grep -rn "run_tool_safely(" --include="*.py" .` — 20 call sites total, all consistent; this also
  means `uv run pytest` would have failed with a `TypeError` if any call site had been missed, which it
  did not).
- **Ran the gates myself, not just re-read the Self-test/Fixes tables**:
  - `uv sync && uv run pytest -q` on `16dfaf2`: **17 passed** (installed `uv` fresh into this review
    sandbox first; matches the Fixes-section table).
  - `sudo docker build --platform linux/amd64 -t eset-protect-mcp:review2-verify .`: succeeded.
  - Container smoke test against the freshly built image: `GET /health` → 200; `tools/list` with no
    headers → 401 listing all three missing header names.
  - **End-to-end credential-leak check against the running container** (stronger than Round 1's
    standalone script, which exercised the module directly rather than the real HTTP server): called
    `tools/call eset_list_devices` with a distinctive fake username/password/`X-Eset-Region: us`. The
    container's outbound call reached the real `us.business-account.iam.eset.systems` host (this
    sandbox has outbound network access to it) and got back `400 Bad Request`, which `auth.py` maps to
    `{"error":{"code":"unauthorized", ...}}` — confirming the credential-rejection path runs end to end.
    Grepped the container's full log output for the fake password string and for the substring
    `Bearer`: neither appears anywhere in the logs. (This exercises `auth.py`'s own unlogged POST, not
    `api_client.log_api_call`, since auth failure short-circuits before any ESET Connect resource call
    is made — but it is exactly the path real bad or in-flight credentials would take, and it stayed
    clean.)
  - `diff <(sed -n '1,71p' ~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md)
    <(sed -n '19,89p' README.md)`: exit 0, byte-for-byte match, unchanged by this round.
  - `git merge-base --is-ancestor 16dfaf2 origin/main`: not an ancestor (not yet merged, as expected
    before this review passes); `origin/main` is still at `be47d42`, matching the `[DEV]` stub's `BASE`,
    so no re-sync is needed before merging.
  - `gitleaks` is not installed in this review sandbox; not independently re-run. Round 1's "Fixes"
    table reports "no leaks found" (5 commits scanned) on this same diff — taken as-is, not verified.

Approved — merging into `main`, publishing to INT, and the connector wiki are the review leg's next
steps (`references/mcp-track.md` §4.4/§4.5), not part of this review record.

Status: frozen @ 16dfaf2
