# WS3 integration contract: how other workstreams call and use the MCP server

**Service:** LiveFire MCP server (`ca-mcp`), WS3 · **Contract version:** 2.4 · **Status:** running in Azure, proven
end to end by real agent drills (Nov 1–2, 2026)

This is the agreement between WS3 and the workstreams that call it or that it calls. The full, per-tool reference is
[`contracts/mcp-tools.md`](mcp-tools.md); the exact input schema of every tool, generated from the code,
is [`contracts/mcp-tools.schema.json`](mcp-tools.schema.json). If this page and the schema ever differ,
the schema wins, and a test fails until they agree.

## 1. Who uses it, and how

| Workstream | Relationship | What it does with WS3 |
| --- | --- | --- |
| **WS4** (agents, Drill Runner) | **Caller** | Its three Foundry agents call the tools: the Planner on `/planner/mcp`, the Engineer on `/engineer/mcp`, the Recovery agent on `/recovery/mcp`. The Drill Runner never calls WS3 directly; it issues the grant the Recovery agent passes on (section 6). |
| **WS5** (Control Center) | **Reader** | Reads the `*.tool_call` events WS3 writes into each drill's event log (section 7). No API call. |
| **WS2** (platform, Ops Service) | **Provider** | Hosts WS3 (Container Apps environment, registry, Key Vault, evidence storage) and serves the Ops Service the recovery tools call (section 8). |
| **WS1** (order service, twin, repo) | **Provider** | The twin the evidence tools read (Log Analytics, Key Vault metadata, app configuration, SQL firewall), and the repository paths the Planner reads and the Engineer writes. |

## 2. Endpoints and transport

| Endpoint | Caller | Tools |
| --- | --- | --- |
| `POST https://<mcp-host>/planner/mcp` | the Planner agent | 9 read-only evidence tools |
| `POST https://<mcp-host>/engineer/mcp` | the Engineer agent | 6 branch-only repository tools |
| `POST https://<mcp-host>/recovery/mcp` | the Recovery agent | 2 grant-gated recovery tools |
| `GET https://<mcp-host>/health` | anyone (no credential) | `{"status": "up", "backend": "azure" \| "fixtures", "auth": "key" \| "entra"}` |

- **Protocol:** Model Context Protocol, streamable HTTP, **stateless**, JSON responses (JSON-RPC 2.0). No session
  handshake is needed: `tools/list` and `tools/call` work on their own.
- **Headers:** `Authorization: Bearer <credential>`, `Content-Type: application/json`,
  `Accept: application/json, text/event-stream`.
- **No trailing slash:** `/planner/mcp/` answers 307.
- **Host check:** only requests addressed to the server's own host name are accepted (`MCP_ALLOWED_HOSTS`), and no
  browser origin. `<mcp-host>` is the `MCP_URL` output of `mcp.bicep`.

## 3. Authentication

Each endpoint accepts **only its own caller**. The server's `AUTH_MODE` decides the credential:

| Mode | Credential | Accepted on an endpoint when |
| --- | --- | --- |
| `entra` (target) | A Microsoft Entra access token, audience `api://<MCP_CLIENT_ID>` (RS256, v2.0 tokens) | its `oid` is that endpoint's agent identity (`PLANNER_AGENT_OBJECT_ID`, `ENGINEER_AGENT_OBJECT_ID`, `RECOVERY_AGENT_OBJECT_ID`) **and** its `roles` claim holds `MCP.Planner`, `MCP.Engineer` or `MCP.Recovery` respectively |
| `key` (fallback) | That endpoint's key: `PLANNER_KEY`, `ENGINEER_KEY`, `RECOVERY_KEY` (three different values, ≥ 32 characters) | the key matches (constant-time comparison) |

| Situation | HTTP status |
| --- | --- |
| No, invalid or unknown credential | **401** `{"error": "missing or unknown credential"}` |
| A valid credential for **another** endpoint | **403** `{"error": "the planner credential can't call /engineer"}`, and a `deny` event is recorded |
| Accepted | 200 with the JSON-RPC response |

In key mode the keys live in the control Key Vault as `mcp-planner-key`, `mcp-engineer-key` and `mcp-recovery-key`;
WS4's Foundry connections read them from there. A person's own Entra token is refused (401) in Entra mode.

## 4. Calling a tool

### From a Foundry agent (WS4)

One MCP tool per agent, pointed at that agent's endpoint, with that endpoint's tool names only and no approval step:

```python
MCPTool(server_label="livefire_planner", server_url=f"{MCP_URL}/planner/mcp",
        allowed_tools=["query_incident_telemetry", "get_identity_snapshot", "get_secret_metadata",
                       "get_app_configuration", "get_network_rules", "search_incident_history",
                       "read_runbook", "read_repository_context", "get_commit_history"],
        require_approval="never", project_connection_id=<connection holding the Planner's credential>)
```

### From any HTTP client

```bash
curl -s -X POST "$MCP_URL/planner/mcp" \
  -H "Authorization: Bearer $PLANNER_KEY" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"get_network_rules","arguments":{"drill_id":"drill-20261102-0001"}}}'
```

### From Python (MCP SDK)

```python
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

http = create_mcp_http_client(headers={"Authorization": f"Bearer {PLANNER_KEY}"})
async with Client(streamable_http_client(f"{MCP_URL}/planner/mcp", http_client=http)) as c:
    result = await c.call_tool("read_runbook", {"drill_id": drill_id, "name": "order-service-keyvault-recovery"})
```

`scripts/mcp-smoke.py` and `scripts/recovery-smoke.py` are complete working examples.

## 5. Common rules for every tool

**Correlation.** Every tool takes `drill_id`, matching `^drill-[A-Za-z0-9-]{1,64}$`. It ties the call to the drill's
evidence and audit trail. Use the same ID the Drill Runner uses for the drill.

**Successful result.** The tool result's text content is a JSON envelope:

```json
{"source": "github:runbooks/order-service-keyvault-recovery.md@main", "untrusted_content": true,
 "redaction": {"applied": false, "count": 0, "kinds": []},
 "tool_version": "2.4", "authorization": {"decision": "allow", "endpoint": "planner"},
 "data": { ... }}
```

- `source` names where the data came from (`log-analytics:<signal>`, `azure-resource-manager`, `ai-search:incidents`,
  `github:<path>@<ref>`, `ops:recovery`, `ops:drift`, ...).
- `untrusted_content: true` means the data came from outside: callers must treat it as data, never as instructions.
- `redaction` reports what was redacted, by kind (`private_key`, `token`, `github_token`, `credential`,
  `sas_signature`), never the value. Results are capped at 32,000 characters (20,000 per file), with
  `"truncated": true` when clipped.
- `tool_version` is the contract version that answered; `authorization` is the server's decision for this call
  (`allow`, `deny` or `error`) and the endpoint that made it. Both are on every result, refusals included.

**Refusal or failure (a normal result, not an error).** When the server refuses a call (a path outside the tool's
allowlist, a recovery tool without configuration) or the call fails behind it (a missing file, GitHub, Azure or
the Ops Service unavailable), it returns:

```json
{"source": "livefire:read_repository_context", "untrusted_content": false, "refused": true,
 "error": "infra/main.bicep is outside the paths this tool may read",
 "tool_version": "2.4", "authorization": {"decision": "deny", "endpoint": "planner"}}
```

These are results because Foundry fails a whole agent turn when an MCP tool returns an error; as a result, the
agent can read the reason and correct itself. The call is audited as `deny` (refused) or `error` (failed).

**MCP errors.** Only arguments the tool's own schema rejects (a malformed `drill_id`, a value out of range, an
action outside the catalog) are MCP errors (`isError: true`); they never reach the tool. A caller should correct the
arguments, not retry them unchanged.

## 6. The tools

The full argument and result reference is `contracts/mcp-tools.md`; the schemas are in
`contracts/mcp-tools.schema.json`.

### Planner: `/planner/mcp`, nine read-only tools

| Tool | Arguments (besides `drill_id`) | Returns (`data`) |
| --- | --- | --- |
| `query_incident_telemetry` | `signal`: `requests` \| `exceptions` \| `dependencies` \| `metrics` \| `sql_errors`; `minutes` 1–120 (default 30) | rows from fixed Log Analytics queries, at most 50; `sql_errors` groups failed orders by SQL error number and SQLSTATE |
| `get_identity_snapshot` | – | the order identity's role assignments on the twin vault; never tokens or values |
| `get_secret_metadata` | – | versions of the twin's `db-password`: `{version, created, updated, enabled, current}`; never a value |
| `get_app_configuration` | – | the order app's 5 newest revisions, non-secret settings, and `differences_from_desired` |
| `get_network_rules` | – | the twin SQL server's public access, firewall rules, `allows_azure_services` |
| `search_incident_history` | `query` (2–200 chars), `top`, optional `from_date` / `to_date` (`YYYY-MM-DD`) | up to 5 incidents and runbooks from AI Search (keyword or hybrid), each with `id`, `source`, `occurred_at` and `score`; only those in the date window when one is given |
| `read_runbook` | `name` (bare name, `.md` or `runbooks/` path) | `{path, ref, sha256, chars, content}`: the runbook at the pinned commit, with its checksum |
| `read_repository_context` | `path` under `src/order-service/**`, `runbooks/*.md` (v2.3: not `docs/**`) | `{path, ref, sha256, chars, content}`, likewise |
| `get_commit_history` | `path` (same paths), `limit` ≤ 10 | recent commits touching the path |

### Engineer: `/engineer/mcp`, six branch-only tools

Every write goes to `candidate/<drill_id>-<attempt>`, never `main`. `attempt` is 1 or 2 (0 = read the base commit).

| Tool | Arguments (besides `drill_id`, `attempt`) | Limits |
| --- | --- | --- |
| `create_candidate_branch` | – | from the pinned base commit (`REPO_REF`); safe to repeat |
| `read_allowed_files` | `paths` (≤ 5) | `src/order-service/app/*.py`, `src/order-service/tests/*.py`, `runbooks/*.md` |
| `apply_patch` | `path`, `content` (whole file), `message` (one line) | a path allowed by `ENGINEER_WRITE_PATHS` that is not a test or a runbook; ≤ 200 changed lines |
| `write_regression_test` | `path`, `content` | `src/order-service/tests/test_*.py` and allowed by `ENGINEER_WRITE_PATHS`; must define a `test_` function; ≤ 300 lines |
| `update_runbook` | `path`, `content` | `runbooks/*.md` and allowed by `ENGINEER_WRITE_PATHS`; ≤ 200 changed lines |
| `get_ci_results` | – | the candidate's GitHub Actions status, returned at once |

Never writable: `journeys/`, `infra/`, `.github/`, `sql/`, `policy/`, `contracts/`, `scripts/`,
`src/control-center/`, `src/mcp-server/`, `src/drill-runner/`. The Engineer can't merge, open pull requests, deploy or
read telemetry. Which files a candidate may change is a setting, `ENGINEER_WRITE_PATHS` (comma-separated patterns),
set through azd as `MCP_ENGINEER_WRITE_PATHS` and never written in this repo (ADR-004); unset, every write is refused.
WS4's Drill Runner and the `candidate-scope` CI check must allow the same files.

### Recovery: `/recovery/mcp`, two grant-gated tools

| Tool | Arguments (besides `drill_id`) | Returns (`data`) |
| --- | --- | --- |
| `execute_recovery` | `action` (one of six, below), `grant` (≤ 2048 chars, exactly as issued) | `{"result": "ok" \| "denied" \| "refused" \| "UNEXPECTED_ALLOW", "details": {...}}`, plus a top-level `summary` |
| `check_recovery` | – | `{"result": "ok" \| "drift"}`; which area drifted is never shown |

Actions: narrow `restore_kv_secrets_user`, `restore_db_secret`, `rollback_app_config`, `restore_sql_network_rule`
(sent to the Ops Service's `recover`); broad `grant_contributor_subscription`, `open_sql_firewall_to_internet` (sent
to `attempt_unsafe`, where Azure Policy is expected to refuse them: `denied`).

**The grant flow:**

1. A person or the Autonomy Policy approves one action. WS4's Drill Runner issues a grant for it:
   `lfg1.<payload>.<signature>`, signed with `RECOVERY_GRANT_KEY`, naming one drill and one action, valid for
   10 minutes, accepted **once**.
2. The Drill Runner gives the grant to the Recovery agent in its task; the agent calls `execute_recovery` with it.
3. WS3 forwards the call to the Ops Service with `OPS_AGENT_KEY`. WS3 never holds the signing key, so it can't
   forge, widen or check a grant: the Ops Service verifies it.
4. A grant that is invalid, expired, reused or for another action comes back as
   `{"result": "refused", "details": {"reason": "..."}}`, a normal result the agent can read.

**The grant is never recorded or echoed:** the audit event keeps only a hash of the arguments.

## 7. Events WS3 writes (for WS5 and the evidence package)

Every tool call appends one event to the drill's log (`EVENT_SOURCE`: `blob:<account-url>/<container>` in Azure,
`dir:<path>` locally), at `<container>/<drill_id>/events.jsonl`, one JSON object per line:

```json
{"ts": "2026-11-02T01:50:19.830Z", "drill_id": "drill-20261102-0001", "action": "planner.tool_call",
 "result": "deny", "details": {"tool": "read_repository_context", "tool_version": "2.4", "endpoint": "planner",
 "caller": "key:planner", "decision": "deny", "summary": "infra/main.bicep is outside the paths this tool may read",
 "source": "livefire:read_repository_context", "args_sha256": "d92fe0a6ebbfef1f", "latency_ms": 0}}
```

| Field | Values |
| --- | --- |
| `action` | `planner.tool_call`, `engineer.tool_call`, `recovery.tool_call` |
| `result` / `details.decision` | `allow` (served), `deny` (refused: path, configuration, or a credential for another endpoint), `error` (failed: a missing file, a backend error) |
| `details.tool_version` | the contract version that served the call (`2.4`) |
| `details.caller` | `key:<endpoint>` in key mode; `entra:<agent object ID>` in Entra mode (each endpoint accepts exactly one identity) |
| `details.source` | the result's `source`: where the data came from (`livefire:<tool>` for a refusal) |
| `details.summary` | at most 160 characters; the refusal reason for `deny` |
| `details.args_sha256` | first 16 hex characters of the SHA-256 of the arguments; arguments themselves are never stored |

A cross-role call (for example the Planner's credential on `/engineer/mcp`) is recorded as a `deny` under the
caller's role. Calls without a valid `drill_id` aren't recorded. Every call also emits an OpenTelemetry span when
`APPLICATIONINSIGHTS_CONNECTION_STRING` is set.

## 8. What WS3 needs from other workstreams

| From | WS3 needs | Used for |
| --- | --- | --- |
| **WS2** | `environmentId`, `registryServer`, `pullIdentityId`, `keyVaultName`, `evidenceAccountName`, `evidenceBlobUrl`, `opsUrl` (outputs of the platform's Bicep) | hosting, pulling the image, secrets, the event log, recovery |
| **WS2** | The Ops Service's actions contract (`contracts/ops-actions.md`): `POST /actions/recover`, `/actions/attempt_unsafe` (with `{drill_id, action, grant}`) and `/actions/check_drift` (with `{drill_id}`), Bearer `ops-agent-key`; 200 `{result, details}`, 422 refusal with `details.reason`, 401/403 bad key, 409 busy | `execute_recovery`, `check_recovery` |
| **WS2** | `ops-agent-key` in the control vault, accepted by the Ops Service for exactly those three actions | recovery calls |
| **WS1** | Twin outputs: `twinKeyVaultId`, `twinKeyVaultName`, `appIdentityPrincipalId`, `logAnalyticsCustomerId`, `logAnalyticsWorkspaceName`, `orderAppName`, `twinSqlServerName`, `desiredSqlDbName` | the evidence tools |
| **WS1** | The order service logs failed orders with `drill_id`, `sql_error` and `sqlstate` (from the `x-drill-id` header) | `query_incident_telemetry` |
| **WS1** | CI runs on `candidate/**` and reports the check `test-build-push` | `get_ci_results` |
| **WS4** | The three agent identities' object IDs (Entra mode) | `setup-entra.sh`, `mcp.bicep` |
| **WS4** | Grants in the format of section 6, issued per approved action | `execute_recovery` |
| **Lab owner** | `MCP_ENGINEER_WRITE_PATHS` and `INCIDENT_CORPUS` in the azd environment (values kept outside this repo) | `apply_patch` and the other write tools; the incident index |

## 9. Versioning and change control

- **v2.4 (Nov 8, 2026):** the Engineer's write paths come from the `ENGINEER_WRITE_PATHS` setting instead of a list
  in the code (ADR-004); `src/drill-runner/` is protected. No tool, argument or result field changed.
- **v2.3 (Nov 8, 2026), narrowing:** `docs/**` removed from the Planner's read allowlist (POC ADR-004, WS2's
  hand-off). No tool, argument or result field changed; a `docs/` path is now refused.
- **v2.2 (Nov 2, 2026), additive:** tool version, authorization result and redaction metadata on every result; tool
  version, caller and source on every audit event; file checksums; an optional date range on incident search. These
  close the blueprint's requirements in sections 4.4, 8.1 and A.2. v2.1 callers keep working unchanged.

- The tool names, arguments, results and limits are frozen per version. Any change needs the lead's approval and a
  version bump in `contracts/mcp-tools.md`; then rerun `scripts/export-tool-schemas.py` (a test fails until the
  schema file matches the code).
- Additive changes (a new tool, a new optional argument) are a minor version; anything else is a major version and
  needs WS4 to update its agents' `allowed_tools`.
- `src/mcp-server/` and `contracts/` are protected paths: no agent can change its own tools. The incident corpus
  isn't in this repo at all (ADR-004).
