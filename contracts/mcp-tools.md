# MCP tool contract, v2.4

v1.0 was frozen at G1 (Oct 26). v1.1 (Oct 30) changed only the Authentication section. v2.0 (Oct 31) adds three
read-only Planner tools and a telemetry query, and widens the Engineer's write paths. v2.1 (Oct 31) adds the Recovery agent's endpoint, which executes approved
recovery actions with a grant. v2.2 (Nov 2) adds provenance and audit fields the blueprint requires (4.4, 8.1,
A.2) and an optional date range on incident search; additive only (see "v2.2" below). v2.3 (Nov 8) narrows the
Planner's read allowlist: `docs/**` is removed (see "v2.3" below). v2.4 (Nov 8) takes the Engineer's write paths
from a setting, `ENGINEER_WRITE_PATHS` (see "v2.4" below). Any other change needs the lead's approval and a
version bump.

Endpoints: https://<mcp-host>/planner/mcp, https://<mcp-host>/engineer/mcp and (v2.1)
https://<mcp-host>/recovery/mcp, MCP streamable HTTP, stateless, JSON responses. Post to the path with no trailing
slash: `/recovery/mcp/` answers 307.

Authentication: Authorization: Bearer <credential>. The server's AUTH_MODE decides the credential.
- entra (target): a Microsoft Entra access token for audience api://<livefire-mcp client ID>.
  /planner/mcp accepts only the Planner agent identity holding app role MCP.Planner;
  /engineer/mcp accepts only the Engineer agent identity holding app role MCP.Engineer;
  /recovery/mcp accepts only the Recovery agent identity (RECOVERY_AGENT_OBJECT_ID) holding app role MCP.Recovery.
- key (fallback): the endpoint's own key (PLANNER_KEY, ENGINEER_KEY, RECOVERY_KEY). The three keys differ.
In both modes: a missing, invalid or unknown credential gets 401. A valid credential for the other
endpoint gets 403, recorded as a deny event.

Every tool takes drill_id (^drill-[A-Za-z0-9-]{1,64}$).
Results: {"source", "untrusted_content": true, "redaction", "tool_version", "authorization", "data"}, secrets redacted, at most 32,000 characters
(20,000 per file). Refusals are normal results with `refused: true` (see the last section). Every call is written to the
drill's evidence as planner.tool_call, engineer.tool_call or recovery.tool_call.

## Planner: nine read-only tools

| Tool | Arguments | Limits |
| --- | --- | --- |
| query_incident_telemetry | signal (requests, exceptions, dependencies, metrics, sql_errors), minutes | 1 to 120 minutes; 50 rows; fixed queries only |
| get_identity_snapshot | none | Twin vault only; never tokens or secret values |
| get_secret_metadata (v2.0) | none | The twin's db-password secret: versions only; never a value |
| get_app_configuration (v2.0) | none | The order app: 5 newest revisions; non-secret settings only |
| get_network_rules (v2.0) | none | The twin SQL server: public network access and firewall rules |
| search_incident_history | query, top, (v2.2) from_date, to_date | 2 to 200 characters; 5 results; order service only; dates YYYY-MM-DD bound occurred_at |
| read_runbook | name | ^[a-z0-9-]{1,64}$, at the pinned commit |
| read_repository_context | path | src/order-service/**, runbooks/*.md (v2.3: docs/** removed) |
| get_commit_history | path, limit | Same paths; 10 commits |

The v2.0 results (`data`):

- `query_incident_telemetry` with `signal: sql_errors`: rows of `{sql_error, sqlstate, ExceptionType, events,
  first_seen, last_seen}`. Failed orders since the drill began, grouped by SQL Server error number and SQLSTATE.
- `get_secret_metadata`: `{vault, secret, versions: [{version, created, updated, enabled, current}]}`, newest
  first, at most 10. `version` is the first 6 characters of the version ID. `current` is the version an unversioned
  read returns.
- `get_app_configuration`: `{app, desired: {SQL_DB_NAME}, current_revision, revisions: [{name, created, active,
  image, env}], differences_from_desired: [{name, desired, current}]}`. `env` leaves out every secret reference and
  every setting whose name looks like a secret (password, token, key, connection string, credential).
- `get_network_rules`: `{server, public_network_access, firewall_rules: [{name, start_ip, end_ip}],
  allows_azure_services}`. `allows_azure_services` is true when a 0.0.0.0 to 0.0.0.0 rule exists.

## Engineer: six branch-only tools (the branch is always candidate/<drill_id>-<attempt>)

| Tool | Arguments | Limits |
| --- | --- | --- |
| read_allowed_files | paths, attempt (0 = base commit) | 5 files from src/order-service/app/*.py, src/order-service/tests/*.py, runbooks/*.md |
| create_candidate_branch | attempt (1 or 2) | From the pinned base commit; safe to repeat |
| apply_patch | attempt, path, content, message | (v2.4) a path matching ENGINEER_WRITE_PATHS that is not a test or a runbook; 200 changed lines; one-line message |
| write_regression_test | attempt, path, content | src/order-service/tests/test_*.py, also matching ENGINEER_WRITE_PATHS; must define test_; 300 changed lines |
| update_runbook | attempt, path, content | runbooks/*.md, also matching ENGINEER_WRITE_PATHS; 200 changed lines |
| get_ci_results | attempt | Candidate branch only; returns status at once |

(v2.4) Which files a candidate may change is a setting, `ENGINEER_WRITE_PATHS`: comma-separated patterns (`*` within
one folder, `**` across folders), set through azd (`MCP_ENGINEER_WRITE_PATHS`), never written in this repo. Unset,
every write is refused; a pattern that could match a protected path stops the server. WS4's Drill Runner and the
`candidate-scope` CI check (`CANDIDATE_ALLOWED_PATHS`, ADR-020) must allow the same files. Example with placeholder
paths: `src/example/app/module.py,src/order-service/tests/test_*.py,runbooks/*.md`.

Never writable: journeys/, infra/, .github/, sql/, policy/, contracts/, scripts/, src/control-center/,
src/mcp-server/, src/drill-runner/. The Engineer can't read telemetry, merge, open pull requests, deploy or commit to main.

## Configuration the Azure backend needs (v2.0)

`ORDER_APP_NAME`, `TWIN_SQL_SERVER_NAME` and `DESIRED_SQL_DB_NAME` (default `orders`), plus `TWIN_SECRET_NAME`
(default `db-password`). Without them, the matching tool refuses with "not configured". The MCP identity needs Key
Vault Reader on the twin vault (metadata only; on an access-policy vault, a secrets `list` access policy instead), and Reader on the twin SQL server and on the order app
(`mcp-twin-access.bicep`).

## Recovery: two grant-gated tools (v2.1)

The Recovery agent executes the recovery action a person (or the Autonomy Policy) approved. The workflow issues a
grant for exactly that action: `lfg1.<payload>.<signature>`, signed with RECOVERY_GRANT_KEY, which only the Drill
Runner and the Ops Service hold. It names one drill and one action, expires in 10 minutes and is accepted once. The
MCP server only passes it on; it can't forge, widen or check one. It calls the Ops Service with OPS_AGENT_KEY, which
the Ops Service accepts only for `recover`, `attempt_unsafe` (both with a grant) and `check_drift`.

| Tool | Arguments | Result `data` |
| --- | --- | --- |
| `execute_recovery` | `action` (one of the six catalog actions), `grant` (≤ 2048 characters) | `{"result": "ok" \| "denied" \| "refused" \| "UNEXPECTED_ALLOW", "details": {...}}` from the Ops Service |
| `check_recovery` | none | `{"result": "ok" \| "drift"}`. Which area drifted is never shown: the diagnosis stays the Planner's |

- The four narrow actions go to `POST /actions/recover`; `grant_contributor_subscription` and
  `open_sql_firewall_to_internet` go to `POST /actions/attempt_unsafe`, so Azure Policy can refuse them.
- A refusal by the Ops Service (an invalid, expired, reused or mismatched grant; HTTP 422) is a normal result,
  `{"result": "refused", "details": {"reason": ...}}`, so the agent can read why. An action outside the catalog is
  a tool error. An Ops Service failure (401, 403, 409, 5xx, unreachable) is a tool error.
- **The grant is never recorded.** The `recovery.tool_call` event keeps only a hash of the arguments, and the result
  never echoes the grant.
- Both tools return structured content: `result.structuredContent` is the envelope `{"source", "untrusted_content",
  "data", "summary"}` (`source` is `ops:recovery` or `ops:drift`).
- Configuration: `OPS_URL` (the Ops Service's internal URL) and `OPS_AGENT_KEY` (at least 32 characters). Without
  `OPS_URL` the server still starts and both tools refuse with "recovery tools are not configured".

## Refusals are results, not MCP errors (2026-11-01)

Foundry fails a whole agent turn (`400 tool_user_error`) when an MCP tool returns an error, so the agent never
gets to correct itself. Every tool therefore returns a refusal as a normal result:
`{"source": "livefire:<tool>", "untrusted_content": false, "refused": true, "error": "<why>"}`, still recorded as
a `deny` (or `error`) tool-call event. Arguments the tool's own schema rejects (a malformed drill ID, a value out
of range, an action outside the catalog) remain MCP errors; the Drill Runner retries such a turn once, telling the
agent which call was rejected (`agent.tool_rejected`). `read_runbook` accepts the bare name, the file name or the
path (`order-service-keyvault-recovery`, `….md`, `runbooks/….md`).

## v2.4: the Engineer's write paths come from a setting (2026-11-08)

Tool names, arguments and result shapes are unchanged, so WS4's `allowed_tools` stay as they are.

- **Why:** POC ADR-004. A list of the exact files a candidate may change, in this public repo, tells the agents where
  to look. The list now lives in the azd environment (`MCP_ENGINEER_WRITE_PATHS`), passed to the server as
  `ENGINEER_WRITE_PATHS`.
- **Rules:** `apply_patch` takes a path that matches the setting and is neither a test nor a runbook;
  `write_regression_test` and `update_runbook` keep their own shapes and must also match the setting. Unset, every
  write is refused. `src/drill-runner/` joins the protected paths.
- Every result's `tool_version` is `"2.4"`.

## v2.3: docs/ off the Planner's allowlist (2026-11-08)

Narrowing, not additive: `read_repository_context` and `get_commit_history` now refuse `docs/**`. Tool names, arguments
and result shapes are unchanged, so WS4's `allowed_tools` stay as they are.

- **Why:** POC ADR-004 (accepted Oct 28) and WS2's WS3 hand-off: `docs/`, `CLAUDE.md` and the paths that hold the
  smoke tests' expected results (`src/ops-service/`, `referee/`, `scripts/`) must stay unreadable to the agents, so
  they can't read the demo script or the answers. Only `docs/` was on the list; the others never were.
- **Allowlist now:** `src/order-service/**` and `runbooks/*.md`. A path outside it is refused as a result
  (`refused: true`), as before.
- Results carried `tool_version` `"2.3"`.

## v2.2: provenance and audit fields (2026-11-02)

Additive: no tool, argument or result field was removed or renamed, so v2.1 callers keep working.

- **Every result** (served, refused or failed) carries `"tool_version"` (`"2.2"` then, `"2.3"` now) and
  `"authorization": {"decision": "allow" | "deny" | "error", "endpoint": "planner" | "engineer" | "recovery"}`.
- **Every served result** carries `"redaction": {"applied", "count", "kinds"}`: how many values were redacted, by
  kind (`private_key`, `token`, `github_token`, `credential`, `sas_signature`). Never the redacted value.
- **Every audit event** (`*.tool_call`) adds `tool_version`, `caller` and `source` to `details`. `caller` is
  `key:<endpoint>` in key mode and `entra:<agent object ID>` in Entra mode (each endpoint accepts exactly one
  identity). `source` is the result's `source`.
- **`read_runbook` and `read_repository_context`** return `{path, ref, sha256, chars, content}`: `ref` is the branch
  or commit read (`REPO_REF`), `sha256` the checksum of the whole file (before any truncation), `chars` its length.
- **`search_incident_history`** takes optional `from_date` and `to_date` (`YYYY-MM-DD`, empty for no bound) that
  bound `occurred_at`; a date that isn't a calendar date, or a range that runs backwards, is refused. Results echo
  the window and, from AI Search, add `score` (the retrieval score). The arguments are plain strings because Foundry
  rejects `anyOf` in tool schemas.
