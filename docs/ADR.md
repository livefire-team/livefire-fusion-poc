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

<!-- Copy the block below for each new decision -->

## ADR-00N: <short title>
- **Date:**
- **Status:** Proposed
- **Context:** What problem or constraint forces a decision?
- **Options considered:** (1) … (2) … (3) …
- **Decision:** What we chose, in one or two sentences.
- **Consequences:** Good and bad results, what it makes harder later.
- **Implemented in:** PR #__
