# BUILD_STATUS — WS1 (Twin and order service)

> Purpose: if a session ends (usage limit, closed laptop), the next Claude session reads THIS file and continues
> exactly where we stopped. Keep it accurate. Update after every step and PR, and before ending any session.

**Last updated:** 2026-10-28 by session #1
**Current gate target:** G2 (Nov 2)

## FIRST THING THE NEXT SESSION SHOULD DO
Plan item #3 on branch `feat/sql-schema-seed` (committed and pushed, no PR yet). Blocker: Docker needs CPU
virtualization, which was OFF in the HP firmware. Ask the user whether they turned on "Virtualization Technology"
in the BIOS (HP: Esc then F10 at power-on). Check with
`(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled` (must be True) and `docker info`. Then run
`.\scripts\local-sql.ps1` twice, open PR #3, review, ask "Merge PR #3?".

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
| Tools verified | git 2.56 ✅ / gh 2.103 ✅ / python 3.12.10 ✅ / docker 29.9 (CLI ✅; engine ❌ until BIOS virtualization is on) / az 2.91 + bicep 0.48 ✅ |

Machine note: the Claude app's shell may start with a stale PATH. Prefix PowerShell commands with
`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`
if `git`/`gh`/`az`/`docker` are "not recognized". ODBC Driver 18 is not installed (only needed outside Docker).

## Plan (ordered PRs) — approved by the user 2026-10-28
| # | PR / task | Purpose | Status | Link |
|---|---|---|---|---|
| 1 | chore: project scaffold | Rules, ADRs, status, glossary, folders | merged | PR #1 |
| 2 | docs: twin contract + plan | `contracts/twin-interface.md` (Phase 1) and this plan | merged | PR #2 |
| 3 | feat(sql): schema + seed | Phase 2 + compose file with local SQL Server; run twice | in progress | |
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
- Last command run: wrote sql/ scripts, docker-compose.yml, scripts/local-sql.ps1
- Uncommitted / unpushed files: none expected
- Test status: n/a (docs and empty folders only)

## Done (with evidence)
- Machine set up: gh, az + bicep, Docker Desktop installed via winget (git and Python were already present).
- GitHub org `livefire-team` created by the user; repo `livefire-fusion-poc` created (public, README on `main`).
- PR #1 scaffold merged (merge commit c3427c7); repo set to merge-commit only.
- PR plan approved (table above).
- PR #2 contract v1 + plan merged (merge commit 9b698f1). Team message drafted for the user to send.

## Blockers / questions for the user or other workstreams
- Docker engine cannot start: "Virtualization is disabled in firmware" (HP All-in-One 24-df0xxx, AMD Ryzen 3 3250U,
  BIOS AMI F.33). User enables SVM / "Virtualization Technology" in BIOS setup. Fallback if impossible: run the
  SQL and image tests in GitHub Actions instead of locally.
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
- 2026-10-28 session #1: tools installed, gh login, org + repo created, PR #1 and PR #2 merged, plan approved, PR #3 started.
