# BUILD_STATUS — WS1 (Twin and order service)

> Purpose: if a session ends (usage limit, closed laptop), the next Claude session reads THIS file and continues
> exactly where we stopped. Keep it accurate. Update after every step and PR, and before ending any session.

**Last updated:** 2026-10-28 by session #1
**Current gate target:** G2 (Nov 2)

## FIRST THING THE NEXT SESSION SHOULD DO
If PR #1 (`chore/project-scaffold`) is still open: check its CI/review state and ask the user "Merge PR #1?".
If it is merged: `git checkout main; git pull --ff-only`, then do step 5 of the starter prompt — turn Build Guide
Phases 1–8 into an ordered PR plan, get the user's approval, and record it in the Plan table below.

## Environment facts
| Item | Value |
|---|---|
| GitHub repo | https://github.com/livefire-team/livefire-fusion-poc (public, org `livefire-team`, user is admin) |
| Local path | C:\Users\venka\projects\livefire-fusion-poc |
| Kit folder | C:\Users\venka\projects\livefire-ws1-kit |
| Default branch | main |
| Working branch | chore/project-scaffold |
| Azure resource group | not yet deployed (will be `rg-lf-twin-<env>`, created by WS2) |
| Image | ghcr.io/livefire-team/order-service:<tag> (not built yet) |
| GitHub account | venkataare (gh logged in, HTTPS); git identity "Venkata Are" / noreply email |
| Tools verified | git 2.56 ✅ / gh 2.103 ✅ / python 3.12.10 ✅ / docker 29.9 ✅ / az 2.91 + bicep 0.48 ✅ |

Machine note: the Claude app's shell may start with a stale PATH. Prefix PowerShell commands with
`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`
if `git`/`gh`/`az`/`docker` are "not recognized". ODBC Driver 18 is not installed (only needed outside Docker).

## Plan (ordered PRs) — provisional until approved in step 5
| # | PR / task | Status | Link |
|---|---|---|---|
| 1 | chore: project scaffold | PR open | PR #1 |
| 2 | docs: contracts/twin-interface.md | not started | |
| 3 | feat: SQL schema + seed | not started | |
| 4 | feat: secret provider + catalog (TDD) | not started | |
| 5 | feat: db + main + templates (TDD) | not started | |
| 6 | ci: Dockerfile + GitHub Actions -> GHCR | not started | |
| 7 | test: local Docker Compose False-Green rehearsal | not started | |
| 8 | feat: infra/modules/twin.bicep | not started | |
| 9 | docs: runbook v1 + seeded history | not started | |
| 10 | docs: hand-offs (WS2/WS3/WS4/WS5) | not started | |
| G2 | load generator, CI scans, candidate builds, architecture note | not started | |

Status values: not started | in progress | PR open | merged | blocked

## In progress right now
- Branch: chore/project-scaffold
- Last command run: `gh pr create` for the scaffold
- Uncommitted / unpushed files: none expected
- Test status: n/a (docs and empty folders only)

## Done (with evidence)
- Machine set up: gh, az + bicep, Docker Desktop installed via winget (git and Python were already present).
- GitHub org `livefire-team` created by the user; repo `livefire-fusion-poc` created (public, README on `main`).

## Blockers / questions for the user or other workstreams
- Teammates (WS2–WS5) are not yet invited to the `livefire-team` org/repo — need their GitHub usernames.
- Tell WS2–WS5 the repo URL and image path (`ghcr.io/livefire-team/order-service`).
- Tell WS3: keep `docs/` and `CLAUDE.md` off the agents' `read_repository_context` allowlist (ADR-004).

## Hand-offs owed
- [ ] WS2: image name/tag, twin.bicep merged, contract additions (appInsightsConnectionString output, principalType + secretRefreshSeconds), local stack
- [ ] WS3: two seed commit hashes, runbook path, telemetry names
- [ ] WS4: allowed/protected paths for the Engineer
- [ ] WS5: metric names (orders_completed, orders_failed{reason})

## Decisions log pointer
See `docs/ADR.md` (latest: ADR-004).

## Session log (newest first)
- 2026-10-28 session #1: tools installed, gh login, org + repo created, scaffold PR opened.
