"""Contracts v2.0: each fault leaves its own evidence, and no result ever names the fault. The fault sets here are
neutral placeholders (fixtures/planner.json); the drill's real evidence sets stay out of this public repo (ADR-004)."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from conftest import ENGINEER_KEY, PLANNER_KEY, WRITE_PATHS
from test_server import data, run, session_call

FAULTS = ("example-fault-a", "example-fault-b")
NEW_TOOLS = ("get_secret_metadata", "get_app_configuration", "get_network_rules")


def start(server, drill, fault):
    """The drill.start event the Drill Runner writes; the fixtures backend reads the fault from it."""
    d = server["evidence"] / drill
    d.mkdir(exist_ok=True)
    (d / "events.jsonl").write_text(json.dumps({"ts": "2026-10-26T09:29:00Z", "drill_id": drill,
                                                "action": "drill.start", "result": "ok",
                                                "details": {"fault": fault, "mode": "Autonomous Twin"}}) + "\n")


def evidence(server, fault):
    drill = f"drill-v2-{fault}"
    if fault is not None:
        start(server, drill, fault)
    calls = [("query_incident_telemetry", {"drill_id": drill, "signal": "sql_errors"}),
             ("query_incident_telemetry", {"drill_id": drill, "signal": "dependencies"}),
             ("get_identity_snapshot", {"drill_id": drill}),
             *[(t, {"drill_id": drill}) for t in NEW_TOOLS]]
    out = run(session_call(server["url"] + "/planner/mcp", PLANNER_KEY, calls))
    return [data(r) for r in out]


@pytest.mark.parametrize("fault", FAULTS)
def test_every_result_is_untrusted_and_never_names_the_fault(server, fault):
    results = evidence(server, fault)
    assert all(r["untrusted_content"] is True for r in results)
    text = json.dumps(results)
    for name in FAULTS:
        assert name not in text


def test_each_fault_set_replaces_only_the_evidence_it_holds(server):
    base, a, b = evidence(server, None), evidence(server, "example-fault-a"), evidence(server, "example-fault-b")
    assert base[0]["data"]["rows"] == [] and a[0]["data"]["rows"] and b[0]["data"]["rows"] == []
    assert base[2]["data"]["has_secrets_user_role"] is False and a[2]["data"]["has_secrets_user_role"] is True
    assert base[4]["data"]["differences_from_desired"] == [] == a[4]["data"]["differences_from_desired"]
    assert b[4]["data"]["differences_from_desired"] == [{"name": "EXAMPLE_SETTING", "desired": "a", "current": "b"}]
    assert base[5]["data"] == a[5]["data"] == b[5]["data"]          # neither set touches the network rules


def test_a_fault_the_fixture_has_no_set_for_gets_the_default_set(server):
    assert evidence(server, "unknown-fault")[2]["data"]["has_secrets_user_role"] is False


def test_secret_metadata_never_carries_a_value(server):
    for fault in (None, *FAULTS):
        for v in evidence(server, fault)[3]["data"]["versions"]:
            assert set(v) == {"version", "created", "updated", "enabled", "current"}


def test_the_engineer_endpoint_has_none_of_the_new_tools(server):
    tools, *calls = run(session_call(server["url"] + "/engineer/mcp", ENGINEER_KEY,
                                     [("list", None), *[(t, {"drill_id": "drill-v2-x"}) for t in NEW_TOOLS]]))
    assert not set(NEW_TOOLS) & set(tools)
    assert all(c.is_error for c in calls)


# ---------------------------------------------------------------- the Engineer's write paths come from a setting

def test_the_engineer_may_patch_only_the_configured_code_paths(server):
    url = server["url"] + "/engineer/mcp"
    drill = "drill-v2-engineer"
    _, allowed, other, test_file, runbook = run(session_call(url, ENGINEER_KEY, [
        ("create_candidate_branch", {"drill_id": drill, "attempt": 1}),
        ("apply_patch", {"drill_id": drill, "attempt": 1, "message": "change the example module",
                         "path": "src/order-service/app/example.py", "content": "x = 1\n"}),
        ("apply_patch", {"drill_id": drill, "attempt": 1, "message": "change the app",
                         "path": "src/order-service/app/main.py", "content": "x = 1\n"}),
        ("apply_patch", {"drill_id": drill, "attempt": 1, "message": "a test through apply_patch",
                         "path": "src/order-service/tests/test_example.py", "content": "def test_x(): pass\n"}),
        ("apply_patch", {"drill_id": drill, "attempt": 1, "message": "a runbook through apply_patch",
                         "path": "runbooks/example.md", "content": "# x\n"})]))
    assert not allowed.is_error and "refused" not in allowed.content[0].text
    for refused in (other, test_file, runbook):                   # tests and runbooks have their own tools
        assert not refused.is_error and json.loads(refused.content[0].text)["refused"]


def test_write_paths_are_read_from_the_setting(monkeypatch):
    from engineer_tools import write_paths
    assert write_paths(" a/b.py , src/x/test_*.py,,runbooks/*.md ") == ("a/b.py", "src/x/test_*.py", "runbooks/*.md")
    monkeypatch.setenv("ENGINEER_WRITE_PATHS", "a/b.py")
    assert write_paths() == ("a/b.py",)
    monkeypatch.delenv("ENGINEER_WRITE_PATHS")
    assert write_paths() == () and write_paths("") == ()


@pytest.mark.parametrize("bad", ["infra/main.bicep", ".github/workflows/x.yml", "src/mcp-server/app/guard.py",
                                 "src/drill-runner/livefire/contracts.py", "src/*/x.py",
                                 "/etc/passwd", "a/../b.py", "**"])
def test_a_protected_or_unsafe_write_path_stops_the_server(bad):
    from engineer_tools import write_paths
    with pytest.raises(RuntimeError, match="ENGINEER_WRITE_PATHS"):
        write_paths(f"src/order-service/app/example.py,{bad}")


def test_with_no_write_paths_every_write_is_refused():
    import anyio
    from mcp import Client
    import engineer_tools
    from backends.fixtures import FixtureRepo

    class Store:
        def append(self, *a):
            pass
    mcp = engineer_tools.build(FixtureRepo({"src/order-service/app/example.py": "x = 0\n"}), Store(), "main", ())

    async def calls():
        async with Client(mcp) as c:
            await c.call_tool("create_candidate_branch", {"drill_id": "drill-x", "attempt": 1})
            return [await c.call_tool(name, {"drill_id": "drill-x", "attempt": 1, "path": path, "content": content,
                                             **extra})
                    for name, path, content, extra in (
                        ("apply_patch", "src/order-service/app/example.py", "x = 1\n", {"message": "change it"}),
                        ("write_regression_test", "src/order-service/tests/test_x.py", "def test_x(): pass\n", {}),
                        ("update_runbook", "runbooks/x.md", "# x\n", {}))]
    for r in anyio.run(calls):
        assert json.loads(r.content[0].text)["refused"]


def test_the_server_uses_the_setting(server):
    import engineer_tools
    import main
    assert main.WRITE_PATHS == engineer_tools.write_paths(",".join(WRITE_PATHS)) == WRITE_PATHS


# ---------------------------------------------------------------- the Azure backend, against mocked SDK clients

def azure_evidence():
    from backends.azure import AzureEvidence
    e = AzureEvidence.__new__(AzureEvidence)
    e.vault_name, e.secret_name, e.twin_rg = "kv-twin", "db-password", "rg-lf-twin-dev"
    e.order_app, e.sql_server, e.desired = "ca-order", "sql-lf-x", {"SQL_DB_NAME": "orders"}
    e._secrets, e._aca, e._sql = MagicMock(), MagicMock(), MagicMock()
    return e


def test_azure_secret_metadata_lists_versions_and_never_reads_a_value():
    e = azure_evidence()
    t = lambda d: datetime(2026, 10, d, tzinfo=timezone.utc)
    e._secrets.list_properties_of_secret_versions.return_value = [
        NS(version="aaaaaaaa11", created_on=t(1), updated_on=t(1), enabled=True),
        NS(version="bbbbbbbb22", created_on=t(26), updated_on=t(26), enabled=True)]
    out = e.secret_metadata("drill-1")
    assert [v["current"] for v in out["versions"]] == [True, False] and out["versions"][0]["version"] == "bbbbbb"
    assert out["versions"][0]["created"] == "2026-10-26T00:00:00Z"
    e._secrets.get_secret.assert_not_called()


def test_azure_app_configuration_drops_secrets_and_diffs_the_desired_state():
    e = azure_evidence()
    env = [NS(name="SQL_DB_NAME", value="orders_other", secret_ref=None),
           NS(name="SQL_USER", value="order_app", secret_ref=None),
           NS(name="DB_PASSWORD", value="Hunter2!", secret_ref=None),
           NS(name="APPLICATIONINSIGHTS_CONNECTION_STRING", value="InstrumentationKey=abc", secret_ref=None),
           NS(name="OPS_KEY", value=None, secret_ref="ops-key")]
    container = NS(image="acr/order-service@sha256:1", env=env)
    e._aca.container_apps.get.return_value = NS(properties=NS(latest_revision_name="r2",
                                                               template=NS(containers=[container])))
    e._aca.container_apps_revisions.list_revisions.return_value = [
        NS(name="r2", properties=NS(created_time=datetime(2026, 10, 26, tzinfo=timezone.utc), active=True,
                                    template=NS(containers=[container])))]
    out = e.app_configuration("drill-1")
    assert out["revisions"][0]["env"] == {"SQL_DB_NAME": "orders_other", "SQL_USER": "order_app"}
    assert out["differences_from_desired"] == [{"name": "SQL_DB_NAME", "desired": "orders",
                                                "current": "orders_other"}]
    assert "Hunter2" not in json.dumps(out) and "InstrumentationKey" not in json.dumps(out)


def test_azure_network_rules_report_the_missing_azure_services_rule():
    e = azure_evidence()
    e._sql.servers.get.return_value = NS(public_network_access="Enabled")
    e._sql.firewall_rules.list_by_server.return_value = [NS(name="office", start_ip_address="10.0.0.1",
                                                            end_ip_address="10.0.0.1")]
    out = e.network_rules("drill-1")
    assert out["allows_azure_services"] is False and out["public_network_access"] == "Enabled"
    e._sql.firewall_rules.list_by_server.return_value.append(
        NS(name="AllowAllWindowsAzureIps", start_ip_address="0.0.0.0", end_ip_address="0.0.0.0"))
    assert e.network_rules("drill-1")["allows_azure_services"] is True


def test_sql_errors_query_is_fixed_and_scoped_to_the_drill():
    from backends.azure import KQL
    q = KQL["sql_errors"].format(drill_id="drill-1", minutes=30)
    assert 'run_id startswith "drill-1"' in q and "sql_error" in q and "ago(30m)" in q
