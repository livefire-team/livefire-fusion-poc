# WS4: contracts, Drill Runner, agents and evidence

Workstream 4 of LiveFire Fusion runs the drill: a deterministic Microsoft Agent Framework workflow with two Foundry
agents (Planner, read-only; Engineer, branch-only) and three human gates. It talks to the platform only through WS2's
Ops Service, WS3's MCP server, GitHub (CI and one pull request) and the shared event log the Control Center reads.
Deployment decisions: `docs/ADR.md`, ADR-026. Reference: the WS4 build guide and build steps (outside git, ADR-004).

## What's where

| Path | What it is |
| --- | --- |
| `src/drill-runner/livefire/` | `contracts.py` (v1.1), `workflow.py` (the stages), `policy.py` (Command Gate, checks, verdict), `ports.py` (Ops, GitHub, event log), `agents.py` (Foundry), `evidence.py` (the sealed package, scorecard, operational debt), `runner.py` (one drill per run), `stubs.py` |
| `src/drill-runner/agents/` | Both agent definitions (`*.yaml`) and instructions (`*.md`). The instructions carry an `{allowed_paths}` placeholder, filled from `ENGINEER_WRITE_PATHS` when a version is created |
| `src/drill-runner/tests/` | 62 tests: contracts, policy, the whole workflow on stubs (T-00 to T-10), v1.1, Ops and CI replies |
| `contracts/` | `event-catalog.md`, `handoffs.md` (v1.1), `ops-actions.md` (WS2's v2.1 as implemented), `schemas/` (generated) |
| `infra/modules/foundry.bicep` | Foundry account, project, the pinned model with Prompt Shields, one MCP connection per agent |
| `infra/modules/drill-runner.bicep` | `job-drill-runner` and `id-lf-drill-runner` (four roles, none on the twin); pulls with `id-lf-acrpull` |
| `scripts/create_agents.py` | Creates, pins and verifies both agent versions (`--dry-run` offline) |
| `scripts/agent-smoke.py` | Runs each pinned agent once on real evidence, with the workflow's own checks |
| `scripts/start-drill.sh` | Starts one drill (Autonomous Twin by default); refuses a second while one runs |
| `scripts/verify_package.py`, `scripts/export_schemas.py` | Recompute a drill's verdict from its sealed events; regenerate the schemas |
| `.github/workflows/drill-runner.yml` | Tests, Bandit and Semgrep, an in-image stub drill, then GHCR and the lab registry |

## How it fits what is deployed

- **Ops Service (WS2, `ca-ops`, contract v2.1):** the runner calls the v1 action names, which v2.1 keeps as aliases.
  Candidate images must be `<registry>/order-service:sha-<40 hex>`, which WS1's CI pushes on every candidate branch.
- **MCP server (WS3, `ca-mcp`, contract v2.4, key mode):** one Foundry connection per endpoint holds that endpoint's
  key, read from the control vault at deploy time. The Planner uses 6 of its 9 read-only tools, the Engineer all 6.
- **Control Center (WS5):** reads the same event log; it asks with `approval.requested` and answers with
  `approval.decided` and `kill.requested`.
- **CI (WS1):** a candidate passes only when both `order-service.yml` and `security.yml` succeed on its exact commit.
- **Write paths:** one list, in configuration only (ADR-004): the azd value `MCP_ENGINEER_WRITE_PATHS` feeds WS3's
  server, the runner job (`ENGINEER_WRITE_PATHS`) and the agents' instructions, and matches `CANDIDATE_ALLOWED_PATHS`.

## Run it on a laptop (no Azure)

```bash
python3.12 -m venv ~/.venvs/ws4 && . ~/.venvs/ws4/bin/activate
pip install -r src/drill-runner/requirements-dev.txt
(cd src/drill-runner && pytest -q)                        # 62 passed
cd src/drill-runner && EVENT_SOURCE=dir:../../evidence python -m livefire.runner --drill-id drill-local-0001 \
  --stub --stub-delay 0 --mode "Autonomous Twin" --auto-approve open_pr   # ends VERIFIED
python ../../scripts/verify_package.py ../../evidence/drill-local-0001     # seven ok lines
```

## Deploy to the lab (two passes, ADR-026)

Prerequisites: ca-mcp deployed (README-WS3.md), `ops-runner-key` in the control vault (WS2), and the runner's GitHub
credential (below). Every step goes through `scripts/deploy.sh`, which leaves WS4 out of a provision, and names what
is missing, rather than fail the lab's deployment.

1. **Foundry (first pass).**
   ```bash
   azd env set MODEL_NAME gpt-5.1 && azd env set MODEL_VERSION 2025-11-13
   scripts/deploy.sh foundry        # prints FOUNDRY_PROJECT_ENDPOINT and MODEL_DEPLOYMENT
   ```
   If the lab rejects the Prompt Shields policy: `azd env set PROMPT_SHIELDS off`, rerun, and tell the lead.
2. **Create, verify and pin the agents** (needs the runner's packages installed, and Azure AI User on the project,
   which the first pass gave the deployer):
   ```bash
   scripts/deploy.sh agents         # sets PLANNER_AGENT and ENGINEER_AGENT in azd
   set -a; eval "$(azd env get-values)"; set +a
   python scripts/agent-smoke.py "drill-agent-smoke-$(date +%m%d-%H%M)"              # Planner only, read-only
   ```
   Add `--engineer` to also have the Engineer write a `candidate/` branch (best while the fault is on; build steps 5C).
3. **The runner's GitHub credential.** Create the GitHub App `livefire-runner` (Actions read, Checks read, Contents
   read, Pull requests read and write, Metadata read; installed on this repo only), then:
   ```bash
   az keyvault secret set --vault-name "$(azd env get-value CONTROL_KEYVAULT_NAME)" -n gh-runner-private-key \
     --file <downloaded .pem> -o none
   azd env set RUNNER_GITHUB_APP_ID <app id> && azd env set RUNNER_GITHUB_INSTALLATION_ID <installation id>
   ```
   Fallback: a fine-grained token as `gh-runner-token`, and `azd env set RUNNER_GITHUB_AUTH token`.
4. **The runner (second pass).** CI pushes `drill-runner:sha-<40 hex>` to the lab registry on every merge to main:
   ```bash
   azd env set RUNNER_IMAGE "$(azd env get-value REGISTRY_SERVER)/drill-runner:sha-<merge commit>"
   scripts/deploy.sh runner         # prints RUNNER_JOB_NAME and the runner identity's four roles
   ```
5. **A drill.** `scripts/start-drill.sh` (Autonomous Twin) or `scripts/start-drill.sh Supervised`, then open the
   printed Control Center link.

## Known gaps

- `scripts/start-load.sh` (WS1) doesn't exist yet: drills run without `metrics.orders`, so the scorecard's
  throughput, backlog and failed-order fields are empty, and the package says so in `residual_risks`.
- The deny policy is off in `lf-eh`, so the broad option is refused by Azure RBAC (`AuthorizationFailed`), the
  labelled fallback, until WS2 runs `scripts/deploy.sh policy`.
- Hosted agents with their own Entra IDs (build steps 5A) are not built: this is the prompt-agent fallback (5B),
  which blueprint 9.4 permits; the lead records it in `docs/decisions.md`.
