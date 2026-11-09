# Architecture Decision Records (ADR)

Every architectural decision gets an entry here BEFORE or WITH the code that implements it.
Newest at the bottom. Never delete an entry; if a decision changes, add a new ADR that supersedes the old one
and change the old one's status to `Superseded by ADR-00N`.

Status values: Proposed | Accepted | Superseded | Rejected

---

## ADR-001: Use the hackathon plan's stack (Python 3.12, FastAPI, Bicep, Container Apps, GHCR)
- **Date:** 2026-10-28
- **Status:** Accepted
- **Context:** The LiveFire Fusion PoC Implementation Plan fixes the stack so all five workstreams integrate.
- **Options considered:** (1) follow the plan; (2) substitute tools we know better.
- **Decision:** Follow the plan, including the pinned versions in the WS1 Build Guide's `requirements.txt`.
  Deviations require a new ADR and the lead's approval.
- **Consequences:** Less freedom, but WS2–WS5 can rely on our names, outputs and image tag.
- **Implemented in:** PR #1

## ADR-002: Host the shared repo in a GitHub org, public
- **Date:** 2026-10-28
- **Status:** Accepted
- **Context:** The Build Guide (Phase 0) asks for "a repo in an org the team controls" shared by WS1 and WS2, and
  says to decide early whether the image package can be public. The PoC plan lists "which org, public or private"
  as an open question. No team repo existed yet.
- **Options considered:** (1) new free org `livefire-team`, public repo; (2) repo under a personal account;
  (3) private repo (Bandit instead of CodeQL, registry credentials in the Container App).
- **Decision:** Create the free org `livefire-team` and the public repo `livefire-team/livefire-fusion-poc`.
  The image will be `ghcr.io/livefire-team/order-service` (lowercase, as GHCR requires) and its package public.
- **Consequences:** Free CodeQL; Container Apps pulls the image with no registry credential, so `twin.bicep` stays
  simple. Ownership is not tied to one person (more org admins can be added). Anyone can read the code and the
  commit history — acceptable because the repo holds no secrets and is a demo.
  Teammates must be invited to the org/repo before they can push.
- **Implemented in:** PR #1 (repo created 2026-10-28)

## ADR-003: Merge commits only — never squash or rebase-merge
- **Date:** 2026-10-28
- **Status:** Accepted
- **Context:** The demo depends on specific commits in `main` staying exactly as written, one by one.
  A squash merge collapses a PR's commits into one; a rebase merge rewrites them.
- **Options considered:** (1) squash merges (tidy history); (2) rebase merges; (3) merge commits only.
- **Decision:** Merge every PR with a merge commit (`gh pr merge <N> --merge`). Never force-push `main`.
  Disable squash and rebase merging in the repo settings so nobody can do it by accident.
- **Consequences:** History is noisier (one merge commit per PR) but every commit survives exactly as written.
- **Implemented in:** PR #1 (repo settings change applied with the owner's approval)

## ADR-004: Keep the spec documents out of the repo
- **Date:** 2026-10-28
- **Status:** Accepted
- **Context:** The starter prompt asked for the Build Guide and PoC plan under `docs/reference/`. The Build Guide
  contains the full demo script. The repo is public (ADR-002), and the Planner agent's
  `read_repository_context` tool reads allowlisted repo paths, so the script would sit next to the code.
- **Options considered:** (1) commit them and rely on WS3's allowlist excluding `docs/`; (2) keep them only in the
  local kit folder and git-ignore `docs/reference/`.
- **Decision:** Option 2. The specs stay in `C:\Users\venka\projects\livefire-ws1-kit\reference\`; `CLAUDE.md`
  points there. Demo-specific working rules live in a git-ignored `CLAUDE.local.md`. WS3 keeps `docs/` and
  `CLAUDE.md` off the agent allowlist.
- **Consequences:** A new laptop or teammate needs the kit folder (or the PDFs) separately. The demo cannot be
  spoiled by reading the repo's current files. (PR #1's first commit predates this and keeps older wording.)
- **Implemented in:** PR #1

## ADR-005: Local SQL Server credentials are generated, not committed; port bound to localhost
- **Date:** 2026-10-28
- **Status:** Accepted
- **Context:** The Build Guide's Phase 7 `docker-compose.yml` hard-codes the local SA password and publishes port
  1433 on all interfaces. The repo is public, so anyone on the same network could log in with a published password.
- **Options considered:** (1) copy the guide as is; (2) generate the password into a git-ignored `.env` on first
  run and bind the port to `127.0.0.1`.
- **Decision:** Option 2. `scripts/local-sql.ps1` creates `.env` with `LOCAL_SA_PASSWORD` if missing; compose reads
  it and refuses to start without it. sqlcmd reads the password from inside the container, not the command line.
- **Consequences:** No credential in git; SQL reachable only from this PC. First run must go through the script
  (or a hand-made `.env`). The app's local `order_app` password is handled the same way in plan item #9.
- **Implemented in:** PR #3

## ADR-006: One replica of the order service; liveness and readiness probes on `/health` only
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** The twin runs a single small order service. Container Apps can scale out to several replicas and
  restarts or stops routing to a replica whose probes fail. The service has two health endpoints: `/health`
  (the process is up) and `/health/dependencies` (Key Vault and SQL are reachable).
- **Options considered:** (1) autoscale with probes on `/health/dependencies`; (2) exactly one replica
  (min = max = 1) with both probes on `/health`.
- **Decision:** Option 2, as the contract (`contracts/twin-interface.md`) requires. Probes on `/health` keep the
  platform from restarting the app or taking it out of rotation because of a dependency outage; dependency health
  is reported by `/health/dependencies` and telemetry instead.
- **Consequences:** Predictable behaviour and cost: every request hits the same instance. No horizontal scaling or
  redundancy, which is acceptable for a disposable twin. A dependency outage shows up in telemetry and
  `/health/dependencies`, not as restarts.
- **Implemented in:** PR #4 (`infra/modules/twin.bicep`)

## ADR-007: Azure SQL Basic tier for the twin database
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** The twin needs a small, cheap database that answers the first request quickly.
  Serverless databases can auto-pause and take time to resume.
- **Options considered:** (1) Basic (DTU) tier; (2) serverless `GP_S_Gen5` with auto-pause; (3) serverless
  `GP_S_Gen5` with `autoPauseDelay: -1` (never pause).
- **Decision:** Basic tier: always on and the cheapest fixed option. Fallback only if an Azure Policy blocks Basic:
  switch to option 3 (serverless that never pauses), recorded as a new ADR.
- **Consequences:** No cold start; 2 GB size and 5 DTU limits are ample for the twin's few tables.
- **Implemented in:** PR #4 (`infra/modules/twin.bicep`)

## ADR-008: Plain Bicep resources rather than Azure Verified Modules (AVM)
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** Azure Verified Modules are Microsoft-maintained Bicep modules for each resource type. The twin needs
  exact control over replicas, probes and a deterministic role-assignment name that WS2 relies on.
- **Options considered:** (1) AVM modules for each resource; (2) plain `resource` declarations in one module.
- **Decision:** Option 2. The twin is small, and AVM parameter names change between versions.
- **Consequences:** We own the resource definitions (API versions, defaults) and must update them ourselves;
  in return the file is short, readable and stable for WS2's `main.bicep`.
- **Implemented in:** PR #4 (`infra/modules/twin.bicep`)

## ADR-009: Test-only Python packages in `requirements-dev.txt`
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** The container image only needs the runtime packages in `src/order-service/requirements.txt`
  (pinned versions from the build guide). Tests also need pytest and pytest-cov, and an unpinned
  `pip install pytest` can change behaviour between runs.
- **Options considered:** (1) add pytest to `requirements.txt`; (2) install pytest unpinned in CI;
  (3) a separate `requirements-dev.txt` that starts with `-r requirements.txt` and pins the test tools.
- **Decision:** Option 3 (pytest 8.4.2, pytest-cov 7.0.0). `src/order-service/pytest.ini` puts `app/` on the
  import path so `pytest` works from `src/order-service` or the repo root.
- **Consequences:** The image stays free of test tools; local runs and CI use the same test versions.
  CI should install `requirements-dev.txt` instead of `requirements.txt pytest`.
- **Implemented in:** PR #5 (`src/order-service/requirements-dev.txt`, `src/order-service/pytest.ini`)

## ADR-010: Image tags — immutable `sha-<commit>` plus moving `g1`, pushed only from `main`
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** WS2 deploys the order service from GHCR. Rehearsals need a version that never changes under them;
  the G1 milestone needs one well-known name that always points at the latest good build of `main`.
- **Options considered:** (1) only `latest`; (2) only per-commit tags; (3) a per-commit tag plus one moving tag.
- **Decision:** Option 3. Every push to `main` that touches the service pushes `ghcr.io/<org>/order-service:sha-<7-char
  commit>` (never overwritten, used for rehearsals) and `:g1` (moves to the newest `main` build, the G1 hand-off name).
  Pull requests build and smoke-test the image but never push it.
- **Consequences:** A rehearsal pinned to a `sha-` tag is reproducible; `g1` changes whenever `main` changes, so it
  is not used for rehearsals. Unmerged branches never reach the registry. The GHCR package must be made public by
  hand once, after the first push (or WS2 needs a `read:packages` token).
- **Implemented in:** PR #7 (`.github/workflows/order-service.yml`)

## ADR-011: CI design for the order service
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** The build guide's workflow is one job that installs `requirements.txt pytest`, runs on pull requests
  that touch `src/order-service/**` (not workflow-only changes), and grants `packages: write` to the whole workflow. Our PRs are
  stacked (each PR's base is the previous PR's branch), tests now need `requirements-dev.txt` (ADR-009) and a
  coverage gate, and we want the image proven to start before it is published.
- **Options considered:** (1) the guide's single job as written; (2) two jobs, `test` then `image`, with
  `packages: write` on `image`; (3) three jobs, `test` -> `image` -> `publish`, where only `publish` can write
  packages and it never runs for pull requests.
- **Decision:** Option 3 (revised in PR #7 review; option 2 still gave the pull-request build a job token that
  could write packages). Triggers: `push` to `main` and `pull_request` with no base-branch filter (so stacked PRs
  are checked), both limited to `src/order-service/**` and the workflow file, plus manual `workflow_dispatch`.
  - `test` (`contents: read`): Python 3.12, `unixodbc` (pyodbc needs `libodbc`), `requirements-dev.txt`, pytest
    with `--cov-fail-under=80`.
  - `image` (needs `test`, `contents: read`): `docker build`, run the container bound to `127.0.0.1:8000`,
    `/health` must return 200 `{"status":"up"}` and `/health/dependencies` must answer (200 or 503); container
    logs are printed on any failure. The tested image is saved with `docker save` and uploaded as a one-day
    artifact; its image ID is a job output.
  - `publish` (needs `image`, only `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`,
    `contents: read` + `packages: write`): downloads the artifact, `docker load`s it, fails unless the image ID
    equals the one `image` tested, logs in to GHCR with `GITHUB_TOKEN` and pushes `sha-<short sha>` and `g1`.
  The smoke container sets `SECRET_SOURCE=file:/nonexistent` because the default Key Vault source needs
  `KEYVAULT_URL` at start-up and CI has no Azure. Plain `docker build`/`save`/`load`/`push` replace
  `docker/build-push-action` so the pushed image is exactly the one smoke-tested. Every checkout uses
  `persist-credentials: false`. Every action is pinned to a full commit SHA with the release tag in a comment
  (`actions/checkout` v7.0.1, `actions/setup-python` v7.1.0, `actions/upload-artifact` v7.0.2,
  `actions/download-artifact` v8.0.2, `docker/login-action` v4.7.0; all run on Node 24).
  The Dockerfile checks the Microsoft package signing key's fingerprint before trusting it and labels the image
  with `org.opencontainers.image.source` so GHCR links the package to this repo.
- **Consequences:** A broken image or a coverage drop blocks publishing, and pull-request runs never hold a
  token that can write packages. Three jobs and the image artifact cost a little more CI time and storage
  (artifact kept one day). SHA pins do not pick up action fixes automatically: bump them deliberately (look up
  the tag's commit with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`, dereferencing annotated tags).
- **Implemented in:** PR #7 (`.github/workflows/order-service.yml`, `src/order-service/Dockerfile`)

## ADR-012: Local stack uses a file as the Key Vault stand-in and a generated app password
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** The local Docker Compose stack (Build Guide Phase 7) has no Key Vault and no managed identity. The
  guide's example uses fixed passwords for the SA and `order_app` logins, publishes ports on all interfaces, and
  writes the app password with `echo`.
- **Options considered:** (1) the guide's fixed passwords and ports as written; (2) run a Key Vault emulator
  locally; (3) the app's existing `SECRET_SOURCE=file:<path>` mode with a generated password in a git-ignored file.
- **Decision:** Option 3. `scripts/local-sql.ps1` also creates the `order_app` login and user (same grants as the
  guide) with a password generated from the crypto random-number generator (no `;` `}` `!`), stored in the
  git-ignored `.local/secret.txt` and kept on later runs; the login's password is re-applied each run so the two
  stay in step. The password reaches `sqlcmd` as an environment variable used as a scripting variable, so it is
  never on a command line. The `orders` service mounts `.local` at `/run/livefire`, reads
  the password from `secret.txt` with a 2-second refresh window, and is published on `127.0.0.1:8000` only.
  `scripts/local-access-drill.ps1` changes that file to walk through access stages and prints what the app reports.
- **Consequences:** No local credential is in git and the stack runs with no Azure access or extra containers
  (fits a 6 GB PC). The file source is a stand-in: it does not exercise managed identity or Key Vault RBAC, which are
  only checked in the lab. Deleting `.local/secret.txt` makes the next `local-sql.ps1` run generate a new password.
- **Implemented in:** PR #9 (`docker-compose.yml`, `scripts/local-sql.ps1`, `scripts/local-access-drill.ps1`)

## ADR-013: Security scans in CI and their fail policy
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** G2 asks for gitleaks, pip-audit, Trivy and CodeQL in CI. The repo is public, so CodeQL is free.
  `gitleaks-action` needs a paid licence for organisation repos, and third-party scanner actions that run whatever
  their tag points at are a supply-chain risk. A scan that fails on every unfixable base-image CVE would block every
  PR without anything we could do about it.
- **Options considered:** (1) the vendors' wrapper actions (`gitleaks-action`, `trivy-action`); (2) the official
  release binaries, downloaded at a fixed version and checked against a fixed SHA-256 checksum; and for the fail
  policy (a) report only, (b) fail on any finding, (c) fail on HIGH/CRITICAL findings that have a fix available.
- **Decision:** Option 2 with policy (c). New workflow `.github/workflows/security.yml` runs on every pull request
  (any base) and on pushes to `main`, as four jobs with read-only tokens: `gitleaks` scans the full git history
  (`--redact`, fails on any finding); `pip-audit` audits `src/order-service/requirements.txt` and
  `requirements-dev.txt` (fails on any known vulnerability); `codeql` analyses the Python code (only this job has
  `security-events: write`; alerts go to the repo's Security tab); `trivy` scans the repository for vulnerable
  dependencies and misconfigurations (Dockerfile, IaC) and then the order-service image built in the job, both with
  `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`. Actions are pinned to commit SHAs (ADR-011);
  `pip-audit` is pinned by version. The local SQL Server image in `docker-compose.yml` is pinned to
  `2022-CU27-GDR1-ubuntu-22.04` (same digest as `2022-latest` on 2026-10-29) instead of the moving tag.
- **Consequences:** A leaked secret, a fixable HIGH/CRITICAL CVE or a misconfiguration blocks the PR; unfixed
  base-image CVEs are not blocking, so they need a periodic look (rebuild on a newer base when fixes land). Trivy does
  not read Bicep directly, so `infra/` is only covered once it is compiled to ARM JSON. Scanner versions and
  checksums are bumped by hand (`gh api repos/<owner>/<repo>/releases/latest`, then the release's checksums file).
  Any gitleaks allowlist entry goes in `.gitleaks.toml` with a comment saying why it is not a secret. The first run
  found three false positives (two Azure built-in role IDs in `twin.bicep`, the Microsoft signing-key fingerprint
  in the Dockerfile), now allowlisted by exact value; a dev-only pytest advisory (PYSEC-2026-1845), fixed by moving
  `requirements-dev.txt` to pytest 9.0.3; and Trivy check DS-0031 reading the Dockerfile build argument
  `MS_KEY_FPR` as a secret name, fixed by renaming it `MS_SIGNING_FINGERPRINT`.
- **Implemented in:** PR #11 (`.github/workflows/security.yml`, `.gitleaks.toml`, `docker-compose.yml`)

## ADR-014: Candidate builds from `candidate/<drill-id>-<attempt>` branches
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** G2 asks for candidate builds: a push to a `candidate/*` branch must build, test and publish an image
  that WS2's deploy step can run as a new revision, named after the drill. Branch names are chosen by whoever pushes,
  so they are untrusted input to the workflow, and a candidate must never replace the `g1` image.
- **Options considered:** (1) a separate candidate workflow; (2) extend `order-service.yml` so candidate pushes run
  the same `test` -> `image` -> `publish` path as `main`; and for the tag (a) the raw branch name, (b) a tag parsed
  from a strictly validated branch name.
- **Decision:** Option 2 with (b). `on.push.branches` adds `candidate/**`. A new first job `candidate-tag` (no token
  permissions) reads `github.ref` through an environment variable, requires
  `^candidate/([a-z0-9][a-z0-9-]{0,47})-([1-9][0-9]?)$` (lowercase drill ID, attempt 1-99) and outputs
  `candidate-<drill-id>-<attempt>`; any other `candidate/` name fails the run before tests. `publish` (still the
  only job with `packages: write`) runs for pushes to `main` or to a valid candidate branch and always pushes
  `sha-<short sha>`; it pushes `g1` only from `main` and the candidate tag only from candidate branches (re-checked
  against the pattern before use). Pull requests still run `test` and `image` only.
- **Consequences:** WS2 deploys `ghcr.io/livefire-team/order-service:candidate-<drill-id>-<attempt>` (or the
  `sha-` tag for an exact build). Anyone who can push a `candidate/` branch can publish a candidate tag, so branch
  protection or a ruleset should limit who can create those branches. The workflow's `paths` filter still applies:
  a candidate push that changes nothing under `src/order-service/` or the workflow does not build. Pushing to the
  same candidate branch again moves its candidate tag; the `sha-` tag stays immutable.
- **Implemented in:** PR #12 (`.github/workflows/order-service.yml`)

## ADR-015: Load generator as a Container Apps Job with an in-memory retry backlog
- **Date:** 2026-10-29
- **Status:** Accepted
- **Context:** G2 asks for a load generator that calls `POST /api/orders` at a steady rate and retries failed orders
  from a backlog, so throughput, backlog and the drain after recovery are real numbers in Application Insights. It
  must run next to the twin without changing the `twin.bicep` contract.
- **Options considered:** (1) a Container App with one always-on replica; (2) a Container Apps Job (manual or
  schedule trigger) that runs for a set duration; (3) an external tool such as Azure Load Testing or k6. For the
  backlog: (a) in memory, bounded; (b) a queue or table in Azure.
- **Decision:** Option 2 with (a). `src/load-generator/` is a Python 3.12 package (`python -m loadgen`, standard
  library HTTP client, `azure-monitor-opentelemetry` pinned like the order service). Each tick (60 /
  `RATE_PER_MINUTE` seconds) sends one new order, cycling through `SKUS`, with `x-drill-id: DRILL_ID` when set, then
  up to `RETRIES_PER_TICK` (default 5) due retries. 5xx, 408, 429 and network errors go to a backlog capped at
  `MAX_BACKLOG` (default 500) with exponential backoff from `RETRY_BASE_SECONDS` (2) to `RETRY_MAX_SECONDS` (60);
  other 4xx answers and backlog overflow are counted as dropped. The run stops after `DURATION_SECONDS` (0 = no limit)
  or on SIGTERM; invalid settings exit with code 2. Metrics (only exported when
  `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, logger `loadgen`): `loadgen_orders_sent` (counter, attributes
  `kind` = `new`/`retry`, `result` = `ok`/`failed`), `loadgen_orders_dropped` (counter, attribute `reason`) and
  `loadgen_backlog_size` (gauge); a `loadgen status sent=.. backlog=.. dropped=..` log line every 30 ticks and at the
  end. `infra/modules/loadgen.bicep` defines the job `caj-loadgen` (one replica per execution, no retries of the
  replica, timeout `durationSeconds` + 300 s) in the existing environment `cae-lf-twin`, found by name with an
  `existing` reference, so `twin.bicep` gets no new parameter or output. The connection string is a job secret.
  Workflow `.github/workflows/load-generator.yml` mirrors `order-service.yml` (test, image smoke test, publish
  `sha-<short>` and `g2` from `main` only); `security.yml` also audits and scans the load generator.
- **Consequences:** No extra Azure resources and nothing to clean up between runs, but the backlog is lost if a job
  execution ends: orders still in it at the end are not placed (the final status line shows how many). WS2 deploys
  the module after `twin.bicep` and starts runs with `az containerapp job start`. The `load-generator` GHCR package
  must be made public like `order-service`. The rate is capped at 600 per minute.
- **Implemented in:** PR #14 (`src/load-generator/`, `infra/modules/loadgen.bicep`, `.github/workflows/load-generator.yml`)

## ADR-016: Key Vault access-policy model (Path B) for the twin's access fault
- **Date:** 2026-11-01
- **Status:** Accepted (WS2)
- **Context:** The lab probe (`docs/lab-probe-2026-10-30.md`) allows both ways of removing the app's Key Vault access:
  Path A, the `rbac` model (delete the Key Vault Secrets User role assignment, plus the deny policy and
  `id-lf-ops`'s limited role from `PATH_A_CONTROLS=on`), and Path B, the `accessPolicy` model (delete the app
  identity's access policy entry). The twin in `rg-lf-twin-lf-eh` is provisioned with `accessPolicy`, where the
  change showed in `/health/dependencies` within about 5 s (3 runs). `rbac` role changes can take up to about
  10 minutes and were not measured. G2 is Nov 2.
- **Options considered:** (1) Path A: reprovision with `KV_PERMISSION_MODEL=rbac` and `PATH_A_CONTROLS=on`, then
  measure propagation again; (2) Path B: keep `KV_PERMISSION_MODEL=accessPolicy` and `PATH_A_CONTROLS=off`.
- **Decision:** Option 2. No deny policy and no `ops-access.bicep` roles are deployed.
- **Consequences:** No reprovisioning, and the measured propagation applies. `lib.sh`, `main.bicep` and
  `main.parameters.json` still default to `rbac`, so every new azd environment needs
  `azd env set KV_PERMISSION_MODEL accessPolicy`. `id-lf-ops` gets no role on the twin vault; an access-policy
  restore needs `Microsoft.KeyVault/vaults/accessPolicies/write`, so the identity that runs it must be granted that
  separately. With no deny policy, `recover.sh broad` is refused only if the identity running it lacks role
  assignment rights; run as the lab's subscription Owner it is allowed (the script then removes the assignment and
  exits 3).
- **Implemented in:** azd environment settings only (no code change)

<!-- Copy the block below for each new decision -->

## ADR-017: Private registry for what runs in the lab; GHCR stays the build output
- **Date:** 2026-11-04 (updated 2026-11-05: immutable OIDC subject)
- **Status:** Accepted (WS2)
- **Context:** WS3's and WS4's Bicep pull images with an AcrPull-only identity, and the Ops Service must deploy an
  immutable image it can resolve itself. CI already publishes tested images to public GHCR.
- **Options considered:** (1) keep pulling from GHCR; (2) a private Azure Container Registry per lab, filled from
  GHCR or by CI over OIDC.
- **Decision:** Option 2. `control.bicep` creates the registry (Basic, no admin user), `id-lf-acrpull` (AcrPull only)
  and `id-lf-ci` (AcrPush only, trusted by the repo's `acr-push` environment). `scripts/deploy.sh images` imports
  each component's last `main` build from GHCR as `:sha-<full commit>`; CI's `acr` jobs push the same tested image
  for later commits and candidate branches. The Ops Service deploys only `<registry>/order-service:sha-<40 hex>`,
  resolved to its digest.
- **Consequences:** Each new lab needs `scripts/deploy.sh images` and, for CI pushes, `scripts/deploy.sh github`
  (repo admin). No registry password exists anywhere. GitHub signs this repo's OIDC tokens with the immutable
  subject (`repo:livefire-team@349630330/livefire-fusion-poc@1437908536:environment:acr-push`; the numbers are the
  org's and repo's permanent IDs, so a deleted and re-created repo of the same name gets no access). `GITHUB_REPOS`
  entries therefore carry those IDs, one entry per repo; a repo on the older format is listed as `owner/name`. To
  add a repo, take its entry from `gh api repos/<owner>/<name>/actions/oidc/customization/sub --jq
  '.sub_claim_prefix | ltrimstr("repo:")'`; that repo must answer `"use_default": true` there (custom claim keys
  never match `repo:<entry>:environment:acr-push`).
- **Implemented in:** `infra/modules/control.bicep`, `infra/main.bicep`, `infra/main.parameters.json`,
  `scripts/deploy.sh`, the `acr` jobs in `.github/workflows/`

## ADR-018: The Ops Service is the only path from the control plane into the twin
- **Date:** 2026-11-04
- **Status:** Accepted (WS2)
- **Context:** The Drill Runner (WS4) and the Recovery tools (WS3) need to change the twin without holding Azure
  rights themselves.
- **Decision:** `ca-ops` (internal ingress, one replica, `id-lf-ops`) implements `contracts/ops-actions.md` v2.1.
  Callers never name a resource; startup fails unless every target sits in `rg-lf-twin-*`. Two keys: the runner key
  for every action, the agent key for `recover`, `attempt_unsafe` and `check_drift` with a signed single-use grant.
  The Referee runs as `job-referee` with its own identity and read-only SQL login; the Ops Service may only start it
  and read its executions. Events go to an append-only Blob container (version-level immutability, unlocked).
  `id-lf-ops` gets custom roles scoped to the order app, the twin vault's access policies (or, on the `rbac`
  model, a conditional RBAC Administrator limited to Key Vault Secrets User), and starting `job-referee`.
- **Consequences:** Only the `identity-rbac` fault is enabled; the other v2.0 faults are refused until their rights
  exist. Laptop scripts in `scripts/` remain for manual drills.
- **Implemented in:** `src/ops-service/`, `referee/run.py`, `infra/modules/ops.bicep`, `infra/modules/ops-twin-access.bicep`

## ADR-019: Subscription-wide deny of broad roles, with the access-policy model kept
- **Date:** 2026-11-04
- **Status:** Accepted (WS2); amends ADR-016's "no deny policy"
- **Context:** The broad recovery option must be refused by the platform, and by Azure Policy rather than by a
  missing right. ADR-016 kept the vault on the access-policy model; that choice is independent of the deny policy.
- **Decision:** `DENY_BROAD_POLICY=on` assigns `lf-deny-broad-roles` at subscription scope (Owner, Contributor and
  User Access Administrator assignments are denied for everyone). After it is proven in effect,
  `BROAD_ATTEMPT_ROLE=on` gives `id-lf-ops` RBAC Administrator on the subscription with a condition that allows only
  Contributor, and only for the order app's identity, so its attempt reaches Azure Policy. `policy-off` removes that
  role first and keeps the policy until it is gone. No team Bicep assigns any of the three denied roles.
- **Consequences:** Nobody in the lab can assign those three roles while the policy is on, including the team. If the
  policy were removed, `id-lf-ops` could grant Contributor; the Ops Service removes any such grant at once and
  records `UNEXPECTED_ALLOW`.
- **Implemented in:** `infra/main.bicep`, `infra/modules/broad-attempt-access.bicep`. Proven in the lab (`lf-eh`)
  on 2026-11-05: the first `RequestDisallowedByPolicy` from `id-lf-ops` was drill
  `drill-smoke-policy-20261105-0216-6e1e` at 02:16:12 UTC (`smoke policy`, through the Ops Service with a signed
  grant; the `recover.broad` event's `refused_by` is `Azure Policy`).

## ADR-020: Candidate pushes are gated by a path check and the security scans
- **Date:** 2026-11-08
- **Status:** Accepted (WS1)
- **Context:** A candidate push built, tested and published its image, but ran no security scans (`security.yml`
  ran only on pull requests and `main`, and a candidate never gets a pull request before the drills end) and nothing
  checked which files it changed. WS4 deploys a candidate only when CI passed (`ci_gates_passed`), so CI is the last
  automated check before a candidate runs in the twin. CodeQL reports alerts without failing its job, so on a push
  with no pull request it gates nothing.
- **Options considered:** (1) rely on the MCP server's write limits alone; (2) a CI path check with the allowed
  patterns written in the workflow; (3) a CI path check with the patterns in a repository Actions variable, plus the
  scans and bandit on candidate pushes.
- **Decision:** Option 3. A `candidate-scope` job runs on candidate pushes in both `order-service.yml` (before
  `test`, so nothing is published on failure) and `security.yml` (which has no paths filter, so it runs on every
  candidate push). It runs `main`'s copy of `scripts/candidate-scope.sh`, not the candidate's, on the files changed
  since the merge base with `main`, and fails if any is outside the patterns in `CANDIDATE_ALLOWED_PATHS` (one
  extended regex per line, matched against the whole path). It fails closed when the variable is missing, empty or
  invalid, logs counts and refused files only, and escapes file names so they can't inject workflow commands.
  `security.yml` now also runs on `candidate/**` pushes and gains a `bandit` job that fails on medium or high
  findings in `src/order-service/app` and `src/load-generator/loadgen`. `gitleaks` scans only the history of the
  commit under test (`--log-opts="--full-history HEAD"`): the full-depth checkout also fetches every other branch,
  whose commits are scanned by their own runs against their own `.gitleaks.toml`.
- **Consequences:** A candidate that changes any other file publishes no image. Changing the allowed paths needs a
  repository admin (Settings > Secrets and variables > Actions > Variables), not a pull request, so the change is
  not in git history; the owner records it in the team channel. The patterns must match the MCP server's write
  limits, or a valid candidate fails here. A candidate CI pass now means both workflows ended `success` for the
  candidate's head commit; a missing run is not a pass.
  This catches mistakes, not a candidate that rewrites CI: a push runs the workflow files from its own commit, so a
  candidate that edits `.github/workflows/` could drop the job, print the variable, or publish an image (the
  `acr-push` environment allows `candidate/*`). The controls for that sit outside CI: the Engineer's GitHub App has
  no Workflows permission (GitHub then refuses any push that touches `.github/workflows/`), the MCP server writes
  only allowed paths, and the drill runner re-checks a candidate's changed files before it deploys. The refused-file
  names in the log also let repeated candidates probe the list; with the MCP write limits in place, that reveals
  nothing a candidate can use.
- **Implemented in:** `scripts/candidate-scope.sh`, `referee/tests/test_candidate_scope.py`,
  `.github/workflows/order-service.yml`, `.github/workflows/security.yml`

## ADR-021: The load generator writes metrics.orders lines to the drill's event log
- **Date:** 2026-11-08
- **Status:** Accepted (WS1); the field list needs WS4's approval for the event catalog
- **Context:** The Control Center's Orders per minute, Failed orders and Backlog tiles read `metrics.orders` lines from
  the drill's event log (`<drill-id>/events.jsonl`, in a folder or the evidence container), and show a dash until they
  arrive. The load generator reported only to Application Insights (ADR-015).
- **Options considered:** (1) the Control Center queries Application Insights; (2) a separate job that turns
  Application Insights metrics into events; (3) the load generator writes the lines itself.
- **Decision:** Option 3. With `EVENT_SOURCE` set (`dir:<path>`, or `blob:https://<account host>/<container>` with the
  job's managed identity), `loadgen/events.py` writes one line every `METRICS_INTERVAL_SECONDS` (1-300, default 30)
  and a last one when the run ends or is stopped, in the shape every event writer uses:
  `{"ts", "drill_id", "action": "metrics.orders", "result": "ok", "details": {"orders_per_min", "failed_total",
  "backlog", "recovered_total", "dropped_total", "window_s"}}`. `orders_per_min` counts orders placed (HTTP 201, new
  or retried) in the window, scaled to a minute; `failed_total` counts new orders whose first attempt failed;
  `recovered_total` counts retries that later succeeded; `dropped_total` counts orders given up on. `EVENT_SOURCE`
  needs a `drill-` `DRILL_ID`, or the job exits with code 2. Lines go through a bounded queue to a background writer,
  so a slow or unreachable store never holds up the orders; a failed write, or a store that cannot be opened, logs a
  warning and the load carries on. The Blob client has short timeouts and no SDK retries (a retried append could
  write a line twice; a lost line costs little because every line carries running totals), and shutdown waits at
  most 10 s for queued lines. Creating the append blob never replaces one another writer already started
  (`if_none_match="*"`). The Application Insights metrics are unchanged.
- **Consequences:** The tiles get numbers without a query layer. Writing to Blob needs an identity with Storage Blob
  Data Contributor on the evidence container (a follow-up with WS2); until then the job runs without `EVENT_SOURCE`.
  `infra/modules/loadgen-identity.bicep` gives the job `id-lf-loadgen` with a custom role on the evidence container
  alone (create and append blobs; no read, no delete) and a condition that limits those writes to
  `drill-<id>/events.jsonl`. It can still append to any drill's event log (or write a new version of one; the
  container's version-level immutability keeps the earlier versions), so those logs are not tamper-proof against this
  identity; other evidence files are out of its reach. The storage account comes from the deployment
  (`control.outputs.evidenceAccountName`), not from a hand-typed URL. Wiring it into `main.bicep` is WS2's change.
  The image gains `azure-identity` and `azure-storage-blob`. If WS4's catalog names these fields differently, the
  catalog wins and this module follows.
- **Implemented in:** `src/load-generator/loadgen/events.py`, `config.py`, `runner.py`, `__main__.py`,
  `src/load-generator/tests/test_events.py` (PR #35); `infra/modules/loadgen-identity.bicep`, `loadgen.bicep`
- **Update 2026-11-08 (WS2): wired into `main.bicep`.** `loadgen-identity` (control resource group) and `loadgen`
  (twin resource group, after the twin) deploy only when `LOADGEN_IMAGE` is set, like the Ops Service's images.
  `scripts/deploy.sh images` imports `load-generator` into the private registry with the other components and sets
  `LOADGEN_IMAGE`; the job pulls it with `id-lf-acrpull` (new optional `registryServer` and `pullIdentityId` on
  `loadgen.bicep`, as on `twin.bicep`, ADR-017), and `AZURE_CLIENT_ID` still names `id-lf-loadgen`. The drill ID
  comes from `LOADGEN_DRILL_ID`; while it is empty, the job gets no `EVENT_SOURCE` and writes no lines (it would
  otherwise exit with code 2). The job keeps the name `caj-loadgen`, so a provision replaces the hand-deployed
  one in place. Open: one drill ID per deployment, so lines for a live drill need that drill's ID set before the
  provision. Outputs `LOADGEN_JOB_NAME` and `LOADGEN_PRINCIPAL_ID`. Implemented in `infra/main.bicep`,
  `infra/main.parameters.json`, `infra/modules/loadgen.bicep`, `scripts/deploy.sh`.

## ADR-022: WS3's MCP server lives in this repo and deploys with the platform
- **Date:** 2026-11-08
- **Status:** Proposed (WS3); needs WS2's review of the `main.bicep`, `deploy.sh` and `postprovision.sh` changes
- **Context:** WS3 was built as a standalone extract (`livefire-team/ws3-mcp-server`). The plan has one repo, one azd
  environment and one `main.bicep`; CI only pushes images, and `azd provision` deploys. A second deploy path for
  `ca-mcp` would fight the shared template. The Planner reads this repo, so ADR-004's allowlist applies.
- **Options considered:** (1) keep the extract and deploy `ca-mcp` from its own workflow, with an identity that can
  assign roles; (2) move WS3 here and add its two modules to `main.bicep`, like the Ops Service.
- **Decision:** Option 2. `ca-mcp` deploys once `MCP_IMAGE` is set and the Ops Service is deployed (`/recovery`
  calls it). `deploy.sh images` treats `mcp-server` like the other images; `deploy.sh apps` leaves `ca-mcp` out,
  naming what is missing, until its GitHub credentials are in the control vault, so WS3 can't fail a platform
  provision. If the control vault can't be read at all, the deploy stops before `azd provision` instead of
  dropping `ca-mcp`: an access problem must not look like a deliberate skip. `postprovision.sh` creates the three endpoint keys once (like the Ops keys) and reloads the incident
  index from `INCIDENT_CORPUS` when it is set. Contract v2.3: the Planner reads only `src/order-service/**` and `runbooks/*.md`, never `docs/`,
  `CLAUDE.md`, `src/ops-service/`, `referee/` or `scripts/`. On an access-policy twin vault, `id-lf-mcp` gets a
  secrets `list` policy (metadata, never values), re-added after the twin on every provision.
  Because this repo is public and the agents read it (ADR-004), nothing drill-specific comes with WS3: the incident
  corpus stays in the private `ws3-mcp-server` repo (`load-incidents.py --corpus`, or the azd value
  `INCIDENT_CORPUS`); the fixtures backend ships neutral placeholder evidence (`FIXTURES` points a rehearsal at the
  private file); and contract v2.4 takes the Engineer's write paths from `ENGINEER_WRITE_PATHS` (azd value
  `MCP_ENGINEER_WRITE_PATHS`), refusing every write when it is unset and refusing to start on a pattern that could
  match a protected path. `src/drill-runner/`, `src/ops-service/`, `referee/`, `docs/`, `azure.yaml` and `.gitleaks.toml` join the protected paths,
  which are now the only in-code limit on writes. File text is redacted before it is cut to size.
- **Consequences:** WS2's scripts now know about a fourth image. `deploy.sh` leaves `ca-mcp` out until
  `MCP_ENGINEER_WRITE_PATHS` is set. WS4's Drill Runner list and `CANDIDATE_ALLOWED_PATHS` (ADR-020) must allow the
  same files; WS4's list should also move to a setting before it lands here. WS3's coverage gate is 80% (the Azure
  backends are tested only in the lab). WS4's `PROTECTED_PATHS` should match the longer protected list. The standalone repo is retired once this merges.
- **Implemented in:** this PR (`src/mcp-server/`, `infra/modules/mcp*.bicep`, `.github/workflows/mcp-server.yml`)

## ADR-00N: <short title>
- **Date:**
- **Status:** Proposed
- **Context:** What problem or constraint forces a decision?
- **Options considered:** (1) … (2) … (3) …
- **Decision:** What we chose, in one or two sentences.
- **Consequences:** Good and bad results, what it makes harder later.
- **Implemented in:** PR #__
