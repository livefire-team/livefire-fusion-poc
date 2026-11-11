# LiveFire Fusion — WS4 G2 Build Steps

**Owner:** WS4 (Agents, workflow, frozen contracts)
**Gate:** G2 — each component alone
**Team deadline:** Monday, **2026-11-09** (per workstream request; the reference repos contain earlier G2 dates)
**Prepared:** 2026-11-05
**Target repository:** `https://github.com/livefire-team/ws4-new`
**Language/runtime:** Python 3.12; PowerShell on Windows, Bash in CloudLabs
**Source baseline:** `livefire-ws4-starter-v2 1.zip`; checked against uploaded WS1/WS2, WS3 and WS5 sources and the Oct 20 implementation plan.

> IMPORTANT: These are **build and acceptance instructions**, not a claim that Azure G2 integration has passed. The starter README reports G1's 33 tests and dry-run checks passed in its author's environment; the current delivered bundle adds independent preflight checks. Azure, Foundry, real MCP, GitHub writes, GHCR and Ops have NOT been run in this preparation environment. Preserve the source's original G1 contracts and obtain approval for interface changes.

## A. Exactly what G2 means

The implementation plan's G2 gate is **component-level integration**: MCP endpoints return real evidence; *each* agent runs separately against the lab; WS2's Referee and Ops Service and WS1's CI-to-GHCR work; WS5 shows live stages. **G3** is the two clean-lab, fully verified T-01 runs and visible denials. For WS4 specifically, deliver (a) pinned Foundry Planner and Engineer, (b) validated real MCP outputs, (c) working runner code/tests and deployable image, (d) frozen handoffs + evidence of separate smoke tests. Do not label a stubbed `VERIFIED` as an Azure verification.

### WS4's boundaries

- **WS4 owns:** `src/drill-runner/`, `agents/*.yaml`, `agents/*.md`, `contracts/`, `scripts/create_agents.py`, `scripts/agent-smoke.py`, `infra/modules/foundry.bicep`, `infra/modules/drill-runner.bicep`, WS4 CI and evals.
- **WS3 owns:** MCP server, `/planner/mcp` + `/engineer/mcp`, connection keys, real evidence backends, GitHub branch-limited write tools.
- **WS2 owns:** Ops Service `/actions/<name>`, referee, Key Vault fault/restore, lab bootstrap, Bicep deployment root.
- **WS1 owns:** order-service code repository, candidate branch CI, tested order-service images and protected golden journey.
- **WS5 owns:** Control Center and its `approval.decided` / `kill.requested` events and display.

**Repository warning:** WS4 code is delivered to `livefire-team/ws4-new`, but **runtime** `GITHUB_REPO` MUST point to `livefire-team/livefire-fusion-poc` (the WS1 order-service repository). Do not set `GITHUB_REPO=livefire-team/ws4-new` for the Engineer or candidate CI.

## B. Day-by-day critical path (Nov 5–9)

1. **Thu Nov 5:** Baseline audit, offline tests, WS1 image-tag decision, WS3 endpoint/key handoff, WS2 Foundry/Control RG outputs, repo write access.
2. **Fri Nov 6:** Lab Azure identity/model probe, deploy Foundry module and separate MCP connections; create both versioned agents from YAML; verify pinned versions.
3. **Sat Nov 7:** Live Planner smoke (options + brief), review evidence/citations, inspect MCP calls and test cross-role denial. Engineer smoke **only after WS1 authorizes a disposable candidate branch**.
4. **Sun Nov 8:** Integration regression tests and fixes; runner Docker build and Actions run; Blob/WS5 event sharing, inspect evidence package locally; document blockers and reviewer sign-off.
5. **Mon Nov 9:** Re-run tests and live agent smokes; archive sanitized proof, produce G2 pass/fail matrix, submit branch/PR to WS4. Do not quietly mark unperformed Azure checks passed.

## C. Prerequisites and safety (execute in order)

**Step 01 — Confirm the right destination and authorization.** Open `https://github.com/livefire-team/ws4-new` while signed in to GitHub. Confirm you can create a branch in this org repo (public visibility does **not** imply write access). If you see a 404, check org membership/repo URL with owner. Do not fork unless the team explicitly requests it.

**Step 02 — Obtain the missing handoffs.** Ask WS2 for CloudLabs duration, Azure subscription/tenant/region, control resource group, Key Vault name, evidence Blob URL/container, Foundry creation rights, Ops URL/status, referee status; WS3 for MCP URL, endpoint host allowlist, separate Planner/Engineer connection existence and key readiness; WS1 for candidate-branch ruleset, CI and GHCR image format; WS5 for the event-store source and test URL. Record owners in `docs/G2-ACCEPTANCE-MATRIX.md`.

**Step 03 — Start from the WS4 project root.** The root is the folder containing `README-WS4.md`, `scripts/`, `contracts/`, `src/drill-runner/` and `infra/`. Do not copy WS1/WS2 files wholesale into `ws4-new`; their current copies are separate projects and may conflict. Do not upload evidence files, access tokens, PEMs, `azd` settings, or `.env`.

**Step 04 — Choose the shell.** Windows: VS Code **Terminal > New Terminal > PowerShell**. CloudLabs: Bash terminal. PowerShell snippets below assume you are in the root. Where a Bash equivalent is provided, run it in CloudLabs instead.

**Step 05 — Inspect your local tools (Windows PowerShell).**

```powershell
Get-Location
git --version
py -3.12 --version
az version
azd version
az bicep version
```

If `py -3.12` fails, use the lab's Python 3.12 or an existing approved `.venv` Python. No administrator access is required if the environment already provides Python. Do not install Azure tools to a locked-down company laptop without approval.

**Step 06 — Create a disposable local Python environment (PowerShell).**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src\drill-runner\requirements-dev.txt
.\.venv\Scripts\python.exe --version
```

Bash alternative:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r src/drill-runner/requirements-dev.txt
```

Expected: packages install; `agent-framework-core`, `azure-ai-projects`, `openai`, `pydantic` resolve. If dependency resolution fails, capture a sanitized error and tell WS4. Avoid changing pinned versions without team approval.

**Step 07 — Run the static G2 preflight.**

```powershell
.\.venv\Scripts\python.exe scripts\g2-preflight.py --repo-root .
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_g2_preflight.py -v
```

Expected: mandatory starter files and agent definitions are present. This preflight is **not** a live Azure test. Optional cross-repo consistency: pass `--ws1-root <path-to-extracted-livefire-fusion-poc-main>` to identify the known SHA-image-tag mismatch.

**Step 08 — Run all original WS4 offline tests.**

```powershell
Push-Location src\drill-runner
..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

Expected from the **starter's prior report**: 33 passing tests; your own result is authoritative. Tests cover contracts, policy, workflow, kill switch, budgets, evidence integrity and T-00 through T-10. If an Azure package is unavailable, do not describe that as a test failure in code.

**Step 09 — Reproduce a local supervised T-01 drill (stubs).**

```powershell
$env:EVENT_SOURCE = "dir:$((Get-Location).Path)\evidence"
Push-Location src\drill-runner
..\..\.venv\Scripts\python.exe -m livefire.runner --drill-id drill-g2-stub-001 --scenario T-01 --stub --stub-delay 0 --auto-approve broad,narrow,deploy,open_pr
Pop-Location
.\.venv\Scripts\python.exe scripts\verify_package.py evidence\drill-g2-stub-001
```

Use a **new** `drill-...` ID each time; duplicate drill IDs are refused to protect event evidence. Expected: `VERIFIED` and successful evidence validation **on stubs only**. `evidence/` is gitignored and must not be published if sensitive.

**Step 10 — Inspect the generated event contract and sealed package.**

```powershell
Get-Content evidence\drill-g2-stub-001\events.jsonl | Select-String 'planner.options|planner.brief|engineer.change_report|ci.result|verdict|approval'
Get-Content evidence\drill-g2-stub-001\package.json | Select-Object -First 30
```

Confirm structured events have `ts`, `drill_id`, `action`, `result`, `details`; `package.json` contains version, six verdict inputs, agent pins and a SHA-256 of the event log as sealed. **Never edit the sealed files.**

**Step 11 — Verify frozen contract schemas without changing interfaces.**

```powershell
.\.venv\Scripts\python.exe scripts\export_schemas.py
.\.venv\Scripts\python.exe -m pytest -q src\drill-runner\tests\test_contracts.py
```

Run `git diff -- contracts` afterwards. If the generated schemas differ, stop and request lead approval; `CONTRACT_VERSION=1.0` is frozen at G1. Send the changed schema/version to WS2, WS3 and WS5 before any merge.

## D. Azure/Foundry deployment (CloudLabs, authorized resource group only)

**Step 12 — Begin a new CloudLabs lab with enough remaining time.** CloudLabs labs are disposable. Verify the Azure subscription, tenant, role and region with `az account show`; do not run production resource changes outside the authorized lab.

```bash
az login                 # only if your lab is not already logged in
az account show --query '{subscription:id,tenant:tenantId,user:user.name}' -o json
az group list --query '[].{name:name,location:location}' -o table
```

Do not paste secret values, full `azd env get-values`, or access tokens into the team chat.

**Step 13 — Confirm the day-1 Azure probe results with WS2.** Determine (a) GPT-5.x availability/version/quota; (b) whether role assignments and Foundry project creation are allowed; (c) Key Vault RBAC **Path A** versus access policy **Path B**; (d) access to the control Key Vault, control Container Apps environment and evidence Blob. Do not claim a specific model version is available until the probe verifies it.

**Step 14 — Check WS3 MCP is running.** Obtain `MCP_URL` in `https://...` form and confirm `GET $MCP_URL/health` returns an expected service status. WS3 must configure `MCP_ALLOWED_HOSTS` for its actual Container Apps hostname, and two distinct endpoint keys in the control Key Vault. The Planner connection must not use the Engineer key.

```bash
curl -fsS "$MCP_URL/health"
```

Do not print/copy endpoint keys into evidence or repository files. WS3's `/planner/mcp` and `/engineer/mcp` require bearer authentication; this is **not** the same credential as the runner's Ops key.

**Step 15 — Validate WS4 Bicep modules independently.** These commands check syntax only; they do not deploy resources.

```bash
az bicep build --file infra/modules/foundry.bicep --stdout > /dev/null
az bicep build --file infra/modules/drill-runner.bicep --stdout > /dev/null
```

WS4 supplies `infra/main.ws4-snippet.bicep` to WS2's root `infra/main.bicep`. **Do not** deploy the snippet by itself. Confirm symbols for `controlRg`, `controlKeyVaultName`, `principalId`, `principalType`, `control.outputs.environmentId`, `control.outputs.evidenceAccountName`, `mcp.outputs.mcpUrl`, and WS2 Ops URL are actually present in the consolidated root.

**Step 16 — Deploy Foundry through WS2's agreed infrastructure root.** Use WS2's `azd provision` / documented bootstrap after the root imports WS3 and WS4 modules; set the model name, exact version and capacity from the lab probe. The Foundry Bicep builds one AI Services resource, one `proj-livefire` project, a version-pinned model and **two** MCP connections (`livefire-planner-mcp`, `livefire-engineer-mcp`). Check the resulting `FOUNDRY_PROJECT_ENDPOINT` and `MODEL_DEPLOYMENT` outputs. If Foundry or model quota is blocked, capture the denied operation and stop the live-agent track; proceed with offline G2 proof and mark Azure blocked.

**Step 17 — Confirm identity access.** The principal running `scripts/create_agents.py` needs Azure AI User rights on the Foundry project. The eventual runner's managed identity needs scoped access to Foundry, the evidence Blob and its dedicated control Key Vault secrets. Follow least privilege; never grant Owner/Contributor to an agent to get around a 403.

**Step 18 — Set **non-secret** configuration for the agent creator.** Bash example (fill in the lab's actual values; do not commit or paste them):

```bash
export FOUNDRY_PROJECT_ENDPOINT='https://<your-foundry>.services.ai.azure.com/api/projects/proj-livefire'
export MODEL_DEPLOYMENT='<actual-deployment-name>'
export MCP_URL='https://<actual-ws3-mcp-host>'
```

PowerShell equivalent:

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = 'https://<your-foundry>.services.ai.azure.com/api/projects/proj-livefire'
$env:MODEL_DEPLOYMENT = '<actual-deployment-name>'
$env:MCP_URL = 'https://<actual-ws3-mcp-host>'
```

**Step 19 — Validate agent definitions without live writes.** From the **WS4 root**:

```bash
python scripts/create_agents.py --dry-run
```

Expected: JSON definition of each agent, each with only its own MCP tools. Look for Planner's six read-only tools and Engineer's six restricted branch-writing tools. Output is generated for inspection; dry-run does **not** authenticate to Azure.

**Step 20 — Create pinned agent versions in the authorized Foundry project.** **This is a live Azure write**; perform only after checking project and role scope.

```bash
python scripts/create_agents.py
```

Record two printed values of the form `PLANNER_AGENT=lf-planner:<version>` and `ENGINEER_AGENT=lf-engineer:<version>` (version labels are examples). Export them for subsequent steps. Never edit agent prompts manually in the portal; change `agents/*.yaml`/`.md` in WS4 and create a new version.

**Step 21 — Verify exactly what you deployed.**

```bash
export PLANNER_AGENT='lf-planner:<actual-version>'
export ENGINEER_AGENT='lf-engineer:<actual-version>'
python scripts/create_agents.py --verify "$PLANNER_AGENT" "$ENGINEER_AGENT"
```

Expected checks for each pin: instruction SHA matches repository text, one tool connection only, exact allowed tool list, approval mode and deployment model. Any mismatch means stop, repair or repin; don't continue with an unreviewed version.

## E. Independent live-agent tests (core of WS4 G2)

**Step 22 — Smoke-test the Planner alone before allowing writes.** WS3 should have its Azure backend or explicitly labeled fixture-backed lab endpoint running; the former proves **real evidence**, the latter proves only connectivity.

```bash
python scripts/agent-smoke.py drill-g2-planner-001
```

Expected: first call yields `PlannerOutput(stage=options)` with `RecoveryOptions`, second yields `PlannerOutput(stage=brief)` with `RemediationBrief`; `check_options`, `check_brief`, `check_secrets` show `ok` and real MCP tool-call evidence is traceable by drill ID. Inspect actual output rather than assuming the command exits nonzero for bad checks (see Step 23).

**Step 23 — Manually review Planner acceptance gates.** Confirm a narrow `restore_kv_secrets_user` option, a broad `grant_contributor_subscription` option if offered, evidence references to **real** WS3 sources, no secret values, high-enough confidence, two or more brief evidence refs, allowed paths only, and the pinned `drill_id`. A successful HTTP call alone **does not** meet G2. Check actual Foundry trace and `planner.tool_call` events, not merely the model's claims.

**Step 24 — Confirm the MCP boundary denial without model prompting.** Ask WS3 to run its scripted cross-role test (`scripts/mcp-smoke.py`) or use a controlled request with the Planner key against `/engineer/mcp`; expected **HTTP 403** and an `engineer.tool_call`/`planner.tool_call` deny event recorded for the valid drill ID. Do **not** copy keys into screenshots or logs. T-03 must be a server-side denial.

**Step 25 — Get explicit WS1 approval for a disposable Engineer smoke branch.** The supplied `scripts/agent-smoke.py --engineer` is **NOT read-only**: it can create `candidate/<drill-id>-1` and commit code/test/runbook changes through WS3. Ensure the target is `livefire-team/livefire-fusion-poc`, branch ruleset allows WS3's Engineer GitHub App (without broad permissions), the baseline `main` commit is pinned and WS1 agrees to the test. Use a unique, short, lowercase drill ID such as `drill-g2eng-001` so WS1 candidate branch regex accepts it. **Do not run this against `ws4-new`.**

**Step 26 — Run the Engineer once only with authorization.**

```bash
# ONLY after WS1 grants approval and WS3 is using its real GitHub backend:
python scripts/agent-smoke.py drill-g2eng-001 --engineer
```

Expected: candidate branch `candidate/drill-g2eng-001-1`; valid `ChangeReport`, at most 3 changed paths within the allowlist, a bounded fix under `secret_provider.py`, a regression test, and an updated runbook. Ensure **no modification** to `journeys/`, `.github/`, `infra/`, `main` or another branch. The Engineer must not merge or deploy.

**Step 27 — Validate real candidate CI and do not confuse statuses.** On the **WS1 repository**, check the candidate branch's `order-service.yml` workflow for tests, security checks and GHCR publishing. Confirm the run's commit SHA, the built image tag, permissions and any failed steps. If the image isn't published or the workflow isn't green, the candidate is **not ready for G3 deployment**, even if the model returned a valid `ChangeReport`.

**Step 28 — Resolve the image-tag contract before G3.** The uploaded WS1 workflow publishes `ghcr.io/livefire-team/order-service:sha-<7-character SHA>`; the WS4 `Ci` stage currently constructs `:sha-<full 40-character SHA>` and the WS4 Ops-action contract says `:sha-<40 hex>`. **This is an actual cross-workstream mismatch in the uploaded files.** Preferred approach: have WS1 also publish an immutable full-40-character `sha-` tag while retaining short tags, then WS2 deploy the full tag. Alternatively WS4+WS2 can agree on short tags and formally revise/approve the frozen contract. **Do not silently rewrite a G1 contract or mark this resolved without the WS1 and WS2 owners.**

**Step 29 — Clean up the Engineer smoke safely.** Keep evidence/links and inform WS1 of the created branch. After owner approval, remove only the disposable `candidate/drill-g2eng-001-1` branch via the appropriate GitHub branch management flow; do not delete team branches, Git history or protected files. If that branch carries useful work, leave it for an explicit code review.

## F. Runner, CI, Ops and WS5 seams

**Step 30 — Validate real adapters locally as far as possible.** Inspect `livefire/ports.py` (`HttpOps`, `GitHubRepo`), `livefire/agents.py` (`FoundryAgents`) and `livefire/events.py` (dir/Blob store). The workflow's `--stub` route bypasses these; passing only stub tests proves logic, not credentials, network or Azure. Run the smoke checks individually before attempting live orchestration.

**Step 31 — Validate Azure Ops contract with WS2 (do not inject faults yet).** Confirm `OPS_URL` is an internal-only Container App accessible **from the runner's Container Apps environment**, and the runner identity can read its `ops-runner-key` from control Key Vault. WS2 actions: `reset_twin`, `run_referee`, `inject_fault`, `wait_for`, `restore_access`, `attempt_broad_recovery`, `deploy_revision`, `kill`. Each request includes `drill_id`; verify `OpsResult` schema and event names with WS2. A reachable `/health` endpoint is not the same as authorization to issue fault commands. Never call `inject_fault` without lab coordination.

**Step 32 — Review controls before any live drill.** Confirm Supervised is default, Advisory blocks execution, Autonomous Twin only executes preauthorized twin-scoped actions, max **2 candidate attempts**, token and tool-call budgets, stage timeouts, deterministic six-factor verdict and kill/reset. Prohibit agent-originated merges and edits to golden `journeys/`.

**Step 33 — Confirm shared evidence store with WS5.** Choose a single `EVENT_SOURCE`: `dir:<common-directory>` for local integration or `blob:<account-blob-url>/<container>` for Azure. WS4 and WS5 **must** use the same store and drill ID; the Control Center reads `events.jsonl` and writes only `approval.decided` and `kill.requested`. Confirm `package.json` remains beside the event log for WS5 evidence viewing. Check that timestamps are ISO UTC and events contain all five required fields.

**Step 34 — Run a staged WS5 demonstration without Azure if blocked.** Start the WS5 UI against the same local `evidence` folder as WS4 stubs; run a fresh stub drill with a nonzero `--stub-delay`. Verify timeline, the broad denial, approval buttons and the final package. Label it **stubbed integration**, not a live Foundry or real Azure demo. If WS5 deployment is ready, repeat against the shared Blob and review approval/kill behavior.

**Step 35 — Build the WS4 runner image.** On a host with a working Docker engine:

```bash
docker build -t drill-runner:g2-local src/drill-runner
```

Expected: the image builds from `src/drill-runner/Dockerfile` with pinned runtime dependencies. G2 only requires that the container is buildable; do not publish credentials or evidence directories in an image.

**Step 36 — Test CI in `ws4-new`.** The included `.github/workflows/drill-runner.yml` runs tests and agent definition dry-run on PR, then builds/pushes `ghcr.io/livefire-team/drill-runner:sha-<commit>` on `main`. Check Actions permissions `contents:read`, `packages:write`, GHCR package visibility and status. **Pushing the code to GitHub does not by itself mean the workflow passed.** Review the Actions run after publication.

**Step 37 — Integrate runner Bicep only after WS2's control outputs stabilize.** `drill-runner.bicep` creates `id-lf-drill-runner`, scoped Azure AI/Blob/Key Vault access, a manual Container Apps Job with no ingress, and environment variables for Foundry, Ops, repo and shared events. Confirm secrets exist in Key Vault, image tag is immutable/pullable, service-identity access works and Bicep root parameters match. The actual Azure job execution is a G3 preparation step if WS2 Ops isn't ready by G2.

**Step 38 — Check startup expectations before running a live job.** The current Dockerfile/runner reads a drill ID from the command line or `DRILL_ID`; ensure the job start supplies it. Validate the full command with WS2 and the job's revision/environment; do not launch a job that immediately fails because `DRILL_ID` is missing. Use a unique drill ID per execution and check job logs for the actual terminal state.

**Step 39 — Prove evidence integrity.** Verify each local completed drill's sealed package with `scripts/verify_package.py`, then visually check its six boolean verdict inputs (authorization, policy, technical health, CI, journey, saved order/payment). G2 acceptance may be agent-level evidence without a full VERIFIED drill; do not forge package entries to satisfy a gate.

**Step 40 — Review the evaluation set.** Inspect `src/drill-runner/evals/rubric.yaml` and `evals/score.py`. The ten-run scoring criteria belong closer to **code freeze**, not this G2 deadline; record the evaluation design and run the cases possible locally. Check prompt-injection scenario T-08, hard budget T-07 and kill switch T-09 in stubs; obtain live results only when the dependencies are present.

## G. G2 demonstration, documentation and submission

**Step 41 — Write a concise proof record.** For each check, record UTC time, environment (offline fixture/lab), command, redacted output path, observed result, Git commit/image/agent version, owner and PASS/FAIL/BLOCKED. Do not attach secret-bearing logs. Use `docs/G2-ACCEPTANCE-MATRIX.md`.

**Step 42 — Capture separate live-agent evidence.** Save sanitized outputs for `create_agents.py --verify`, Planner options+brief, Foundry/MCP trace identifiers, the cross-role 403, and (if authorized) Engineer candidate branch / CI URL. This matters more at G2 than a combined workflow video.

**Step 43 — Send workstream handoffs.** Use `docs/G2-HANDOFFS.md`: WS1 gets the candidate SHA-tag mismatch and branch permissions requirement; WS2 gets Foundry/runner module parameters and Ops contract questions; WS3 gets endpoint/tool/connection requirements; WS5 gets the event source, pinned agents, events and approval semantics. Obtain acknowledgement.

**Step 44 — Review the repository changes.** From a local clone of **`ws4-new`**, not the WS1 repo:

```powershell
git status --short
git diff --check
git branch --show-current
git remote -v
```

Expected: the remote is `https://github.com/livefire-team/ws4-new.git`, not `livefire-fusion-poc` or a fork. Review all changed files; `.venv/`, `.env`, keys and `evidence/` should never be staged.

**Step 45 — Create a G2 feature branch, not a direct `main` write.**

```powershell
git switch -c docs/ws4-g2-2026-11-09
git add README-WS4.md .gitignore docs scripts/g2-preflight.py tests/test_g2_preflight.py
git diff --cached --stat
git diff --cached --check
git commit -m "docs(ws4): add G2 build and verification pack"
git push -u origin docs/ws4-g2-2026-11-09
```

If this is a **fresh repo** with no starter files, copy the staged WS4 bundle into the clone first, then `git add` the WS4-owned files (excluding credentials/evidence), inspect the staged changes, and commit. If branch exists choose another name. Open a PR to `main` and obtain reviewer/CI approvals. Do not force push to main or bypass branch protection.

**Step 46 — GitHub Desktop alternative (no fork).** File > Clone repository > URL `https://github.com/livefire-team/ws4-new.git` > choose local folder. Copy the prepared bundle's contents into that cloned folder **without overwriting changed team files**. In GitHub Desktop review **Changes** for secret files, set Current Branch > New Branch to `docs/ws4-g2-2026-11-09`, enter commit message, **Commit to branch**, **Publish branch** and **Create Pull Request**. If Publish fails, ask the organization owner to grant **Write** access; public read access is insufficient.

**Step 47 — Final G2 verification (Nov 9).** Re-run offline tests, local package verification, scripts preflight; then rerun available live agent smokes and check actual traces. Validate version pins and CI. Mark each line of the acceptance matrix PASS / FAIL / BLOCKED / NOT RUN with truthful evidence. Require reviewer sign-off before calling WS4 G2 complete.

**Step 48 — Prepare the G3 handoff.** Record live Ops Job start configuration, the exact candidate image-tag resolution, WS2's final Ops URL, WS3's final repo/auth bindings, WS5's live Blob event consumption and any unverified foundry API/schema behavior. G3 is not part of the G2 PASS claim.

## H. Fast troubleshooting

| Symptom | Likely cause | Recovery |
|---|---|---|
| `py -3.12` not found | Python only in existing lab/venv | Use lab Python 3.12 or `\.venv\Scripts\python.exe` |
| `ModuleNotFoundError: agent_framework` | Requirements not installed in active interpreter | Install `requirements-dev.txt` with the exact Python used for tests |
| `403` creating Foundry agent | Wrong project/role/tenant | Verify project scope and Azure AI User role with WS2, not with a broad new role |
| `404` or 401 on MCP call | Incorrect hostname/path/key or Foundry connection | Validate WS3 hostname allowlist and each project's connection; don't log token |
| Planner returns bad JSON | Strict schema mismatches or agent output issue | Inspect response/validation errors; create and pin a new agent version after changes |
| Engineer created no candidate | WS3 fixture backend / GitHub App restrictions | Confirm real backend, target **WS1 repo**, candidate ruleset and App permissions |
| CI green but image not found | **7 vs 40 character SHA tag mismatch** | Agree cross-team contract fix before deployment |
| `OPS_URL` unavailable | WS2 Ops service not yet built/routable | Mark live job blocked; continue agent-level G2 |
| `DRILL_ID` required | Job started without per-run ID | Supply a valid, new `drill-...` ID |
| Control Center shows no live events | WS4/WS5 point to different folder/container | Align `EVENT_SOURCE` and permissions; verify same `drill_id` |
| `VERIFIED` from stubs | Real dependencies not exercised | Label result **offline only**; require live independent smokes for G2 |
| GitHub Desktop asks to fork | No Write permission for org repository | Request org/repo Write access; don't fork without team approval |

## I. Definitive G2 acceptance criteria

1. **All offline WS4 tests pass** against the delivered commit and Python 3.12.
2. **Schemas remain frozen at v1.0** or changes have lead-approved version bumps and updated downstream teams.
3. **Foundry project and model actually deployed** to CloudLabs, or documented **BLOCKED** with exact Azure response.
4. **Pinned Planner and Engineer created and verified** against YAML, or documented BLOCKED.
5. **Planner calls real WS3 MCP endpoint** and outputs checked options+brief with evidence; fixture-only is separate and insufficient for real-evidence acceptance.
6. **Engineer calls real WS3 engineer endpoint on an authorized candidate branch** and yields valid ChangeReport, or is explicitly BLOCKED pending WS1 permissions.
7. **Cross-role denial** is enforced by WS3 and recorded (403, no cross-role write).
8. **Runner Docker build and WS4 Actions** are green on the actual branch/commit, or marked NOT RUN/BLOCKED.
9. **WS2/WS5 interfaces are acknowledged:** OpsAction shape, shared evidence source, approval/kill events, no model-computed verdict.
10. **Known mismatches documented and owned:** candidate image SHA tag, WS2 Ops availability, agent and MCP connector compatibility, job drill-id start; no false PASS.

## J. Source and verification provenance

- Uploaded **`LiveFire_Fusion_PoC_Implementation_Plan.md`**, Oct 20 2026: G2 scope, five-workstream roles, architecture, six-factor verdict, allowed tool catalogs, governance and time-bound CloudLabs.
- Uploaded **`livefire-ws4-starter-v2 1.zip`**: contracts v1.0, Python runner, Azure Bicep, agent YAML/prompts, tests, stubs and scripts. Starter README reports **33 passing tests in its original author's Oct 23 environment** (not the present Azure environment).
- Uploaded **`livefire-fusion-poc-main.zip`**: WS1/WS2 status as of Oct 31 2026, candidate branch GitHub Actions, short Git commit image tags, WS2 referee and lab integration scripts.
- Uploaded **`livefire-ws3-starter(2).zip`**: WS3 read-only Planner endpoint, restricted Engineer endpoint, MCP keys, fixtures/real backends and cross-role-denial smoke.
- Uploaded **`livefire-ws5-starter-v2 1.zip`** and **`WS5--main.zip`**: Control Center event contract, approvals, kill switch and real-vs-stub integration instructions.
- **Not provided in current uploads:** `mdfiles.zip` (G1 build-step compilation) and a separately named `ws3-mcp-server-main.zip`. These guides are based on the available starter/readme/repo snapshots; reconcile with any newer committed changes before deployment.

**Important integrity rule:** Every PASS recorded below should come from an observed command/run in your actual lab or local environment. Planned work, checked-in code and mock results are never substituted for successful independent live-agent runs.
