# Event catalog, v1.1

v1.1 (2026-11-12, additive): `drill.start` adds `target_recovery_s` and `agent_kind`; `ci.result` adds `checks`;
`package.ready` adds the scorecard summary, the operational-debt counts and the next-drill recommendation; new
`guardrail.blocked`. A v1.0 reader keeps working: no field was removed or renamed.

Every line of `evidence/<drill_id>/events.jsonl` is `{"ts","drill_id","action","result","details"}`.
Writers keep the events they already write: WS2's Ops Service (`reset`, `fault.inject`, `fault.restore`,
`wait.ok`, `wait.forbidden`, `recover.broad`, `referee.<label>`, `deploy.revision` with the image's `digest`), WS3's MCP server
(`planner.tool_call`, `engineer.tool_call`), the Control Center (`approval.decided`, `kill.requested`) and
WS1's load generator (`metrics.orders`).

Referee labels: `baseline`, `during-fault`, `after-restore`, `after-fix`, `after-refault` (new: the durability
check), `after-restart` (G1 manual drills only).

Events the Drill Runner writes:

| Action | Result | Details |
| --- | --- | --- |
| drill.start | ok | mode, scenario, target_recovery_s (v1.1), policy, agents (name:version), agent_kind (v1.1: prompt, hosted or stub), prompt_sha256, model_deployment, contract_version, runner_version |
| planner.options | ok | options [{id, label}], recommended, confidence, hypothesis, response_id |
| approval.requested | ok | request_id (apr-N), purpose (recovery, deploy, acceptance), options [{id, label}] |
| approval.preauthorized | ok | action, mode, policy_version |
| approval.decided | timeout | only when nobody chose in time: request_id, option_id "timeout" |
| planner.brief | ok | summary, confidence, acceptance_criteria (count), response_id |
| engineer.change_report | ok | branch, attempt, commits, changed_paths (the branch's real diff), response_id |
| ci.result | pass, fail | attempt, branch, commit (full SHA), run_url, failed [{workflow, conclusion, url, jobs}], checks (v1.1: {workflow file: conclusion}, both order-service.yml and security.yml must succeed) |
| usage | ok | agent, tokens, input_tokens, output_tokens, tool_calls, est_cost_usd, response_id |
| verdict | terminal state | reason, inputs, attempts, tokens, est_cost_usd |
| package.ready | ok, error | path, sha256, events_sha256; v1.1: verified_recovery_s, target_recovery_s, operational_debt ({kind: count}), next_drill_recommendation |
| guardrail.blocked | blocked | v1.1: agent, detail. Prompt Shields on the model deployment refused a call; the drill ends ESCALATED_SECURITY |
| package.pr | ok, rejected, no_decision, error | url, branch, approver |
| drill.end | ok, cleanup_failed | terminal, cleanup, pr_url |
