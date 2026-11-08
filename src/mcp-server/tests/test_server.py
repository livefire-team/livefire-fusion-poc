import asyncio
import json

import httpx
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from conftest import ENGINEER_KEY, PLANNER_KEY

DRILL = "drill-test-0001"


def run(coro):
    return asyncio.run(coro)


async def session_call(url, key, calls):
    transport = streamable_http_client(url, http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {key}"}))
    async with Client(transport) as client:
        out = []
        for name, args in calls:
            if name == "list":
                out.append(sorted(t.name for t in (await client.list_tools()).tools))
            else:
                out.append(await client.call_tool(name, args))
        return out


def data(result):
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


def test_each_endpoint_lists_only_its_own_tools(server):
    planner, = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [("list", None)]))
    engineer, = run(session_call(server["url"] + "/engineer/mcp", ENGINEER_KEY, [("list", None)]))
    assert planner == ["get_app_configuration", "get_commit_history", "get_identity_snapshot", "get_network_rules",
                       "get_secret_metadata", "query_incident_telemetry", "read_repository_context", "read_runbook",
                       "search_incident_history"]
    assert engineer == ["apply_patch", "create_candidate_branch", "get_ci_results", "read_allowed_files",
                        "update_runbook", "write_regression_test"]


def test_planner_tools_return_labelled_redacted_evidence(server):
    tele, ident, search, runbook, doc, commits = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [
        ("query_incident_telemetry", {"drill_id": DRILL, "signal": "exceptions", "minutes": 30}),
        ("get_identity_snapshot", {"drill_id": DRILL}),
        ("search_incident_history", {"drill_id": DRILL, "query": "certificate renewal"}),
        ("read_runbook", {"drill_id": DRILL, "name": "order-service-keyvault-recovery"}),
        ("read_repository_context", {"drill_id": DRILL, "path": "src/order-service/README.md"}),
        ("get_commit_history", {"drill_id": DRILL, "path": "src/order-service/app/main.py"}),
    ]))
    t = data(tele)
    assert t["untrusted_content"] is True and t["data"]["row_count"] == 2
    assert data(ident)["data"]["has_secrets_user_role"] is False
    assert data(search)["data"]["results"][0]["id"] == "EX-102"
    assert "Example runbook" in data(runbook)["data"]["content"]
    assert "Password=[redacted]" in data(doc)["data"]["content"] and "Example-Not-Real" not in json.dumps(data(doc))
    assert data(commits)["data"]["commits"][0]["message"].startswith("refactor(example)")


def test_planner_cannot_read_docs_or_test_oracles(server):
    """v2.3 (POC ADR-004 and WS2's hand-off): docs/, CLAUDE.md and the paths holding the smoke tests' expected results
    stay off the Planner's allowlist, so the agents can't read the demo script or the answers."""
    paths = ["docs/architecture.md", "docs/handoffs.md", "CLAUDE.md", "CLAUDE.local.md", "src/ops-service/ops/main.py",
             "referee/assert_order.py", "scripts/drill.sh", "src/order-service/../../docs/ADR.md"]
    results = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY,
                               [(tool, {"drill_id": DRILL, "path": p}) for p in paths
                                for tool in ("read_repository_context", "get_commit_history")]))
    assert all(data(r)["refused"] for r in results), [data(r) for r in results if not data(r).get("refused")]


def test_planner_refuses_bad_paths_and_arguments(server):
    traversal, protected, bad_id, too_long = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, [
        ("read_repository_context", {"drill_id": DRILL, "path": "../etc/passwd"}),
        ("read_repository_context", {"drill_id": DRILL, "path": "journeys/test_order_journey.py"}),
        ("get_identity_snapshot", {"drill_id": "not-a-drill"}),
        ("query_incident_telemetry", {"drill_id": DRILL, "signal": "exceptions", "minutes": 500}),
    ]))
    # A refusal by the tool itself is a normal result the agent can act on (Foundry fails the turn on an MCP error);
    # an argument the schema rejects is still an MCP error
    assert data(traversal)["refused"] and data(protected)["refused"] and "outside" in data(protected)["error"]
    assert bad_id.is_error and too_long.is_error


def test_engineer_can_only_change_allowed_paths_on_its_branch(server):
    url = server["url"] + "/engineer/mcp"
    small = "\n".join(["x = 1"] * 5)
    huge = "\n".join(f"line_{i} = {i}" for i in range(400))
    branch, base, patch, journey, test_bad, test_ok, too_big, ci = run(session_call(url, ENGINEER_KEY, [
        ("create_candidate_branch", {"drill_id": DRILL, "attempt": 1}),
        ("read_allowed_files", {"drill_id": DRILL, "paths": ["src/order-service/app/example.py"]}),
        ("apply_patch", {"drill_id": DRILL, "attempt": 1, "message": "change the example module",
                         "path": "src/order-service/app/example.py", "content": small}),
        ("apply_patch", {"drill_id": DRILL, "attempt": 1, "message": "make the journey pass",
                         "path": "journeys/test_order_journey.py", "content": "def test(): pass"}),
        ("write_regression_test", {"drill_id": DRILL, "attempt": 1, "path": "src/order-service/app/hack.py",
                                   "content": "def test_x(): pass"}),
        ("write_regression_test", {"drill_id": DRILL, "attempt": 1,
                                   "path": "src/order-service/tests/test_example_change.py",
                                   "content": "def test_recovers():\n    assert True\n"}),
        ("apply_patch", {"drill_id": DRILL, "attempt": 1, "message": "rewrite everything",
                         "path": "src/order-service/app/example.py", "content": huge}),
        ("get_ci_results", {"drill_id": DRILL, "attempt": 1}),
    ]))
    assert data(branch)["data"]["branch"] == f"candidate/{DRILL}-1"
    assert "class Example" in data(base)["data"]["files"]["src/order-service/app/example.py"]
    assert data(patch)["data"]["changed_lines"] > 0
    assert data(journey)["refused"] and "protected" in data(journey)["error"]
    assert data(test_bad)["refused"] and not data(test_ok).get("refused")
    assert data(too_big)["refused"] and "limit" in data(too_big)["error"]
    assert data(ci)["data"]["conclusion"] == "success"


def test_keys_are_bound_to_their_endpoint_and_cross_use_is_recorded(server):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "apply_patch", "arguments": {"drill_id": DRILL}}}
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    none = httpx.post(server["url"] + "/engineer/mcp", json=body, headers=headers)
    cross = httpx.post(server["url"] + "/engineer/mcp", json=body,
                       headers={**headers, "Authorization": f"Bearer {PLANNER_KEY}"})
    assert none.status_code == 401 and cross.status_code == 403
    events = [json.loads(l) for l in (server["evidence"] / DRILL / "events.jsonl").read_text().splitlines()]
    assert any(e["result"] == "deny" and "refused on /engineer" in e["details"]["summary"] for e in events)
    assert any(e["action"] == "planner.tool_call" and e["result"] == "allow" for e in events)


def test_tool_schemas_avoid_constructs_foundry_rejects(server):
    import main
    from mcp import Client

    async def schemas():
        out = {}
        for srv in (main.planner, main.engineer):
            async with Client(srv) as c:
                out.update({t.name: json.dumps(t.input_schema) for t in (await c.list_tools()).tools})
        return out
    for name, schema in run(schemas()).items():
        assert not any(k in schema for k in ("anyOf", "allOf", "oneOf", "$ref")), name


def test_requests_for_another_host_are_rejected(server):
    r = httpx.post(server["url"] + "/planner/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Authorization": f"Bearer {PLANNER_KEY}", "Host": "evil.example",
                            "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    assert r.status_code in (400, 421)


def test_read_runbook_accepts_the_name_the_file_name_or_the_path(server):
    # An agent may pass the bare name, the file name or the path; refusing any of them would end its turn
    names = ["order-service-keyvault-recovery", "order-service-keyvault-recovery.md",
             "runbooks/order-service-keyvault-recovery.md"]
    results = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY,
                               [("read_runbook", {"drill_id": DRILL, "name": n}) for n in names]
                               + [("read_runbook", {"drill_id": DRILL, "name": "../../etc/passwd"})]))
    for r in results[:3]:
        assert data(r)["data"]["path"] == "runbooks/order-service-keyvault-recovery.md"
    assert data(results[3])["refused"] and "not a runbook name" in data(results[3])["error"]
