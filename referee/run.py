"""The Referee as one Container Apps Job execution (job-referee), started by the Ops Service's run_referee.

Runs the pinned journey and the SQL check once, writes referee-result.json in the same shape as scripts/referee.sh
(plus duration_s, trace_url and browser), then uploads the run folder to the evidence container.

Environment: DRILL_ID, RUN_ID, LABEL, RUN_DIR (r<n>-<label>), ORDER_APP_URL, SQL_SERVER_FQDN, SQL_DB_NAME,
REFEREE_SQL_PASSWORD; EVIDENCE_URL (https://<account>.blob.core.windows.net/<container>) and AZURE_CLIENT_ID to
upload; JOURNEY_COMMIT (baked into the image); WORK_DIR (default /tmp/referee).
Exit codes: 0 a verdict was written (PASS or FAIL: read the file), 2 INCONCLUSIVE, 3 the result could not be saved.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DRILL = re.compile(r"^drill-[A-Za-z0-9-]{1,64}$")
RUN_DIR = re.compile(r"^r[0-9]{1,3}-[a-z][a-z0-9-]{0,31}$")
NULL_COUNTS = {"orders_persisted": None, "payment_auths_persisted": None}
NOTES = ("step", "error", "confirmation")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verdict(journey_rc: int, sql_rc: int) -> str:
    """Same rule as referee.sh: pytest 1 = a failed test; 2+ = it could not run. SQL 2 = the check could not run."""
    if journey_rc >= 2 or sql_rc >= 2:
        return "INCONCLUSIVE"
    return "PASS" if journey_rc == 0 and sql_rc == 0 else "FAIL"


def read_note(outdir: Path, name: str) -> str:
    f = outdir / f"{name}.txt"
    return f.read_text().strip() if f.is_file() else ""


def run_checks(env: dict, outdir: Path, runner=subprocess.run) -> tuple[int, int, dict]:
    child = {**os.environ, **env, "OUTDIR": str(outdir)}
    journey = runner([sys.executable, "-m", "pytest", str(ROOT / "journeys" / "test_order_journey.py"),
                      "--browser", "chromium", "--tracing", "retain-on-failure",
                      "--output", str(outdir / "playwright"), "-q", "-p", "no:cacheprovider"],
                     env=child, cwd=str(ROOT), timeout=150)
    sql = runner([sys.executable, str(HERE / "assert_order.py")], env=child, cwd=str(ROOT), timeout=60,
                 capture_output=True, text=True)
    try:
        counts = json.loads(sql.stdout or "")
        if not isinstance(counts, dict):
            raise ValueError
    except ValueError:
        counts, sql_rc = dict(NULL_COUNTS), max(sql.returncode, 2)
    else:
        sql_rc = sql.returncode
    return journey.returncode, sql_rc, counts


def build_result(env: dict, outdir: Path, journey_rc: int, sql_rc: int, counts: dict, started: float,
                 started_at: str, container: str) -> dict:
    traces = sorted(outdir.glob("playwright/**/trace.zip"))
    trace_url = None
    if traces and container:
        trace_url = f"{container}/{env['DRILL_ID']}/{env['RUN_DIR']}/{traces[0].relative_to(outdir).as_posix()}"
    return {
        "drill_id": env["DRILL_ID"], "run_id": env["RUN_ID"], "label": env["LABEL"],
        "journey_commit": env.get("JOURNEY_COMMIT", "unknown"), "started_at": started_at, "ended_at": now(),
        "journey_passed": journey_rc == 0, "last_step": read_note(outdir, "step"), "error": read_note(outdir, "error"),
        "confirmation_number": read_note(outdir, "confirmation"),
        "orders_persisted": counts.get("orders_persisted"), "payment_auths_persisted": counts.get("payment_auths_persisted"),
        "verdict": verdict(journey_rc, sql_rc), "duration_s": round(time.monotonic() - started, 1),
        "trace_url": trace_url, "browser": "local-chromium",
    }


def upload(evidence_url: str, client_id: str, outdir: Path, prefix: str) -> list[str]:
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import ContainerClient
    account_url, _, container = evidence_url.rstrip("/").rpartition("/")
    client = ContainerClient(account_url, container, credential=ManagedIdentityCredential(client_id=client_id))
    names = []
    files = [p for p in outdir.rglob("*") if p.is_file() and p.name != "referee-result.json"]
    for path in files + [outdir / "referee-result.json"]:          # the result last: its presence means done
        name = f"{prefix}/{path.relative_to(outdir).as_posix()}"
        with path.open("rb") as f:
            client.upload_blob(name, f, overwrite=False)
        names.append(name)
    return names


def main(env: dict | None = None, runner=subprocess.run, uploader=upload) -> int:
    env = dict(os.environ if env is None else env)
    missing = [k for k in ("DRILL_ID", "RUN_ID", "LABEL", "RUN_DIR", "ORDER_APP_URL") if not env.get(k)]
    if missing or not DRILL.fullmatch(env.get("DRILL_ID", "")) or not RUN_DIR.fullmatch(env.get("RUN_DIR", "")) \
            or not env.get("RUN_ID", "").startswith(env.get("DRILL_ID", "") + "-r"):
        print(f"referee: bad or missing settings {missing or ['DRILL_ID/RUN_ID/RUN_DIR']}", file=sys.stderr)
        return 2
    outdir = Path(env.get("WORK_DIR", "/tmp/referee")) / env["DRILL_ID"] / env["RUN_DIR"]
    outdir.mkdir(parents=True, exist_ok=True)
    started, started_at = time.monotonic(), now()
    try:
        journey_rc, sql_rc, counts = run_checks(env, outdir, runner)
    except subprocess.TimeoutExpired:
        journey_rc, sql_rc, counts = 2, 2, dict(NULL_COUNTS)
    evidence_url = env.get("EVIDENCE_URL", "")
    container = evidence_url.rstrip("/").rpartition("/")[2] if evidence_url else ""
    result = build_result(env, outdir, journey_rc, sql_rc, counts, started, started_at, container)
    (outdir / "referee-result.json").write_text(json.dumps(result, indent=2))
    print(f"referee {env['LABEL']}: {result['verdict']} ({env['RUN_ID']}, {result['duration_s']} s)")
    if evidence_url:
        try:
            uploader(evidence_url, env.get("AZURE_CLIENT_ID", ""), outdir, f"{env['DRILL_ID']}/{env['RUN_DIR']}")
        except Exception as exc:                       # no saved result means no verdict for the Ops Service
            print(f"referee: upload failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
    return 2 if result["verdict"] == "INCONCLUSIVE" else 0


if __name__ == "__main__":
    sys.exit(main())
