import time

import pytest
from conftest import AGENT, DRILL, GRANT_KEY, grant

from ops import grants


def test_round_trip():
    g = grants.verify(GRANT_KEY, grant("restore_kv_secrets_user", "recover"), DRILL, "restore_kv_secrets_user",
                      "recover")
    assert g.drill_id == DRILL and g.approved_by == "test-approver" and g.gid.startswith("grt-")


@pytest.mark.parametrize("token,drill,action,purpose,reason", [
    (lambda: grant("restore_kv_secrets_user", "recover"), "drill-other-1", "restore_kv_secrets_user", "recover",
     "another drill"),
    (lambda: grant("restore_kv_secrets_user", "recover"), DRILL, "restore_db_secret", "recover", "another action"),
    (lambda: grant("grant_contributor_subscription", "policy_test"), DRILL, "grant_contributor_subscription",
     "recover", "purpose"),
    (lambda: grant("restore_kv_secrets_user", "recover", now=time.time() - 3600), DRILL, "restore_kv_secrets_user",
     "recover", "expired"),
    (lambda: grants.sign("k" * 40, DRILL, "restore_kv_secrets_user", "recover", "x"), DRILL,
     "restore_kv_secrets_user", "recover", "signature"),
    (lambda: "lfg1.e30.c2ln", DRILL, "restore_kv_secrets_user", "recover", "signature"),
    (lambda: "not-a-grant", DRILL, "restore_kv_secrets_user", "recover", "not a recovery grant"),
    (lambda: "", DRILL, "restore_kv_secrets_user", "recover", "missing"),
    (lambda: "lfg1." + "a" * 3000 + ".b", DRILL, "restore_kv_secrets_user", "recover", "oversized"),
])
def test_bad_grants_are_refused(token, drill, action, purpose, reason):
    with pytest.raises(grants.GrantRefused, match=reason):
        grants.verify(GRANT_KEY, token(), drill, action, purpose)


def test_tampered_payload_fails_the_signature():
    head, payload, sig = grant("restore_kv_secrets_user", "recover").split(".")
    forged = grants._b64(grants._unb64(payload).replace(b"drill-test-0001", b"drill-test-0002"))
    with pytest.raises(grants.GrantRefused, match="signature"):
        grants.verify(GRANT_KEY, f"{head}.{forged}.{sig}", "drill-test-0002", "restore_kv_secrets_user", "recover")


def test_agent_needs_a_grant(call, events, twin):
    call("inject_fault")
    status, body = call("recover", key=AGENT, action="restore_kv_secrets_user")
    assert status == 422 and "missing" in body["details"]["reason"] and twin.entries == 0
    assert events()[-1]["action"] == "grant.refused"


def test_a_grant_works_once_and_is_never_written_down(call, events, twin, evidence):
    call("inject_fault")
    token = grant("restore_kv_secrets_user", "recover")
    assert call("recover", key=AGENT, action="restore_kv_secrets_user", grant=token)[0] == 200
    call("inject_fault")
    status, body = call("recover", key=AGENT, action="restore_kv_secrets_user", grant=token)
    assert status == 422 and body["details"]["reason"] == "grant already used" and twin.entries == 0
    log = (evidence / DRILL / "events.jsonl").read_text()
    assert token not in log and token.split(".")[2] not in log


def test_used_grants_survive_a_restart_of_the_service(call, service, twin):
    call("inject_fault")
    token = grant("restore_kv_secrets_user", "recover")
    call("recover", key=AGENT, action="restore_kv_secrets_user", grant=token)
    service.used_grants.clear()                       # a new process has no memory; the event log still knows
    call("inject_fault")
    assert call("recover", key=AGENT, action="restore_kv_secrets_user", grant=token)[1]["details"]["reason"] \
        == "grant already used"


def test_a_policy_test_grant_cannot_run_the_restore(call, twin):
    call("inject_fault")
    token = grant("restore_kv_secrets_user", "policy_test")
    assert call("recover", key=AGENT, action="restore_kv_secrets_user", grant=token)[0] == 422
    assert twin.entries == 0
