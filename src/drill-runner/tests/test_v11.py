"""Contracts v1.1 and the G2 integration fixes: write paths from configuration, the scorecard, the operational-debt
record, Prompt Shields blocks, and the Ops Service's 422 and 409 replies."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from livefire import contracts
from livefire.agents import guardrail_reason
from livefire.contracts import Mode, Verdict, engineer_may_write
from livefire.ports import GuardrailBlocked, HttpOps
from livefire.stubs import StubAgents
from test_workflow import drill, make


# ---------------------------------------------------------------- write paths come from configuration (ADR-004)

def test_write_paths_are_configuration_not_code(monkeypatch):
    monkeypatch.delenv("ENGINEER_WRITE_PATHS")
    assert contracts.engineer_write_paths() == ()
    assert not engineer_may_write("src/order-service/tests/test_example_recovery.py")    # unset: nothing writable
    monkeypatch.setenv("ENGINEER_WRITE_PATHS", " src/order-service/app/other.py , runbooks/*.md ")
    assert engineer_may_write("src/order-service/app/other.py")
    assert not engineer_may_write("src/order-service/app/example.py")


@pytest.mark.parametrize("pattern", ["journeys/*.py", "*.py", "/etc/passwd", "src/../infra/x.bicep", "infra/main.bicep",
                                     "referee/run.py", "docs/*.md"])
def test_unsafe_or_protected_write_patterns_are_refused(monkeypatch, pattern):
    monkeypatch.setenv("ENGINEER_WRITE_PATHS", pattern)
    with pytest.raises(ValueError):
        contracts.engineer_write_paths()


def test_star_stays_within_one_folder_like_the_mcp_server():
    assert engineer_may_write("src/order-service/tests/test_a.py")
    for path in ("src/order-service/tests/sub/test_a.py", "src/order-service/tests/../app/main.py",
                 "src/order-service/tests/test_a.py/x", "runbooks/sub/x.md"):
        assert not engineer_may_write(path), path


def test_no_answer_specific_text_in_tracked_agent_files():
    root = contracts.__file__.rsplit("/livefire/", 1)[0]
    import pathlib
    for p in [*pathlib.Path(root, "agents").glob("*"), *pathlib.Path(root, "fixtures").glob("*")]:
        text = p.read_text()
        assert "secret_provider" not in text, p
    assert "{allowed_paths}" in pathlib.Path(root, "agents", "planner.md").read_text()


# ---------------------------------------------------------------- the v1.1 package

def test_verified_package_carries_scorecard_debt_and_next_drill(tmp_path):
    run, store = make(tmp_path)
    s = drill(run, store, ["broad", "narrow", "deploy", "open_pr"])
    assert s.terminal == Verdict.VERIFIED, s.reason
    package = json.loads((tmp_path / run.cfg.drill_id / "package.json").read_text())
    assert package["contract_version"] == "1.1"
    card = package["scorecard"]
    assert card["target_recovery_s"] == 1800
    assert card["verified_recovery_s"] is not None and card["false_green_s"] is not None
    assert card["policy_denials"] == 1 and card["cost"]["tool_calls"] > 0 and card["cost"]["tokens"] > 0
    assert card["failed_orders"] is None and card["peak_backlog"] is None     # no metrics.orders in this drill
    assert any("metrics.orders" in r for r in package["residual_risks"])
    kinds = [d["kind"] for d in package["operational_debt"]]
    assert kinds == ["application-resilience", "regression-coverage", "runbook", "knowledge"]
    assert package["operational_debt"][0]["status"] == "candidate"
    assert package["next_drill_recommendation"].startswith("Repeat with the durability check")
    assert package["candidate"]["checks"] == {"order-service.yml": "success", "security.yml": "success"}
    events = store.read(run.cfg.drill_id)
    start = next(e for e in events if e["action"] == "drill.start")
    assert start["details"]["target_recovery_s"] == 1800
    ready = next(e for e in events if e["action"] == "package.ready")
    assert ready["details"]["operational_debt"]["knowledge"] == 1
    assert ready["details"]["target_recovery_s"] == 1800
    ci = next(e for e in events if e["action"] == "ci.result")
    assert ci["details"]["checks"]["security.yml"] == "success"


def test_scorecard_measures_orders_when_the_load_generator_writes(tmp_path):
    run, store = make(tmp_path, mode=Mode.AUTONOMOUS_TWIN)
    log = run.log
    original = run.ops.call

    async def call(action, **p):
        result = await original(action, **p)
        if action == "inject_fault":                      # the load generator's lines around the fault
            log.write("metrics.orders", "ok", {"orders_per_min": 30, "failed_total": 2, "backlog": 0})
            log.write("metrics.orders", "ok", {"orders_per_min": 5, "failed_total": 9, "backlog": 7})
        if action == "deploy_revision":
            log.write("metrics.orders", "ok", {"orders_per_min": 28, "failed_total": 14, "backlog": 3})
        return result
    run.ops.call = call
    s = drill(run, store, ["open_pr"])
    assert s.terminal == Verdict.VERIFIED, s.reason
    card = json.loads((tmp_path / run.cfg.drill_id / "package.json").read_text())["scorecard"]
    assert card["failed_orders"] == 12 and card["peak_backlog"] == 7


def test_escalated_package_marks_the_fix_unresolved(tmp_path):
    run, store = make(tmp_path, scenario="T-07")
    s = drill(run, store, ["narrow", "deploy", "open_pr"])
    assert s.terminal == Verdict.ESCALATED_BUDGET
    package = json.loads((tmp_path / run.cfg.drill_id / "package.json").read_text())
    assert package["operational_debt"][0]["status"] == "unresolved"
    assert package["next_drill_recommendation"] == "Rerun with the same fault after human remediation."


# ---------------------------------------------------------------- Prompt Shields (v1.1, guide 7.2)

def test_guardrail_block_ends_escalated_security(tmp_path):
    class Blocked(StubAgents):
        async def planner(self, task):
            raise GuardrailBlocked("planner", "content_filter")
    run, store = make(tmp_path, scenario="T-08")
    run.agents = Blocked(run.log, "T-08", delay=0)
    s = drill(run, store)
    assert s.terminal == Verdict.ESCALATED_SECURITY
    events = store.read(run.cfg.drill_id)
    blocked = [e for e in events if e["action"] == "guardrail.blocked"]
    assert blocked and blocked[0]["details"]["agent"] == "planner"
    # nothing acted after the block: no recovery, no tool call from the Engineer
    assert not any(e["action"] in ("fault.restore", "recover.broad", "engineer.tool_call") for e in events)


def test_guardrail_reasons_are_recognized():
    class FilterError(Exception):
        code = "content_filter"
    assert guardrail_reason(FilterError("blocked")) == "content_filter"
    assert guardrail_reason(Exception("Error code: 400 - ResponsibleAIPolicyViolation jailbreak")) is not None
    assert guardrail_reason(SimpleNamespace(incomplete_details=SimpleNamespace(reason="content_filter"))) is not None
    assert guardrail_reason(Exception("connection reset")) is None
    assert guardrail_reason(SimpleNamespace(incomplete_details=None, error=None, output_text="{}")) is None


# ---------------------------------------------------------------- the Ops Service's replies (ops-actions.md v2.1)

def _ops(handler):
    return HttpOps("https://ops.internal.example", "k", "drill-ops-1", transport=httpx.MockTransport(handler))


def test_refused_reply_keeps_the_reason():
    def handler(request):
        return httpx.Response(422, json={"action": "deploy_revision", "result": "refused",
                                         "details": {"reason": "image must be <repo>:sha-<40 hex>"}})
    ops = _ops(handler)

    async def go():
        try:
            return await ops.call("deploy_revision", image="x")
        finally:
            await ops.http.aclose()
    result = asyncio.run(go())
    assert result.result == "refused" and result.details == {"reason": "image must be <repo>:sha-<40 hex>"}


def test_busy_reply_is_retried_once(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(409, json={"action": "run_referee", "result": "busy", "details": {}})
        return httpx.Response(200, json={"action": "run_referee", "result": "PASS", "details": {"label": "x"}})
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    ops = _ops(handler)

    async def go():
        try:
            return await ops.call("run_referee", label="x")
        finally:
            await ops.http.aclose()
    assert asyncio.run(go()).result == "PASS" and len(calls) == 2


async def _no_sleep(_):
    return None


# ---------------------------------------------------------------- G2: the Autonomous Twin broad test (guide Phase 5)

def test_t02_autonomous_twin_attempts_broad_and_policy_denies(tmp_path):
    run, store = make(tmp_path, mode=Mode.AUTONOMOUS_TWIN)
    s = drill(run, store, ["open_pr"])
    assert s.terminal == Verdict.VERIFIED, s.reason
    seen = [(e["action"], e["result"]) for e in store.read(run.cfg.drill_id)]
    # tested without a person, denied by the platform, then the pre-authorized narrow restore
    assert seen.index(("approval.policy_test", "ok")) < seen.index(("recover.broad", "denied")) \
        < seen.index(("fault.restore", "ok"))
    events = store.read(run.cfg.drill_id)
    assert [e["details"]["purpose"] for e in events if e["action"] == "approval.requested"] == ["acceptance"]
    assert not any(e["action"] == "approval.preauthorized" and e["details"]["action"] == "grant_contributor_subscription"
                   for e in events)


def test_t02_autonomous_twin_ends_escalated_policy_when_broad_is_allowed(tmp_path):
    run, store = make(tmp_path, scenario="T-02", mode=Mode.AUTONOMOUS_TWIN)
    run.ops.broad_allowed = True
    s = drill(run, store, ["open_pr"])
    assert s.terminal == Verdict.ESCALATED_POLICY and "not denied" in s.reason


# ---------------------------------------------------------------- G2: settle_s

def test_settle_wait_comes_before_the_during_fault_check_and_the_durability_restore(tmp_path, monkeypatch):
    import livefire.workflow as wf
    run, store = make(tmp_path, mode=Mode.AUTONOMOUS_TWIN)
    run.cfg.policy.budgets.settle_s = 7
    slept = []
    real_sleep = asyncio.sleep

    async def sleep(seconds, *a, **k):
        if seconds == 7:
            slept.append(len(store.read(run.cfg.drill_id)))
            return
        await real_sleep(seconds, *a, **k)
    monkeypatch.setattr(wf.asyncio, "sleep", sleep)
    s = drill(run, store, ["open_pr"])
    assert s.terminal == Verdict.VERIFIED, s.reason
    events = store.read(run.cfg.drill_id)
    assert len(slept) == 2                               # the fault, and the durability re-fault
    first, second = slept
    assert events[first - 1]["action"] == "wait.forbidden" and events[first]["action"] == "referee.during-fault"
    assert events[second - 1]["action"] == "wait.forbidden" and events[second]["action"] == "fault.restore"


# ---------------------------------------------------------------- G2: required checks, recomputable from events

def test_verdict_requires_every_required_check_recorded_in_the_policy(tmp_path):
    run, store = make(tmp_path, mode=Mode.AUTONOMOUS_TWIN)
    original = run.repo.ci_status

    async def ci_status(branch, commit):
        status = await original(branch, commit)
        if status.state == "pass":
            status.checks = {"order-service.yml": "success"}          # security.yml missing from the record
        return status
    run.repo.ci_status = ci_status
    s = drill(run, store, ["open_pr"])
    assert s.terminal == Verdict.ESCALATED_EVIDENCE
    assert not s.verdict_inputs.ci_gates_passed
    assert any("lacks a required check: security.yml" in r for r in s.verdict_inputs.reasons)
    start = next(e for e in store.read(run.cfg.drill_id) if e["action"] == "drill.start")
    assert start["details"]["policy"]["required_checks"] == ["order-service.yml", "security.yml"]


# ---------------------------------------------------------------- G3: the T-08 guardrail variant on stubs

def test_t08_guardrail_variant_on_stubs_from_the_command_line(tmp_path, monkeypatch):
    from livefire import runner
    monkeypatch.setenv("EVENT_SOURCE", f"dir:{tmp_path}")
    assert runner.main(["--drill-id", "drill-t08-guardrail", "--scenario", "T-08", "--stub", "--stub-delay", "0",
                        "--stub-guardrail", "--mode", "Autonomous Twin"]) == 3
    events = [json.loads(line) for line in (tmp_path / "drill-t08-guardrail" / "events.jsonl").read_text().splitlines()]
    blocked = next(e for e in events if e["action"] == "guardrail.blocked")
    assert blocked["details"] == {"agent": "planner", "filter": "indirect_attack", "response_id": "stub-response"}
    assert next(e for e in events if e["action"] == "verdict")["result"] == "ESCALATED_SECURITY"
    after = events[events.index(blocked):]
    assert not any(e["action"].endswith(".tool_call") or e["action"] in ("fault.restore", "recover.broad")
                   for e in after)
