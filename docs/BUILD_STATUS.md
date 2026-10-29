# BUILD_STATUS — WS1 (Twin and order service)

> Purpose: if a session ends (usage limit, closed laptop), the next Claude session reads THIS file and continues
> exactly where we stopped. Keep it accurate. Update after every step and PR, and before ending any session.

**Last updated:** 2026-10-29 by session #2
**Current gate target:** G2 (Nov 2)

## FIRST THING THE NEXT SESSION SHOULD DO
The owner reviews and merges the stack bottom-up: PR #3 (base `main`) first, then PR #4 (base
`feat/sql-schema-seed`), then PR #5 (base `feat/twin-bicep`), then PR #6 (base `feat/secret-provider`), then PR #7 (base
`feat/order-service-app`), then PR #8 (base `ci/order-service-image`), then PR #9 (base `docs/runbook-v1`), then the plan item #10 PR (base `test/local-rehearsal`).
Merge each with `gh pr merge <N> --merge` only on the
owner's explicit "Merge", and after each merge retarget the next PR's base to `main` (`gh pr edit <N> --base main`).
Then send the hand-offs in `docs/handoffs.md` (plus the items shared directly). After PR #7 merges and the first `main` run pushes the image, the owner makes the GHCR
package public (Phase 4 step 4) and tells WS2 the image name.

## Environment facts
| Item | Value |
|---|---|
| GitHub repo | https://github.com/livefire-team/livefire-fusion-poc (public, org `livefire-team`, user is admin) |
| Local path | C:\Users\venka\projects\livefire-fusion-poc |
| Kit folder | C:\Users\venka\projects\livefire-ws1-kit |
| Default branch | main |
| Working branch | test/local-rehearsal (stacked on docs/runbook-v1) |
| Azure resource group | not yet deployed (will be `rg-lf-twin-<env>`, created by WS2) |
| Image | ghcr.io/livefire-team/order-service:<tag> (`sha-<7-char commit>` and `g1`, pushed by CI from `main` only; not pushed yet) |
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
| 4 | feat(infra): twin.bicep | Phase 5 + ADRs (1 replica, /health probes, Basic SQL, plain resources); `az bicep build` | PR open | PR #4 |
| 5 | feat(order-service): secret provider + catalog | Phase 3 steps 1–3, 7, TDD | PR open | [PR #5](https://github.com/livefire-team/livefire-fusion-poc/pull/5) |
| 6 | feat(order-service): db, pages, health, telemetry | Phase 3 steps 4–6, TDD with DB stubbed | PR open | [PR #6](https://github.com/livefire-team/livefire-fusion-poc/pull/6) |
| 7 | ci: Dockerfile + Actions -> GHCR | Phase 4; `sha-<commit>` + `:g1`; user makes package public | PR open | [PR #7](https://github.com/livefire-team/livefire-fusion-poc/pull/7) |
| 8 | docs: runbook v1 | Phase 6 | PR open | PR #8 |
| 9 | test: local Docker Compose rehearsal | Phase 7 steps 1–4; app in compose, file as Key Vault stand-in | PR open | [PR #9](https://github.com/livefire-team/livefire-fusion-poc/pull/9) |
| 10 | docs: hand-offs | Phase 8; `docs/handoffs.md` | PR open | PR10LINK |
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
- Branch: docs/handoffs (stacked on test/local-rehearsal), plan item #10; next: plan item #11
- Previous: test/local-rehearsal (stacked on docs/runbook-v1), PR #9
- Last commands run: `.\scripts\local-sql.ps1` twice, `.\scripts\local-access-drill.ps1` (ran all 4 stages, exit 0),
  `docker compose down`, and `pytest -q src/order-service --cov=src/order-service/app`: 59 passed, coverage 99%
- Uncommitted / unpushed files: none expected
- Test status: order-service unit tests green 2026-10-29. Nothing deployed to Azure (WS2 deploys via `main.bicep`).

## Done (with evidence)
- Machine set up: gh, az + bicep, Docker Desktop installed via winget (git and Python were already present).
- GitHub org `livefire-team` created by the user; repo `livefire-fusion-poc` created (public, README on `main`).
- PR #1 scaffold merged (merge commit c3427c7); repo set to merge-commit only.
- PR plan approved (table above).
- PR #2 contract v1 + plan merged (merge commit 9b698f1). Team message drafted for the user to send.
- Docker blocker resolved 2026-10-29: the user enabled CPU virtualization in the HP BIOS; engine 29.9.2 runs.
- PR #3 opened; `local-sql.ps1` run twice locally with identical results.
- PR #4 opened: `infra/modules/twin.bicep` (contract v1 parameters/outputs) + compile harness
  `infra/tests/twin.test.bicep`; build and lint clean; ADR-006 to ADR-008 added.
- PR #5 opened: order-service `requirements.txt` (guide pins) + `requirements-dev.txt`, `secret_provider.py`,
  `catalog.py` (matches `sql/seed.sql`), tests written first (RED shown), 13 passed, 100% coverage; ADR-009 added.
- PR #6 opened: `db.py`, `main.py` (pages, JSON API, `/health`, `/health/dependencies`, drill ID, telemetry) and the
  four templates; TestClient tests written first with SQL/Key Vault stubbed (RED shown), 39 passed, 100% coverage.
- PR #7 opened: `src/order-service/Dockerfile` (guide, ODBC 18, non-root) + `.dockerignore`, workflow
  `.github/workflows/order-service.yml` (test -> image build + smoke test -> push `sha-`/`g1` from `main` only);
  local image built and smoke-tested; ADR-010 and ADR-011 added.
- PR #7 review fixes: workflow split into `test` -> `image` (read-only, smoke test, image saved as artifact) ->
  `publish` (`main` push only, `packages: write`, pushes the same tested image); actions pinned to commit SHAs;
  `persist-credentials: false`; smoke port bound to localhost. Dockerfile: OCI source label, Microsoft key
  fingerprint check, curl purged. `.dockerignore`: `.env*`, `.git`. ADR-011 revised. Verified by CI (no local Docker).

- PR #9 opened: `orders` service added to `docker-compose.yml` (file secret source, `127.0.0.1:8000`);
  `local-sql.ps1` now also creates the `order_app` login with a generated password in `.local/secret.txt` (run
  twice, same result); `scripts/local-access-drill.ps1` run against the local stack (all 4 stages ran); ADR-012.
- Plan item #10 PR opened: `docs/handoffs.md` lists what WS2, WS3 and WS5 need (image and tags, Bicep output and
  pass-throughs, local stack, SQL reset order, runbook path, telemetry and metric names).

## Blockers / questions for the user or other workstreams
- Teammates (WS2–WS5) are not yet invited to the `livefire-team` org/repo — need their GitHub usernames.
- Tell WS2–WS5 the repo URL and image path (`ghcr.io/livefire-team/order-service`).
- Owner, after PR #7 merges and the first `main` run is green: make the GHCR package `order-service` public
  (org Packages -> order-service -> Package settings -> Visibility: Public), then tell WS2 the image
  `ghcr.io/livefire-team/order-service:g1` (`sha-` tags for rehearsals).
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
See `docs/ADR.md` (latest: ADR-012).

## Session log (newest first)
- 2026-10-29 session #2: plan item #10 hand-offs page `docs/handoffs.md`, stacked on PR #9.
- 2026-10-29 session #2: PR #9 local Docker Compose stack with the app and the local access drill script, stacked on PR #8.
- 2026-10-29 session #2: PR #7 Dockerfile + GitHub Actions workflow (image built and smoke-tested locally), stacked on PR #6.
- 2026-10-29 session #2: PR #6 order pages, API, health checks and telemetry (TDD, 100% coverage), stacked on PR #5.
- 2026-10-29 session #2: PR #5 secret provider + catalog (TDD, 100% coverage), stacked on PR #4.
- 2026-10-29 session #2: PR #4 twin.bicep built (compile + lint clean), stacked on PR #3.
- 2026-10-29 session #2: Docker unblocked, local-sql.ps1 fixed for PowerShell 5.1 and run twice, PR #3 updated.
- 2026-10-28 session #1: tools installed, gh login, org + repo created, PR #1 and PR #2 merged, plan approved, PR #3 started.
