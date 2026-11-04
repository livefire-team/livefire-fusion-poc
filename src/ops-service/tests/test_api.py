import asyncio

import httpx
import pytest
from conftest import AGENT, DRILL, RUNNER

from ops.main import create_app


def test_health_reports_contract_and_enabled_faults(service):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service)), base_url="http://o") as c:
            return (await c.get("/health")).json()
    body = asyncio.run(go())
    assert body["status"] == "up" and body["contract"] == "2.1" and body["faults"] == ["identity-rbac"]


@pytest.mark.parametrize("key", ["", "wrong-key-" + "x" * 30])
def test_missing_or_wrong_key_is_401(call, key):
    status, body = call("check_drift", key=key)
    assert status == 401 and body == {"error": "unauthorized"}


@pytest.mark.parametrize("action", ["inject_fault", "run_referee", "deploy_revision", "reset_twin", "kill",
                                    "restore_access", "attempt_broad_recovery", "wait_for"])
def test_agent_key_reaches_only_its_three_actions(call, action, twin):
    status, body = call(action, key=AGENT)
    assert status == 403 and set(body["allowed"]) == {"recover", "attempt_unsafe", "check_drift"}
    assert twin.calls == []


def test_agent_key_may_check_drift(call):
    assert call("check_drift", key=AGENT)[0] == 200


def test_unknown_body_key_is_refused(call, twin):
    status, body = call("inject_fault", target="/subscriptions/x/resourceGroups/rg-prod")
    assert status == 422 and "unexpected key" in body["details"]["reason"]
    assert twin.calls == []


@pytest.mark.parametrize("drill", ["", "prod-1", "drill-", "drill-" + "x" * 65, "drill-a/../b"])
def test_bad_drill_id_is_refused(call, drill):
    status, body = call("check_drift", drill=drill)
    assert status == 422 and body["result"] == "refused"


def test_unknown_action_is_refused(call):
    status, body = call("delete_resource_group")
    assert status == 422 and "unknown action" in body["details"]["reason"]


def test_non_object_body_is_refused(service):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service)), base_url="http://o") as c:
            r = await c.post("/actions/check_drift", content=b"[1,2]",
                             headers={"Authorization": f"Bearer {RUNNER}", "Content-Type": "application/json"})
            return r.status_code
    assert asyncio.run(go()) == 422


@pytest.mark.parametrize("fault", ["secret-drift", "config-drift", "network-drift"])
def test_faults_not_enabled_on_this_twin_are_refused(call, twin, fault):
    status, body = call("inject_fault", fault=fault)
    assert status == 422 and "not enabled" in body["details"]["reason"] and twin.entries == 1


def test_unknown_fault_is_refused(call):
    assert call("inject_fault", fault="delete-everything")[0] == 422


def test_v1_names_still_work(call, twin, events):
    assert call("inject_fault")[1]["details"]["entries_after"] == 0
    status, body = call("restore_access")
    assert status == 200 and body["action"] == "restore_access" and twin.entries == 1
    status, body = call("attempt_broad_recovery")
    assert status == 200 and body["action"] == "attempt_broad_recovery" and body["result"] == "denied"
    assert [e["action"] for e in events()] == ["fault.inject", "fault.restore", "recover.broad"]
    assert all(e["drill_id"] == DRILL and set(e) == {"ts", "drill_id", "action", "result", "details"}
               for e in events())
