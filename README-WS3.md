# WS3: MCP server and evidence corpus

Workstream 3 of LiveFire Fusion. It gives the drill's three AI agents their tools, and nothing else:

- **`/planner/mcp`**: nine read-only evidence tools (telemetry, identity, secret metadata, app configuration, SQL
  network rules, incident history, runbooks, repository files, commit history).
- **`/engineer/mcp`**: six branch-only repository tools (a `candidate/<drill>-<attempt>` branch, a patch to two
  allowed files, a regression test, a runbook update, CI status).
- **`/recovery/mcp`**: two grant-gated tools that execute one approved recovery action through WS2's Ops Service and
  check the twin's drift.

Every call is authenticated per endpoint, checked against a server-side allowlist, wrapped as untrusted data,
redacted, and written to the drill's audit trail with its tool version, caller, authorization result and source.

- How it fits the whole system, with diagrams: [docs/ws3-architecture.md](docs/ws3-architecture.md).
- How other workstreams call it: [contracts/mcp-contract.md](contracts/mcp-contract.md). Per-tool reference:
  [contracts/mcp-tools.md](contracts/mcp-tools.md). Machine-readable schemas:
  [contracts/mcp-tools.schema.json](contracts/mcp-tools.schema.json).
- Why it lives here and how it deploys: `docs/ADR.md`, ADR-022.

## What's where

| Path | What it is |
| --- | --- |
| `src/mcp-server/` | The server (Python 3.12, MCP SDK, Starlette): `app/`, placeholder fixtures for laptop runs, tests, `Dockerfile` |
| `src/mcp-server/app/planner_tools.py`, `engineer_tools.py`, `recovery_tools.py` | The three tool registries, with their path allowlists |
| `src/mcp-server/app/guard.py` | Protected paths, the result envelope, redaction, refusals, the audit record |
| `src/mcp-server/app/entra_auth.py` | Entra mode: validates each agent identity's token |
| `src/mcp-server/app/backends/` | `azure.py` (Log Analytics, ARM, Key Vault, SQL, AI Search), `github.py` (GitHub Apps), `fixtures.py` (offline) |
| `contracts/mcp-contract.md`, `mcp-tools.md`, `mcp-tools.schema.json` | The tool contract (v2.4) and its generated schemas. `contracts/ops-actions.md` (WS2) is what `/recovery` calls |
| `infra/modules/mcp.bicep` | `ca-mcp`, its identity `id-lf-mcp` and roles, and the AI Search service |
| `infra/modules/mcp-twin-access.bicep` | `id-lf-mcp`'s read roles on the twin (and, on an access-policy vault, a secrets `list` policy) |
| `.github/workflows/mcp-server.yml` | CI: tests with coverage, Bandit, Semgrep, image smoke test, then GHCR and the lab registry |
| `scripts/run-local.sh`, `fake-ops.py`, `mcp-smoke.py`, `recovery-smoke.py` | Laptop run and smoke tests, against a local or deployed server |
| `scripts/load-incidents.py` | Builds and loads the AI Search index from the private incident corpus (`--corpus`) |
| `scripts/export-tool-schemas.py` | Regenerates `contracts/mcp-tools.schema.json` from the code |
| `scripts/create-secrets.sh`, `setup-entra.sh` | One-time setup: the GitHub credentials in Key Vault, Entra mode |

## Run it on a laptop (no Azure, no GitHub)

```bash
python3.12 -m venv .venv-ws3 && . .venv-ws3/bin/activate
pip install -r src/mcp-server/requirements-dev.txt
(cd src/mcp-server && pytest -q --cov=app)   # 69 passed
scripts/run-local.sh                         # ends with SMOKE TEST PASSED and RECOVERY SMOKE TEST PASSED
scripts/run-local.sh --serve                 # keep it running and print the three keys, for your own client
```

`run-local.sh` generates three endpoint keys, starts the server with `BACKEND=fixtures` and
`EVENT_SOURCE=dir:./evidence`, starts `fake-ops.py` (a stand-in for the Ops Service) with one valid grant, and runs:

- `mcp-smoke.py`: lists every endpoint's tools, calls every Planner tool, and proves a key for one endpoint gets 403
  on the others;
- `recovery-smoke.py`: a valid grant executes, the same grant again is refused, `check_recovery` answers, and the
  Planner's key gets 403 on `/recovery`.

The audit trail is then in `evidence/<drill-id>/events.jsonl` (git-ignored).

## Deploy to Azure

`ca-mcp` deploys with the rest of the platform through `scripts/deploy.sh` and the shared azd environment. It
follows the Ops Service: `main.bicep` deploys it once `OPS_IMAGE`, `REFEREE_IMAGE` and `MCP_IMAGE` are all set.

1. **GitHub credentials, once per lab.** The Planner reads the repo and the Engineer pushes `candidate/**` branches.
   - **GitHub Apps (the target):** two Apps installed on this repo only. Planner: Contents read, Metadata read.
     Engineer: Contents read and write, Actions read, Metadata read. Note each App's **App ID** and its
     **installation ID** (a number at the end of the installation's URL, not the App's Client ID), then:

     ```bash
     azd env set GITHUB_PLANNER_APP_ID <id>;  azd env set GITHUB_PLANNER_INSTALLATION_ID <number>
     azd env set GITHUB_ENGINEER_APP_ID <id>; azd env set GITHUB_ENGINEER_INSTALLATION_ID <number>
     scripts/create-secrets.sh "$(azd env get-value CONTROL_KEYVAULT_NAME)" planner-app.pem engineer-app.pem
     ```
   - **Fine-grained tokens (the fallback):** `azd env set MCP_GITHUB_AUTH token`, then store `gh-planner-token` and
     `gh-engineer-token` in the control vault.

   The three endpoint keys (`mcp-planner-key`, `mcp-engineer-key`, `mcp-recovery-key`) are created by
   `postprovision.sh`, like the Ops Service's keys. `create-secrets.sh` creates any that are missing too.
2. **Image.** CI pushes `mcp-server:sha-<commit>` to GHCR and the lab registry on every merge to `main`.
   `scripts/deploy.sh images` sets `MCP_IMAGE` from the last commit that changed `src/mcp-server/`.
3. **Engineer write paths.** `azd env set MCP_ENGINEER_WRITE_PATHS '<pattern>,<pattern>,...'`: the files a
   candidate may change. The value lives only in the azd environment and the private repo, never here (ADR-004);
   it must match WS4's Drill Runner list and `CANDIDATE_ALLOWED_PATHS`.
4. **Deploy.** `scripts/deploy.sh apps` (or `all` on a fresh lab). If a secret, App ID or the step 3 value is missing,
   it leaves `ca-mcp` out of that provision and names what's missing, so the rest of the platform still deploys.
   The provision prints `MCP_URL`, which WS4 uses for the agents' connections.
5. **Incident index.** The incidents are the agents' test material, so they stay in the private `ws3-mcp-server`
   repo (ADR-004). Point the azd environment at a checkout of it:
   `azd env set INCIDENT_CORPUS <path>/ws3-mcp-server/evidence-corpus/incidents`. `postprovision.sh` then reloads
   the index on every provision (without it, it warns and carries on); hybrid once
   `OPENAI_ENDPOINT` and `EMBEDDING_DEPLOYMENT` (WS4) are set in the azd environment, with
   `azd env set SEARCH_VECTOR_FIELD content_vector`. If a region is out of AI Search capacity,
   `azd env set SEARCH_LOCATION <region>`.
6. **Smoke-test the deployed server** in key mode, with the keys from the control vault:

   ```bash
   KV="$(azd env get-value CONTROL_KEYVAULT_NAME)"; k() { az keyvault secret show --vault-name "$KV" -n "$1" --query value -o tsv; }
   MCP_URL="$(azd env get-value MCP_URL)" PLANNER_KEY="$(k mcp-planner-key)" ENGINEER_KEY="$(k mcp-engineer-key)" \
     RECOVERY_KEY="$(k mcp-recovery-key)" python scripts/mcp-smoke.py drill-deploy-check
   ```
7. **Entra mode (the target)**, once WS4 has the three agent identities:
   `scripts/setup-entra.sh <planner-oid> <engineer-oid> <recovery-oid>`, then `azd env set MCP_AUTH_MODE entra`,
   `MCP_CLIENT_ID` and `PLANNER_AGENT_OBJECT_ID` / `ENGINEER_AGENT_OBJECT_ID` / `RECOVERY_AGENT_OBJECT_ID`, and
   `scripts/deploy.sh apps`. From then on only those identities get in, and a person's token gets 401.
8. **Code freeze:** `azd env set MCP_REPO_REF <base commit SHA>` instead of `main`, then `scripts/deploy.sh apps`.

What the twin needs from WS1 and WS2 is in [contracts/mcp-contract.md](contracts/mcp-contract.md), section 8.
The Planner never reads `docs/`, `CLAUDE.md`, `src/ops-service/`, `referee/` or `scripts/` (ADR-004): its
allowlist is `src/order-service/**` and `runbooks/*.md`.

## Configuration

| Setting | Meaning |
| --- | --- |
| `BACKEND` | `fixtures` (laptop) or `azure` |
| `AUTH_MODE` | `key` or `entra` |
| `PLANNER_KEY`, `ENGINEER_KEY`, `RECOVERY_KEY` | Key mode: the three endpoint keys (different, ≥ 32 characters) |
| `ENTRA_TENANT_ID`, `MCP_CLIENT_ID`, `PLANNER_AGENT_OBJECT_ID`, `ENGINEER_AGENT_OBJECT_ID`, `RECOVERY_AGENT_OBJECT_ID` | Entra mode |
| `EVENT_SOURCE` | Where audit events go: `dir:<path>` or `blob:https://<account>.blob.core.windows.net/<container>` |
| `MCP_ALLOWED_HOSTS` | Host names the server answers to (default `127.0.0.1:*,localhost:*`; `mcp.bicep` sets its FQDN) |
| `REPO_REF` | The branch or commit the tools read and branch from (`main` until code freeze) |
| `GITHUB_REPO` | `owner/name` |
| `GITHUB_PLANNER_APP_ID`, `GITHUB_PLANNER_INSTALLATION_ID`, `GITHUB_PLANNER_PRIVATE_KEY` (or `GITHUB_PLANNER_TOKEN`) | The Planner's GitHub credential; the same three for `ENGINEER` |
| `OPS_URL`, `OPS_AGENT_KEY` | The Ops Service, for `/recovery`; without `OPS_URL` both recovery tools refuse |
| `LOG_ANALYTICS_WORKSPACE_ID`, `TWIN_KEYVAULT_ID`, `APP_IDENTITY_PRINCIPAL_ID`, `ORDER_APP_NAME`, `TWIN_SQL_SERVER_NAME`, `DESIRED_SQL_DB_NAME`, `TWIN_SECRET_NAME` | The twin the evidence tools read (Azure backend) |
| `SEARCH_ENDPOINT`, `SEARCH_INDEX`, `SEARCH_VECTOR_FIELD` | AI Search (`content_vector` once the index is hybrid) |
| `AZURE_CLIENT_ID` | The managed identity the server signs in to Azure with |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional: OpenTelemetry to Application Insights |
| `FIXTURES`, `KNOWLEDGE_DIR` | Fixtures backend only: the evidence file, and findings earlier local drills left |

## Security controls, in short

- One credential per endpoint. A credential for another endpoint gets 403, recorded as a deny event (T-03).
- Server-side allowlists for every path and branch; the agents never hold the GitHub or Azure credentials (T-04).
- All tool output is marked untrusted and redacted. The corpus's planted instruction (INC-1055) causes no tool call
  (T-08).
- The Recovery tools pass on a single-use grant they can't forge or read. The grant is never logged.
- Fixed telemetry queries only; secret values never leave Key Vault (metadata only).
- The image runs as a non-root user; CI scans code, dependencies, secrets and the image.
