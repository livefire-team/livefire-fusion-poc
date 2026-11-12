# Lead decisions

Gate decisions the team lead records (WS4 build steps, section 5). Architectural decisions stay in `ADR.md`.
An entry marked **Proposed** is a draft for the lead: the lead confirms it by changing it to **Decided**, with the date.

## D-001: WS4 uses the prompt-agent fallback for G2 and G3, not hosted agents

- **Status:** Proposed (drafted 2026-11-12 for the lead; WS4 build steps 5A/5B, blueprint 9.4)
- **Blocking reason for the target (5A):** hosted agents with their own Entra Agent IDs and Toolboxes are not built
  or proven in Foundry, and the Foundry commands for them must still be verified against current Microsoft docs.
  The G2 date has passed and code freeze is Nov 13.
- **Fallback in use (5B):** two Foundry prompt agents (`lf-planner`, `lf-engineer`), each with one direct `MCPTool`
  through its own project connection, which holds only that endpoint's key (WS3 key mode, ca-mcp contract v2.4).
  The tool contract, the tool lists, the output schemas and every workflow gate are identical to the target.
- **What it costs:** prompt agents in one project share one identity, so roles are separated by the per-endpoint keys
  (a Planner key gets 403 on `/engineer/mcp`, T-03), not by Entra. Anyone with access to the project can read the
  keys in its connections: keep project access to the team, and rotate both MCP keys after the demo.
- **Evidence to fill in after deployment:** agent pins from `scripts/deploy.sh agents`; `create_agents.py --verify`
  output; `scripts/agent-smoke.py` output with a tool call from each agent; WS3's T-03 drill
  (`drill-g3-check-1111`, cross-role 403 and deny event).

## D-002: `id-lf-drill-runner` holds four roles, not six

- **Status:** Proposed (drafted 2026-11-12)
- **Context:** the G2 checklist's "exactly six" counts two roles for the v1.2 learning loop (Search Index Data
  Contributor on the search service, Cognitive Services OpenAI User on the Foundry resource), which writes each
  drill's finding into the incident index. The learning loop is not part of this build.
- **Decision proposed:** four roles: Azure AI User on the project, Storage Blob Data Contributor on the evidence
  container, and Key Vault Secrets User on `ops-runner-key` and on the runner's GitHub secret. Nothing on the twin.
  The image pull uses the shared `id-lf-acrpull`. Adding the learning loop later adds the two roles with it.

## D-003: The broad option is refused by Azure RBAC until the deny policy is on

- **Status:** Proposed (drafted 2026-11-12); owner WS2
- **Context:** the subscription-wide deny policy is off in `lf-eh` (since 2026-11-08). The Ops Service then reports
  the broad attempt as `denied` with `AuthorizationFailed` (refused by Azure RBAC), the labelled fallback, instead of
  `RequestDisallowedByPolicy`.
- **To close it:** WS2 runs `scripts/deploy.sh policy` before the T-02 evidence run and the demo.
