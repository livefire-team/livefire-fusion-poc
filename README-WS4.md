# WS4 starter files, v2 (LiveFire Fusion: agents, workflow and contracts)

Follow "WS4 Build Steps" for what to run and where.

Changed since v1 (Oct 23): infra/main.ws4.bicep is replaced by infra/main.ws4-snippet.bicep, the lines to paste
into main.bicep. It now passes the runner's GitHub App IDs and principalType, reuses WS3's githubRepo
parameter, and outputs RUNNER_PRINCIPAL_ID. It compiles with no warnings together with WS2's main.bicep, the WS3
and WS5 snippets and a stand-in for WS2's G2 control.bicep outputs. Everything else is unchanged.

Files from the "WS4 Build Guide", as tested on Oct 23 2026:
- src/drill-runner: 33 tests pass (contracts, policy, and the Agent Framework workflow on stubs, T-00 to T-10).
- Every scenario reaches its expected terminal state from the command line (--stub --auto-approve).
- A stubbed drill reached VERIFIED in WS5's real Control Center, with all four decisions clicked in Chromium.
- scripts/create_agents.py --dry-run builds both Foundry agent definitions.
- infra/modules/foundry.bicep and drill-runner.bicep compile with no lint warnings.
- handoffs/ws5-csrf-first-visit.patch fixes a Control Center first-visit CSRF bug; WS5's 12 tests still pass.
Not yet verified (needs Azure): Foundry calls and strict-schema acceptance, the MCP connection type, the
Container Apps Job, WS2's Ops Service (not built yet), live GitHub calls, the Docker build.

Run locally, all stubs:
  cd src/drill-runner && pip install -r requirements-dev.txt && pytest -q
  EVENT_SOURCE=dir:../../evidence python -m livefire.runner --drill-id drill-g1-demo --stub --stub-delay 1

## G2 work package (due 2026-11-09)

- **Start here:** [`docs/WS4-G2-BUILD-STEPS.md`](docs/WS4-G2-BUILD-STEPS.md) — numbered build, Azure, independent-agent and GitHub publication steps.
- [`docs/G2-ACCEPTANCE-MATRIX.md`](docs/G2-ACCEPTANCE-MATRIX.md) — truthful live/offline test evidence and sign-off.
- [`docs/G2-HANDOFFS.md`](docs/G2-HANDOFFS.md) — four-team integration handoffs and urgent candidate-image SHA mismatch.
- [`scripts/g2-preflight.py`](scripts/g2-preflight.py) — standard-library static readiness check (no Azure calls, no credentials printed).
- [`.env.g2.example`](.env.g2.example) — placeholders only; do not commit real env files.
- [`docs/G2-RELEASE-NOTES.md`](docs/G2-RELEASE-NOTES.md) — changes, checks, blockers and publishing status.

The G2 package does not claim live Foundry/CloudLabs completion. The CI and live agent smoke must be executed with the real team credentials and real Azure resources, and evidence recorded in the matrix.
