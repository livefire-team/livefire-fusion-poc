# BUILD_STATUS — WS1 (Twin and order service)

> Purpose: if a session ends (usage limit, closed laptop), the next Claude session reads THIS file and continues
> exactly where we stopped. Keep it accurate. Update after every step and PR, and before ending any session.

**Last updated:** 2026-11-05 (WS2 G2: lab sections 5-8 done on `lf-eh`: control plane, evidence check, images in
the private registry, `ca-ops` and the jobs, `smoke auth` passed, deny policy ON and proven; next is section 9)
**Current gate target:** G2 (Mon Nov 9; moved from Nov 2)

## FIRST THING THE NEXT SESSION SHOULD DO
All WS1 PRs (#1-#14) are merged into `main` (2026-10-30, merge commits; last merge 8e37fd0); every `main` run is green.
Ask the owner which owner action below is done, then help with the next open one (G2 is Nov 2).
`main` is protected by ruleset `protect-main` (changes only via PR), so even status updates need a small PR.

Note: plan row numbers and PR numbers differ. Plan #14 (architecture note) is PR #13, and plan #13 (load generator) is PR #14.

### Owner actions
1. DONE 2026-10-30: rulesets `candidate-branches` (only admins create/push `candidate/**`) and `protect-main`.
   Still to do: add WS4's Engineer agent identity as a bypass actor on `candidate-branches` once WS4 names it.
2. Make the GHCR packages `order-service` and `load-generator` public (org > Packages > package settings >
   Change visibility). Both have been published from `main`.
3. Tell WS2: `azd env set ORDER_IMAGE ghcr.io/livefire-team/order-service:g1`, the `APPINSIGHTS_CONNECTION_STRING`
   output line, and `infra/modules/loadgen.bicep`.
4. Send WS3 and WS4 their private hand-offs (see `CLAUDE.local.md`).
5. Agree `SECRET_REFRESH_SECONDS` with WS2 and WS5.
6. Lab checks and the joint drill with WS2 (Phase 7 steps 5-7).
7. Invite teammates to the `livefire-team` org.

## Environment facts
| Item | Value |
|---|---|
| GitHub repo | https://github.com/livefire-team/livefire-fusion-poc (public, org `livefire-team`, user is admin) |
| Local path | C:\Users\venka\projects\livefire-fusion-poc |
| Kit folder | C:\Users\venka\projects\livefire-ws1-kit |
| Default branch | main |
| Working branch | test/local-rehearsal (stacked on docs/runbook-v1) |
| Azure resource group | `rg-lf-twin-lf-eh` (azd env `lf-eh`, eastus2), provisioned by WS2 with `azd provision` |
| Image | ghcr.io/livefire-team/order-service:<tag> (`sha-<7-char commit>` and `g1`, pushed by CI from `main` only; not pushed yet) |
| GitHub account | venkataare (gh logged in, HTTPS); git identity "Venkata Are" / noreply email |
| Tools verified | git 2.56 ✅ / gh 2.103 ✅ / python 3.12.10 ✅ / docker 29.9 (CLI ✅; engine ✅ after BIOS virtualization enabled 2026-10-29) / az 2.91 + bicep 0.48 ✅ |

Machine note: the Claude app's shell may start with a stale PATH. Prefix PowerShell commands with
`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`
if `git`/`gh`/`az`/`docker` are "not recognized". ODBC Driver 18 is not installed (only needed outside Docker).
WS2 Mac note: ODBC Driver 18 loads OpenSSL from Homebrew's `/opt/homebrew/opt/openssl` and cannot use OpenSSL 4;
point that link at 3 with `ln -sfn openssl@3 /opt/homebrew/opt/openssl` (done 2026-10-31; a brew upgrade may undo it).

## Plan (ordered PRs) — approved by the user 2026-10-28
| # | PR / task | Purpose | Status | Link |
|---|---|---|---|---|
| 1 | chore: project scaffold | Rules, ADRs, status, glossary, folders | merged | PR #1 |
| 2 | docs: twin contract + plan | `contracts/twin-interface.md` (Phase 1) and this plan | merged | PR #2 |
| 3 | feat(sql): schema + seed | Phase 2 + compose file with local SQL Server; run twice | merged | [PR #3](https://github.com/livefire-team/livefire-fusion-poc/pull/3) |
| 4 | feat(infra): twin.bicep | Phase 5 + ADRs (1 replica, /health probes, Basic SQL, plain resources); `az bicep build` | merged | [PR #4](https://github.com/livefire-team/livefire-fusion-poc/pull/4) |
| 5 | feat(order-service): secret provider + catalog | Phase 3 steps 1–3, 7, TDD | merged | [PR #5](https://github.com/livefire-team/livefire-fusion-poc/pull/5) |
| 6 | feat(order-service): db, pages, health, telemetry | Phase 3 steps 4–6, TDD with DB stubbed | merged | [PR #6](https://github.com/livefire-team/livefire-fusion-poc/pull/6) |
| 7 | ci: Dockerfile + Actions -> GHCR | Phase 4; `sha-<commit>` + `:g1`; user makes package public | merged | [PR #7](https://github.com/livefire-team/livefire-fusion-poc/pull/7) |
| 8 | docs: runbook v1 | Phase 6 | merged | [PR #8](https://github.com/livefire-team/livefire-fusion-poc/pull/8) |
| 9 | test: local Docker Compose rehearsal | Phase 7 steps 1–4; app in compose, file as Key Vault stand-in | merged | [PR #9](https://github.com/livefire-team/livefire-fusion-poc/pull/9) |
| 10 | docs: hand-offs | Phase 8; `docs/handoffs.md` | merged | [PR #10](https://github.com/livefire-team/livefire-fusion-poc/pull/10) |
| G1 | G1 checklist | Phase 8 step 5 items all ticked | not started | |
| 11 | ci: security scans (G2) | gitleaks, pip-audit, Trivy, CodeQL; ADR-013 | merged | [PR #11](https://github.com/livefire-team/livefire-fusion-poc/pull/11) |
| 12 | ci: candidate builds (G2) | `candidate/*` -> `candidate-<drill-id>` tags | merged | [PR #12](https://github.com/livefire-team/livefire-fusion-poc/pull/12) |
| 13 | feat: load generator (G2) | Container Apps Job, steady POST /api/orders + backlog retries | merged | [PR #14](https://github.com/livefire-team/livefire-fusion-poc/pull/14) |
| 14 | docs: architecture note (G2) | `docs/architecture.md` — the only file WS3 indexes | merged | [PR #13](https://github.com/livefire-team/livefire-fusion-poc/pull/13) |

Outside PRs (with WS2, needs Azure): agree `SECRET_REFRESH_SECONDS` with WS2/WS5; check twin after first
`azd provision` (Phase 7 steps 5–6); joint drill with WS2 (Phase 7 step 7).
If time runs short before Nov 2, cut #13 then #12 first.

Status values: not started | in progress | PR open | merged | blocked

## In progress right now
- 2026-10-31: WS2 branch `ws2-starter` is [PR #16](https://github.com/livefire-team/livefire-fusion-poc/pull/16) to
  `main`: lab probe results doc, WS2 starter files (`azure.yaml`, `infra/main.bicep`, `scripts/`, `referee/`,
  `journeys/`) and two new `twin.bicep` outputs (`logAnalyticsWorkspaceName`, `logAnalyticsCustomerId`; contract
  updated). Also a referee fix: pytest-playwright deletes its `--output` folder at start, which removed the run's
  evidence folder, so `referee.sh` now passes `--output "$OUTDIR/playwright"`. And a `lib.sh` fix: event
  timestamps used `%3N` (GNU `date` only), so on macOS every `events.jsonl` line had an invalid time like
  `...T01:06:20.3NZ`; they are now whole seconds (`...T01:11:57Z`). Needs WS1 owner review before merge.
- Twin provisioned in `rg-lf-twin-lf-eh`; every `postprovision.sh` step is in place (firewall rule, schema + seed,
  `order_app` / `referee_ro`, Key Vault `db-password`, `REFEREE_SQL_PASSWORD`). Baseline drill
  `drill-20261101-0058-4514` PASS (journey confirmed, 1 order, 1 payment authorization).
- Drills by hand 2026-10-31 and 2026-11-01 (`for i in 1 2 3; do ./scripts/drill.sh || break; done`, model
  `accessPolicy`). Drill IDs, verdicts and App Insights rows are in the WS2 Mac's git-ignored notes (ADR-004).
  - `az containerapp revision restart` is a rolling restart: it returns at once, and the old replica keeps serving
    for about 20 s until the new one is ready. `reset.sh` now notes the replica names before the restart, then
    waits (max 300 s) until none of them is listed. A reset takes about 70 s (old replica gone after 50-58 s).
  - `drill.sh` now waits until `SECRET_REFRESH_SECONDS` + 1 s have passed since the baseline run before the next
    run (default 10, same as `main.parameters.json`); the measured gap is now about 16 s.
  - App Insights tip: `az monitor app-insights query -o table` prints nothing (its result is nested), so add
    `--query "tables[0].rows[*].{timestamp:[0], run_id:[1], exception:[2], message:[3]}"` (use `rows[*]`, not
    `rows[]`, and don't name a column `type`, which table output hides), or use `-o tsv --query "tables[0].rows"`.
- Key Vault access propagation measured 2026-10-31 (`./scripts/measure-propagation.sh 3`, drill
  `drill-20261101-0106-9260`, model `accessPolicy`):

  | Run | Access removed -> `/health/dependencies` shows `forbidden` | Access restored -> shows `ok` |
  |---|---|---|
  | 1 | 1 s | 1 s |
  | 2 | 0 s | 1 s |
  | 3 | 0 s | 1 s |

  The first poll saw the new state every time. The stopwatch starts only after `fault.sh` finishes its two
  `az keyvault show` checks, so read it as "within about 5 s", not "instant". `/health/dependencies` makes a fresh
  Key Vault read on every call. Not measured: the `rbac` model. The lab probe
  says Path A (real role removal) applies, and `lib.sh` and `main.bicep` default to `rbac`; role changes can take
  up to about 10 minutes. Decided 2026-11-01 (ADR-016): the joint drill stays on Path B (`accessPolicy`,
  `PATH_A_CONTROLS` off), so the measurement above applies and no `rbac` measurement is needed.
- 2026-11-01: G1 drill evidence summary for the three 12:00-12:06 drills (verdicts, delays, screenshots, trace
  paths) written on the WS2 Mac in `evidence/` only (git-ignored, ADR-004).
- Pending (replaces the 2026-11-01 `PATH_A_CONTROLS` plan, ADR-019): the subscription-wide deny of new Owner,
  Contributor and User Access Administrator assignments now comes from `scripts/deploy.sh policy`
  (`DENY_BROAD_POLICY=on`, then `BROAD_ATTEMPT_ROLE=on` for `id-lf-ops`). Still waiting for every workstream to
  confirm none of their identities needs those roles; `ops-access.bicep` is replaced by `ops-twin-access.bicep`.
- WS2 G2 (G2 Mon Nov 9). All three PRs are merged into `main` with merge commits (2026-11-04):
  - [PR #20](https://github.com/livefire-team/livefire-fusion-poc/pull/20), `ws2/g1-carryover` (25541d4): the 7
    `ws2-starter` commits made after PR #16 (the `reset.sh` replica wait, the `drill.sh` refresh-window wait,
    ADR-016, status and glossary notes).
  - [PR #21](https://github.com/livefire-team/livefire-fusion-poc/pull/21), `ws2/ops-service` (d507fe3):
    `src/ops-service/`, `referee/run.py`, their workflows.
  - [PR #22](https://github.com/livefire-team/livefire-fusion-poc/pull/22), `ws2/g2-platform` (f014dd6, approved
    and merged by WS1): Bicep for the control plane, private registry, evidence store, `ca-ops`, `job-referee`
    and the deny policy; `scripts/deploy.sh`; `contracts/ops-actions.md`; ADR-017 to ADR-019. It merged before
    the lab run, so the lab proves `main` as it is. A fix found in the lab goes in a new PR, and so do the lab
    records the guide puts "in PR 3" (ADR-019's "Implemented in" line, `docs/rebuild-timing.md`).
  - GHCR: the tags `deploy.sh images` picks from `main` are `order-service:sha-f014dd6`,
    `ops-service:sha-d507fe3` and `referee:sha-f014dd6`; all three pull without signing in, so the packages
    are public.
  - Checked 2026-11-04 (read-only): every `Microsoft.App` action in `ops-twin-access.bicep` and `ops.bicep`
    exists (`az provider operation show -n Microsoft.App`).
  - Lab sections 5-7 done 2026-11-05 01:28-01:56 UTC on `lf-eh`, from `main` at f014dd6 (results in the WS2
    Mac's git-ignored `docs/reference/g2-evidence.md`, ADR-004):
    - `AZURE_PRINCIPAL_TYPE` set to `User` (it was `ServicePrincipal`; the lab sign-in is a user).
    - `deploy.sh infra`: control plane deployed, the hook seeded the five control-vault secrets, baseline PASS.
      Platform hand-off posted to WS3, WS4 and WS5.
    - `evidence_check.py`: EVIDENCE CHECK PASSED. A plain delete of the event log, tried by hand, was also refused
      by the policy (409 `BlobImmutableDueToPolicy`).
    - `deploy.sh images` (GHCR import, no build), then `deploy.sh apps`: the twin on the registry image (baseline
      PASS), `ca-ops` internal with 1 replica and "Application startup complete", `job-referee`, `job-ops-smoke`,
      the three custom roles. From outside Azure, `OPS_URL` gets Azure's 404 "Unavailable" page.
    - `deploy.sh smoke auth`: SMOKE PASSED (7 of 7 rows).
  - Lab section 8 done 2026-11-05 02:08-02:18 UTC, after every workstream agreed:
    - `deploy.sh policy`: the deny policy refused `recover.sh broad` (as the WS2 owner) on the first attempt
      (`RequestDisallowedByPolicy`, nothing granted), then `id-lf-ops` got its conditioned RBAC Administrator role.
      Both provisions' baselines PASS.
    - `deploy.sh smoke policy`: SMOKE PASSED. `id-lf-ops`, through the Ops Service with a signed grant: denied
      `RequestDisallowedByPolicy`, `refused_by: Azure Policy`; the same grant again and a forged grant: 422.
      Recorded in ADR-019's "Implemented in".
    - **The deny policy is ON for the whole lab subscription.** Nobody can create Owner, Contributor or User
      Access Administrator assignments until `scripts/deploy.sh policy-off` runs. Run it before the lab ends or
      before any teardown.
  - Lab notes:
    - Activate `.venv` before every `deploy.sh` or `azd` command: the postprovision hook runs `referee.sh`,
      which needs `python` and `pytest` (without them the baseline is INCONCLUSIVE and the hook fails).
    - `azd provision` prints no hook output when the hook succeeds. The newest `evidence/drill-*/r1-baseline`
      folder shows the baseline ran.
    - azd's warning that `AllowAllWindowsAzureIps` contains a reserved word is a false alarm: that is the name
      Azure itself uses for "allow Azure services", and the deployment succeeds.
    - `deploy.sh smoke` waits 90 s for the job's console log, but it took about 3 minutes to reach Log
      Analytics. Rerun the query it prints (`ContainerAppConsoleLogs_CL`, `ContainerGroupName_s startswith
      '<execution>'`) a little later.
  - Next, in order: tell the lead the refusal is Azure Policy from `id-lf-ops` (G2 Must met) and that
    `policy-off` exists. Section 9 (planned Fri Nov 6): `smoke all` three times in a row, then read one smoke
    drill's events from Blob.
  - Follow-up from the lab: `scripts/evidence_check.py` never deletes the event log itself, and its version
    delete of the event log is refused for being the current version (`OperationNotAllowedOnRootBlob`), not by
    the policy. Add a "delete the event log" step that must be refused by the policy, with a test.
  - PR #22 review follow-ups (not fixed): `infra`/`all` could refuse `BROAD_ATTEMPT_ROLE=on` until the policy
    assignment exists; `job-ops-smoke` could get its own identity; the order-app operator role could be assigned
    on `ca-order`, `cae-lf-twin` and `id-order-app` instead of the twin resource group; `apps` could check
    `ORDER_IMAGE` is a registry `sha-<40>` tag; `order-service.yml`'s `az account set` may fail for an AcrPush-only
    identity (WS1 file, see section 11); the control vault name is fixed, so reprovisioning after `azd down`
    needs `--purge`. Not done on purpose: a `predown` hook that runs `policy-off`, because the policy is
    subscription-wide and a teardown of a second environment would remove it for `lf-eh` too.
- Last commands run (WS2 Mac, with `.venv` active): `scripts/deploy.sh smoke policy`; before that
  `scripts/deploy.sh policy`; before that `scripts/deploy.sh smoke auth` (lab sections 5-8 above);
  before that the read-only checks (`az account show`,
  `azd env get-values`, `az provider operation show -n Microsoft.App`); before that the App Insights
  `exceptions` query (above); before that
  `for i in 1 2 3; do ./scripts/drill.sh || break; done`
  (three drills, run twice, above); before that `./scripts/reset.sh` alone (old replica gone after 58 s) and
  `./scripts/measure-propagation.sh 3`; earlier on the WS1 PC:
  `pytest -q src/order-service --cov=src/order-service/app`: 59 passed, coverage 99%
- Uncommitted / unpushed files: none expected (`evidence/` is local drill output and is not committed)
- Test status: order-service unit tests green 2026-10-29. Twin deployed to Azure by WS2 via `main.bicep`; baseline PASS.

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
- PR #10 opened: `docs/handoffs.md` lists what WS2, WS3 and WS5 need (image and tags, Bicep output and
  pass-throughs, local stack, SQL reset order, runbook path, telemetry and metric names).
- PR #11 opened: `.github/workflows/security.yml` (gitleaks full history, pip-audit, CodeQL Python, Trivy repo +
  image scan; fail on fixable HIGH/CRITICAL); local SQL image pinned to `2022-CU27-GDR1-ubuntu-22.04`; ADR-013.
- PR #12 opened: `order-service.yml` also runs on pushes to `candidate/<drill-id>-<attempt>` branches; the
  branch name is validated by a strict pattern and published as `candidate-<drill-id>-<attempt>` plus `sha-`
  (never `g1`); contract row added; ADR-014. Verified by CI on the PR (no candidate branch pushed).
- PR #13 opened: `docs/architecture.md` (components, request flow, secrets and configuration, health
  endpoints, telemetry names, CI/CD and image tags, runbook location) for WS3's search index.
- PR #14 opened: `src/load-generator/` (TDD, tests first, coverage 98%), Dockerfile (non-root), workflow
  `load-generator.yml` (test -> image smoke test -> publish `sha-`/`g2` from `main`), `infra/modules/loadgen.bicep`
  (Container Apps Job in `cae-lf-twin`, `az bicep build` clean, `twin.bicep` unchanged); security scans cover it;
  contract addition (G2) and ADR-015.

## Blockers / questions for the user or other workstreams
- Teammates (WS2–WS5) are not yet invited to the `livefire-team` org/repo — need their GitHub usernames.
- Tell WS2–WS5 the repo URL and image path (`ghcr.io/livefire-team/order-service`).
- Owner, after PR #14 merges and the first `main` run of `load-generator.yml` is green: make the GHCR package
  `load-generator` public too, then tell WS2 the image `ghcr.io/livefire-team/load-generator:g2`.
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
- [ ] WS5: metric names (orders_completed, orders_failed{reason}, loadgen_orders_sent, loadgen_orders_dropped, loadgen_backlog_size)

## Decisions log pointer
See `docs/ADR.md` (latest: ADR-019).

## Session log (newest first)
- 2026-11-05: WS2 G2 lab section 8: every workstream agreed; deny policy ON; `id-lf-ops` refused by Azure Policy
  through the Ops Service (`smoke policy` passed); ADR-019 "Implemented in" updated.
- 2026-11-05: WS2 G2 lab sections 5-7 on `lf-eh`: control plane provisioned, evidence check passed, images
  imported into the private registry, `ca-ops` and the jobs deployed, `smoke auth` passed. Platform hand-off
  posted to WS3, WS4 and WS5.
- 2026-11-04: #20 and #21 merged by the WS2 owner, #22 approved and merged by WS1 (merge commits); every `main`
  run green, all three images published. Read-only lab checks: signed in as a user, `lf-eh` on `accessPolicy`
  with `SECRET_REFRESH_SECONDS=10`, `AZURE_PRINCIPAL_TYPE` still to change to `User`; the Bicep's
  `Microsoft.App` actions all exist.
- 2026-11-04: review passes on #20, #21 and #22. #20: drill results moved out of this file (ADR-004). #21: `kill`
  now cancels the running action and resets under the lock; `drill_id`/`label` use `fullmatch`; keys left out of
  the `Settings` repr; the Referee image drops the unused `virtualenv` (Trivy HIGH); 113 tests, coverage 81.83%,
  CI green. #22: the broad-attempt role names only the order app identity, and `policy-off` removes it before the
  policy; `referee/tests` 48 passed; CI green.
- 2026-11-04: WS2 G2 Mac checks of the whole starter in a scratch worktree: Ops Service 105 passed, coverage 81.65%;
  `referee/tests` 58 of 59 (the `deploy.sh images` test failed on `/bin/bash` 3.2: an empty array under `set -u`;
  fixed on `ws2/g2-platform`, all pass); `az bicep build` and lint clean; ShellCheck clean. Ops Service on the fake
  twin: `smoke policy` and `smoke drill` passed; `smoke auth` failed only "tag not in the registry" (the fake
  registry accepts every tag). PR #21 opened. Owner (org owner): make GHCR packages `ops-service` and `referee`
  public after PR #21's first `main` run.
- 2026-11-04: WS2 G2 started. `ws2/g1-carryover` merges `ws2-starter` into `main` (one conflict, `scripts/drill.sh`,
  resolved to `main`'s INCONCLUSIVE handling plus the refresh-window wait); `pytest referee/tests -q` 43 passed.
  WS2 Mac notes (M1, with the Intel Homebrew in `/usr/local`, which no longer gets bottles): ShellCheck comes from
  `pip install shellcheck-py` in `.venv`; the only bash is `/bin/bash` 3.2;
  `referee/requirements.txt` and `src/ops-service/requirements-dev.txt` pin different pytest versions, so install
  `src/ops-service/requirements.txt` and `pytest-cov` next to the referee's pytest instead of both files at once.
- 2026-11-01: WS2 Mac has a private drill guide at `docs/reference/drill-guide.md` (git-ignored, ADR-004): purpose,
  how to run, twin-only checks. It exists only on that Mac.
- 2026-11-01: `drill.sh` waits out the secret refresh window before r2 (gap now about 16 s) and its comments are
  neutral (ADR-004); three drills again.
- 2026-10-31: the rolling restart landed mid-drill; `reset.sh` now waits for the old replica to go; three drills;
  r1-to-r2 timing margin only about 1-2 s.
- 2026-10-31: Key Vault propagation measured (`accessPolicy`: within about 5 s, 3 runs); `lib.sh` event timestamps
  fixed for macOS; `rbac` still unmeasured.
- 2026-10-31: PR #16 referee fix (evidence folder kept); WS2 Mac OpenSSL link fixed; twin baseline PASS.
- 2026-10-31: `ws2-starter` pushed (WS2 starter files, lab probe doc, two `twin.bicep` outputs); PR opened to `main`.
- 2026-10-30 session #2: owner merged PRs #3-#14 bottom-up (merge commits, CI green after each); rulesets added.
- 2026-10-29 session #2: final BUILD_STATUS; load generator hardened (partial reads, bounded config, steady schedule, non-overlapping job runs). PR #14 load generator (G2), stacked on PR #13.
- 2026-10-29 session #2: PR #13 architecture note `docs/architecture.md` (G2), stacked on PR #12.
- 2026-10-29 session #2: PR #12 candidate builds (G2), stacked on PR #11.
- 2026-10-29 session #2: PR #11 security scans workflow (G2), stacked on PR #10.
- 2026-10-29 session #2: PR #10 hand-offs page `docs/handoffs.md`, stacked on PR #9.
- 2026-10-29 session #2: PR #9 local Docker Compose stack with the app and the local access drill script, stacked on PR #8.
- 2026-10-29 session #2: PR #7 Dockerfile + GitHub Actions workflow (image built and smoke-tested locally), stacked on PR #6.
- 2026-10-29 session #2: PR #6 order pages, API, health checks and telemetry (TDD, 100% coverage), stacked on PR #5.
- 2026-10-29 session #2: PR #5 secret provider + catalog (TDD, 100% coverage), stacked on PR #4.
- 2026-10-29 session #2: PR #4 twin.bicep built (compile + lint clean), stacked on PR #3.
- 2026-10-29 session #2: Docker unblocked, local-sql.ps1 fixed for PowerShell 5.1 and run twice, PR #3 updated.
- 2026-10-28 session #1: tools installed, gh login, org + repo created, PR #1 and PR #2 merged, plan approved, PR #3 started.
