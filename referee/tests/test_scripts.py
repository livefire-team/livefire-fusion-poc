"""referee.sh and drill.sh behaviour, driven through fake commands (no Azure needed)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parents[1] / "scripts"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")

DRILL = "drill-test-1"
SUB = "00000000-0000-0000-0000-000000000000"
PRINCIPAL = "11111111-1111-1111-1111-111111111111"
VALUES = f"""TWIN_RG=rg-lf-twin-test
KEYVAULT_ID=/subscriptions/{SUB}/resourceGroups/rg-lf-twin-test/providers/Microsoft.KeyVault/vaults/kv
AZURE_SUBSCRIPTION_ID={SUB}
APP_IDENTITY_PRINCIPAL_ID={PRINCIPAL}
ORDER_APP_NAME=app
ORDER_APP_URL=http://app.example.test
SQL_SERVER_FQDN=sql.example
SQL_DB_NAME=db
SQL_ADMIN_PASSWORD=x
"""


def fake(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake(bin_dir / "azd", f"cat <<'EOF'\n{VALUES}EOF\n")
    fake(bin_dir / "sqlcmd", "exit 0\n")
    fake(bin_dir / "curl", "echo '{}'\n")
    return tmp_path


def run_script(sandbox, name, *args, az_body=None, scripts=SCRIPTS):
    fake(sandbox / "bin" / "az", az_body or AZ_APP)
    env = {**os.environ, "PATH": f"{(sandbox / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}", "DRILL_ID": DRILL}
    return subprocess.run([BASH, (scripts / name).as_posix(), *args], cwd=sandbox, env=env,
                          capture_output=True, text=True, timeout=60)


def events(sandbox):
    lines = (sandbox / "evidence" / DRILL / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


AZ_APP = f"""case "$*" in
  "account show"*) echo {SUB} ;;
  *) echo rev-1 ;;
esac
"""


def copied_scripts(sandbox):
    copy = sandbox / "scripts"
    shutil.copytree(SCRIPTS, copy)
    return copy


# ---- referee.sh ----

COUNTS = '{"orders_persisted":1,"payment_auths_persisted":1}'
NULLS = {"orders_persisted": None, "payment_auths_persisted": None}


@pytest.fixture
def referee(sandbox):
    """Runs referee.sh with a fake journey and SQL check; returns the process and the result file's contents."""
    bin_dir = sandbox / "bin"
    if shutil.which("jq") is None:
        fake(bin_dir / "jq", f'"{Path(sys.executable).as_posix()}" "{(TESTS / "fake_jq.py").as_posix()}" "$@"\n')

    def run(journey=0, sql=0, sql_output=COUNTS):
        fake(bin_dir / "pytest", f'echo "$*" > "{sandbox.as_posix()}/pytest-args"\nexit {journey}\n')
        fake(bin_dir / "python", f"printf '%s' '{sql_output}'\nexit {sql}\n")
        result = run_script(sandbox, "referee.sh", "stage")
        files = sorted((sandbox / "evidence" / DRILL).glob("r*-stage/referee-result.json"))
        return result, json.loads(files[-1].read_text(encoding="utf-8"))
    return run


@pytest.mark.parametrize("journey, sql, verdict, code", [
    (0, 0, "PASS", 0),
    (1, 0, "FAIL", 1),
    (0, 1, "FAIL", 1),
    (1, 1, "FAIL", 1),
    (0, 2, "INCONCLUSIVE", 2),
    (1, 2, "INCONCLUSIVE", 2),
    (2, 0, "INCONCLUSIVE", 2),
    (5, 1, "INCONCLUSIVE", 2),
])
def test_referee_verdict_and_exit_code_follow_the_two_checks(referee, journey, sql, verdict, code):
    result, recorded = referee(journey=journey, sql=sql)
    assert result.returncode == code
    assert recorded["verdict"] == verdict
    assert f"referee stage: {verdict}" in result.stdout


@pytest.mark.parametrize("output", ["", "not json", "[1]"])
def test_referee_is_inconclusive_with_null_counts_when_the_sql_check_prints_no_object(referee, output):
    result, recorded = referee(sql=0, sql_output=output)
    assert result.returncode == 2
    assert recorded["verdict"] == "INCONCLUSIVE"
    assert {name: recorded[name] for name in NULLS} == NULLS


def test_referee_keeps_browser_output_in_its_own_folder_inside_the_evidence_folder(referee, sandbox):
    result, _ = referee()
    assert result.returncode == 0
    assert f"--output evidence/{DRILL}/r1-stage/playwright " in (sandbox / "pytest-args").read_text(encoding="utf-8")


def test_referee_exits_two_when_it_stops_before_a_verdict(sandbox):
    fake(sandbox / "bin" / "azd", "exit 1\n")  # no settings: lib.sh stops on the first unset one
    result = run_script(sandbox, "referee.sh", "stage")
    assert result.returncode == 2


# ---- drill.sh ----

def drill_scripts(sandbox, referee_exits=None, fault_exit=0):
    """Fakes every script drill.sh calls. referee_exits maps a stage to the referee's exit code; the default is 0."""
    copy = copied_scripts(sandbox)
    exits = "\n".join(f"  {stage}) exit {code} ;;" for stage, code in (referee_exits or {}).items())
    fake(copy / "new-drill.sh", f"echo {DRILL}\n")
    fake(copy / "reset.sh", f"mkdir -p evidence/{DRILL}\n")
    fake(copy / "fault.sh", f"exit {fault_exit}\n")
    fake(copy / "wait-for.sh", "exit 0\n")
    fake(copy / "referee.sh", f'case "$1" in\n{exits}\n  *) exit 0 ;;\nesac\n')
    return copy


def test_drill_prints_what_each_stage_observed_and_exits_zero(sandbox):
    copy = drill_scripts(sandbox, referee_exits={"baseline": 1})
    result = run_script(sandbox, "drill.sh", scripts=copy)
    assert result.returncode == 0
    assert f"{DRILL}: baseline=FAIL during-fault=PASS after-restore=PASS after-restart=PASS" in result.stdout


def test_drill_shows_an_inconclusive_stage_and_exits_two(sandbox):
    copy = drill_scripts(sandbox, referee_exits={"during-fault": 2})
    result = run_script(sandbox, "drill.sh", scripts=copy)
    assert result.returncode == 2
    assert "during-fault=INCONCLUSIVE" in result.stdout


def test_drill_stops_with_a_non_zero_exit_when_a_step_between_stages_fails(sandbox):
    copy = drill_scripts(sandbox, fault_exit=1)
    result = run_script(sandbox, "drill.sh", scripts=copy)
    assert result.returncode == 1
    assert "baseline=" not in result.stdout
