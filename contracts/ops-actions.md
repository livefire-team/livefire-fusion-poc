# Ops Service actions, v2.1, as implemented for G2 (WS2 implements; WS4 approves; WS4's runner and WS3's `/recovery` call)

The wire format is WS4's `ops-actions.md` v2.1. This file records what the G2 Ops Service (`src/ops-service/`)
actually does, including the parts of v2.1 that this twin does not enable yet.

`POST /actions/<action>` on `https://ca-ops.internal.<environment domain>` (internal ingress only), JSON body with
`drill_id` (`^drill-[A-Za-z0-9-]{1,64}$`) and only the keys listed below.

| Key | Secret (control vault) | May call |
| --- | --- | --- |
| `Authorization: Bearer <ops-runner-key>` | `ops-runner-key` (Drill Runner, `job-ops-smoke`) | every action; `recover` and `attempt_unsafe` without a grant (`executed_by: workflow`) |
| `Authorization: Bearer <ops-agent-key>` | `ops-agent-key` (MCP server `/recovery`) | `recover`, `attempt_unsafe` (each with a valid grant), `check_drift`; anything else is 403 |

Replies: `200 {"action", "result", "details"}`. `401` wrong or missing key. `403` agent key on another action.
`409` with `result: busy` while another mutating action runs, or `result: stopped` when the kill switch ran during
this action. `422` with `result: refused` and `details.reason`. `503` with `result: error` and `details.reason` when
Azure or the Referee gave no answer: no verdict, never a FAIL. `action` in the reply is the name called (v1 aliases
keep their names). Every reply within 210 s.

| Action | Body besides `drill_id` | Results | Event |
| --- | --- | --- | --- |
| `inject_fault` | `fault`: `identity-rbac` (default). `secret-drift`, `config-drift`, `network-drift` are refused: not enabled on this twin | ok | `fault.inject {fault, model, entries_after}` |
| `recover` | `action`: `restore_kv_secrets_user`; `grant` (agent key: required) | ok | `fault.restore {fault, action, model, noop, entries_after, executed_by, grant_id?, approved_by?}` |
| `attempt_unsafe` | `action`: `grant_contributor_subscription`; `grant` (agent key: required, purpose `policy_test`) | denied, UNEXPECTED_ALLOW | `recover.broad {action, fault, code, refused_by, executed_by, grant_id?, approved_by?, simulated?}`; when allowed, the grant is deleted at once and `removed` says whether that worked |
| `check_drift` | none | ok, drift | `drift.check {identity, secret, config, network}`; only `identity` is checked, the others are `not_checked` |
| `restore_access` | none | ok | v1 alias of `recover restore_kv_secrets_user` |
| `attempt_broad_recovery` | none | denied, UNEXPECTED_ALLOW | v1 alias of `attempt_unsafe grant_contributor_subscription` |
| `wait_for` | `state` (`ok`, `forbidden`, `conformant`, `drifted`), `timeout_s` integer 1–180, `since` (ISO 8601, optional) | ok, timeout | on ok only: `wait.ok` (ok, conformant), `wait.forbidden`, `wait.drifted`, with `seconds` since `since` |
| `run_referee` | `label` (`^[a-z][a-z0-9-]{0,31}$`) | PASS, FAIL | `referee.<label>` with the Referee result; `INCONCLUSIVE` and a 503 when the job wrote no result |
| `deploy_revision` | `image`: `<IMAGE_REPO>:sha-<40 hex>` only | ok | `deploy.revision {image, digest, revision, seconds}`; deployed as `<IMAGE_REPO>@<digest>`; another registry, repository, a movable tag or a tag missing from the registry is 422 |
| `reset_twin` | none | ok | `reset {by: workflow, access_restored, restarted or redeployed, image, rows_deleted, dependencies, seconds}` |
| `kill` | none | ok | `reset {by: kill, ...}`; never waits for the lock; an action that was in flight writes nothing more and returns 409 |

Run numbers: each `run_referee` call is run `r<n>`, where n is one more than the drill's `referee.*` events, so the
Referee's run ID is `<drill_id>-r<n>` and its files are in `<drill_id>/r<n>-<label>/` in the evidence container.

## Recovery grants

`lfg1.<payload>.<signature>`: base64url JSON payload `{v, gid, drill_id, action, purpose, exp, approved_by}`, signed
with HMAC-SHA256 over `lfg1.<payload>` using `RECOVERY_GRANT_KEY`, base64url without padding. `purpose` is `recover`
for `recover` and `policy_test` for `attempt_unsafe`. Valid for 10 minutes, accepted once: a `gid` already in the
drill's event log is refused. Refusals write `grant.refused {action, reason}`; the grant itself is never written.
Reference code: `src/ops-service/ops/grants.py` (`sign`, `verify`); WS4's runner must sign with the same function.

## Referee result additions (v1.1)

`duration_s` (number), `trace_url` (`evidence/<drill_id>/r<n>-<label>/playwright/.../trace.zip`, or null when the run
kept no trace), `browser` (`local-chromium`), `journey_commit` (the full commit baked into the Referee image),
`execution` (the job execution name).
