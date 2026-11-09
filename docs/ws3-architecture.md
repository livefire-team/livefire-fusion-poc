# WS3 architecture: the MCP server in LiveFire Fusion

**Component:** LiveFire MCP server (`ca-mcp`) · **Workstream:** WS3 · **Contract:** v2.3 · **Status:** running in Azure,
used by real Foundry agents in every Autonomous drill scenario (Nov 1–2, 2026)

## 1. What this component is, in one paragraph

LiveFire Fusion rehearses a cyber-recovery on a disposable Azure twin of an order service. A fault is injected, AI
agents investigate and recover it, an independent Referee checks that customers can really order again, and an
agent proposes a code change on a candidate branch. **WS3 is
the only door between those AI agents and the outside world.** The agents hold no Azure credentials, no GitHub
tokens and no shell. Every piece of evidence they read and every change they make goes through one of the MCP
server's three endpoints. Each endpoint authenticates its own agent, allows only its own tools, checks every argument
against a server-side allowlist, wraps every result as untrusted data, redacts secrets, and writes an audit record.
That is what makes the agents' autonomy safe to demonstrate: they can reason freely, but they can only *act* through
a narrow, typed, audited interface.

## 2. Where WS3 sits in the ecosystem

| Workstream | Owns | Relationship to WS3 |
| --- | --- | --- |
| WS1 | The order service, its disposable Azure twin (Container Apps, SQL, Key Vault, telemetry), the repository | WS3 **reads** the twin's evidence and the repo; the Engineer writes only candidate branches |
| WS2 | The platform (Container Apps environment, registry, Key Vault, evidence storage), the Ops Service, the Referee, Azure Policy | WS3 **runs on** the platform; the Recovery tools **call** the Ops Service |
| **WS3** | **The MCP server, the incident corpus and index, the GitHub controls** | The agents' governed tool interface |
| WS4 | The Foundry agents (Planner, Engineer, Recovery) and the Drill Runner workflow | The agents **call** WS3; the Drill Runner issues the grants the Recovery agent passes on |
| WS5 | The Fusion Control Center | **Reads** WS3's audit events to show every tool call live |

```mermaid
flowchart TB
    subgraph WS4["WS4: agents and workflow"]
        Runner["Drill Runner<br/>deterministic workflow"]
        Planner["Planner agent<br/>read-only"]
        Engineer["Engineer agent<br/>branch-only"]
        Recovery["Recovery agent<br/>grant-gated"]
        Runner -->|"task, brief"| Planner
        Runner -->|"validated brief"| Engineer
        Runner -->|"approved action + grant"| Recovery
    end

    subgraph WS3["WS3: MCP server (ca-mcp)"]
        PMCP["/planner/mcp<br/>9 evidence tools"]
        EMCP["/engineer/mcp<br/>6 repository tools"]
        RMCP["/recovery/mcp<br/>2 recovery tools"]
    end

    subgraph WS1["WS1: twin and repository"]
        Twin["Order service twin<br/>Container Apps, SQL, Key Vault"]
        Telemetry["Log Analytics<br/>Application Insights"]
        Repo["GitHub repository<br/>source, runbooks, CI"]
    end

    subgraph WS2["WS2: platform"]
        Ops["Ops Service<br/>recover, check drift"]
        Store["Evidence storage<br/>drill event logs"]
        Referee["Referee<br/>real customer order"]
    end

    Search["Azure AI Search<br/>incident index (WS3)"]
    CC["WS5: Control Center"]

    Planner -->|"MCP, own credential"| PMCP
    Engineer -->|"MCP, own credential"| EMCP
    Recovery -->|"MCP, own credential"| RMCP

    PMCP -->|"fixed queries"| Telemetry
    PMCP -->|"metadata, configuration, firewall rules"| Twin
    PMCP -->|"hybrid search"| Search
    PMCP -->|"read at pinned commit"| Repo
    EMCP -->|"candidate branch only"| Repo
    RMCP -->|"grant + agent key"| Ops
    Ops -->|"one narrow action"| Twin

    PMCP & EMCP & RMCP -->|"audit events"| Store
    Store --> CC
    Runner --> Referee
    Referee -->|"order journey"| Twin
```

What WS3 deliberately does **not** do: inject faults, deploy, run the Referee, approve anything, or decide the
verdict. Those are deterministic operations in the Drill Runner and the Ops Service, outside the agents' reach.

## 3. Inside the component

One container serves three isolated MCP servers. Each has its own tool registry; a credential for one endpoint is
refused on the others. Everything a tool returns or records passes through one shared guard.

```mermaid
flowchart LR
    Call["HTTPS request<br/>Bearer credential"] --> Guard["KeyGuard<br/>who is calling, which endpoint"]
    Guard -->|"wrong endpoint: 403 + deny event"| Deny["Audit: deny"]
    Guard -->|"unknown: 401"| Reject["Rejected"]
    Guard -->|"its own endpoint"| Router{"Endpoint"}

    Router --> P["Planner registry<br/>planner_tools.py"]
    Router --> E["Engineer registry<br/>engineer_tools.py"]
    Router --> R["Recovery registry<br/>recovery_tools.py"]

    subgraph Rules["guard.py: applied to every call"]
        Allow["Allowlists<br/>paths, branches, sizes, actions"]
        Env["Envelope<br/>untrusted_content, source, tool_version"]
        Red["Redaction<br/>keys, tokens, signatures"]
        Aud["Audit record<br/>caller, decision, source, latency"]
    end

    P & E & R --> Rules

    subgraph Backends["backends/"]
        Az["azure.py<br/>Log Analytics, ARM, Key Vault, AI Search"]
        Gh["github.py<br/>GitHub App tokens, contents, refs, checks"]
        Fx["fixtures.py<br/>offline evidence for laptops and tests"]
        OpsC["OpsClient<br/>Ops Service, agent key"]
    end

    P --> Az & Gh
    E --> Gh
    R --> OpsC
    P & E --> Fx
    Aud --> Events["Event store<br/>Blob, or a local folder"]
```

| Module | Responsibility |
| --- | --- |
| `main.py` | Starts the three MCP servers, the `KeyGuard` (authentication per endpoint), host checks and `/health` |
| `entra_auth.py` | Entra mode: validates a token's signature, audience, issuer, `oid` and app role for each endpoint |
| `planner_tools.py` | The nine read-only evidence tools, and the paths the Planner may read |
| `engineer_tools.py` | The six branch-only tools, the write allowlist and patch-size limits |
| `recovery_tools.py` | The two recovery tools and the Ops Service client; forwards the grant, never records it |
| `guard.py` | Allowlists, protected paths, the result envelope, redaction, refusals as results, the audit record |
| `livefire_events.py` | The drill event log (`blob:` in Azure, `dir:` locally), shared with the other workstreams |
| `backends/` | Where data comes from: Azure, GitHub, or fixtures for offline runs |

## 4. How it is used during a drill

The drill's agents reach WS3 at four moments. This is the Autonomous Twin flow.

```mermaid
sequenceDiagram
    autonumber
    participant DR as Drill Runner (WS4)
    participant PL as Planner agent
    participant RC as Recovery agent
    participant EN as Engineer agent
    participant MCP as MCP server (WS3)
    participant OPS as Ops Service (WS2)
    participant REF as Referee (WS2)

    DR->>DR: Baseline order passes, fault injected, order fails
    DR->>PL: Investigate (drill_id, catalog)
    PL->>MCP: /planner: telemetry, identity, secrets, config, network, history, runbook
    MCP-->>PL: Evidence (untrusted, redacted, sourced)
    PL-->>DR: Diagnosis, options, ordered recovery plan
    DR->>DR: Policy check, pre-authorization, issue single-use grant
    DR->>RC: Execute approved action (grant)
    RC->>MCP: /recovery: execute_recovery(action, grant), check_recovery
    MCP->>OPS: POST /actions/recover (agent key, grant)
    OPS-->>MCP: ok, then drift: ok
    MCP-->>RC: Result (grant never echoed or logged)
    DR->>REF: Order journey after restore
    REF-->>DR: Journey result
    DR->>PL: Explain the result
    PL->>MCP: /planner: source code, commit history, runbook
    PL-->>DR: Remediation brief (allowed paths, acceptance criteria)
    DR->>EN: Make the change
    EN->>MCP: /engineer: branch, read, test, patch, runbook
    MCP-->>EN: Commits on candidate/drill-…-1 only
    DR->>DR: CI, deploy candidate, Referee passes, verdict VERIFIED
```

### One evidence call, in detail

```mermaid
sequenceDiagram
    autonumber
    participant PL as Planner agent (Foundry)
    participant KG as KeyGuard
    participant T as Planner tool
    participant G as guard.py
    participant AZ as Azure (Log Analytics)
    participant EV as Evidence store

    PL->>KG: POST /planner/mcp tools/call query_incident_telemetry
    KG->>KG: Credential belongs to /planner?
    KG->>T: Yes: dispatch
    T->>T: Schema check: drill_id pattern, signal enum, minutes 1-120
    T->>AZ: Fixed KQL template (no free-form query)
    AZ-->>T: Rows
    T->>G: envelope(source, rows)
    G->>G: Redact secrets, cap size, mark untrusted
    G->>EV: planner.tool_call (allow, caller, source, tool_version, latency)
    G-->>PL: {source, untrusted_content, redaction, tool_version, authorization, data}
```

### A refused call

```mermaid
sequenceDiagram
    autonumber
    participant EN as Engineer agent
    participant MCP as MCP server
    participant EV as Evidence store

    EN->>MCP: apply_patch(path = journeys/order.spec.ts)
    MCP->>MCP: Protected path: refuse before touching GitHub
    MCP->>EV: engineer.tool_call (deny, reason)
    MCP-->>EN: {refused: true, error: "journeys/... is a protected path"}
    Note over EN,MCP: A readable result, not an MCP error, so the agent can correct itself
    EN->>MCP: Planner credential on /engineer/mcp
    MCP->>EV: deny event under the caller's role
    MCP-->>EN: HTTP 403
```

### The recovery grant

```mermaid
sequenceDiagram
    autonumber
    participant DR as Drill Runner (WS4)
    participant RC as Recovery agent
    participant MCP as /recovery/mcp (WS3)
    participant OPS as Ops Service (WS2)

    DR->>DR: Approved action, sign grant (RECOVERY_GRANT_KEY): one drill, one action, 10 min, once
    DR->>RC: Task with the grant
    RC->>MCP: execute_recovery(action, grant)
    MCP->>OPS: POST /actions/recover {drill_id, action, grant} with OPS_AGENT_KEY
    OPS->>OPS: Verify signature, drill, action, expiry, unused
    OPS-->>MCP: 200 ok (or 422 refused, with the reason)
    MCP-->>RC: {result: ok | refused, details}
    Note over MCP: WS3 never holds the signing key: it can't forge, widen or check a grant, and never logs it
```

## 5. Azure deployment

```mermaid
flowchart TB
    subgraph Control["Control resource group"]
        CAE["Container Apps environment (WS2)"]
        MCP["ca-mcp<br/>Container App, 1-2 replicas"]
        ID["id-lf-mcp<br/>user-assigned managed identity"]
        PULL["id-lf-acrpull<br/>pull identity (WS2)"]
        ACR["Container Registry (WS2)"]
        KV["Control Key Vault (WS2)<br/>endpoint keys, GitHub App keys, ops-agent-key"]
        ST["Evidence storage (WS2)<br/>drill event logs"]
        SRCH["Azure AI Search (WS3)<br/>index: incidents"]
        OPS["ca-ops: Ops Service (WS2)"]
        FDY["Foundry project (WS4)<br/>agents and MCP connections"]
        CAE --> MCP
        MCP -. "identity" .-> ID
        MCP -. "pull image" .-> PULL --> ACR
    end

    subgraph Twin["Twin resource group (WS1)"]
        TKV["Twin Key Vault<br/>db-password"]
        LAW["Log Analytics + App Insights"]
        SQL["Azure SQL server"]
        APP["ca-order: order service"]
    end

    Entra["Microsoft Entra ID<br/>livefire-mcp app roles (Entra mode)"]
    GH["GitHub<br/>two GitHub Apps"]

    ID -->|"Key Vault Secrets User"| KV
    ID -->|"Storage Blob Data Contributor"| ST
    ID -->|"Search Index Data Reader"| SRCH
    ID -->|"Log Analytics Reader"| LAW
    ID -->|"Reader + Key Vault Reader: metadata only"| TKV
    ID -->|"Reader"| SQL
    ID -->|"Reader"| APP
    MCP -->|"internal URL, agent key"| OPS
    FDY -->|"MCP over HTTPS"| MCP
    MCP -->|"App installation tokens"| GH
    Entra -. "tokens for agent identities" .-> FDY
```

The container has **no secret in its configuration**: the endpoint keys, the GitHub App private keys and the Ops key
are Key Vault references resolved by Container Apps with the managed identity. Its Azure reads use the same identity.
The deployer also gets Search roles, to load the index after each rebuild.

## 6. Azure services WS3 uses, and why

| Service | What WS3 uses it for | Why it's needed |
| --- | --- | --- |
| **Azure Container Apps** | Hosts `ca-mcp` (0.5 vCPU, 1 GiB, 1–2 replicas, HTTPS ingress) in the platform's environment | Managed HTTPS endpoint with managed identity and Key Vault references, so no secret is baked in; the same environment as the Ops Service, which the recovery tools reach on its internal URL |
| **Managed identity** (`id-lf-mcp`) | Every Azure call the server makes, and resolving its secrets | No credentials in code or configuration; least-privilege roles scoped to exactly the resources the tools read |
| **Azure Container Registry** | Stores the `mcp-server:sha-<commit>` image, pulled by a pull-only identity | Private, immutable, scanned images; CI pushes through OIDC, so GitHub stores no Azure secret |
| **Azure Key Vault** (control) | Endpoint keys, GitHub App private keys, `ops-agent-key` | Credentials never leave Key Vault or reach the agents; rotation is a Key Vault change |
| **Azure Key Vault** (twin) | `get_secret_metadata`: versions and timestamps of `db-password`, never the value (Key Vault Reader) | Shows *when* a secret changed, without ever showing a secret |
| **Azure Monitor: Log Analytics and Application Insights** | `query_incident_telemetry`: fixed KQL templates over requests, exceptions, dependencies, metrics and SQL errors | The Planner needs real telemetry, tied to the drill ID; fixed queries stop free-form or exfiltrating queries |
| **Azure Resource Manager** | `get_identity_snapshot` (role assignments on the twin vault), `get_app_configuration` (revisions and non-secret settings), `get_network_rules` (SQL firewall) | Current resource state for the Planner to compare; read-only roles on exactly those resources |
| **Azure AI Search** | The `incidents` index: curated incidents and runbooks, keyword and hybrid (vector) retrieval, filtered to the order service and optionally a date range | Grounds the Planner in prior incidents with provenance and a retrieval score, from a bounded corpus rather than the open web |
| **Azure OpenAI embeddings (via Foundry, WS4)** | The search index's vectorizer embeds queries for hybrid retrieval | Matches by meaning that keyword search misses |
| **Azure Blob Storage** (evidence) | Appends one `*.tool_call` event per call to `<drill_id>/events.jsonl` | One shared, append-only drill log that the Control Center, the evidence package and the scorecard all read |
| **Microsoft Entra ID** | Entra mode: the `livefire-mcp` app registration, the app roles `MCP.Planner`, `MCP.Engineer`, `MCP.Recovery`, each assigned to one agent identity | Each agent authenticates as itself, with no shared key; a person's own token is refused |
| **Microsoft Foundry (WS4)** | The caller: each agent has one MCP tool pointed at its endpoint, through a project connection | Agents reach tools only through MCP; the connection holds the credential, never the agent |
| **OpenTelemetry → Application Insights** | A span per tool call (endpoint, tool, decision, version) | Tool calls appear in the same trace as the model calls, for the demo and for diagnosis |

## 7. The tools, and why each exists

### Planner: read-only evidence (`/planner/mcp`)

| Tool | Reads | Why the Planner needs it |
| --- | --- | --- |
| `query_incident_telemetry` | Log Analytics (fixed queries; `sql_errors` groups failed orders by SQL error number) | Shows *that* customers fail and with which errors |
| `get_identity_snapshot` | Role assignments on the twin vault | The identity's current access to the vault |
| `get_secret_metadata` | Versions of the twin's `db-password` | When each secret version was created |
| `get_app_configuration` | The order app's revisions and their differences from the desired settings | Which settings differ from the desired state, and since which revision |
| `get_network_rules` | The SQL server's firewall rules | The current firewall rules |
| `search_incident_history` | AI Search incidents and runbooks | Prior incidents and runbooks, with provenance |
| `read_runbook` | A runbook at the pinned commit, with its checksum | What the procedure says |
| `read_repository_context` | Allowed source and docs at the pinned commit, with checksum | How the code behaves |
| `get_commit_history` | Recent commits touching an allowed path | When and why a file changed |

### Engineer: branch-only changes (`/engineer/mcp`)

| Tool | Does | Why |
| --- | --- | --- |
| `create_candidate_branch` | Creates `candidate/<drill_id>-<attempt>` from the pinned base commit | Every change is isolated, reviewable and kept as evidence; never `main` |
| `read_allowed_files` | Reads up to 5 allowed files (base or its own branch) | The minimum context to write a fix, nothing more |
| `apply_patch` | Commits the full new content of one file allowed by `ENGINEER_WRITE_PATHS` (≤ 200 lines changed) | The change itself, bounded in place and size |
| `write_regression_test` | Commits `src/order-service/tests/test_*.py` | Keeps the change covered by a test |
| `update_runbook` | Commits a runbook change | Keeps the procedure in step with the change |
| `get_ci_results` | Reads the candidate's GitHub Actions status | Lets the Engineer react to its own CI failure on attempt 2 |

### Recovery: grant-gated execution (`/recovery/mcp`)

| Tool | Does | Why |
| --- | --- | --- |
| `execute_recovery` | Asks the Ops Service to run one approved action, with its single-use grant | The agent carries out recovery itself, but only exactly what a person or policy approved |
| `check_recovery` | Asks whether the twin matches its desired state (ok or drift, never which part) | Confirms the action worked without handing the diagnosis to the wrong agent |

### Developer and operator tools in this folder

| Tool | Why it exists |
| --- | --- |
| **Python 3.12, MCP SDK, Starlette, uvicorn** | The server: MCP streamable HTTP in stateless JSON mode, so any HTTP client or Foundry can call it without a session |
| **Docker and Docker Compose** | The same image locally and in Azure; `scripts/run-local.sh` runs the server and a stand-in Ops Service with no Azure |
| **GitHub Apps** (Planner: read; Engineer: contents write, actions read) | Short-lived installation tokens per role, scoped to one repository; the agents never see them |
| **GitHub rulesets and CODEOWNERS** | `main` needs a reviewed pull request and passing checks; candidate branches can't be deleted; neither GitHub App can bypass them (only repo admins, and only through a pull request) |
| **GitHub Actions + Bandit, Semgrep, pip-audit, gitleaks, Trivy** | Free security gates on every change (no GitHub Advanced Security needed), then an OIDC push to the private registry |
| **Bicep** | `mcp.bicep` and `mcp-twin-access.bicep`: the app, identity, search service and exactly the roles above, reproducibly |
| **pytest** (68 tests) | Endpoint isolation, allowlists, redaction, the envelope, audit fields, refusals, the grant path, Entra validation, and a contract check |
| **`export-tool-schemas.py`** | Publishes every tool's schema from the code; a test fails if the published contract drifts |
| **`fake-ops.py`** | Lets anyone test the recovery path offline with the same wire contract as the real Ops Service |

## 8. Design decisions

| Decision | Reason |
| --- | --- |
| **Three endpoints, one container** | Separate registries and credentials give least privilege per agent; one deployment keeps it cheap and simple. The blueprint allows either. |
| **Agents hold no credentials** | The MCP server holds them (in Key Vault) and enforces policy server-side, so a prompt-injected agent still can't exceed its tools. |
| **Fixed queries and allowlists, not free-form access** | An agent can't widen what it reads or writes by asking cleverly. |
| **Every result marked untrusted, and redacted** | Tool output can contain hostile text (T-08). The agents treat it as data; secrets never enter model context. |
| **Refusals are results, not errors** | Foundry fails the whole agent turn on an MCP error; a readable refusal lets the agent correct itself, and it is still audited. |
| **The grant is verified downstream, not by WS3** | WS3 can't forge or widen what it can't sign; compromising WS3 doesn't grant recovery authority. |
| **Arguments hashed in the audit, never stored** | The audit proves what happened without copying payloads (or a grant) into logs. |
| **Stateless MCP over HTTP** | Any replica can serve any call; scaling and restarts lose nothing. |
| **Fixtures backend** | The full server runs offline, so tests, demos and other teams don't need Azure. |

## 9. Security boundaries at a glance

```mermaid
flowchart LR
    subgraph Untrusted["Untrusted"]
        Agent["AI agent output<br/>tool arguments"]
        Data["Logs, incidents, repo text<br/>tool results"]
    end
    subgraph WS3B["WS3 enforcement"]
        Auth["Authenticate per endpoint"]
        Schema["Schema + allowlist"]
        Wrap["Untrusted wrapper + redaction"]
        Audit["Audit every call"]
    end
    subgraph Downstream["Independent controls"]
        OpsV["Ops Service<br/>grant verification"]
        Policy["Azure Policy<br/>denies broad roles"]
        Rules["GitHub rulesets<br/>protect main"]
        CI["CI gates"]
    end
    Agent --> Auth --> Schema
    Schema --> OpsV --> Policy
    Schema --> Rules --> CI
    Data --> Wrap --> Agent
    Auth & Schema & Wrap --> Audit
```

WS3 is one layer of defence, not the only one: even if WS3 were bypassed, the Ops Service still verifies every grant,
Azure Policy still denies broad roles, GitHub rulesets still protect `main`, and CI still gates every candidate.

## 10. Further reading

- [README-WS3.md](../README-WS3.md): running it and deploying it.
- [contracts/mcp-contract.md](../contracts/mcp-contract.md): how other workstreams call it.
- [contracts/mcp-tools.md](../contracts/mcp-tools.md) and [contracts/mcp-tools.schema.json](../contracts/mcp-tools.schema.json):
  the per-tool contract and schemas.
