"""One complete identity-fault drill over HTTP on the fake twin, the way WS4's runner and WS3's Recovery tools call."""
from conftest import AGENT, BASE, CANDIDATE, grant


def verdict(call, label):
    status, body = call("run_referee", label=label)
    assert status == 200, body
    return body["result"]


def test_full_drill_with_agent_recovery_candidate_and_durability(call, events, twin):
    assert call("reset_twin")[1]["result"] == "ok"
    assert verdict(call, "baseline") == "PASS"

    assert call("inject_fault", fault="identity-rbac")[1]["details"] == {
        "fault": "identity-rbac", "model": "fake", "entries_after": 0}
    status, body = call("wait_for", state="forbidden", timeout_s=5)
    assert status == 200 and body["result"] == "ok"
    assert verdict(call, "during-fault") == "FAIL"

    status, body = call("attempt_unsafe", key=AGENT, action="grant_contributor_subscription",
                        grant=grant("grant_contributor_subscription", "policy_test"))
    assert status == 200 and body["result"] == "denied"
    assert body["details"]["code"] == "RequestDisallowedByPolicy" and body["details"]["refused_by"] == "Azure Policy"
    assert body["details"]["simulated"] is True and body["details"]["executed_by"] == "agent"

    status, body = call("recover", key=AGENT, action="restore_kv_secrets_user",
                        grant=grant("restore_kv_secrets_user", "recover"))
    assert status == 200 and body["details"]["executed_by"] == "agent"
    assert body["details"]["approved_by"] == "test-approver" and body["details"]["grant_id"].startswith("grt-")
    assert call("wait_for", state="ok", timeout_s=5)[1]["result"] == "ok"
    assert call("check_drift", key=AGENT)[1]["result"] == "ok"
    assert verdict(call, "after-restore") == "FAIL"

    status, body = call("deploy_revision", image=CANDIDATE)
    assert status == 200 and body["details"]["digest"].startswith("sha256:")
    assert twin.image == f"{CANDIDATE.split(':')[0]}@{body['details']['digest']}"
    assert verdict(call, "after-fix") == "PASS"

    call("inject_fault")
    call("wait_for", state="forbidden", timeout_s=5)
    verdict(call, "during-refault")
    assert call("recover", action="restore_kv_secrets_user")[1]["details"]["executed_by"] == "workflow"
    assert verdict(call, "after-refault") == "PASS"

    body = call("reset_twin")[1]
    assert body["details"]["redeployed"] and twin.image.startswith(BASE.split(":")[0] + "@")

    log = events()
    referee = [(e["action"], e["result"], e["details"]["run_id"].rsplit("-", 1)[1]) for e in log
               if e["action"].startswith("referee.")]
    assert referee == [("referee.baseline", "PASS", "r1"), ("referee.during-fault", "FAIL", "r2"),
                       ("referee.after-restore", "FAIL", "r3"), ("referee.after-fix", "PASS", "r4"),
                       ("referee.during-refault", "FAIL", "r5"), ("referee.after-refault", "PASS", "r6")]
    assert [e["action"] for e in log if not e["action"].startswith(("referee.", "wait."))] == [
        "reset", "fault.inject", "recover.broad", "fault.restore", "drift.check", "deploy.revision",
        "fault.inject", "fault.restore", "reset"]


def test_recover_when_nothing_is_drifted_is_a_recorded_noop(call, events):
    status, body = call("recover", action="restore_kv_secrets_user")
    assert status == 200 and body["details"]["noop"] is True
    assert events()[-1]["action"] == "fault.restore"


def test_check_drift_reports_identity_drift_only(call):
    call("inject_fault")
    body = call("check_drift")[1]
    assert body["result"] == "drift"
    assert body["details"] == {"identity": "drift", "secret": "not_checked", "config": "not_checked",
                               "network": "not_checked"}


def test_unexpected_allow_is_reported_and_removed(call, twin, events):
    twin.broad_code = ""
    body = call("attempt_unsafe", action="grant_contributor_subscription")[1]
    assert body["result"] == "UNEXPECTED_ALLOW" and body["details"]["removed"] is True
    assert events()[-1]["result"] == "UNEXPECTED_ALLOW"


def test_rbac_refusal_is_labelled_as_rbac_not_policy(call, twin):
    twin.broad_code = "AuthorizationFailed"
    body = call("attempt_unsafe", action="grant_contributor_subscription")[1]
    assert body["details"]["code"] == "AuthorizationFailed" and body["details"]["refused_by"] == "Azure RBAC"


def test_broad_and_narrow_actions_cannot_be_swapped(call, twin):
    assert call("recover", action="grant_contributor_subscription")[0] == 422
    assert call("attempt_unsafe", action="restore_kv_secrets_user")[0] == 422
    assert call("attempt_unsafe", action="open_sql_firewall_to_internet")[0] == 422
    assert call("recover", action="restore_db_secret")[0] == 422
    assert twin.calls == []
