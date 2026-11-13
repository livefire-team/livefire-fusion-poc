"""start-load.sh, and how start-drill.sh calls it, driven through fake az and azd (no Azure needed)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parents[1] / "scripts"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("jq") is None, reason="bash and jq are needed")

VALUES = """TWIN_RG="rg-lf-twin-test"
CONTROL_RG="rg-lf-control-test"
LOADGEN_JOB_NAME="caj-loadgen"
RUNNER_JOB_NAME="job-drill-runner"
CONTROL_CENTER_URL="https://cc.example"
"""
TEMPLATE = {
    "name": "load-generator",
    "image": "acrlftest.azurecr.io/load-generator:sha-" + "1" * 40,
    "env": [
        {"name": "ORDER_APP_URL", "value": "https://ca-order.example"},
        {"name": "DRILL_ID", "value": "drill-loadgen-1107"},
        {"name": "EVENT_SOURCE", "value": "blob:https://evidence.example/evidence"},
        {"name": "APPLICATIONINSIGHTS_CONNECTION_STRING", "secretRef": "appinsights-connection-string"},
    ],
}


def fake(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def calls(sandbox):
    f = sandbox / "calls.log"
    return f.read_text().splitlines() if f.exists() else []


def az_body(running="", template=None):
    return f"""echo "az $*" >> LOG
case "$*" in
  "containerapp job execution list"*"Running"*"name"*) printf '%s' "{running}" ;;
  "containerapp job execution list"*) echo 0 ;;
  "containerapp job show"*"--query id"*) echo "/subscriptions/0/resourceGroups/rg/providers/Microsoft.App/jobs/$5" ;;
  "containerapp job show"*"containers[0]"*) cat TEMPLATE ;;
  "rest --method post"*)
    for a in "$@"; do [ "$prev" = --body ] && printf '%s' "$a" > "DIR/body-$(echo "$*" | grep -o 'jobs/[a-z-]*' | cut -d/ -f2).json"; prev="$a"; done
    echo exec-1 ;;
esac
"""


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "scripts").mkdir()
    for name in ("start-load.sh", "start-drill.sh"):
        if (SCRIPTS / name).exists():
            shutil.copy(SCRIPTS / name, tmp_path / "scripts")
    fake(tmp_path / "bin" / "azd", f"cat <<'EOF'\n{VALUES}EOF\n")
    (tmp_path / "template.json").write_text(json.dumps(TEMPLATE))
    return tmp_path


def run(sandbox, script, *args, az=None, values=None):
    if values is not None:
        fake(sandbox / "bin" / "azd", f"cat <<'EOF'\n{values}EOF\n")
    body = (az or az_body()).replace("LOG", (sandbox / "calls.log").as_posix()) \
        .replace("TEMPLATE", (sandbox / "template.json").as_posix()).replace("DIR", sandbox.as_posix())
    fake(sandbox / "bin" / "az", body)
    env = {**os.environ, "PATH": f"{(sandbox / 'bin').as_posix()}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run([BASH, (sandbox / "scripts" / script).as_posix(), *args], cwd=sandbox, env=env,
                          capture_output=True, text=True, timeout=60)


def test_start_load_starts_the_job_for_this_drill_and_keeps_its_secret_references(sandbox):
    result = run(sandbox, "start-load.sh", "drill-20261112-101500")
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads((sandbox / "body-caj-loadgen.json").read_text())
    env = {e["name"]: e for e in body["containers"][0]["env"]}
    assert env["DRILL_ID"]["value"] == "drill-20261112-101500"
    assert [e["name"] for e in body["containers"][0]["env"]].count("DRILL_ID") == 1
    assert env["APPLICATIONINSIGHTS_CONNECTION_STRING"] == {"name": "APPLICATIONINSIGHTS_CONNECTION_STRING",
                                                            "secretRef": "appinsights-connection-string"}
    assert body["containers"][0]["image"] == TEMPLATE["image"]
    assert any("-g rg-lf-twin-test" in c for c in calls(sandbox) if c.startswith("az containerapp job show"))
    assert "load for drill-20261112-101500 started (exec-1)" in result.stdout


def test_start_load_stops_an_earlier_drills_run_first(sandbox):
    result = run(sandbox, "start-load.sh", "drill-20261112-101500", az=az_body(running="caj-loadgen-old1"))
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(sandbox)
    stop = next(i for i, c in enumerate(log) if c.startswith("az containerapp job stop"))
    start = next(i for i, c in enumerate(log) if c.startswith("az rest --method post"))
    assert stop < start and "--job-execution-name caj-loadgen-old1" in log[stop]


@pytest.mark.parametrize("bad", ["", "drill-", "not-a-drill", "drill-a b", "drill-" + "x" * 60])
def test_start_load_refuses_anything_but_a_drill_id(sandbox, bad):
    result = run(sandbox, "start-load.sh", bad)
    assert result.returncode == 2
    assert calls(sandbox) == []


def test_start_load_without_a_load_generator_says_so_and_succeeds(sandbox):
    result = run(sandbox, "start-load.sh", "drill-20261112-101500",
                 values=VALUES.replace('LOADGEN_JOB_NAME="caj-loadgen"\n', ""))
    assert result.returncode == 0
    assert "no load generator in this environment" in result.stdout
    assert not any(c.startswith("az rest") for c in calls(sandbox))


def test_start_load_warns_when_the_job_writes_no_event_lines(sandbox):
    template = dict(TEMPLATE, env=[e for e in TEMPLATE["env"] if e["name"] != "EVENT_SOURCE"])
    (sandbox / "template.json").write_text(json.dumps(template))
    result = run(sandbox, "start-load.sh", "drill-20261112-101500")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARNING: caj-loadgen writes no metrics.orders lines" in result.stderr


def test_start_load_stop_ends_running_load_only(sandbox):
    result = run(sandbox, "start-load.sh", "--stop", az=az_body(running="caj-loadgen-a1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("--job-execution-name caj-loadgen-a1" in c for c in calls(sandbox) if "job stop" in c)
    assert not any(c.startswith("az rest") for c in calls(sandbox))


def test_start_drill_starts_the_load_for_the_same_drill(sandbox):
    result = run(sandbox, "start-drill.sh", "Supervised", "T-01")
    assert result.returncode == 0, result.stdout + result.stderr
    runner = json.loads((sandbox / "body-job-drill-runner.json").read_text())
    drill = {e["name"]: e.get("value") for e in runner["containers"][0]["env"]}["DRILL_ID"]
    load = json.loads((sandbox / "body-caj-loadgen.json").read_text())
    assert {e["name"]: e.get("value") for e in load["containers"][0]["env"]}["DRILL_ID"] == drill
    assert f"{drill} started: Supervised, T-01" in result.stdout


def test_start_drill_still_prints_the_drill_when_the_load_cannot_start(sandbox):
    fake(sandbox / "scripts" / "start-load.sh", 'echo "start-load failed" >&2; exit 1\n')
    result = run(sandbox, "start-drill.sh", "Supervised", "T-01")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARNING: no load for this drill" in result.stderr
    assert "started: Supervised, T-01" in result.stdout and "Watch it:" in result.stdout


def env_of(sandbox):
    runner = json.loads((sandbox / "body-job-drill-runner.json").read_text())
    return {e["name"]: e.get("value") or e.get("secretRef") for e in runner["containers"][0]["env"]}


@pytest.mark.parametrize("drill,mode,scenario,prove", [
    ("baseline", "Supervised", "T-00", "1"), ("supervised", "Supervised", "T-01", "1"),
    ("autonomous", "Autonomous Twin", "T-01", "1"), ("advisory", "Advisory", "T-01", "1"),
    ("broad", "Supervised", "T-02", "1"), ("quick", "Autonomous Twin", "T-01", "0"),
    ("kill", "Supervised", "T-09", "1")])
def test_start_drill_named_drills_set_mode_scenario_and_durability(sandbox, drill, mode, scenario, prove):
    result = run(sandbox, "start-drill.sh", drill)
    assert result.returncode == 0, result.stdout + result.stderr
    env = env_of(sandbox)
    assert (env["MODE"], env["SCENARIO"], env["PROVE_DURABLE"]) == (mode, scenario, prove)
    assert f"started: {mode}, {scenario}" in result.stdout and f"({drill} drill)" in result.stdout


def test_start_drill_keeps_the_template_and_its_secret_references(sandbox):
    (sandbox / "template.json").write_text(json.dumps({**TEMPLATE, "env": TEMPLATE["env"] + [
        {"name": "MODE", "value": "Supervised"}, {"name": "PROVE_DURABLE", "value": "1"}]}))
    assert run(sandbox, "start-drill.sh", "quick").returncode == 0
    runner = json.loads((sandbox / "body-job-drill-runner.json").read_text())
    names = [e["name"] for e in runner["containers"][0]["env"]]
    assert sorted(names) == sorted(set(names))                       # each value once
    assert env_of(sandbox)["APPLICATIONINSIGHTS_CONNECTION_STRING"] == "appinsights-connection-string"


@pytest.mark.parametrize("args", [("Supervised", "T-05"), ("nope",), ("repeat", "2", "supervised"),
                                  ("repeat", "x"), ("suite", "--bogus")])
def test_start_drill_refuses_bad_requests_before_calling_azure(sandbox, args):
    result = run(sandbox, "start-drill.sh", *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not any(c.startswith("az rest") for c in calls(sandbox))


def test_start_drill_list_names_every_drill(sandbox):
    result = run(sandbox, "start-drill.sh", "--list")
    assert result.returncode == 0
    for drill in ("baseline", "supervised", "autonomous", "advisory", "broad", "quick", "kill"):
        assert f"\n{drill} " in result.stdout
