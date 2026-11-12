"""postprovision.sh and deploy.sh images, driven through fake az, azd, sqlcmd and docker (no Azure needed)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parents[1] / "scripts"
BASH = shutil.which("bash")
GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(BASH is None or GIT is None, reason="bash and git are needed")

VALUES = """TWIN_RG=rg-lf-twin-test
CONTROL_RG=rg-lf-control-test
SQL_SERVER_FQDN=sql-lf-x.database.windows.net
SQL_DB_NAME=orders
SQL_ADMIN_PASSWORD=x
KEYVAULT_NAME=kv-lf-twin
ORDER_APP_NAME=ca-order
CONTROL_KEYVAULT_NAME=kv-lfc-test
REFEREE_SQL_PASSWORD=existing-referee-pw
REGISTRY_NAME=acrlftest
REGISTRY_SERVER=acrlftest.azurecr.io
AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000000
OPS_PRINCIPAL_ID=11111111-1111-1111-1111-111111111111
"""


def fake(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def log_lines(sandbox):
    f = sandbox / "calls.log"
    return f.read_text().splitlines() if f.exists() else []


@pytest.fixture
def sandbox(tmp_path):
    bins = tmp_path / "bin"
    bins.mkdir()
    log = (tmp_path / "calls.log").as_posix()
    fake(bins / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{VALUES}EOF\n'
                       f'else echo "azd $*" >> {log}; fi\n')
    fake(bins / "curl", "echo 203.0.113.7\n")
    fake(bins / "sqlcmd", f'echo "sqlcmd $*" >> {log}\n')
    fake(bins / "openssl", "echo generated-value\n")
    fake(bins / "docker", f'echo "docker $*" >> {log}\n')
    return tmp_path


def run(sandbox, script, *args, az_body, cwd=None):
    fake(sandbox / "bin" / "az", az_body.replace("LOG", (sandbox / "calls.log").as_posix()))
    env = {**os.environ, "PATH": f"{(sandbox / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([BASH, script, *args], cwd=cwd or sandbox, env=env, capture_output=True, text=True,
                          timeout=60)


# ---- postprovision.sh ----

def copy_repo_bits(sandbox):
    (sandbox / "sql").mkdir()
    (sandbox / "sql" / "schema.sql").write_text("")
    (sandbox / "sql" / "seed.sql").write_text("")
    scripts = sandbox / "scripts"
    scripts.mkdir()
    shutil.copy(SCRIPTS / "postprovision.sh", scripts)
    if (SCRIPTS / "cc-secrets.sh").exists():
        shutil.copy(SCRIPTS / "cc-secrets.sh", scripts)
    fake(scripts / "new-drill.sh", "echo drill-test-0001\n")
    fake(scripts / "wait-for.sh", "exit 0\n")
    fake(scripts / "referee.sh", f'echo "referee $*" >> {(sandbox / "calls.log").as_posix()}\n')
    return scripts / "postprovision.sh"


AZ_VAULT_HAS_RUNNER_KEY = """echo "az $*" >> LOG
case "$*" in
  "keyvault secret list"*) echo ops-runner-key ;;
  "keyvault secret show"*"referee-sql-password"*) echo existing-referee-pw ;;
  "keyvault secret show"*) exit 1 ;;
  "containerapp show"*) echo rev-1 ;;
esac
"""


def test_postprovision_creates_only_missing_keys_and_reuses_passwords(sandbox):
    script = copy_repo_bits(sandbox)
    result = run(sandbox, script.as_posix(), az_body=AZ_VAULT_HAS_RUNNER_KEY)
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    sets = [c for c in calls if c.startswith("az keyvault secret set") and "kv-lfc-test" in c]
    names = [c.split(" -n ")[1].split()[0] for c in sets]
    assert names == ["ops-agent-key", "recovery-grant-key", "mcp-planner-key", "mcp-engineer-key", "mcp-recovery-key",
                     "ops-cleanup-sql-password"]
    assert "azd env set REFEREE_SQL_PASSWORD existing-referee-pw" in calls
    sql = (sandbox / "calls.log").read_text()
    assert "CREATE USER ops_cleanup" in sql and "GRANT SELECT, DELETE ON dbo.orders TO ops_cleanup" in sql
    assert calls[-1] == "referee baseline"


def run_postprovision_with_search(sandbox, extra):
    script = copy_repo_bits(sandbox)
    log = (sandbox / "calls.log").as_posix()
    values = VALUES + "SEARCH_ENDPOINT=https://srch-test.search.windows.net\n" + extra
    fake(sandbox / "bin" / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{values}EOF\n'
                                  f'else echo "azd $*" >> {log}; fi\n')
    fake(sandbox / "bin" / "python3", f'echo "python3 $*" >> {log}\n')
    return run(sandbox, script.as_posix(), az_body=AZ_VAULT_HAS_RUNNER_KEY)


def test_postprovision_loads_no_incidents_without_a_private_corpus(sandbox):
    result = run_postprovision_with_search(sandbox, "")
    assert result.returncode == 0, result.stderr
    assert "incident index not loaded: set INCIDENT_CORPUS" in result.stderr
    assert not any("load-incidents.py" in c for c in log_lines(sandbox))


def test_postprovision_loads_the_incidents_from_the_private_corpus(sandbox):
    corpus = sandbox / "private" / "incidents"
    corpus.mkdir(parents=True)
    result = run_postprovision_with_search(sandbox, f"INCIDENT_CORPUS={corpus.as_posix()}\n")
    assert result.returncode == 0, result.stderr
    loads = [c for c in log_lines(sandbox) if "load-incidents.py" in c]
    assert loads == [f"python3 scripts/load-incidents.py --endpoint https://srch-test.search.windows.net "
                     f"--corpus {corpus.as_posix()}"]


AZ_VAULT_NOT_READY_YET = """echo "az $*" >> LOG
case "$*" in
  "keyvault secret list"*)
    n=$(cat list-calls 2>/dev/null || echo 0); echo $((n+1)) > list-calls
    if [ "$n" -lt 2 ]; then echo "Forbidden" >&2; exit 1; fi
    echo ops-runner-key; echo ops-agent-key; echo recovery-grant-key
    echo mcp-planner-key; echo mcp-engineer-key; echo mcp-recovery-key ;;
  "keyvault secret show"*) echo same ;;
  "containerapp show"*) echo rev-1 ;;
esac
"""


def test_postprovision_waits_for_the_vault_role(sandbox):
    script = copy_repo_bits(sandbox)
    text = script.read_text().replace("sleep 10", "sleep 0")
    script.write_text(text)
    result = run(sandbox, script.as_posix(), az_body=AZ_VAULT_NOT_READY_YET)
    assert result.returncode == 0, result.stderr
    assert "waiting for Key Vault access to apply" in result.stderr
    assert not [c for c in log_lines(sandbox) if c.startswith("az keyvault secret set") and "-key" in c]


AZ_TWIN_VAULT_SSL_INSPECTED = """echo "az $*" >> LOG
case "$*" in
  "keyvault secret list --vault-name kv-lf-twin"*)
    echo "ERROR: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed" >&2; exit 1 ;;
  "keyvault secret list"*) echo ops-runner-key ;;
  "containerapp show"*) echo rev-1 ;;
esac
"""


def test_postprovision_stops_before_any_change_when_the_twin_vault_is_unreachable(sandbox):
    script = copy_repo_bits(sandbox)
    script.write_text(script.read_text().replace("sleep 10", "sleep 0"))
    result = run(sandbox, script.as_posix(), az_body=AZ_TWIN_VAULT_SSL_INSPECTED)
    assert result.returncode == 1
    assert "SQL passwords unchanged" in result.stderr
    calls = log_lines(sandbox)
    assert not [c for c in calls if c.startswith("sqlcmd")]
    assert not [c for c in calls if c.startswith(("az keyvault secret set", "az sql", "azd env set"))]
    assert len([c for c in calls if c.startswith("az keyvault secret list")]) == 2   # no retries on a TLS error


AZ_DB_PASSWORD_WRITE_FAILS_ONCE = """echo "az $*" >> LOG
case "$*" in
  "keyvault secret set --vault-name kv-lf-twin -n db-password"*)
    n=$(cat set-calls 2>/dev/null || echo 0); echo $((n+1)) > set-calls
    if [ "$n" -lt 1 ]; then echo "Forbidden" >&2; exit 1; fi ;;
  "keyvault secret list"*) echo ops-runner-key; echo ops-agent-key; echo recovery-grant-key ;;
  "keyvault secret show"*) echo same ;;
  "containerapp show"*) echo rev-1 ;;
esac
"""


def test_postprovision_retries_the_db_password_write(sandbox):
    script = copy_repo_bits(sandbox)
    script.write_text(script.read_text().replace("sleep 10", "sleep 0"))
    result = run(sandbox, script.as_posix(), az_body=AZ_DB_PASSWORD_WRITE_FAILS_ONCE)
    assert result.returncode == 0, result.stderr
    sets = [c for c in log_lines(sandbox) if c.startswith("az keyvault secret set --vault-name kv-lf-twin -n db-password")]
    assert len(sets) == 2


# ---- deploy.sh images ----

def git(repo, *args):
    subprocess.run([GIT, "-C", repo.as_posix(), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def rev(repo, ref="HEAD"):
    return subprocess.run([GIT, "-C", repo.as_posix(), "rev-parse", ref], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A repo whose main history is merge commits, like the team's (ADR-003)."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run([GIT, "init", "-q", "--bare", "-b", "main", origin.as_posix()], check=True)
    subprocess.run([GIT, "clone", "-q", origin.as_posix(), work.as_posix()], check=True, capture_output=True)
    (work / "scripts").mkdir()
    shutil.copy(SCRIPTS / "deploy.sh", work / "scripts")
    for d in ("src/order-service", "src/ops-service", "src/load-generator", "referee", "journeys"):
        (work / d).mkdir(parents=True)
        (work / d / "x.txt").write_text("1")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    for component in ("src/load-generator", "src/ops-service", "referee"):
        git(work, "switch", "-qc", f"feat-{component.split('/')[-1]}")
        (work / component / "x.txt").write_text("2")
        git(work, "commit", "-qam", f"change {component}")
        git(work, "switch", "-q", "main")
        git(work, "merge", "-q", "--no-ff", f"feat-{component.split('/')[-1]}", "-m", f"merge {component}")
    (work / "README.md").write_text("docs")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "docs only")
    git(work, "push", "-q", "origin", "main")
    return work


AZ_IMPORT = """echo "az $*" >> LOG
case "$*" in
  "acr repository show"*"order-service"*) exit 0 ;;
  "acr repository show"*) exit 1 ;;
esac
"""


def test_images_picks_each_components_last_merge_on_main_and_imports_it(sandbox, repo):
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT, cwd=repo)
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    ops_merge = rev(repo, "HEAD~1^1")      # the merge that changed src/ops-service (first parent of referee's merge)
    referee_merge = rev(repo, "HEAD~1")
    loadgen_merge = rev(repo, "HEAD~3")
    imports = [c for c in calls if c.startswith("az acr import")]
    assert any(f"--source ghcr.io/livefire-team/ops-service:sha-{ops_merge[:7]}" in c
               and f"--image ops-service:sha-{ops_merge}" in c for c in imports)
    assert any(f"--source ghcr.io/livefire-team/referee:sha-{referee_merge[:7]}" in c for c in imports)
    assert any(f"--source ghcr.io/livefire-team/load-generator:sha-{loadgen_merge[:7]}" in c
               and f"--image load-generator:sha-{loadgen_merge}" in c for c in imports)
    assert not any("order-service" in c for c in imports)       # already in the registry: not imported again
    assert f"azd env set OPS_IMAGE acrlftest.azurecr.io/ops-service:sha-{ops_merge}" in calls
    assert f"azd env set REFEREE_IMAGE acrlftest.azurecr.io/referee:sha-{referee_merge}" in calls
    assert f"azd env set LOADGEN_IMAGE acrlftest.azurecr.io/load-generator:sha-{loadgen_merge}" in calls
    assert any(c.startswith("azd env set ORDER_IMAGE acrlftest.azurecr.io/order-service:sha-") for c in calls)
    assert "no commit at origin/main touches mcp-server: skipped" in result.stdout   # WS3 optional (ADR-022)
    assert "azd env set MCP_IMAGE " in calls             # a stale image from another ref is not left behind


AZ_IMPORT_NO_MCP_IN_GHCR = """echo "az $*" >> LOG
case "$*" in
  "acr repository show"*"order-service"*) exit 0 ;;
  "acr repository show"*) exit 1 ;;
  "acr import"*"mcp-server"*) echo "manifest unknown" >&2; exit 1 ;;
esac
"""


def test_images_carries_on_when_the_mcp_server_image_is_missing(sandbox, repo):
    (repo / "src" / "mcp-server").mkdir(parents=True)
    (repo / "src" / "mcp-server" / "x.txt").write_text("1")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add mcp-server")
    git(repo, "push", "-q", "origin", "main")
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT_NO_MCP_IN_GHCR,
                 cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "mcp-server image not imported" in result.stderr
    calls = log_lines(sandbox)
    assert any(c.startswith("azd env set OPS_IMAGE") for c in calls)
    assert not any(c.startswith("azd env set MCP_IMAGE acrlftest") for c in calls)


def test_images_imports_mcp_server_once_it_is_on_main(sandbox, repo):
    git(repo, "switch", "-qc", "feat-mcp")
    (repo / "src" / "mcp-server").mkdir(parents=True)
    (repo / "src" / "mcp-server" / "x.txt").write_text("1")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add mcp-server")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "feat-mcp", "-m", "merge mcp-server")
    git(repo, "push", "-q", "origin", "main")
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT, cwd=repo)
    assert result.returncode == 0, result.stderr
    merge = rev(repo)
    calls = log_lines(sandbox)
    assert any(c.startswith("az acr import") and f"--source ghcr.io/livefire-team/mcp-server:sha-{merge[:7]}" in c
               for c in calls)
    assert f"azd env set MCP_IMAGE acrlftest.azurecr.io/mcp-server:sha-{merge}" in calls


AZ_IMPORT_NO_LOADGEN_IN_GHCR = """echo "az $*" >> LOG
case "$*" in
  "acr repository show"*"order-service"*) exit 0 ;;
  "acr repository show"*) exit 1 ;;
  "acr import"*"load-generator"*) echo "manifest unknown" >&2; exit 1 ;;
esac
"""


def test_images_carries_on_when_the_load_generator_image_is_missing(sandbox, repo):
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT_NO_LOADGEN_IN_GHCR,
                 cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "load-generator image not imported" in result.stderr and "LOADGEN_IMAGE unchanged" in result.stderr
    calls = log_lines(sandbox)
    assert any(c.startswith("azd env set OPS_IMAGE") for c in calls)
    assert not any(c.startswith("azd env set LOADGEN_IMAGE") for c in calls)


def test_an_unknown_phase_prints_the_whole_usage(sandbox):
    result = run(sandbox, copy_deploy(sandbox).as_posix(), "verfy", az_body="")
    assert result.returncode == 2
    assert result.stdout.rstrip().splitlines()[-1].startswith("#   scripts/deploy.sh verify ")


# ---- deploy.sh apps: ca-mcp only when its secrets are in the control vault (ADR-022) ----
APPS_VALUES = VALUES + """OPS_IMAGE=acrlftest.azurecr.io/ops-service:sha-1
REFEREE_IMAGE=acrlftest.azurecr.io/referee:sha-1
ORDER_IMAGE=acrlftest.azurecr.io/order-service:sha-1
MCP_IMAGE=acrlftest.azurecr.io/mcp-server:sha-1
OPS_URL=https://ca-ops.internal.example.azurecontainerapps.io
GITHUB_PLANNER_APP_ID=1
GITHUB_PLANNER_INSTALLATION_ID=2
GITHUB_ENGINEER_APP_ID=3
GITHUB_ENGINEER_INSTALLATION_ID=4
MCP_ENGINEER_WRITE_PATHS=src/example/app/module.py
"""
ALL_MCP_SECRETS = ("ops-agent-key mcp-planner-key mcp-engineer-key mcp-recovery-key "
                   "gh-planner-private-key gh-engineer-private-key")


def run_apps(sandbox, vault_secrets, phase="apps", extra=""):
    log = (sandbox / "calls.log").as_posix()
    fake(sandbox / "bin" / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{APPS_VALUES}{extra}EOF\n'
                                  f'else echo "azd $*" >> {log}; fi\n')
    added = (sandbox / "added").as_posix()
    az = (f'echo "az $*" >> LOG\ncase "$*" in\n'
          f'  "keyvault secret list"*) printf "%s\\n" {vault_secrets}; cat {added} 2>/dev/null || true ;;\n'
          f'  "keyvault secret set"*) for a in "$@"; do [ "$prev" = -n ] && echo "$a" >> {added}; prev="$a"; done ;;\n'
          f'esac\n')
    return run(sandbox, copy_deploy(sandbox).as_posix(), phase, az_body=az)


def test_infra_also_leaves_ca_mcp_out_when_its_secrets_are_missing(sandbox):
    result = run_apps(sandbox, "ops-agent-key", phase="infra")
    assert result.returncode == 0, result.stderr
    assert "ca-mcp left out of this provision" in result.stderr
    calls = log_lines(sandbox)
    assert calls.index("azd env set MCP_IMAGE ") < calls.index("azd provision")


def test_entra_mode_needs_the_client_id_and_the_three_agent_identities(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS, extra="MCP_AUTH_MODE=entra\nMCP_CLIENT_ID=abc\n")
    assert result.returncode == 0, result.stderr
    for name in ("PLANNER_AGENT_OBJECT_ID", "ENGINEER_AGENT_OBJECT_ID", "RECOVERY_AGENT_OBJECT_ID"):
        assert f"azd env value {name}" in result.stderr
    assert "azd env value MCP_CLIENT_ID" not in result.stderr
    assert "azd env set MCP_IMAGE " in log_lines(sandbox)


@pytest.mark.parametrize("phase", ["infra", "apps"])
def test_an_unreadable_vault_stops_the_deploy_instead_of_dropping_ca_mcp(sandbox, phase):
    log = (sandbox / "calls.log").as_posix()
    fake(sandbox / "bin" / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{APPS_VALUES}EOF\n'
                                  f'else echo "azd $*" >> {log}; fi\n')
    az = 'echo "az $*" >> LOG\ncase "$*" in "keyvault secret list"*) echo Forbidden >&2; exit 1 ;; esac\n'
    result = run(sandbox, copy_deploy(sandbox).as_posix(), phase, az_body=az)
    assert result.returncode != 0
    assert "cannot list the secrets in kv-lfc-test; nothing provisioned" in result.stderr
    assert "REQUESTS_CA_BUNDLE" in result.stderr and "left out" not in result.stderr
    calls = log_lines(sandbox)
    assert "azd provision" not in calls and not any(c.startswith("azd env set MCP_IMAGE") for c in calls)


def test_apps_leaves_ca_mcp_out_without_the_engineer_write_paths(sandbox):
    log = (sandbox / "calls.log").as_posix()
    values = APPS_VALUES.replace("MCP_ENGINEER_WRITE_PATHS=src/example/app/module.py\n", "")
    fake(sandbox / "bin" / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{values}EOF\n'
                                  f'else echo "azd $*" >> {log}; fi\n')
    az = f'echo "az $*" >> LOG\ncase "$*" in "keyvault secret list"*) printf "%s\\n" {ALL_MCP_SECRETS} ;; esac\n'
    result = run(sandbox, copy_deploy(sandbox).as_posix(), "apps", az_body=az)
    assert result.returncode == 0, result.stderr
    assert "ca-mcp left out of this provision" in result.stderr
    assert "azd env value MCP_ENGINEER_WRITE_PATHS" in result.stderr


def test_apps_leaves_ca_mcp_out_and_names_what_is_missing(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS.replace("gh-engineer-private-key", ""))
    assert result.returncode == 0, result.stderr
    assert "ca-mcp left out of this provision" in result.stderr
    assert "a running ca-mcp loses its twin vault metadata access until a provision with MCP_IMAGE set" in result.stderr
    assert "secret gh-engineer-private-key in kv-lfc-test" in result.stderr
    calls = log_lines(sandbox)
    assert calls.index("azd env set MCP_IMAGE ") < calls.index("azd provision")


def test_apps_names_caj_loadgen_only_when_its_image_is_set(sandbox):
    assert "caj-loadgen" not in run_apps(sandbox, ALL_MCP_SECRETS).stdout
    result = run_apps(sandbox, ALL_MCP_SECRETS, extra="LOADGEN_IMAGE=acrlftest.azurecr.io/load-generator:sha-1\n")
    assert result.returncode == 0, result.stderr
    assert "caj-loadgen" in result.stdout


def test_apps_deploys_ca_mcp_when_everything_is_there(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS)
    assert result.returncode == 0, result.stderr
    assert "left out" not in result.stderr
    calls = log_lines(sandbox)
    assert "azd provision" in calls and not any(c.startswith("azd env set MCP_IMAGE") for c in calls)


# ---- deploy.sh policy-off ----
def copy_deploy(sandbox):
    scripts = sandbox / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy(SCRIPTS / "deploy.sh", scripts)
    if (SCRIPTS / "cc-secrets.sh").exists():
        shutil.copy(SCRIPTS / "cc-secrets.sh", scripts)
    return scripts / "deploy.sh"


AZ_ROLE_GONE = """echo "az $*" >> LOG
case "$*" in "role assignment list"*) echo 0 ;; esac
"""
AZ_ROLE_STAYS = """echo "az $*" >> LOG
case "$*" in "role assignment list"*) echo 1 ;; esac
"""


def test_policy_off_removes_the_broad_attempt_role_before_the_policy(sandbox):
    result = run(sandbox, copy_deploy(sandbox).as_posix(), "policy-off", az_body=AZ_ROLE_GONE)
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    role = next(i for i, c in enumerate(calls) if c.startswith("az role assignment delete"))
    policy = next(i for i, c in enumerate(calls) if c.startswith("az policy assignment delete"))
    assert role < policy and "azd env set DENY_BROAD_POLICY off" in calls


def test_policy_off_keeps_the_policy_while_the_role_is_still_there(sandbox):
    result = run(sandbox, copy_deploy(sandbox).as_posix(), "policy-off", az_body=AZ_ROLE_STAYS)
    calls = log_lines(sandbox)
    assert result.returncode != 0 and "still holds" in result.stdout
    assert not any(c.startswith("az policy assignment delete") for c in calls)
    assert "azd env set DENY_BROAD_POLICY off" not in calls


# ---- WS4 (ADR-026): job-drill-runner only when its inputs exist; Foundry follows ca-mcp ----
RUNNER_VALUES = """MODEL_NAME=gpt-5.1
MODEL_VERSION=2025-11-13
PLANNER_AGENT=lf-planner:1
ENGINEER_AGENT=lf-engineer:1
RUNNER_GITHUB_APP_ID=5
RUNNER_GITHUB_INSTALLATION_ID=6
RUNNER_IMAGE=acrlftest.azurecr.io/drill-runner:sha-1
"""


def test_runner_deploys_when_everything_is_there(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS + " ops-runner-key gh-runner-private-key", extra=RUNNER_VALUES)
    assert result.returncode == 0, result.stderr
    assert "left out" not in result.stderr
    calls = log_lines(sandbox)
    assert "azd provision" in calls and not any(c.startswith("azd env set RUNNER_IMAGE") for c in calls)


def test_runner_is_left_out_and_names_its_missing_github_key(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS + " ops-runner-key", extra=RUNNER_VALUES)
    assert result.returncode == 0, result.stderr
    assert "job-drill-runner left out of this provision" in result.stderr
    assert "secret gh-runner-private-key in kv-lfc-test" in result.stderr
    assert "ca-mcp left out" not in result.stderr                   # WS3 is unaffected
    calls = log_lines(sandbox)
    assert calls.index("azd env set RUNNER_IMAGE ") < calls.index("azd provision")


def test_runner_token_fallback_needs_the_token_secret_and_no_app_ids(sandbox):
    extra = RUNNER_VALUES.replace("RUNNER_GITHUB_APP_ID=5\nRUNNER_GITHUB_INSTALLATION_ID=6\n", "")
    result = run_apps(sandbox, ALL_MCP_SECRETS + " ops-runner-key gh-runner-token",
                      extra=extra + "RUNNER_GITHUB_AUTH=token\n")
    assert result.returncode == 0, result.stderr
    assert "left out" not in result.stderr


def test_runner_is_left_out_when_ca_mcp_is(sandbox):
    result = run_apps(sandbox, "ops-agent-key ops-runner-key gh-runner-private-key", extra=RUNNER_VALUES)
    assert result.returncode == 0, result.stderr
    assert "ca-mcp left out" in result.stderr and "job-drill-runner left out" in result.stderr
    assert "ca-mcp (MCP_IMAGE)" in result.stderr


def test_runner_is_left_out_without_its_pins(sandbox):
    extra = RUNNER_VALUES.replace("PLANNER_AGENT=lf-planner:1\n", "")
    result = run_apps(sandbox, ALL_MCP_SECRETS + " ops-runner-key gh-runner-private-key", extra=extra)
    assert "azd env value PLANNER_AGENT" in result.stderr and "job-drill-runner left out" in result.stderr


def test_foundry_phase_needs_the_model_and_ca_mcp(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS, phase="foundry")
    assert result.returncode == 1 and "set the model first" in result.stdout
    assert "azd provision" not in log_lines(sandbox)


def test_runner_phase_needs_an_image(sandbox):
    result = run_apps(sandbox, ALL_MCP_SECRETS, phase="runner")
    assert result.returncode == 1 and "no RUNNER_IMAGE" in result.stdout


def test_postprovision_can_skip_only_the_browser_baseline(sandbox, monkeypatch):
    monkeypatch.setenv("POSTPROVISION_BASELINE", "off")
    script = copy_repo_bits(sandbox)
    result = run(sandbox, script.as_posix(), az_body=AZ_VAULT_HAS_RUNNER_KEY)
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    assert "referee baseline" not in calls and "baseline skipped" in result.stdout
    assert any(c.startswith("sqlcmd") for c in calls)                  # everything before it still ran
    assert any("containerapp revision restart" in c for c in calls)


def test_ws4_foundry_phase_skips_the_local_baseline(sandbox):
    log = (sandbox / "calls.log").as_posix()
    values = APPS_VALUES + RUNNER_VALUES + "FOUNDRY_PROJECT_ENDPOINT=https://ais.example/api/projects/p\n"
    fake(sandbox / "bin" / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{values}EOF\n'
                                  f'else echo "azd $* baseline=${{POSTPROVISION_BASELINE:-unset}}" >> {log}; fi\n')
    az = f'echo "az $*" >> LOG\ncase "$*" in "keyvault secret list"*) printf "%s\\n" {ALL_MCP_SECRETS} ;; esac\n'
    result = run(sandbox, copy_deploy(sandbox).as_posix(), "foundry", az_body=az)
    assert result.returncode == 0, result.stderr
    assert "azd provision baseline=off" in log_lines(sandbox)
    assert "FOUNDRY_PROJECT_ENDPOINT=https://ais.example/api/projects/p" in result.stdout


# ---- G3 (ADR-024): WS5's Control Center from its exact GHCR build, deployed once its two secrets exist ----
CC_SHA = "c" * 40


def set_values(sandbox, values):
    log = (sandbox / "calls.log").as_posix()
    fake(sandbox / "bin" / "azd", f'if [ "$1 $2" = "env get-values" ]; then cat <<\'EOF\'\n{values}EOF\n'
                                  f'else echo "azd $*" >> {log}; fi\n')


def test_images_imports_the_control_center_from_its_exact_ghcr_build(sandbox, repo):
    set_values(sandbox, VALUES + f"CONTROL_CENTER_SOURCE=ghcr.io/livefire-team/control-center:sha-{CC_SHA}\n")
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT, cwd=repo)
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    assert any(c.startswith("az acr import") and f"--source ghcr.io/livefire-team/control-center:sha-{CC_SHA}" in c
               and f"--image control-center:sha-{CC_SHA}" in c for c in calls)
    assert f"azd env set CONTROL_CENTER_IMAGE acrlftest.azurecr.io/control-center:sha-{CC_SHA}" in calls


def test_images_refuses_a_control_center_source_that_is_not_an_exact_build(sandbox, repo):
    set_values(sandbox, VALUES + "CONTROL_CENTER_SOURCE=ghcr.io/livefire-team/control-center:latest\n")
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT, cwd=repo)
    assert result.returncode == 1
    assert "CONTROL_CENTER_SOURCE must end in :sha-<40 hex>" in result.stdout
    assert not any("control-center" in c for c in log_lines(sandbox))


def test_images_leaves_the_control_center_alone_without_a_source(sandbox, repo):
    result = run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "images", az_body=AZ_IMPORT, cwd=repo)
    assert result.returncode == 0, result.stderr
    assert not any("control-center" in c or "CONTROL_CENTER" in c for c in log_lines(sandbox))


def test_apps_makes_the_missing_passcode_secrets_then_deploys_the_control_center(sandbox):
    extra = f"CONTROL_CENTER_IMAGE=acrlftest.azurecr.io/control-center:sha-{CC_SHA}\nAZURE_ENV_NAME=lf-g3\n"
    result = run_apps(sandbox, ALL_MCP_SECRETS + " cc-session-secret", extra=extra)
    assert result.returncode == 0, result.stderr
    assert "left out" not in result.stderr
    calls = log_lines(sandbox)
    made = next(i for i, c in enumerate(calls) if c.startswith("az keyvault secret set") and " -n cc-passcode-sha256 " in c)
    assert made < calls.index("azd provision")
    assert not any(" -n cc-session-secret " in c for c in calls if c.startswith("az keyvault secret set"))
    assert not any(c.startswith("azd env set CONTROL_CENTER_IMAGE") for c in calls)
    assert (sandbox / ".local" / "cc-passcode-lf-g3.txt").exists()


def test_apps_deploys_the_control_center_when_its_secrets_exist(sandbox):
    extra = f"CONTROL_CENTER_IMAGE=acrlftest.azurecr.io/control-center:sha-{CC_SHA}\n"
    result = run_apps(sandbox, ALL_MCP_SECRETS + " cc-session-secret cc-passcode-sha256", extra=extra)
    assert result.returncode == 0, result.stderr
    assert "left out" not in result.stderr
    assert not any(c.startswith("azd env set CONTROL_CENTER_IMAGE") for c in log_lines(sandbox))


def test_an_easy_auth_control_center_without_its_client_secret_is_left_out(sandbox):
    extra = (f"CONTROL_CENTER_IMAGE=acrlftest.azurecr.io/control-center:sha-{CC_SHA}\n"
             "CONTROL_CENTER_AUTH_MODE=easyauth\n")
    result = run_apps(sandbox, ALL_MCP_SECRETS + " cc-session-secret", extra=extra)
    assert result.returncode == 0, result.stderr
    assert "ca-control-center left out of this provision" in result.stderr
    assert "secret cc-entra-client-secret in kv-lfc-test" in result.stderr
    assert "scripts/deploy.sh images, then apps" in result.stderr
    assert not any(" -n cc-passcode-sha256 " in c for c in log_lines(sandbox))   # no passcode for Easy Auth
    calls = log_lines(sandbox)
    assert calls.index("azd env set CONTROL_CENTER_IMAGE ") < calls.index("azd provision")
    result = run_apps(sandbox, ALL_MCP_SECRETS + " cc-session-secret cc-entra-client-secret", extra=extra)
    assert result.returncode == 0, result.stderr
    assert "left out" not in result.stderr


# ---- G2 follow-up: smoke keeps polling through a failed status call ----
def run_smoke(sandbox, az_body):
    set_values(sandbox, VALUES + "SMOKE_JOB_NAME=job-ops-smoke\nCONTROL_LOG_ANALYTICS_CUSTOMER_ID=ws-1\n")
    fake(sandbox / "bin" / "az", az_body.replace("LOG", (sandbox / "calls.log").as_posix()))
    env = {**os.environ, "SMOKE_POLL_S": "0", "SMOKE_LOG_WAIT_S": "0",
           "PATH": f"{(sandbox / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([BASH, copy_deploy(sandbox).as_posix(), "smoke", "auth"], cwd=sandbox, env=env,
                          capture_output=True, text=True, timeout=60)


AZ_SMOKE_STATUS_FLAKY = """echo "az $*" >> LOG
case "$*" in
  "containerapp job start"*) echo job-ops-smoke-x1 ;;
  "containerapp job execution show"*)
    n=$(cat show-calls 2>/dev/null || echo 0); echo $((n+1)) > show-calls
    if [ "$n" -lt 2 ]; then echo "ERROR: (ResourceNotFound) not found yet" >&2; exit 1; fi
    echo Succeeded ;;
  "monitor log-analytics query"*) echo "SMOKE PASSED" ;;
esac
"""


def test_smoke_keeps_polling_through_a_failed_status_call(sandbox):
    result = run_smoke(sandbox, AZ_SMOKE_STATUS_FLAKY)
    assert result.returncode == 0, result.stderr
    assert "status: Succeeded" in result.stdout and "SMOKE PASSED" in result.stdout


def test_smoke_stops_after_five_failed_status_calls_in_a_row(sandbox):
    result = run_smoke(sandbox, AZ_SMOKE_STATUS_FLAKY.replace('if [ "$n" -lt 2 ]', 'if true'))
    assert result.returncode != 0
    assert "could not read the execution's status 5 times in a row" in result.stderr


# ---- G3 (ADR-024): deploy.sh all is the one command for a fresh lab ----
# A fake azd that keeps its values, and whose provision plays Bicep's part: Foundry when ca-mcp and the model are
# set, the runner when its image and both pins are set
STATEFUL_AZD = r"""D="DIR"
if [ "$1 $2" = "env get-values" ]; then cat "$D/values.env"; exit 0; fi
if [ "$1 $2" = "env set" ]; then
  echo "azd $*" >> "$D/calls.log"
  grep -v "^$3=" "$D/values.env" > "$D/values.tmp" || true
  printf '%s="%s"\n' "$3" "$4" >> "$D/values.tmp"; mv "$D/values.tmp" "$D/values.env"; exit 0
fi
if [ "$1" = provision ]; then
  eval "$(cat "$D/values.env")"
  echo "azd provision mcp=${MCP_IMAGE:+on} runner=${RUNNER_IMAGE:+on} pins=${PLANNER_AGENT:-none}" >> "$D/calls.log"
  if [ -n "${MCP_IMAGE:-}" ] && [ -n "${MODEL_NAME:-}" ]; then
    echo 'FOUNDRY_PROJECT_ENDPOINT="https://ais.example/api/projects/proj-livefire"' >> "$D/values.env"; fi
  if [ -n "${RUNNER_IMAGE:-}" ] && [ -n "${PLANNER_AGENT:-}" ]; then
    echo 'RUNNER_JOB_NAME="job-drill-runner"' >> "$D/values.env"; fi
  exit 0
fi
echo "azd $*" >> "$D/calls.log"
"""
FAKE_PYTHON = r"""echo "python $*" >> "DIR/calls.log"
case "$*" in
  "-c "*) exit 0 ;;
  *"create_agents.py --verify"*) exit 0 ;;
  *create_agents.py*) echo PLANNER_AGENT=lf-planner:1; echo ENGINEER_AGENT=lf-engineer:1 ;;
esac
"""
FRESH_LAB = """MODEL_NAME="gpt-5.1"
MODEL_VERSION="2025-11-13"
GITHUB_PLANNER_APP_ID="1"
GITHUB_PLANNER_INSTALLATION_ID="2"
GITHUB_ENGINEER_APP_ID="3"
GITHUB_ENGINEER_INSTALLATION_ID="4"
RUNNER_GITHUB_APP_ID="5"
RUNNER_GITHUB_INSTALLATION_ID="6"
MCP_ENGINEER_WRITE_PATHS="src/example/app/module.py"
OPS_URL="https://ca-ops.internal.example.azurecontainerapps.io"
"""
AZ_FRESH_LAB = """echo "az $*" >> LOG
case "$*" in
  "acr repository show"*) exit 0 ;;
  "keyvault secret list"*) printf "%s\\n" ops-agent-key ops-runner-key mcp-planner-key mcp-engineer-key \\
      mcp-recovery-key gh-planner-private-key gh-engineer-private-key gh-runner-private-key ;;
esac
"""


def run_all(sandbox, repo, values, python=FAKE_PYTHON):
    for component in ("src/mcp-server", "src/drill-runner"):
        (repo / component).mkdir(parents=True, exist_ok=True)
        (repo / component / "x.txt").write_text("1")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add mcp-server and drill-runner")
    git(repo, "push", "-q", "origin", "main")
    (sandbox / "values.env").write_text(
        "".join(f'{line.split("=", 1)[0]}="{line.split("=", 1)[1]}"\n' for line in VALUES.splitlines()) + values)
    fake(sandbox / "bin" / "azd", STATEFUL_AZD.replace("DIR", sandbox.as_posix()))
    for name in ("python", "python3"):
        fake(sandbox / "bin" / name, python.replace("DIR", sandbox.as_posix()))
    return run(sandbox, (repo / "scripts" / "deploy.sh").as_posix(), "all", az_body=AZ_FRESH_LAB, cwd=repo)


def test_all_brings_up_the_platform_then_both_ws4_passes(sandbox, repo):
    result = run_all(sandbox, repo, FRESH_LAB)
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    provisions = [c for c in calls if c.startswith("azd provision")]
    assert provisions == ["azd provision mcp= runner= pins=none",          # infra: nothing built yet
                          "azd provision mcp=on runner= pins=none",        # apps: the runner waits for the pins
                          "azd provision mcp=on runner=on pins=lf-planner:1"]  # runner: second WS4 pass
    agents = next(i for i, c in enumerate(calls) if c.endswith("scripts/create_agents.py"))
    assert calls.index(provisions[1]) < agents < calls.index(provisions[2])
    assert any(c.startswith("python scripts/evidence_check.py") for c in calls[calls.index(provisions[2]):])
    assert "RUNNER_JOB_NAME=job-drill-runner" in result.stdout
    assert "deploy.sh all:" in result.stdout


def test_all_keeps_the_agents_it_already_pinned(sandbox, repo):
    result = run_all(sandbox, repo, FRESH_LAB + 'PLANNER_AGENT="lf-planner:7"\nENGINEER_AGENT="lf-engineer:5"\n')
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    assert not any("create_agents.py" in c for c in calls)
    assert "agents already pinned: lf-planner:7 and lf-engineer:5" in result.stdout
    assert [c for c in calls if c.startswith("azd provision")][-1] == "azd provision mcp=on runner=on pins=lf-planner:7"


def test_all_without_a_model_deploys_the_platform_and_says_why_ws4_is_not_there(sandbox, repo):
    result = run_all(sandbox, repo, FRESH_LAB.replace('MODEL_NAME="gpt-5.1"\n', ""))
    assert result.returncode == 0, result.stderr
    calls = log_lines(sandbox)
    assert len([c for c in calls if c.startswith("azd provision")]) == 2
    assert not any("create_agents.py" in c for c in calls)
    assert "WS4 not deployed: no MODEL_NAME" in result.stdout
    assert any(c.startswith("python scripts/evidence_check.py") for c in calls)


def test_all_names_a_missing_runner_input_and_still_verifies(sandbox, repo):
    global AZ_FRESH_LAB
    saved = AZ_FRESH_LAB
    AZ_FRESH_LAB = saved.replace(" gh-runner-private-key", "")
    try:
        result = run_all(sandbox, repo, FRESH_LAB)
    finally:
        AZ_FRESH_LAB = saved
    assert result.returncode == 0, result.stderr
    assert "job-drill-runner not deployed; missing:" in result.stdout
    assert "secret gh-runner-private-key in kv-lfc-test" in result.stdout
    calls = log_lines(sandbox)
    assert len([c for c in calls if c.startswith("azd provision")]) == 2
    assert any(c.startswith("python scripts/evidence_check.py") for c in calls)


def test_all_stops_before_any_change_without_the_agent_packages(sandbox, repo):
    result = run_all(sandbox, repo, FRESH_LAB, python=FAKE_PYTHON.replace('"-c "*) exit 0 ;;', '"-c "*) exit 1 ;;'))
    assert result.returncode == 1
    assert "install the runner's packages first" in result.stdout
    assert not any(c.startswith("azd provision") for c in log_lines(sandbox))


# ---- G3 (ADR-024, ADR-025): a new environment's control vault gets the GitHub App keys and WS5's two secrets ----
KEYS = {"gh-planner-private-key": "planner", "gh-engineer-private-key": "engineer", "gh-runner-private-key": "runner"}
AZ_NEW_CONTROL_VAULT = """echo "az $*" >> LOG
case "$*" in
  "keyvault secret list"*) printf "%s\\n" ops-runner-key EXISTING ;;
  "keyvault secret show --vault-name kv-lfc-source -n gh-planner-private-key"*)
    printf '%s' '"-----BEGIN KEY-----\\nplanner-secret-body\\n-----END KEY-----\\n"' ;;
  "keyvault secret show --vault-name kv-lfc-source -n gh-engineer-private-key"*)
    printf '%s' '"-----BEGIN KEY-----\\nengineer-secret-body\\n-----END KEY-----\\n"' ;;
  "keyvault secret show --vault-name kv-lfc-source -n gh-runner-private-key"*) SOURCE_RUNNER ;;
  "keyvault secret show"*"referee-sql-password"*) echo existing-referee-pw ;;
  "keyvault secret show"*) exit 1 ;;
  "keyvault secret set"*"--file"*)
    for a in "$@"; do case "$prev" in -n) n="$a" ;; --file) f="$a" ;; esac; prev="$a"; done
    cp "$f" "DIR/stored-$n"; echo "$f" > "DIR/tempfile-$n" ;;
  "containerapp show"*) echo rev-1 ;;
esac
"""
FAKE_OPENSSL = """case "$1" in
  rand) echo "random-$2-$3" ;;
  dgst) read -r x || true; echo "hash-of-$x *stdin" ;;
esac
"""


def run_hook(sandbox, extra, existing="", source_runner="exit 1"):
    script = copy_repo_bits(sandbox)
    script.write_text(script.read_text().replace("sleep 10", "sleep 0"))
    set_values(sandbox, VALUES + "AZURE_ENV_NAME=lf-g3\n" + extra)
    fake(sandbox / "bin" / "openssl", FAKE_OPENSSL)
    az = (AZ_NEW_CONTROL_VAULT.replace("EXISTING", existing).replace("SOURCE_RUNNER", source_runner)
          .replace("DIR", sandbox.as_posix()))
    return run(sandbox, script.as_posix(), az_body=az)


needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is needed")


@needs_jq
def test_hook_copies_the_github_app_keys_from_the_source_vault_and_never_shows_them(sandbox):
    result = run_hook(sandbox, "SECRETS_SOURCE_VAULT=kv-lfc-source\n",
                      source_runner="""printf '%s' '"-----BEGIN KEY-----\\nrunner-secret-body\\n-----END KEY-----\\n"'""")
    assert result.returncode == 0, result.stderr
    for name, who in KEYS.items():
        stored = (sandbox / f"stored-{name}").read_text()
        assert stored == f"-----BEGIN KEY-----\n{who}-secret-body\n-----END KEY-----\n"   # exact, no extra newline
        assert not Path((sandbox / f"tempfile-{name}").read_text().strip()).exists()      # the copy is gone
        assert f"copied {name} from kv-lfc-source" in result.stdout
    seen = (sandbox / "calls.log").read_text() + result.stdout + result.stderr
    assert "secret-body" not in seen and "BEGIN KEY" not in seen


@needs_jq
def test_hook_keeps_app_keys_already_in_the_vault(sandbox):
    result = run_hook(sandbox, "SECRETS_SOURCE_VAULT=kv-lfc-source\n",
                      existing="gh-planner-private-key gh-engineer-private-key gh-runner-private-key")
    assert result.returncode == 0, result.stderr
    assert not any("kv-lfc-source" in c for c in log_lines(sandbox))


@needs_jq
def test_hook_names_a_key_the_source_vault_lacks_and_carries_on(sandbox):
    result = run_hook(sandbox, "SECRETS_SOURCE_VAULT=kv-lfc-source\n")
    assert result.returncode == 0, result.stderr
    assert "WARNING: gh-runner-private-key is not in kv-lfc-source" in result.stderr
    assert (sandbox / "stored-gh-planner-private-key").exists()
    assert not (sandbox / "stored-gh-runner-private-key").exists()


def test_hook_stores_the_app_keys_from_a_private_folder(sandbox):
    keys = sandbox / "private" / "github-apps"
    keys.mkdir(parents=True)
    for who in ("planner", "engineer"):
        (keys / f"{who}.pem").write_text(f"{who}-pem")
    result = run_hook(sandbox, f"GITHUB_APP_KEYS={keys.as_posix()}\n")
    assert result.returncode == 0, result.stderr
    assert (sandbox / "stored-gh-planner-private-key").read_text() == "planner-pem"
    assert (sandbox / "stored-gh-engineer-private-key").read_text() == "engineer-pem"
    assert not (sandbox / "stored-gh-runner-private-key").exists()            # no runner.pem in the folder
    assert "stored gh-planner-private-key from" in result.stdout


def test_hook_creates_the_control_center_secrets_and_keeps_the_passcode_private(sandbox):
    result = run_hook(sandbox, "CONTROL_CENTER_SOURCE=ghcr.io/livefire-team/control-center:sha-" + "c" * 40 + "\n")
    assert result.returncode == 0, result.stderr
    passcode = sandbox / ".local" / "cc-passcode-lf-g3.txt"
    assert passcode.stat().st_mode & 0o777 == 0o600
    secret = passcode.read_text()
    assert secret == "random--base64-18" and not secret.endswith("\n")
    assert (sandbox / "stored-cc-passcode-sha256").read_text() == f"hash-of-{secret}"   # the hash of that passcode
    assert (sandbox / "stored-cc-session-secret").read_text() == "random--base64-48"   # no newline
    seen = (sandbox / "calls.log").read_text() + result.stdout + result.stderr
    assert secret not in seen and "random--base64-48" not in seen                       # never argv or a log
    assert ".local/cc-passcode-lf-g3.txt" in result.stdout


def test_hook_keeps_control_center_secrets_already_in_the_vault(sandbox):
    result = run_hook(sandbox, "CONTROL_CENTER_IMAGE=acrlftest.azurecr.io/control-center:sha-1\n",
                      existing="cc-session-secret cc-passcode-sha256")
    assert result.returncode == 0, result.stderr
    assert not any(" -n cc-" in c for c in log_lines(sandbox) if c.startswith("az keyvault secret set"))
    assert not (sandbox / ".local").exists()


def test_hook_makes_no_control_center_secrets_without_the_control_center(sandbox):
    result = run_hook(sandbox, "")
    assert result.returncode == 0, result.stderr
    assert not any(" -n cc-" in c for c in log_lines(sandbox))


def test_hook_makes_no_passcode_for_an_easy_auth_control_center(sandbox):
    result = run_hook(sandbox, "CONTROL_CENTER_IMAGE=acrlftest.azurecr.io/control-center:sha-1\n"
                               "CONTROL_CENTER_AUTH_MODE=easyauth\n")
    assert result.returncode == 0, result.stderr
    sets = [c for c in log_lines(sandbox) if c.startswith("az keyvault secret set")]
    assert any(" -n cc-session-secret " in c for c in sets)
    assert not any(" -n cc-passcode-sha256 " in c for c in sets)
    assert (sandbox / "stored-cc-session-secret").exists()


# ---- G3: a value pasted from a chat (curly quotes, a lost *) never reaches a provision ----
@pytest.mark.parametrize("phase", ["infra", "apps"])
def test_a_provision_stops_on_a_value_pasted_with_curly_quotes(sandbox, phase):
    result = run_apps(sandbox, ALL_MCP_SECRETS, phase=phase,
                      extra="GITHUB_REPOS=‘livefire-team@1/livefire-fusion-poc@2’\n")
    assert result.returncode == 1
    assert "not provisioned: these azd values hold curly quotes or other non-ASCII characters" in result.stderr
    assert "GITHUB_REPOS" in result.stderr and "livefire-team@1" not in result.stderr      # the key, not the value
    assert "azd provision" not in log_lines(sandbox)


# ---- G3: a new identity's Key Vault access can lag its role assignment, so a fresh lab's first apps pass can fail
# on that alone (seen in the first clean-lab build); provision retries that one error ----
def run_flaky_provision(sandbox, message, fails):
    log = (sandbox / "calls.log").as_posix()
    count = (sandbox / "provisions").as_posix()
    fake(sandbox / "bin" / "azd", f'''if [ "$1 $2" = "env get-values" ]; then cat <<'EOF'
{APPS_VALUES}EOF
elif [ "$1" = provision ]; then
  n=$(cat {count} 2>/dev/null || echo 0); echo $((n+1)) > {count}; echo "azd provision" >> {log}
  if [ "$n" -lt {fails} ]; then echo "ERROR: {message}"; exit 1; fi
  echo "SUCCESS: provisioned"
else echo "azd $*" >> {log}; fi
''')
    az = f'echo "az $*" >> LOG\ncase "$*" in "keyvault secret list"*) printf "%s\\\\n" {ALL_MCP_SECRETS} ;; esac\n'
    fake(sandbox / "bin" / "az", az.replace("LOG", log))
    env = {**os.environ, "PROVISION_RETRY_S": "0",
           "PATH": f"{(sandbox / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([BASH, copy_deploy(sandbox).as_posix(), "apps"], cwd=sandbox, env=env,
                          capture_output=True, text=True, timeout=60)


KV_LAG = ("Invalid value: referee-sql-password: Unable to get value using Managed identity /x for secret "
          "referee-sql-password")


def test_provision_retries_while_a_new_identitys_vault_access_applies(sandbox):
    result = run_flaky_provision(sandbox, KV_LAG, fails=1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert log_lines(sandbox).count("azd provision") == 2
    assert "Key Vault access hasn't applied yet" in result.stderr


def test_provision_gives_up_after_three_tries(sandbox):
    result = run_flaky_provision(sandbox, KV_LAG, fails=5)
    assert result.returncode != 0
    assert log_lines(sandbox).count("azd provision") == 3


def test_provision_does_not_retry_other_failures(sandbox):
    result = run_flaky_provision(sandbox, "InvalidTemplate: something else", fails=1)
    assert result.returncode != 0
    assert log_lines(sandbox).count("azd provision") == 1
