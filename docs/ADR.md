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

<!-- Copy the block below for each new decision -->

## ADR-00N: <short title>
- **Date:**
- **Status:** Proposed
- **Context:** What problem or constraint forces a decision?
- **Options considered:** (1) … (2) … (3) …
- **Decision:** What we chose, in one or two sentences.
- **Consequences:** Good and bad results, what it makes harder later.
- **Implemented in:** PR #__
