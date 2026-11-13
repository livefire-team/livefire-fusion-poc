"""Contracts v1.2 (ADR-028): the Engineer can quote the brief, the model sees every limit, and a rejected agent output
leaves an agent.output_invalid event saying which field broke which rule."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from livefire.agents import FoundryAgents, strict_schema
from livefire.contracts import ChangeReport, EvidenceRef, PlannerOutput, RemediationBrief
from livefire.ports import DependencyError

DRILL = "drill-20261113-213408"


def brief(criteria):
    return RemediationBrief(
        incident_id=DRILL,
        evidence_references=[EvidenceRef(source="referee", ref="after-restore", note="the journey failed"),
                             EvidenceRef(source="telemetry", ref="exceptions", note="auth errors after restore")],
        supported_hypothesis="h" * 618, rejected_hypotheses=["r" * 587], affected_components=["order service"],
        required_behavior="b" * 515, acceptance_criteria=criteria,
        allowed_repository_paths=["src/order-service/app/example.py"], prohibited_changes=["journeys/"],
        residual_risks=["x" * 439], confidence=0.86)


def report(**overrides):
    data = dict(drill_id=DRILL, attempt=1, branch=f"candidate/{DRILL}-1", commits=["a1304c3", "13bb775"],
                changed_paths=["src/order-service/app/example.py", "src/order-service/tests/test_example.py",
                               "runbooks/recovery.md"],
                regression_test_path="src/order-service/tests/test_example.py", runbook_path="runbooks/recovery.md",
                evidence_to_change=[{"change": "c", "evidence_ref": "after-restore", "acceptance_criterion": "a"}],
                notes="n")
    data.update(overrides)
    return data


def test_the_engineer_can_quote_every_criterion_of_the_brief_that_broke_drill_20261113_213408():
    # That run's four criteria were 494, 565, 339 and 365 characters; the change report allowed 300
    criteria = [c * n for c, n in zip("abcd", (494, 565, 339, 365))]
    b = brief(criteria)
    mapping = [{"change": "x" * 300, "evidence_ref": "after-restore", "acceptance_criterion": c}
               for c in b.acceptance_criteria]
    ChangeReport.model_validate(report(evidence_to_change=mapping, notes="n" * 900))


def test_a_brief_criterion_still_has_a_cap_and_the_report_accepts_anything_under_it():
    with pytest.raises(ValueError):
        brief(["a" * 801])
    cap = RemediationBrief.model_json_schema()["properties"]["acceptance_criteria"]["items"]["maxLength"]
    mapping = ChangeReport.model_json_schema()["$defs"]["ChangeMapping"]["properties"]
    assert mapping["acceptance_criterion"]["maxLength"] >= cap
    assert mapping["evidence_ref"]["maxLength"] >= EvidenceRef.model_json_schema()["properties"]["ref"]["maxLength"]


def _strings(node, path="$"):
    """Every free-text string or array in a strict schema, with its description."""
    if isinstance(node, dict):
        if node.get("type") in ("string", "array") and "enum" not in node:
            yield path, node.get("description", "")
        for key in ("properties",):
            for name, child in node.get(key, {}).items():
                yield from _strings(child, f"{path}.{name}")
        if "items" in node:
            yield from _strings(node["items"], f"{path}[]")
        for i, child in enumerate(node.get("anyOf", [])):
            yield from _strings(child, f"{path}|{i}")


@pytest.mark.parametrize("model", [PlannerOutput, ChangeReport])
def test_the_model_sees_a_limit_on_every_free_text_field_and_list(model):
    missing = [p for p, d in _strings(strict_schema(model)) if "Limits:" not in d]
    assert not missing, f"no limit the model can see: {missing}"
    s = json.dumps(strict_schema(model))
    for keyword in ('"maxLength"', '"minLength"', '"maxItems"', '"pattern"'):
        assert keyword not in s                       # still strict-mode safe: limits travel as words


def test_the_strict_schema_names_the_criterion_cap():
    s = strict_schema(ChangeReport)
    desc = s["properties"]["evidence_to_change"]["items"]["properties"]["acceptance_criterion"]["description"]
    assert desc == "Limits: 1 to 800 characters."


class Log:
    def __init__(self):
        self.events = []

    def write(self, action, result="ok", details=None):
        self.events.append({"action": action, "result": result, "details": details or {}})


def agents_replying(*texts):
    a = object.__new__(FoundryAgents)
    a.log, replies, a.sent = Log(), list(texts), []

    def respond(role, text, previous=None):
        a.sent.append((text, previous))
        return SimpleNamespace(id=f"resp_{len(a.sent)}", output_text=replies.pop(0), output=[],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5), error=None,
                               incomplete_details=None, status="completed")

    a._respond = respond
    return a


def too_long():
    return json.dumps(report(evidence_to_change=[{"change": "c", "evidence_ref": "after-restore",
                                                  "acceptance_criterion": "SECRET-ISH TEXT " * 60}]))


def test_an_invalid_output_is_recorded_and_the_repair_turn_can_succeed():
    a = agents_replying(too_long(), json.dumps(report()))
    out, usage = asyncio.run(a._run("engineer", {"drill_id": DRILL}, ChangeReport))
    assert out.branch == f"candidate/{DRILL}-1" and usage.tokens == 30
    [event] = a.log.events
    assert event["action"] == "agent.output_invalid" and event["result"] == "invalid"
    d = event["details"]
    assert (d["agent"], d["attempt"], d["response_id"], d["error_count"]) == ("engineer", 1, "resp_1", 1)
    assert d["errors"][0]["loc"] == "evidence_to_change.0.acceptance_criterion"
    assert "800" in d["errors"][0]["msg"]
    assert "SECRET-ISH" not in json.dumps(a.log.events)          # never the output's content
    repair, previous = a.sent[1]
    assert previous == "resp_1" and "field descriptions" in repair and "acceptance_criterion" in repair


def test_two_invalid_outputs_end_with_the_field_in_the_reason():
    a = agents_replying(too_long(), "not json at all")
    with pytest.raises(DependencyError) as err:
        asyncio.run(a._run("engineer", {"drill_id": DRILL}, ChangeReport))
    assert [e["details"]["attempt"] for e in a.log.events] == [1, 2]
    assert str(err.value).startswith("the engineer returned an invalid contract twice (")
    assert len(str(err.value)) <= 300


def test_agents_without_a_log_still_validate():
    a = agents_replying(too_long(), json.dumps(report()))
    a.log = None
    out, _ = asyncio.run(a._run("engineer", {"drill_id": DRILL}, ChangeReport))
    assert out.attempt == 1
