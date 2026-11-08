"""v2.1: the Recovery agent's endpoint. It executes approved actions through the Ops Service, with a grant."""
import asyncio
import json

import httpx
import pytest

from conftest import ENGINEER_KEY, OPS_CALLS, PLANNER_KEY, RECOVERY_KEY
from test_server import data, run, session_call

DRILL = "drill-test-recovery"
GOOD = "lfg1.good.sig"


def rpc(server, key, path, tool, arguments, rid=1):
    """The raw JSON-RPC call the Drill Runner's local client makes, without an MCP session."""
    return httpx.post(f"{server['url']}{path}", timeout=30, json={
        "jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json, text/event-stream"})


def events(server, drill=DRILL):
    path = server["evidence"] / drill / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_the_recovery_endpoint_lists_its_two_tools(server):
    tools, = run(session_call(server["url"] + "/recovery/mcp", RECOVERY_KEY, [("list", None)]))
    assert tools == ["check_recovery", "execute_recovery"]


def test_narrow_actions_recover_and_broad_ones_are_attempted(server):
    OPS_CALLS.clear()
    narrow, broad = run(session_call(server["url"] + "/recovery/mcp", RECOVERY_KEY, [
        ("execute_recovery", {"drill_id": DRILL, "action": "restore_db_secret", "grant": GOOD}),
        ("execute_recovery", {"drill_id": DRILL, "action": "open_sql_firewall_to_internet", "grant": GOOD}),
    ]))
    n, b = data(narrow), data(broad)
    assert n["source"] == "ops:recovery" and n["untrusted_content"] is True
    assert n["data"]["result"] == "ok" and n["data"]["details"]["executed_by"] == "agent"
    assert b["data"]["result"] == "denied"
    assert [(c["route"], c["drill_id"]) for c in OPS_CALLS] == [
        ("recover", DRILL), ("attempt_unsafe", DRILL)]
    assert [c["grant"] for c in OPS_CALLS] == [GOOD, GOOD]          # passed through untouched


def test_a_refusal_is_a_result_the_agent_can_read(server):
    refused, = run(session_call(server["url"] + "/recovery/mcp", RECOVERY_KEY, [
        ("execute_recovery", {"drill_id": DRILL, "action": "restore_kv_secrets_user", "grant": "lfg1.forged.sig"})]))
    out = data(refused)
    assert out["data"] == {"result": "refused", "details": {"reason": "the grant's signature is not valid"}}


def test_check_recovery_never_shows_which_area_drifted(server):
    check, = run(session_call(server["url"] + "/recovery/mcp", RECOVERY_KEY, [
        ("check_recovery", {"drill_id": DRILL})]))
    out = data(check)
    assert out["data"] == {"result": "drift"} and "secret" not in json.dumps(out)


def test_only_catalog_actions_are_accepted(server):
    bad, = run(session_call(server["url"] + "/recovery/mcp", RECOVERY_KEY, [
        ("execute_recovery", {"drill_id": DRILL, "action": "delete_resource_group", "grant": GOOD})]))
    assert bad.is_error


def test_the_grant_is_never_recorded(server):
    import base64
    signature = base64.urlsafe_b64encode(b"fake-signature-for-the-test").decode().rstrip("=")
    secret_grant = ".".join(["lfg1", base64.urlsafe_b64encode(b'{"gid":"grt-1"}').decode().rstrip("="), signature])
    run(session_call(server["url"] + "/recovery/mcp", RECOVERY_KEY, [
        ("execute_recovery", {"drill_id": DRILL, "action": "rollback_app_config", "grant": secret_grant})]))
    recorded = [e for e in events(server) if e["action"] == "recovery.tool_call"]
    assert recorded and all(e["details"]["endpoint"] == "recovery" for e in recorded)
    text = (server["evidence"] / DRILL / "events.jsonl").read_text()
    assert secret_grant not in text and signature not in text and GOOD not in text
    assert {e["details"]["tool"] for e in recorded} >= {"execute_recovery"}


def test_raw_json_rpc_returns_the_envelope_as_structured_content(server):
    r = rpc(server, RECOVERY_KEY, "/recovery/mcp", "execute_recovery",
            {"drill_id": DRILL, "action": "restore_sql_network_rule", "grant": GOOD})
    assert r.status_code == 200
    result = r.json()["result"]
    structured = result["structuredContent"]
    assert structured["source"] == "ops:recovery" and structured["data"]["result"] == "ok"
    assert result["isError"] is False


@pytest.mark.parametrize("key,path", [(RECOVERY_KEY, "/planner/mcp"), (RECOVERY_KEY, "/engineer/mcp"),
                                      (PLANNER_KEY, "/recovery/mcp"), (ENGINEER_KEY, "/recovery/mcp")])
def test_each_credential_opens_only_its_own_endpoint(server, key, path):
    r = rpc(server, key, path, "check_recovery", {"drill_id": DRILL})
    assert r.status_code == 403


def test_an_unknown_credential_is_refused(server):
    assert rpc(server, "x" * 40, "/recovery/mcp", "check_recovery", {"drill_id": DRILL}).status_code == 401


def test_unconfigured_tools_refuse_rather_than_guess(tmp_path):
    import recovery_tools
    from livefire_events import DirEventStore
    mcp = recovery_tools.build(None, DirEventStore(str(tmp_path)))
    assert "not configured" in str(asyncio.run(mcp.call_tool("check_recovery", {"drill_id": DRILL})))


def test_ops_errors_become_tool_errors():
    import recovery_tools
    from mcp.server.mcpserver.exceptions import ToolError

    def handler(request):
        return httpx.Response({"/actions/recover": 401, "/actions/check_drift": 500}.get(request.url.path, 409))
    ops = recovery_tools.OpsClient("http://ops", "a" * 40, transport=httpx.MockTransport(handler))
    for action, match in (("recover", "credential"), ("check_drift", "500"), ("attempt_unsafe", "another action")):
        with pytest.raises(ToolError, match=match):
            asyncio.run(ops.post(action, {"drill_id": DRILL}))
