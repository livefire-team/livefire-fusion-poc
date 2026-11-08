"""Contracts v2.0: the evidence that tells four restore defects apart, without ever naming the defect."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from conftest import ENGINEER_KEY, PLANNER_KEY
from test_server import data, run, session_call

FAULTS = ("identity-rbac", "secret-drift", "config-drift", "network-drift")
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


def test_each_fault_leaves_its_own_trail(server):
    sets = {f: evidence(server, f) for f in FAULTS}
    errors = {f: [row["sql_error"] for row in s[0]["data"]["rows"]] for f, s in sets.items()}
    assert errors == {"identity-rbac": [], "secret-drift": ["18456"], "config-drift": ["4060"],
                      "network-drift": ["40615"]}
    kv_codes = {f: {row["ResultCode"] for row in s[1]["data"]["rows"]} for f, s in sets.items()}
    assert "403" in kv_codes["identity-rbac"] and all("403" not in kv_codes[f] for f in FAULTS[1:])
    roles = {f: s[2]["data"]["has_secrets_user_role"] for f, s in sets.items()}
    assert roles == {"identity-rbac": False, "secret-drift": True, "config-drift": True, "network-drift": True}
    current = {f: next(v for v in s[3]["data"]["versions"] if v["current"])["created"] for f, s in sets.items()}
    assert current["secret-drift"].startswith("2026-10-26") and current["identity-rbac"].startswith("2026-09-14")
    diffs = {f: s[4]["data"]["differences_from_desired"] for f, s in sets.items()}
    assert diffs["config-drift"] == [{"name": "SQL_DB_NAME", "desired": "orders", "current": "orders_restored"}]
    assert all(diffs[f] == [] for f in FAULTS if f != "config-drift")
    azure = {f: s[5]["data"]["allows_azure_services"] for f, s in sets.items()}
    assert azure == {"identity-rbac": True, "secret-drift": True, "config-drift": True, "network-drift": False}


def test_a_drill_without_a_fault_on_record_gets_the_default_set(server):
    assert evidence(server, None)[2]["data"]["has_secrets_user_role"] is False


def test_secret_metadata_never_carries_a_value(server):
    for fault in FAULTS:
        for v in evidence(server, fault)[3]["data"]["versions"]:
            assert set(v) == {"version", "created", "updated", "enabled", "current"}


def test_the_engineer_endpoint_has_none_of_the_new_tools(server):
    tools, *calls = run(session_call(server["url"] + "/engineer/mcp", ENGINEER_KEY,
                                     [("list", None), *[(t, {"drill_id": "drill-v2-x"}) for t in NEW_TOOLS]]))
    assert not set(NEW_TOOLS) & set(tools)
    assert all(c.is_error for c in calls)


def test_the_engineer_may_now_patch_db_py_and_still_not_main_py(server):
    url = server["url"] + "/engineer/mcp"
    drill = "drill-v2-engineer"
    _, db, main = run(session_call(url, ENGINEER_KEY, [
        ("create_candidate_branch", {"drill_id": drill, "attempt": 1}),
        ("apply_patch", {"drill_id": drill, "attempt": 1, "message": "rebuild the connection string per order",
                         "path": "src/order-service/app/db.py", "content": "x = 1\n"}),
        ("apply_patch", {"drill_id": drill, "attempt": 1, "message": "change the app",
                         "path": "src/order-service/app/main.py", "content": "x = 1\n"})]))
    assert not db.is_error and "refused" not in db.content[0].text
    assert not main.is_error and json.loads(main.content[0].text)["refused"]      # a refusal the agent can read


# The Engineer's write allowlist, as contracts/mcp-tools.md publishes it; WS4's Drill Runner holds the same list
# (ENGINEER_WRITE_PATHS) and checks every candidate against it.
ENGINEER_WRITE_PATHS = ("src/order-service/app/secret_provider.py", "src/order-service/app/db.py",
                        "src/order-service/tests/test_*.py", "runbooks/*.md")


def test_engineer_allowlist_matches_the_contracts():
    import sys
    from pathlib import Path
    from engineer_tools import CODE_PATHS, RUNBOOK_PATHS, TEST_PATHS
    assert set(CODE_PATHS + TEST_PATHS + RUNBOOK_PATHS) == set(ENGINEER_WRITE_PATHS)
    runner = Path(__file__).resolve().parents[2] / "drill-runner"       # present when this sits in the full repo
    if runner.is_dir():
        sys.path.insert(0, str(runner))
        from livefire.contracts import ENGINEER_WRITE_PATHS as runner_paths
        assert set(runner_paths) == set(ENGINEER_WRITE_PATHS)


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
    env = [NS(name="SQL_DB_NAME", value="orders_restored", secret_ref=None),
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
    assert out["revisions"][0]["env"] == {"SQL_DB_NAME": "orders_restored", "SQL_USER": "order_app"}
    assert out["differences_from_desired"] == [{"name": "SQL_DB_NAME", "desired": "orders",
                                                "current": "orders_restored"}]
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
