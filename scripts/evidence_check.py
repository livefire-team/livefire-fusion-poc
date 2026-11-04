"""Checks the evidence store's write rules with your own sign-in (az login): appends work; history can't be changed.

    python scripts/evidence_check.py            # reads EVIDENCE_BLOB_URL from the azd environment

Writes one throwaway drill folder, drill-evidence-check-<time>/, which stays until the retention period ends.
Prints what Azure did for each attempt and exits 0 only when every earlier version survived unchanged.
"""
import json
import os
import subprocess
import sys
import time

from azure.core.exceptions import HttpResponseError
from azure.identity import AzureCliCredential
from azure.storage.blob import ContainerClient

LINE_1 = b'{"ts":"t1","drill_id":"x","action":"check.one","result":"ok","details":{}}\n'
LINE_2 = b'{"ts":"t2","drill_id":"x","action":"check.two","result":"ok","details":{}}\n'


def evidence_url() -> str:
    if os.environ.get("EVIDENCE_BLOB_URL"):
        return os.environ["EVIDENCE_BLOB_URL"]
    values = subprocess.run(["azd", "env", "get-values", "-o", "json"], capture_output=True, text=True, check=True)
    return json.loads(values.stdout)["EVIDENCE_BLOB_URL"]


def attempt(fn) -> str:
    try:
        fn()
        return "allowed"
    except HttpResponseError as exc:
        return f"refused ({exc.status_code} {exc.error_code})"


def main() -> int:
    account_url, _, name = evidence_url().rstrip("/").rpartition("/")
    container = ContainerClient(account_url, name, credential=AzureCliCredential())
    drill = f"drill-evidence-check-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    log = container.get_blob_client(f"{drill}/events.jsonl")
    rows, ok = [], True

    log.create_append_blob()
    rows.append(("create append blob", "allowed"))
    rows.append(("append line 1", attempt(lambda: log.append_block(LINE_1))))
    rows.append(("append line 2", attempt(lambda: log.append_block(LINE_2))))
    ok &= rows[-1][1] == "allowed" and rows[-2][1] == "allowed"

    result = container.get_blob_client(f"{drill}/r1-check/referee-result.json")
    result.upload_blob(b'{"verdict":"PASS"}')
    rows.append(("write a result file", "allowed"))

    rows.append(("overwrite the event log", attempt(lambda: log.upload_blob(b"rewritten\n", overwrite=True))))
    rows.append(("overwrite the result file", attempt(lambda: result.upload_blob(b'{"verdict":"FAIL"}',
                                                                                    overwrite=True))))
    rows.append(("delete the result file", attempt(result.delete_blob)))

    # Whatever Azure allowed above, the first versions must still exist, unchanged, and refuse deletion.
    versions = {}
    for b in container.list_blobs(name_starts_with=drill, include=["versions", "immutabilitypolicy"]):
        versions.setdefault(b.name, []).append(b)
    for blob_name, expected in ((log.blob_name, LINE_1 + LINE_2), (result.blob_name, b'{"verdict":"PASS"}')):
        found = sorted(versions.get(blob_name, []), key=lambda b: b.version_id or "")
        if not found:
            rows.append((f"first version of {blob_name.split('/')[-1]}", "MISSING")); ok = False
            continue
        first = found[0]
        data = container.get_blob_client(blob_name).download_blob(version_id=first.version_id).readall()
        same = data == expected
        rows.append((f"first version of {blob_name.split('/')[-1]} unchanged", "yes" if same else "NO"))
        ok &= same
        policy = getattr(first, "immutability_policy", None)
        until = getattr(policy, "expiry_time", None)
        rows.append(("  its immutability policy until", str(until) if until else "NONE"))
        ok &= until is not None
        verdict = attempt(lambda: container.get_blob_client(blob_name).delete_blob(version_id=first.version_id))
        rows.append(("  delete that version", verdict))
        ok &= verdict.startswith("refused")

    width = max(len(r[0]) for r in rows)
    print(f"evidence check on {account_url}/{name}/{drill}/")
    for step, outcome in rows:
        print(f"  {step:<{width}}  {outcome}")
    print("EVIDENCE CHECK PASSED" if ok else "EVIDENCE CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
