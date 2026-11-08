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
    assert names == ["ops-agent-key", "recovery-grant-key", "ops-cleanup-sql-password"]
    assert "azd env set REFEREE_SQL_PASSWORD existing-referee-pw" in calls
    sql = (sandbox / "calls.log").read_text()
    assert "CREATE USER ops_cleanup" in sql and "GRANT SELECT, DELETE ON dbo.orders TO ops_cleanup" in sql
    assert calls[-1] == "referee baseline"


AZ_VAULT_NOT_READY_YET = """echo "az $*" >> LOG
case "$*" in
  "keyvault secret list"*)
    n=$(cat list-calls 2>/dev/null || echo 0); echo $((n+1)) > list-calls
    if [ "$n" -lt 2 ]; then echo "Forbidden" >&2; exit 1; fi
    echo ops-runner-key; echo ops-agent-key; echo recovery-grant-key ;;
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


# ---- deploy.sh policy-off ----
def copy_deploy(sandbox):
    scripts = sandbox / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy(SCRIPTS / "deploy.sh", scripts)
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
