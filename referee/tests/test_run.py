"""referee/run.py, the job entry point, with the journey and SQL check replaced by stubs (no browser, no database)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run  # noqa: E402

DRILL = "drill-20261105-1000-ab12"


def env(tmp_path, **kw):
    return {"DRILL_ID": DRILL, "RUN_ID": f"{DRILL}-r2", "LABEL": "during-fault", "RUN_DIR": "r2-during-fault",
            "ORDER_APP_URL": "https://shop.example", "WORK_DIR": str(tmp_path), "JOURNEY_COMMIT": "abc1234",
            "EVIDENCE_URL": "https://acct.blob.core.windows.net/evidence", **kw}


def stub(journey_rc, sql_rc, counts, notes=None, trace=False, journey_timeout=False):
    def runner(cmd, env, cwd, timeout, **kw):
        outdir = Path(env["OUTDIR"])
        if "pytest" in cmd:
            if journey_timeout:
                raise subprocess.TimeoutExpired(cmd, timeout)
            for name, value in (notes or {}).items():
                (outdir / f"{name}.txt").write_text(value)
            if trace:
                t = outdir / "playwright" / "journeys-test-chromium" / "trace.zip"
                t.parent.mkdir(parents=True)
                t.write_bytes(b"zip")
            return subprocess.CompletedProcess(cmd, journey_rc)
        return subprocess.CompletedProcess(cmd, sql_rc, stdout=counts, stderr="")
    return runner


class Uploads:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, url, client_id, outdir, prefix):
        if self.fail:
            raise RuntimeError("403 AuthorizationPermissionMismatch")
        self.calls.append((url, prefix, sorted(p.name for p in outdir.rglob("*") if p.is_file())))


def result(tmp_path):
    return json.loads((tmp_path / DRILL / "r2-during-fault" / "referee-result.json").read_text())


def test_failed_order_is_a_fail_with_the_step_error_and_trace(tmp_path):
    up = Uploads()
    rc = run.main(env(tmp_path), stub(1, 1, '{"orders_persisted": 0, "payment_auths_persisted": 0}',
                                      {"step": "place-order", "error": "We couldn't place your order"}, trace=True), up)
    r = result(tmp_path)
    assert rc == 0 and r["verdict"] == "FAIL" and r["last_step"] == "place-order"
    assert r["orders_persisted"] == 0 and r["journey_commit"] == "abc1234" and r["browser"] == "local-chromium"
    assert r["trace_url"] == f"evidence/{DRILL}/r2-during-fault/playwright/journeys-test-chromium/trace.zip"
    assert isinstance(r["duration_s"], float)
    assert up.calls[0][1] == f"{DRILL}/r2-during-fault" and "referee-result.json" in up.calls[0][2]


def test_pass_needs_both_checks(tmp_path):
    rc = run.main(env(tmp_path), stub(0, 0, '{"orders_persisted": 1, "payment_auths_persisted": 1}',
                                      {"step": "confirmed", "confirmation": "LF-1234ABCD"}), Uploads())
    r = result(tmp_path)
    assert rc == 0 and r["verdict"] == "PASS" and r["trace_url"] is None and r["confirmation_number"] == "LF-1234ABCD"


def test_browser_success_without_the_saved_order_is_a_fail(tmp_path):
    run.main(env(tmp_path), stub(0, 1, '{"orders_persisted": 0, "payment_auths_persisted": 0}'), Uploads())
    assert result(tmp_path)["verdict"] == "FAIL"


@pytest.mark.parametrize("journey_rc,sql_rc,counts", [(2, 0, '{"orders_persisted": 1}'), (0, 2, "{}"),
                                                       (0, 0, "not json")])
def test_a_check_that_could_not_run_is_inconclusive(tmp_path, journey_rc, sql_rc, counts):
    assert run.main(env(tmp_path), stub(journey_rc, sql_rc, counts), Uploads()) == 2
    assert result(tmp_path)["verdict"] == "INCONCLUSIVE"


def test_a_journey_timeout_is_inconclusive(tmp_path):
    assert run.main(env(tmp_path), stub(0, 0, "{}", journey_timeout=True), Uploads()) == 2


def test_a_failed_upload_is_exit_3(tmp_path):
    assert run.main(env(tmp_path), stub(0, 0, '{"orders_persisted": 1, "payment_auths_persisted": 1}'),
                    Uploads(fail=True)) == 3


@pytest.mark.parametrize("change", [{"DRILL_ID": "prod-1"}, {"RUN_DIR": "../../x"}, {"RUN_ID": "drill-other-r1"},
                                    {"ORDER_APP_URL": ""}, {"RUN_DIR": "r2-during-fault\n"},
                                    {"DRILL_ID": f"{DRILL}\n", "RUN_ID": f"{DRILL}\n-r2"}])
def test_bad_settings_are_refused_before_anything_runs(tmp_path, change):
    calls = []
    assert run.main(env(tmp_path, **change), lambda *a, **k: calls.append(a), Uploads()) == 2 and calls == []


def test_without_evidence_url_it_only_writes_locally(tmp_path):
    up = Uploads()
    assert run.main(env(tmp_path, EVIDENCE_URL=""), stub(0, 0, '{"orders_persisted": 1, "payment_auths_persisted": 1}'),
                    up) == 0
    assert up.calls == [] and result(tmp_path)["verdict"] == "PASS"
