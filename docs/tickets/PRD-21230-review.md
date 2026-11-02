# PRD-21230 · Code review

## Round 1 · 2026-11-02 · reviewed dev/PRD-21230 e6f49bc (base main be47d42)

Verdict: changes requested

### Findings

1. [must-fix] docs/tickets/PRD-21230.md:530,596 — The repo contains Chinese text, violating the
   vendor-mcp-development SOP's English-only rule (SOP §0.4: "仓库内容全部英文：代码、注释、工具描述、
   错误信息、日志、文档、commit message 均无中文"), which explicitly covers the committed ticket doc
   (SKILL.md: "仓库里的流水线文档…和仓库其它内容一样只能用英文（SOP §0.4），不放中文版"). Line 530 quotes
   `references/gates.md`'s Chinese section title "仓库自带的测试"; line 596 quotes "开发锁". Re-running the
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
   "日志与敏感信息" item: "结构化日志带 request-id；不打印凭据 / token / 敏感业务数据"
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
