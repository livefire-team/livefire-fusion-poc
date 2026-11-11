# WS4 G2 cross-workstream handoffs

**Due:** 2026-11-09. **WS4 repository:** `livefire-team/ws4-new`. **Engineer target repository:** `livefire-team/livefire-fusion-poc`.

## H1 — To WS1 (Twin and order service)

- **Urgent contract conflict:** your uploaded `.github/workflows/order-service.yml` publishes `:sha-${GITHUB_SHA::7}`; WS4 `livefire/workflow.py` creates `ghcr.io/<owner>/order-service:sha-<full-40-character commit>` and `contracts/ops-actions.md` requires a 40-hex SHA tag. Preferred: publish both full-sha and short-sha tags, with deploy using full-sha, subject to WS1/WS2 sign-off. Do **not** silently change the frozen v1.0 Ops contract.
- Confirm `candidate/<drill-id>-<attempt>` branch ruleset allows the **WS3 Engineer GitHub credential** with branch-scoped Contents write, Actions read; protect `main`, `journeys/`, `.github/` and `infra/`.
- Your candidate-branch regex caps the `<drill-id>` portion at 48 characters; the WS4 frozen drill ID contract permits longer IDs. For G2 use a short ID `drill-g2eng-001` and decide whether to align regex before G3.
- Provide baseline `main` commit SHA, candidate CI URL, image digest and pullability. WS4 does not control WS1's branch permissions or GHCR publishing.

## H2 — To WS2 (Ops, referee and CloudLabs bootstrap)

- Give WS4: lab subscription/tenant/region, RBAC Path A/Path B probe result, final control resource group/Key Vault name, `control.outputs.environmentId`, `control.outputs.evidenceAccountName`, Ops URL and service status, and model/quota availability.
- Integrate `infra/main.ws4-snippet.bicep` into your actual `infra/main.bicep` **after** WS3 modules, resolving all output and variable names; do not deploy the snippet standalone. Validate `foundry.bicep` and `drill-runner.bicep` modules together.
- Ops routes must be `POST /actions/<action>` with `Authorization: Bearer <ops-runner-key>` and JSON including `drill_id`. Allowed actions listed in `contracts/ops-actions.md`.
- Confirm the runtime manual Job execution passes a new `DRILL_ID`; the Docker runner requires it. Confirm internal connectivity to `OPS_URL` and Blob from the job.
- Coordinate narrow restore and broad-denial tests; do not inject a fault without lab authorization.
- Confirm `deploy_revision` expected tag syntax (full 40-character SHA) aligns with WS1 GHCR and WS4 image value.

## H3 — To WS3 (MCP and evidence)

- Supply MCP base URL with TLS/public ingress, `MCP_ALLOWED_HOSTS` configured, and two **different** endpoint keys stored in control Key Vault (not pasted into a repo).
- Define two Foundry connections exactly `livefire-planner-mcp` -> `/planner/mcp` and `livefire-engineer-mcp` -> `/engineer/mcp`. Confirm Azure client/tool compatibility in the lab, not just fixture tests.
- Planner must offer exactly six read-only tools: `query_incident_telemetry`, `get_identity_snapshot`, `search_incident_history`, `read_runbook`, `read_repository_context`, `get_commit_history`.
- Engineer must offer exactly six restricted tools: `read_allowed_files`, `create_candidate_branch`, `apply_patch`, `write_regression_test`, `update_runbook`, `get_ci_results`.
- Test wrong-role token on Engineer endpoint -> 403 + audit event; return redacted tool data without secret values.
- Real GitHub backend must target **WS1** repo `livefire-team/livefire-fusion-poc`, not `ws4-new`. Confirm candidate branch permission before Engineer smoke.
- Compare WS3 `guard.py` protected paths and write allowlists with WS4 `livefire/contracts.py`; any material change requires WS4 lead version decision.

## H4 — To WS5 (Control Center)

- Event source is shared (`EVENT_SOURCE=dir:<folder>` locally or `EVENT_SOURCE=blob:<account-url>/<container>` in Azure); same drill ID for events, approvals and kill.
- WS4 events follow `ts`, `drill_id`, `action`, `result`, `details`, in `events.jsonl`; `package.json` is immutable after sealing. WS5 writes only `approval.decided` and `kill.requested`.
- Acceptance UI uses `approval.requested` with `apr-N` request IDs and the pending choice options; the human's choice must match a currently offered option, not a cached/past card.
- Distinguish *offline stub* demonstration from *live Foundry/MCP* results on the screen and in narrative. Screen showing `VERIFIED` on stubs does not prove actual Azure recovery.
- Confirm Control Center's new WS5 repo snapshot matches the canonical `Event` schema and that the login, anti-CSRF and approval buttons work.

## H5 — To WS4 reviewer / team lead

- Keep `CONTRACT_VERSION=1.0` until all affected workstreams approve a bump. All outputs must pass Pydantic validation and confidential tool data must be redacted.
- Keep deterministic `compute_verdict` the **only** verifier. Preserve max two candidate attempts, token/tool/time budgets, kill + reset, pinned golden journey, and unmerged PR for human review.
- Record independent Planner and Engineer smoke trace IDs, safe candidate branch and PR/CI URL, model deployment, agent pins, Event store, redacted logs and clear PASS/BLOCKED outcomes.

## Questions requiring owners' answers

1. WS2: Is the live Ops Service implemented and deployed, or is WS4 G2 to finish with independent agents only?
2. WS3: What is the live `MCP_URL`, are the Foundry connections ready, and can the real Engineer GitHub backend write *only* `candidate/**` on WS1?
3. WS1+WS2: Will WS1 publish full SHA GHCR tags to satisfy the frozen Ops deployment contract?
4. WS2: Which Foundry model, version, capacity, region and lab resource group actually passed the probe?
5. WS4 repo admin: Does this contributor have Write access to `livefire-team/ws4-new` and permission to open a G2 PR?
