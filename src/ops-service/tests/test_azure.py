"""The Azure implementation against a recorded fake of ARM, ACR and the order app: exact URLs, bodies and waits."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import GRANT_KEY

from ops.arm import Arm, TokenCache
from ops.referee import EvidenceFiles, JobReferee, RefereeError
from ops.settings import Settings, SettingsError, validate
from ops.twin import CONTRIBUTOR, KV_SECRETS_USER, AzureTwin, TwinError

SUB = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
PID = "11111111-1111-1111-1111-111111111111"
ASSIGN = "22222222-2222-2222-2222-222222222222"
VAULT = f"/subscriptions/{SUB}/resourceGroups/rg-lf-twin-t/providers/Microsoft.KeyVault/vaults/kv-lf-t"
APP = f"/subscriptions/{SUB}/resourceGroups/rg-lf-twin-t/providers/Microsoft.App/containerApps/ca-order"
JOB = f"/subscriptions/{SUB}/resourceGroups/rg-lf-control-t/providers/Microsoft.App/jobs/job-referee"
REPO = "acrlft0001.azurecr.io/order-service"


def settings(model="accessPolicy", **kw):
    base = dict(backend="azure", runner_key="r" * 40, agent_key="a" * 40, grant_key=GRANT_KEY,
                event_source="dir:/tmp/x", kv_model=model, subscription_id=SUB, tenant_id=TENANT,
                twin_rg="rg-lf-twin-t", control_rg="rg-lf-control-t", order_app_name="ca-order",
                order_app_url="https://ca-order.example.io", keyvault_id=VAULT, app_principal_id=PID,
                app_assignment_name=ASSIGN, image_repo=REPO, base_image=f"{REPO}:sha-{'0' * 40}",
                referee_job_name="job-referee", client_id="33333333-3333-3333-3333-333333333333")
    base.update(kw)
    return Settings(**base)


class Cred:
    def get_token(self, scope):
        return SimpleNamespace(token=f"tok-{scope}", expires_on=9_999_999_999)


class FakeAzure:
    """Routes requests to handlers keyed by (method, path); records every call."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.routes = {}

    def on(self, method, path, *responses):
        self.routes[(method, path)] = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content and request.headers.get(
            "content-type", "").startswith("application/json") else None
        self.calls.append((request.method, request.url.path, body))
        queue = self.routes.get((request.method, request.url.path))
        if not queue:
            return httpx.Response(404, json={"error": {"code": "NotFound", "message": request.url.path}})
        status, payload, headers = _unpack(queue.pop(0) if len(queue) > 1 else queue[0])
        return httpx.Response(status, json=payload, headers=headers)


def _unpack(item):
    return item if len(item) == 3 else (item[0], item[1], {})


def make(model="accessPolicy", **kw):
    fake = FakeAzure()
    transport = httpx.MockTransport(fake.handler)
    tokens = TokenCache(Cred())
    s = settings(model, **kw)
    twin = AzureTwin(s, Arm(tokens, transport), tokens, health=httpx.AsyncClient(transport=transport),
                     registry_transport=transport, poll_s=0.001)
    return fake, twin, s


def run(coro):
    return asyncio.run(coro)


# ---- settings allowlist ----

@pytest.mark.parametrize("change,message", [
    ({"twin_rg": "rg-prod-orders"}, "not a twin"),
    ({"keyvault_id": VAULT.replace("rg-lf-twin-t", "rg-prod")}, "inside TWIN_RG"),
    ({"image_repo": "ghcr.io/livefire-team/order-service"}, "IMAGE_REPO"),
    ({"base_image": f"{REPO}:g1"}, "BASE_IMAGE"),
    ({"runner_key": "short"}, "at least 32"),
    ({"agent_key": "r" * 40}, "must all differ"),
    ({"kv_model": "rbac", "app_assignment_name": "nope"}, "APP_ACCESS_ASSIGNMENT_NAME"),
    ({"control_rg": "rg-other"}, "control resource group"),
])
def test_settings_refuse_targets_outside_the_twin(change, message):
    with pytest.raises(SettingsError, match=message):
        validate(settings(**change))


def test_valid_settings_pass():
    assert validate(settings()).keyvault_name == "kv-lf-t"


# ---- access policy model ----

def vault(entries):
    return (200, {"properties": {"accessPolicies": entries}})


ENTRY = {"tenantId": TENANT, "objectId": PID, "permissions": {"secrets": ["get", "list"]}}


def test_access_policy_counts_and_removes_the_app_entry_with_its_own_permissions():
    fake, twin, _ = make()
    fake.on("GET", VAULT, vault([ENTRY, {"objectId": "someone-else", "permissions": {"secrets": ["get"]}}]))
    fake.on("PUT", f"{VAULT}/accessPolicies/remove", (200, {}))
    assert run(twin.access_entries()) == 1
    run(twin.remove_access())
    method, path, body = fake.calls[-1]
    assert (method, path) == ("PUT", f"{VAULT}/accessPolicies/remove")
    assert body["properties"]["accessPolicies"] == [ENTRY]


def test_access_policy_add_grants_get_and_list_only():
    fake, twin, _ = make()
    fake.on("PUT", f"{VAULT}/accessPolicies/add", (200, {}))
    run(twin.add_access())
    assert fake.calls[-1][2]["properties"]["accessPolicies"][0]["permissions"] == {"secrets": ["get", "list"]}


# ---- rbac model ----

def test_rbac_counts_only_secrets_user_on_the_vault_itself():
    fake, twin, _ = make("rbac")
    role = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{KV_SECRETS_USER}"
    fake.on("GET", f"{VAULT}/providers/Microsoft.Authorization/roleAssignments", (200, {"value": [
        {"properties": {"scope": VAULT, "roleDefinitionId": role}},
        {"properties": {"scope": f"/subscriptions/{SUB}", "roleDefinitionId": role}},
        {"properties": {"scope": VAULT, "roleDefinitionId": role.replace(KV_SECRETS_USER, CONTRIBUTOR)}}]}))
    assert run(twin.access_entries()) == 1


def test_rbac_restore_recreates_the_deterministic_assignment_and_tolerates_exists():
    fake, twin, _ = make("rbac")
    path = f"{VAULT}/providers/Microsoft.Authorization/roleAssignments/{ASSIGN}"
    fake.on("PUT", path, (409, {"error": {"code": "RoleAssignmentExists", "message": "exists"}}))
    run(twin.add_access())
    assert fake.calls[-1][2]["properties"]["principalId"] == PID


# ---- the broad attempt ----

def broad_path(fake):
    return next(p for m, p, _ in fake.calls if m == "PUT" and "/roleAssignments/" in p)


@pytest.mark.parametrize("code", ["RequestDisallowedByPolicy", "AuthorizationFailed"])
def test_broad_attempt_reports_the_refusal_code(code):
    fake, twin, _ = make()

    def handler(request):
        fake.calls.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(403, json={"error": {"code": code, "message": "no"}})
    twin.arm.http = httpx.AsyncClient(base_url="https://management.azure.com", transport=httpx.MockTransport(handler))
    outcome = run(twin.attempt_contributor())
    assert not outcome.allowed and outcome.code == code
    method, path, body = fake.calls[-1]
    assert path.startswith(f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments/")
    assert body["properties"]["roleDefinitionId"].endswith(CONTRIBUTOR) and body["properties"]["principalId"] == PID


def test_an_allowed_broad_grant_is_deleted_at_once():
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(201 if request.method == "PUT" else 200, json={})
    _, twin, _ = make()
    twin.arm.http = httpx.AsyncClient(base_url="https://management.azure.com", transport=httpx.MockTransport(handler))
    outcome = run(twin.attempt_contributor())
    assert outcome.allowed and outcome.removed and calls == ["PUT", "DELETE"]


def test_a_broad_failure_without_a_refusal_code_is_an_error():
    _, twin, _ = make()
    twin.arm.http = httpx.AsyncClient(base_url="https://management.azure.com", transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"error": {"code": "InvalidPrincipalId", "message": "x"}})))
    with pytest.raises(TwinError):
        run(twin.attempt_contributor())


# ---- the order app ----

def app_state(image, latest, ready, state="Succeeded"):
    return (200, {"properties": {"provisioningState": state, "latestRevisionName": latest,
                                 "latestReadyRevisionName": ready,
                                 "template": {"containers": [{"name": "order-service", "image": image,
                                                              "env": [{"name": "A", "value": "1"}]}],
                                              "scale": {"minReplicas": 1, "maxReplicas": 1}}}})


def test_deploy_patches_only_the_template_and_waits_for_the_old_replica_to_go():
    fake, twin, _ = make()
    new_ref = f"{REPO}@sha256:{'c' * 64}"
    fake.on("GET", APP, app_state("old", "rev-1", "rev-1"), app_state(new_ref, "rev-2", "rev-1"),
            app_state(new_ref, "rev-2", "rev-2"))
    fake.on("PATCH", APP, (202, {}))
    fake.on("GET", f"{APP}/revisions/rev-2", (200, {"properties": {"runningState": "Running",
                                                                   "healthState": "Healthy"}}))
    fake.on("GET", f"{APP}/revisions/rev-1/replicas", (200, {"value": [{"name": "rep-1"}]}), (200, {"value": []}))
    info = run(twin.deploy_image(new_ref, 30))
    assert info["revision"] == "rev-2" and info["changed"]
    patch = next(b for m, p, b in fake.calls if m == "PATCH")
    assert list(patch) == ["properties"] and list(patch["properties"]) == ["template"]
    assert patch["properties"]["template"]["containers"][0]["image"] == new_ref
    assert patch["properties"]["template"]["containers"][0]["env"] == [{"name": "A", "value": "1"}]


def test_deploy_of_the_running_image_is_a_noop():
    fake, twin, _ = make()
    fake.on("GET", APP, app_state("same", "rev-1", "rev-1"))
    assert run(twin.deploy_image("same", 30))["changed"] is False
    assert not any(m == "PATCH" for m, _, _ in fake.calls)


def test_deploy_failure_is_reported():
    fake, twin, _ = make()
    fake.on("GET", APP, app_state("old", "rev-1", "rev-1"), app_state("new", "rev-2", "rev-1", state="Failed"))
    fake.on("PATCH", APP, (202, {}))
    with pytest.raises(TwinError, match="failed to provision"):
        run(twin.deploy_image("new", 30))


def test_restart_waits_until_every_old_replica_is_replaced():
    fake, twin, _ = make()
    fake.on("GET", APP, app_state("img", "rev-1", "rev-1"))
    fake.on("POST", f"{APP}/revisions/rev-1/restart", (200, {}))
    fake.on("GET", f"{APP}/revisions/rev-1/replicas", (200, {"value": [{"name": "old"}]}),
            (200, {"value": [{"name": "old"}]}), (200, {"value": [{"name": "old"}, {"name": "new"}]}),
            (200, {"value": [{"name": "new"}]}))
    assert run(twin.restart(30))["revision"] == "rev-1"
    assert sum(1 for m, p, _ in fake.calls if p.endswith("/replicas")) == 4


def test_restart_times_out():
    fake, twin, _ = make()
    fake.on("GET", APP, app_state("img", "rev-1", "rev-1"))
    fake.on("POST", f"{APP}/revisions/rev-1/restart", (200, {}))
    fake.on("GET", f"{APP}/revisions/rev-1/replicas", (200, {"value": [{"name": "old"}]}))
    with pytest.raises(TwinError, match="timed out"):
        run(twin.restart(0.05))


def test_dependencies_unreachable_when_the_app_does_not_answer_json():
    fake, twin, _ = make()
    assert run(twin.dependencies()) == {"keyvault": "unreachable", "sql": "unreachable"}


# ---- the registry ----

def test_digest_lookup_uses_only_a_pull_token():
    fake, twin, _ = make()
    digest = "sha256:" + "d" * 64
    fake.on("POST", "/oauth2/exchange", (200, {"refresh_token": "rt"}))
    fake.on("POST", "/oauth2/token", (200, {"access_token": "at"}))
    fake.on("HEAD", "/v2/order-service/manifests/sha-" + "a" * 40, (200, None, {"Docker-Content-Digest": digest}))
    assert run(twin.resolve_digest("sha-" + "a" * 40)) == digest


def test_a_missing_tag_resolves_to_none():
    fake, twin, _ = make()
    fake.on("POST", "/oauth2/exchange", (200, {"refresh_token": "rt"}))
    fake.on("POST", "/oauth2/token", (200, {"access_token": "at"}))
    fake.on("HEAD", "/v2/order-service/manifests/sha-" + "b" * 40, (404, None))
    assert run(twin.resolve_digest("sha-" + "b" * 40)) is None


# ---- the Referee job ----

def job_def():
    return (200, {"properties": {"template": {"containers": [{
        "name": "referee", "image": "acrlft0001.azurecr.io/referee:sha-" + "e" * 40,
        "resources": {"cpu": 1, "memory": "2Gi"},
        "env": [{"name": "ORDER_APP_URL", "value": "https://x"},
                {"name": "REFEREE_SQL_PASSWORD", "secretRef": "referee-sql-password"},
                {"name": "DRILL_ID", "value": "placeholder"}]}]}}})


def test_referee_job_runs_with_the_run_values_and_keeps_secret_references(tmp_path):
    fake = FakeAzure()
    tokens = TokenCache(Cred())
    s = settings(event_source=f"dir:{tmp_path}")
    fake.on("GET", JOB, job_def())
    fake.on("POST", f"{JOB}/start", (202, {"name": "job-referee-abc", "id": "x"}))
    fake.on("GET", f"{JOB}/executions/job-referee-abc", (200, {"properties": {"status": "Running"}}),
            (200, {"properties": {"status": "Failed"}}))
    out = tmp_path / "drill-t-1" / "r2-during-fault"
    out.mkdir(parents=True)
    (out / "referee-result.json").write_text(json.dumps({"verdict": "FAIL", "duration_s": 4}))
    referee = JobReferee(s, Arm(tokens, httpx.MockTransport(fake.handler)), EvidenceFiles(f"dir:{tmp_path}"),
                         poll_s=0.001)
    result = run(referee.run("drill-t-1", "drill-t-1-r2", "during-fault", "r2-during-fault", 5))
    assert result["verdict"] == "FAIL" and result["execution"] == "job-referee-abc"
    start = next(b for m, p, b in fake.calls if m == "POST")
    env = {e["name"]: e for e in start["containers"][0]["env"]}
    assert env["REFEREE_SQL_PASSWORD"] == {"name": "REFEREE_SQL_PASSWORD", "secretRef": "referee-sql-password"}
    assert env["DRILL_ID"]["value"] == "drill-t-1" and env["RUN_DIR"]["value"] == "r2-during-fault"
    assert start["containers"][0]["image"].endswith("e" * 40)


def test_referee_without_a_result_file_is_inconclusive(tmp_path):
    fake = FakeAzure()
    fake.on("GET", JOB, job_def())
    fake.on("POST", f"{JOB}/start", (202, {"name": "exec-1"}))
    fake.on("GET", f"{JOB}/executions/exec-1", (200, {"properties": {"status": "Failed"}}))
    referee = JobReferee(settings(), Arm(TokenCache(Cred()), httpx.MockTransport(fake.handler)),
                         EvidenceFiles(f"dir:{tmp_path}"), poll_s=0.001)
    with pytest.raises(RefereeError, match="wrote no result"):
        run(referee.run("drill-t-1", "drill-t-1-r1", "baseline", "r1-baseline", 5))
