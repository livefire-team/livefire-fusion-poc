# BUILD_STATUS — WS1 (Twin and order service)

> Purpose: if a session ends (usage limit, closed laptop), the next Claude session reads THIS file and continues
> exactly where we stopped. Keep it accurate. Update after every step and PR, and before ending any session.

**Last updated:** 2026-10-29 by session #2
**Current gate target:** G2 (Nov 2)

## FIRST THING THE NEXT SESSION SHOULD DO
PR #3 (base `main`) is open for the owner to review. Merge it with `gh pr merge 3 --merge` only on the owner's
explicit "Merge". Then start plan item #4 on a new branch from `main`. If later PRs are stacked, merge bottom-up and
retarget the next PR's base to `main` after each merge (`gh pr edit <N> --base main`).

## Environment facts
| Item | Value |
|---|---|
| GitHub repo | https://github.com/livefire-team/livefire-fusion-poc (public, org `livefire-team`, user is admin) |
| Local path | C:\Users\venka\projects\livefire-fusion-poc |
| Kit folder | C:\Users\venka\projects\livefire-ws1-kit |
| Default branch | main |
| Working branch | feat/sql-schema-seed |
| Azure resource group | not yet deployed (will be `rg-lf-twin-<env>`, created by WS2) |
| Image | ghcr.io/livefire-team/order-service:<tag> (not built yet) |
| GitHub account | venkataare (gh logged in, HTTPS); git identity "Venkata Are" / noreply email |
| Tools verified | git 2.56 ✅ / gh 2.103 ✅ / python 3.12.10 ✅ / docker 29.9 (CLI ✅; engine ✅ after BIOS virtualization enabled 2026-10-29) / az 2.91 + bicep 0.48 ✅ |

Machine note: the Claude app's shell may start with a stale PATH. Prefix PowerShell commands with
`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`
if `git`/`gh`/`az`/`docker` are "not recognized". ODBC Driver 18 is not installed (only needed outside Docker).

## Plan (ordered PRs) — approved by the user 2026-10-28
| # | PR / task | Purpose | Status | Link |
|---|---|---|---|---|
| 1 | chore: project scaffold | Rules, ADRs, status, glossary, folders | merged | PR #1 |
| 2 | docs: twin contract + plan | `contracts/twin-interface.md` (Phase 1) and this plan | merged | PR #2 |
| 3 | feat(sql): schema + seed | Phase 2 + compose file with local SQL Server; run twice | PR open | PR #3 |
| 4 | feat(infra): twin.bicep | Phase 5 + ADRs (1 replica, /health probes, Basic SQL, plain resources); `az bicep build` | not started | |
| 5 | feat(order-service): secret provider + catalog | Phase 3 steps 1–3, 7, TDD | not started | |
| 6 | feat(order-service): db, pages, health, telemetry | Phase 3 steps 4–6, TDD with DB stubbed | not started | |
| 7 | ci: Dockerfile + Actions -> GHCR | Phase 4; `sha-<commit>` + `:g1`; user makes package public | not started | |
| 8 | docs: runbook v1 | Phase 6 | not started | |
| 9 | test: local Docker Compose rehearsal | Phase 7 steps 1–4; app in compose, file as Key Vault stand-in | not started | |
| 10 | docs: hand-offs | Phase 8 | not started | |
| G1 | G1 checklist | Phase 8 step 5 items all ticked | not started | |
| 11 | ci: security scans (G2) | gitleaks, pip-audit, Trivy, CodeQL | not started | |
| 12 | ci: candidate builds (G2) | `candidate/*` -> `candidate-<drill-id>` tags | not started | |
| 13 | feat: load generator (G2) | Container Apps Job, steady POST /api/orders + backlog retries | not started | |
| 14 | docs: architecture note (G2) | `docs/architecture.md` — the only file WS3 indexes | not started | |

Outside PRs (with WS2, needs Azure): agree `SECRET_REFRESH_SECONDS` with WS2/WS5; check twin after first
`azd provision` (Phase 7 steps 5–6); joint drill PASS, FAIL, FAIL, PASS ×3 (Phase 7 step 7).
If time runs short before Nov 2, cut #13 then #12 first.

Status values: not started | in progress | PR open | merged | blocked

## In progress right now
- Branch: feat/sql-schema-seed
- Last command run: `.\scripts\local-sql.ps1` twice on 2026-10-29 after the sqlcmd password/quoting fix (both exit 0,
  identical output: 2 products, 3 tables, `ix_orders_drill_id`)
- Uncommitted / unpushed files: none expected (fix + compose memory limit + status pushed to PR #3)
- Test status: SQL run-twice check passed 2026-10-29; reviews: 0 CRITICAL/HIGH

## Done (with evidence)
- Machine set up: gh, az + bicep, Docker Desktop installed via winget (git and Python were already present).
- GitHub org `livefire-team` created by the user; repo `livefire-fusion-poc` created (public, README on `main`).
- PR #1 scaffold merged (merge commit c3427c7); repo set to merge-commit only.
- PR plan approved (table above).
- PR #2 contract v1 + plan merged (merge commit 9b698f1). Team message drafted for the user to send.
- Docker blocker resolved 2026-10-29: the user enabled CPU virtualization in the HP BIOS; engine 29.9.2 runs.
- PR #3 opened; `local-sql.ps1` run twice locally with identical results.

## Blockers / questions for the user or other workstreams
- Teammates (WS2–WS5) are not yet invited to the `livefire-team` org/repo — need their GitHub usernames.
- Tell WS2–WS5 the repo URL and image path (`ghcr.io/livefire-team/order-service`).
- Tell WS3: keep `docs/` and `CLAUDE.md` off the agents' `read_repository_context` allowlist (ADR-004).
- Tell WS3: the G2 architecture note will be `docs/architecture.md` only — index that file, not all of `docs/`.
- Contract v1 (`contracts/twin-interface.md`) must be sent to WS2–WS5 the day PR #2 merges.
- If `CLAUDE.local.md` is missing on this PC, recreate it before writing order-service code (see CLAUDE.md).

## Hand-offs owed
- [ ] WS2: image name/tag, twin.bicep merged, contract additions (appInsightsConnectionString output, principalType + secretRefreshSeconds), local stack
- [ ] WS3: Phase 8 items, runbook path, telemetry names
- [ ] WS4: allowed/protected paths for the Engineer
- [ ] WS5: metric names (orders_completed, orders_failed{reason})

## Decisions log pointer
See `docs/ADR.md` (latest: ADR-005).

## Session log (newest first)
- 2026-10-29 session #2: Docker unblocked, local-sql.ps1 fixed for PowerShell 5.1 and run twice, PR #3 updated.
- 2026-10-28 session #1: tools installed, gh login, org + repo created, PR #1 and PR #2 merged, plan approved, PR #3 started.
