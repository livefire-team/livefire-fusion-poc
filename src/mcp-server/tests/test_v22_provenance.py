"""v2.2: what blueprint sections 4.4, 8.1 and A.2 ask of every tool call. Each result carries the tool version, the
authorization result and redaction metadata; each audit event the version, the caller and the source; files come
with their commit and checksum; incident search can be bounded in time."""
import hashlib
import json

from conftest import ENGINEER_KEY, PLANNER_KEY
from test_hybrid import FakeSearch, evidence
from test_server import data, run, session_call

DRILL = "drill-provenance-0001"


def events(server, drill=DRILL):
    return [json.loads(line) for line in (server["evidence"] / drill / "events.jsonl").read_text().splitlines()]


def test_every_result_carries_the_tool_version_and_the_authorization_result(server):
    ok, refused = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [
        ("get_network_rules", {"drill_id": DRILL}),
        ("read_repository_context", {"drill_id": DRILL, "path": "infra/main.bicep"})]))
    ok, refused = data(ok), data(refused)
    assert ok["tool_version"] == refused["tool_version"] == "2.4"
    assert ok["authorization"] == {"decision": "allow", "endpoint": "planner"}
    assert refused["authorization"] == {"decision": "deny", "endpoint": "planner"} and refused["refused"]
    assert ok["redaction"] == {"applied": False, "count": 0, "kinds": []}


def test_every_audit_event_names_the_version_the_caller_and_the_source(server):
    drill = "drill-provenance-0002"
    run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [("get_secret_metadata", {"drill_id": drill})]))
    run(session_call(server["url"] + "/engineer/mcp", ENGINEER_KEY, [
        ("create_candidate_branch", {"drill_id": drill, "attempt": 1})]))
    planner, engineer = (e["details"] for e in events(server, drill))
    assert planner["tool_version"] == engineer["tool_version"] == "2.4"
    assert planner["caller"] == "key:planner" and engineer["caller"] == "key:engineer"
    assert planner["source"] == "key-vault:secret-metadata"                        # where the data came from
    assert engineer["source"].startswith("github:") and "args_sha256" in planner


def test_a_file_comes_with_its_commit_and_checksum(server):
    runbook, source = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [
        ("read_runbook", {"drill_id": DRILL, "name": "order-service-keyvault-recovery"}),
        ("read_repository_context", {"drill_id": DRILL, "path": "src/order-service/app/main.py"})]))
    for result in (data(runbook)["data"], data(source)["data"]):
        assert result["ref"] == "main" and result["chars"] == len(result["content"])
        assert result["sha256"] == hashlib.sha256(result["content"].encode()).hexdigest()


def test_incident_search_can_be_bounded_in_time(server):
    september, everything, backwards, bad = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [
        ("search_incident_history", {"drill_id": DRILL, "query": "example restart certificate",
                                     "from_date": "2026-09-01", "to_date": "2026-09-30"}),
        ("search_incident_history", {"drill_id": DRILL, "query": "example restart certificate"}),
        ("search_incident_history", {"drill_id": DRILL, "query": "example", "from_date": "2026-10-01",
                                     "to_date": "2026-09-01"}),
        ("search_incident_history", {"drill_id": DRILL, "query": "example", "from_date": "2026-13-01"})]))
    hits = data(september)["data"]["results"]
    assert hits and all("2026-09-01" <= h["occurred_at"][:10] <= "2026-09-30" for h in hits)
    assert data(september)["data"]["from_date"] == "2026-09-01"
    assert any(not h["occurred_at"].startswith("2026-09") for h in data(everything)["data"]["results"])
    assert data(backwards)["refused"] and "after" in data(backwards)["error"]
    assert data(bad)["refused"] and "calendar date" in data(bad)["error"]


def test_the_azure_search_filter_bounds_occurred_at():
    search = FakeSearch()
    out = evidence(search).search_incidents("example query", 3, "2026-09-01", "2026-09-30")
    assert search.calls[0]["filter"] == ("service eq 'order-service' and occurred_at ge 2026-09-01T00:00:00Z "
                                         "and occurred_at le 2026-09-30T23:59:59Z")
    assert out[0]["score"] == 1.0                                     # the retrieval score, for provenance
