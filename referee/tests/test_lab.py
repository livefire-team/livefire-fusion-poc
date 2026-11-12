"""lab.sh (sync, state, new-env, teardown), driven through fake az, azd, curl and python.

The fake azd keeps one values file per environment, so tests can check which environment each call touched.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parents[1] / "scripts"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("jq") is None, reason="bash and jq are needed")

BASE = "acrlftest.azurecr.io/order-service:sha-" + "1" * 40
DIGEST = "sha256:" + "d" * 64
LF_EH = f"""AZURE_ENV_NAME="lf-eh"
AZURE_LOCATION="eastus2"
AZURE_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"
TWIN_RG="rg-lf-twin-lf-eh"
CONTROL_RG="rg-lf-control-lf-eh"
KV_PERMISSION_MODEL="accessPolicy"
SECRET_REFRESH_SECONDS="10"
AZURE_PRINCIPAL_TYPE="User"
KEYVAULT_NAME="kv-lf-twin"
KEYVAULT_ID="/subscriptions/0/resourceGroups/rg-lf-twin-lf-eh/providers/Microsoft.KeyVault/vaults/kv-lf-twin"
CONTROL_KEYVAULT_NAME="kv-lfc-test"
EVIDENCE_BLOB_URL="https://evidence.example/evidence"
APP_IDENTITY_PRINCIPAL_ID="22222222-2222-2222-2222-222222222222"
OPS_PRINCIPAL_ID="11111111-1111-1111-1111-111111111111"
ORDER_APP_NAME="ca-order"
ORDER_APP_URL="https://ca-order.example.azurecontainerapps.io"
ORDER_IMAGE="{BASE}"
REGISTRY_NAME="acrlftest"
SQL_ADMIN_PASSWORD="lf-eh-secret"
MCP_ENGINEER_WRITE_PATHS="src/example/app/module.py"
GITHUB_PLANNER_APP_ID="1"
MODEL_NAME="gpt-5.1"
MODEL_VERSION="2025-11-13"
PLANNER_AGENT="lf-planner:4"
RUNNER_SOURCE="ghcr.io/livefire-team/drill-runner:sha-{"a" * 40}"
SEARCH_LOCATION="eastus"
SEARCH_VECTOR_FIELD="a\\"b"
INCIDENT_CORPUS="/nowhere/incidents"
RUNNER_GITHUB_APP_ID="5"
CONTROL_CENTER_SOURCE="ghcr.io/livefire-team/control-center:sha-{"c" * 40}"
CONTROL_CENTER_IMAGE="acrlftest.azurecr.io/control-center:sha-{"c" * 40}"
LOADGEN_DRILL_ID="drill-loadgen-1107"
FOUNDRY_NAME="ais-lf-test"
OPS_IMAGE="acrlftest.azurecr.io/ops-service:sha-{"2" * 40}"
"""

FAKE_AZD = r"""#!/usr/bin/env bash
D="DIR"
env_of() { if [ "$1" = -e ]; then echo "$2"; else cat "$D/selected"; fi; }
case "$1 $2" in
  "env get-values") e="$(env_of "${3:-}" "${4:-}")"; cat "$D/values/$e.env" ;;
  "env list") echo "NAME DEFAULT LOCAL REMOTE"
    for f in "$D"/values/*.env; do n="$(basename "$f" .env)"
      if [ "$n" = "$(cat "$D/selected")" ]; then echo "$n true true false"; else echo "$n false true false"; fi; done ;;
  "env select") echo "azd $*" >> "$D/calls.log"; echo "$3" > "$D/selected" ;;
  "env new") echo "azd $*" >> "$D/calls.log"; : > "$D/values/$3.env"; echo "$3" > "$D/selected" ;;
  "env set") echo "azd $*" >> "$D/calls.log"
    if [ "$3" = -e ]; then e="$4"; shift 4; else e="$(cat "$D/selected")"; shift 2; fi
    if [ "$1" = --file ]; then cat "$2" >> "$D/values/$e.env"; else printf '%s="%s"\n' "$1" "$2" >> "$D/values/$e.env"; fi ;;
  "down --force") echo "azd $* env=$(cat "$D/selected")" >> "$D/calls.log"
    n=$(cat "$D/down-calls" 2>/dev/null || echo 0); echo $((n+1)) > "$D/down-calls"
    [ "$n" -ge "$(cat "$D/down-fails" 2>/dev/null || echo 0)" ] ;;
  *) echo "azd $*" >> "$D/calls.log" ;;
esac
"""


def fake(path: Path, body: str) -> None:
    path.write_text(body if body.startswith("#!") else "#!/usr/bin/env bash\n" + body, encoding="utf-8",
                    newline="\n")
    path.chmod(0o755)


def calls(sandbox):
    f = sandbox / "calls.log"
    return f.read_text().splitlines() if f.exists() else []


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "values").mkdir()
    (tmp_path / "values" / "lf-eh.env").write_text(LF_EH)
    (tmp_path / "selected").write_text("lf-eh\n")
    fake(tmp_path / "bin" / "azd", FAKE_AZD.replace("DIR", tmp_path.as_posix()))
    fake(tmp_path / "bin" / "openssl", "echo generated-value\n")
    fake(tmp_path / "bin" / "python", f'echo "python $*" >> {(tmp_path / "calls.log").as_posix()}\n')
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(SCRIPTS / "lab.sh", scripts)
    return tmp_path


def lab(sandbox, *args, az_body="", curl_body='{"keyvault": "ok", "sql": "ok"}'):
    fake(sandbox / "bin" / "az", az_body.replace("LOG", (sandbox / "calls.log").as_posix()))
    fake(sandbox / "bin" / "curl", f"echo '{curl_body}'\n")
    env = {**os.environ, "PATH": f"{(sandbox / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([BASH, (sandbox / "scripts" / "lab.sh").as_posix(), *args], cwd=sandbox, env=env,
                          capture_output=True, text=True, timeout=60)


# ---- lab.sh state: read-only, is the twin back at its baseline? ----
def az_state(entries="1", image=BASE, revisions="1", scale="1/1", running="0", policy="0"):
    return f"""echo "az $*" >> LOG
case "$*" in
  "keyvault show"*) echo {entries} ;;
  "role assignment list"*) echo {entries} ;;
  "containerapp show"*"image"*) echo {image} ;;
  "containerapp show"*"scale"*) echo {scale} ;;
  "acr repository show"*) echo {DIGEST} ;;
  "containerapp revision list"*) echo {revisions} ;;
  "containerapp job execution list"*) echo {running} ;;
  "policy assignment list"*) echo {policy} ;;
esac
"""


def test_state_passes_at_baseline_and_changes_nothing(sandbox):
    result = lab(sandbox, "state", az_body=az_state())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "twin at baseline" in result.stdout and "NOT" not in result.stdout
    assert "info  deny policy: off" in result.stdout
    mutating = ("delete", "create", "set", "update", "restart", "start", "purge")
    assert not [c for c in calls(sandbox) if any(f" {m} " in f"{c} " for m in mutating)]


def test_state_accepts_the_base_image_by_the_digest_reset_twin_deploys(sandbox):
    result = lab(sandbox, "state", az_body=az_state(image=f"acrlftest.azurecr.io/order-service@{DIGEST}"))
    assert result.returncode == 0, result.stdout
    assert "ok    the order app runs the base image" in result.stdout


@pytest.mark.parametrize("change, expected", [
    ({"entries": "0"}, "NOT   the app has 0 Key Vault access entries (want 1)"),
    ({"entries": "2"}, "NOT   the app has 2 Key Vault access entries (want 1)"),
    ({"image": "acrlftest.azurecr.io/order-service@sha256:" + "c" * 64}, "not the base image"),
    ({"revisions": "2"}, "NOT   2 active revisions (want 1)"),
    ({"scale": "1/3"}, "NOT   replicas min/max 1/3 (want 1/1)"),
])
def test_state_names_each_difference_from_the_baseline(sandbox, change, expected):
    result = lab(sandbox, "state", az_body=az_state(**change))
    assert result.returncode == 1
    assert expected in result.stdout and "twin NOT at baseline" in result.stdout


def test_state_fails_while_dependencies_are_not_ok(sandbox):
    result = lab(sandbox, "state", az_body=az_state(), curl_body='{"keyvault": "forbidden", "sql": "ok"}')
    assert result.returncode == 1
    assert "NOT   dependencies keyvault/sql: forbidden/ok" in result.stdout


def test_state_fails_while_a_drill_is_still_running(sandbox):
    values = sandbox / "values" / "lf-eh.env"
    values.write_text(values.read_text() + 'RUNNER_JOB_NAME="job-drill-runner"\n')
    result = lab(sandbox, "state", az_body=az_state(running="1"))
    assert result.returncode == 1
    assert "NOT   1 drill execution(s) still running" in result.stdout


def test_state_on_the_rbac_model_counts_role_assignments(sandbox):
    values = sandbox / "values" / "lf-eh.env"
    values.write_text(values.read_text().replace('"accessPolicy"', '"rbac"'))
    result = lab(sandbox, "state", az_body=az_state())
    assert result.returncode == 0, result.stdout
    assert any(c.startswith("az role assignment list") and "Key Vault Secrets User" in c for c in calls(sandbox))


# ---- lab.sh new-env: a second environment for the clean-lab rebuild (ADR-025) ----
def values_of(sandbox, env):
    out = {}
    for line in (sandbox / "values" / f"{env}.env").read_text().splitlines():
        k, _, v = line.partition("=")
        out[k] = v.strip('"')
    return out


def test_new_env_copies_the_settings_and_nothing_built_for_lf_eh(sandbox):
    result = lab(sandbox, "new-env", "lf-g3", az_body='echo "az $*" >> LOG\n')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "azd env new lf-g3 --subscription 00000000-0000-0000-0000-000000000000 --location eastus2" in calls(sandbox)
    new, old = values_of(sandbox, "lf-g3"), values_of(sandbox, "lf-eh")
    for k in ("KV_PERMISSION_MODEL", "SECRET_REFRESH_SECONDS", "AZURE_PRINCIPAL_TYPE", "MCP_ENGINEER_WRITE_PATHS",
              "GITHUB_PLANNER_APP_ID", "MODEL_NAME", "MODEL_VERSION", "SEARCH_LOCATION", "INCIDENT_CORPUS",
              "RUNNER_GITHUB_APP_ID", "CONTROL_CENTER_SOURCE", "LOADGEN_DRILL_ID"):
        assert new[k] == old[k], k
    # lf-eh's registry images, pinned agents and outputs belong to lf-eh; secrets are never copied
    for k in ("OPS_IMAGE", "PLANNER_AGENT", "TWIN_RG", "KEYVAULT_NAME", "CONTROL_CENTER_IMAGE", "FOUNDRY_NAME",
              "RUNNER_SOURCE"):
        assert k not in new, k
    assert new["SECRETS_SOURCE_VAULT"] == "kv-lfc-test"       # the hook copies the GitHub App keys from lf-eh's vault
    assert new["SQL_ADMIN_PASSWORD"] == "generated-value"
    assert not any("generated-value" in c for c in calls(sandbox))          # the password never on a command line
    assert new["SEARCH_VECTOR_FIELD"] == 'a"b'                              # azd's escaping undone, not copied
    assert new["ORDER_IMAGE"] == "ghcr.io/livefire-team/order-service:sha-1111111"
    assert "lf-eh-secret" not in result.stdout + result.stderr
    assert "WARNING: INCIDENT_CORPUS is not a folder here" in result.stderr


def test_new_env_refuses_an_existing_name(sandbox):
    result = lab(sandbox, "new-env", "lf-eh", az_body="")
    assert result.returncode != 0 and "already exists" in result.stdout
    assert not any(c.startswith("azd env new") for c in calls(sandbox))


# ---- lab.sh teardown: a second environment only ----
LF_G3 = (LF_EH.replace("lf-eh", "lf-g3").replace("kv-lf-twin", "kv-lf-twin-g3").replace("kv-lfc-test", "kv-lfc-g3")
         .replace("ais-lf-test", "ais-lf-g3"))

AZ_TEARDOWN = """echo "az $*" >> LOG
case "$*" in
  "keyvault list-deleted"*"kv-lfc-g3"*) echo kv-lfc-g3 ;;
  "cognitiveservices account list-deleted"*"ais-lf-g3"*) echo ais-lf-g3 ;;
esac
"""


def add_lf_g3(sandbox, select=False):
    (sandbox / "values" / "lf-g3.env").write_text(LF_G3)
    if select:
        (sandbox / "selected").write_text("lf-g3\n")


def test_teardown_refuses_the_team_environment(sandbox):
    result = lab(sandbox, "teardown", "lf-eh", "--yes", az_body="")
    assert result.returncode != 0 and "refused: lf-eh is the team's environment" in result.stdout
    assert calls(sandbox) == []


def test_teardown_needs_yes(sandbox):
    add_lf_g3(sandbox)
    result = lab(sandbox, "teardown", "lf-g3", az_body="")
    assert result.returncode != 0 and "rerun with --yes" in result.stdout
    assert calls(sandbox) == []


def test_teardown_removes_the_role_unlocks_evidence_then_deletes_and_selects_lf_eh(sandbox):
    add_lf_g3(sandbox, select=True)
    (sandbox / ".azure" / "lf-g3").mkdir(parents=True)
    result = lab(sandbox, "teardown", "lf-g3", "--yes", az_body=AZ_TEARDOWN)
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(sandbox)
    role = next(i for i, c in enumerate(log) if c.startswith("az role assignment delete"))
    unlock = log.index("python scripts/evidence_unlock.py --yes")
    down = next(i for i, c in enumerate(log) if c.startswith("azd down --force --purge"))
    assert role < unlock < down
    assert "11111111-1111-1111-1111-111111111111" in log[role] and "/subscriptions/0000" in log[role]
    assert log[down].endswith("env=lf-g3")
    assert not any(c.startswith("az policy assignment delete") for c in log)      # the shared policy stays
    assert "az keyvault purge -n kv-lfc-g3 -o none" in log                            # left soft-deleted
    assert not any(c.startswith("az keyvault purge -n kv-lf-twin-g3") for c in log)
    assert any(c.startswith("az cognitiveservices account purge -g rg-lf-control-lf-g3 -n ais-lf-g3") for c in log)
    assert (sandbox / "selected").read_text().strip() == "lf-eh"
    assert not (sandbox / ".azure" / "lf-g3").exists()


def test_teardown_of_an_environment_without_outputs_still_deletes_it(sandbox):
    half = "".join(l + "\n" for l in LF_G3.splitlines()
                   if not l.startswith(("OPS_PRINCIPAL_ID=", "EVIDENCE_BLOB_URL=", "CONTROL_KEYVAULT_NAME=")))
    (sandbox / "values" / "lf-g3.env").write_text(half)
    result = lab(sandbox, "teardown", "lf-g3", "--yes", az_body=AZ_TEARDOWN)
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(sandbox)
    assert not any(c.startswith("az role assignment delete") for c in log)    # never with an empty --assignee
    assert "python scripts/evidence_unlock.py --yes" not in log
    assert any(c.startswith("azd down --force --purge") for c in log)
    assert (sandbox / "selected").read_text().strip() == "lf-eh"


def test_teardown_fails_when_a_step_fails(sandbox):
    add_lf_g3(sandbox)
    fake(sandbox / "bin" / "python", 'echo "Forbidden" >&2; exit 1\n')
    result = lab(sandbox, "teardown", "lf-g3", "--yes", az_body=AZ_TEARDOWN)
    assert result.returncode != 0
    assert not any(c.startswith("azd down") for c in calls(sandbox))
    assert (sandbox / "selected").read_text().strip() == "lf-eh"


def test_teardown_unlocks_again_and_retries_a_failed_down_once(sandbox):
    add_lf_g3(sandbox)
    (sandbox / "down-fails").write_text("1")
    result = lab(sandbox, "teardown", "lf-g3", "--yes", az_body=AZ_TEARDOWN)
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(sandbox)
    assert log.count("python scripts/evidence_unlock.py --yes") == 2
    assert len([c for c in log if c.startswith("azd down")]) == 2
    assert (sandbox / "selected").read_text().strip() == "lf-eh"


def test_teardown_selects_lf_eh_again_even_when_it_stops_partway(sandbox):
    add_lf_g3(sandbox, select=True)
    (sandbox / ".azure" / "lf-g3").mkdir(parents=True)
    (sandbox / "down-fails").write_text("2")
    result = lab(sandbox, "teardown", "lf-g3", "--yes", az_body=AZ_TEARDOWN)
    assert result.returncode != 0
    assert (sandbox / "selected").read_text().strip() == "lf-eh"
    assert (sandbox / ".azure" / "lf-g3").exists()          # kept: the environment still exists in Azure


# ---- lab.sh sync: this machine's azd values against the lab's last successful provision (ADR-025) ----
DEPLOYMENT = {
    "p": {
        "environmentName": {"value": "lf-eh"},
        "principalId": {"value": "33333333-3333-3333-3333-333333333333"},
        "sqlAdminPassword": {},
        "orderImage": {"value": BASE},
        "modelName": {"value": "gpt-5.1"},
        "searchLocation": {"value": "eastus"},
        "mcpImage": {"value": "acrlftest.azurecr.io/mcp-server:sha-" + "9" * 40},
        "loadgendrillid": {"value": "drill-loadgen-1111"},        # ARM may change a name's case
        "promptShields": {"value": "on"},                        # the default: the same as unset here
        "controlCenterImage": {"value": ""},
        "modelCapacity": {"value": 40},
    },
    "o": {
        "twiN_RG": {"type": "String", "value": "rg-lf-twin-lf-eh"},
        "mcP_URL": {"type": "String", "value": "https://ca-mcp.example.azurecontainerapps.io"},
        "foundrY_PROJECT_ENDPOINT": {"type": "String", "value": "https://ais.example/api/projects/proj-livefire"},
    },
}


def az_sync(sandbox, name="lf-eh-1794450911"):
    import json
    (sandbox / "infra").mkdir(exist_ok=True)
    shutil.copy(SCRIPTS.parent / "infra" / "main.parameters.json", sandbox / "infra")
    (sandbox / "deployment.json").write_text(json.dumps(DEPLOYMENT))
    env = sandbox / "values" / "lf-eh.env"                 # this machine never had the lab's Search region
    env.write_text("".join(l + "\n" for l in env.read_text().splitlines() if not l.startswith("SEARCH_LOCATION=")))
    return f"""echo "az $*" >> LOG
case "$*" in
  "deployment sub list"*) echo "{name}" ;;
  "deployment sub show"*) cat "{(sandbox / 'deployment.json').as_posix()}" ;;
esac
"""


def test_sync_names_what_differs_from_the_lab_and_changes_nothing(sandbox):
    result = lab(sandbox, "sync", az_body=az_sync(sandbox))
    assert result.returncode == 1, result.stdout + result.stderr
    out = result.stdout
    for k in ("SEARCH_LOCATION", "MCP_IMAGE", "MCP_URL", "FOUNDRY_PROJECT_ENDPOINT", "MODEL_CAPACITY"):
        assert f"missing here  {k}" in out, k
    assert "differs       LOADGEN_DRILL_ID" in out
    assert "info  CONTROL_CENTER_IMAGE is set here, empty in the lab" in out
    for k in ("MODEL_NAME", "TWIN_RG", "ORDER_IMAGE", "AZURE_PRINCIPAL_ID", "AZURE_ENV_NAME", "SQL_ADMIN_PASSWORD",
              "PROMPT_SHIELDS"):
        assert k not in out, k                                   # the same (or the default), azd's own, or secure
    assert "ca-mcp.example" not in out and "drill-loadgen-1111" not in out      # names only, never values
    assert "6 value(s) differ: rerun with --apply" in out
    assert not any(c.startswith("azd env set") for c in calls(sandbox))
    listing = calls(sandbox)[0]
    assert "deployment sub list" in listing and "Succeeded" in listing and "azd-env-name" in listing


def test_sync_apply_takes_the_labs_values(sandbox):
    result = lab(sandbox, "sync", "--apply", az_body=az_sync(sandbox))
    assert result.returncode == 0, result.stdout + result.stderr
    now = values_of(sandbox, "lf-eh")
    assert now["SEARCH_LOCATION"] == "eastus" and now["MODEL_CAPACITY"] == "40"
    assert "PROMPT_SHIELDS" not in now                     # a default is not written into the environment
    assert now["MCP_URL"] == "https://ca-mcp.example.azurecontainerapps.io"
    assert now["LOADGEN_DRILL_ID"] == "drill-loadgen-1111"
    assert now["CONTROL_CENTER_IMAGE"].startswith("acrlftest.azurecr.io/control-center")   # kept, only reported
    assert now["SQL_ADMIN_PASSWORD"] == "lf-eh-secret"
    assert "6 value(s) taken from the lab" in result.stdout


def test_sync_says_so_when_this_machine_is_in_step(sandbox):
    az = az_sync(sandbox)
    assert lab(sandbox, "sync", "--apply", az_body=az).returncode == 0
    result = lab(sandbox, "sync", az_body=az)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "in step with the lab" in result.stdout


def test_sync_stops_without_a_successful_provision(sandbox):
    result = lab(sandbox, "sync", az_body=az_sync(sandbox, name=""))
    assert result.returncode == 1
    assert "no successful provision of lf-eh" in result.stdout


def test_sync_names_values_pasted_with_curly_quotes(sandbox):
    az = az_sync(sandbox)
    env = sandbox / "values" / "lf-eh.env"
    env.write_text(env.read_text() + 'GITHUB_REPOS="‘livefire-team@1/livefire-fusion-poc@2’"\n')
    result = lab(sandbox, "sync", az_body=az)
    assert "WARNING: GITHUB_REPOS holds curly quotes or other non-ASCII characters" in result.stdout
    assert "livefire-team@1" not in result.stdout
