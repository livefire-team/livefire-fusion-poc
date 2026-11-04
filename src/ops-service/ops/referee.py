"""Runs the independent Referee and reads its result.

In Azure the Referee is the Container Apps Job job-referee, with its own identity and read-only SQL login. The Ops
Service may only start it and read its executions; the verdict comes from the result file the job writes.
"""
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Protocol

from .arm import Arm, ArmError
from .settings import Settings

RUN_ENV = ("DRILL_ID", "RUN_ID", "LABEL", "RUN_DIR")
DONE = ("Succeeded", "Failed", "Stopped", "Degraded")


class RefereeError(RuntimeError):
    """The Referee could not produce a verdict: no answer, which is not a FAIL."""


class Referee(Protocol):
    async def run(self, drill_id: str, run_id: str, label: str, run_dir: str, timeout_s: float) -> dict: ...


class EvidenceFiles:
    """Reads one result file from the evidence store named by EVENT_SOURCE."""

    def __init__(self, event_source: str, client_id: str = "", auth: str = "managed-identity"):
        self.source = event_source
        self.container = None
        if event_source.startswith("blob:"):
            from azure.storage.blob import ContainerClient

            from .arm import credential_for
            account_url, _, name = event_source[5:].rpartition("/")
            self.container = ContainerClient(account_url, name, credential=credential_for(auth, client_id))

    def _read(self, path: str) -> bytes | None:
        if self.container is None:
            f = Path(self.source[4:]) / path
            return f.read_bytes() if f.is_file() else None
        blob = self.container.get_blob_client(path)
        return blob.download_blob().readall() if blob.exists() else None

    async def read_json(self, path: str) -> dict | None:
        data = await asyncio.to_thread(self._read, path)
        if data is None:
            return None
        try:
            value = json.loads(data)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None


class JobReferee:
    def __init__(self, s: Settings, arm: Arm, files: EvidenceFiles, poll_s: float = 3.0):
        self.s, self.arm, self.files, self.poll_s = s, arm, files, poll_s

    async def run(self, drill_id: str, run_id: str, label: str, run_dir: str, timeout_s: float) -> dict:
        started = time.monotonic()
        job = await self.arm.get(self.s.referee_job_id, "jobs")
        container = dict(job["properties"]["template"]["containers"][0])
        env = [e for e in container.get("env", []) if e.get("name") not in RUN_ENV]
        env += [{"name": "DRILL_ID", "value": drill_id}, {"name": "RUN_ID", "value": run_id},
                {"name": "LABEL", "value": label}, {"name": "RUN_DIR", "value": run_dir}]
        override = {k: container[k] for k in ("name", "image", "resources", "command", "args") if container.get(k)}
        override["env"] = env
        try:
            execution = await self.arm.request("POST", f"{self.s.referee_job_id}/start", "jobs",
                                               {"containers": [override]})
        except ArmError as exc:
            raise RefereeError(f"could not start {self.s.referee_job_name}: {exc}") from exc
        name = execution.get("name", "")
        if not name:
            raise RefereeError("the job start returned no execution name")
        status = ""
        while time.monotonic() - started < timeout_s:
            await asyncio.sleep(self.poll_s)
            try:
                status = (await self.arm.get(f"{self.s.referee_job_id}/executions/{name}", "jobs")) \
                    .get("properties", {}).get("status", "")
            except ArmError:
                continue
            if status in DONE:
                break
        result = await self.files.read_json(f"{drill_id}/{run_dir}/referee-result.json")
        if result is None:
            raise RefereeError(f"execution {name} ended {status or 'without a status'} and wrote no result")
        result.setdefault("execution", name)
        return result


class FakeReferee:
    """Places one order on the FakeTwin and reports it like the real Referee."""

    def __init__(self, twin):
        self.twin = twin
        self.fail_with: str | None = None    # tests: make the next run inconclusive

    async def run(self, drill_id: str, run_id: str, label: str, run_dir: str, timeout_s: float) -> dict:
        if self.fail_with:
            reason, self.fail_with = self.fail_with, None
            raise RefereeError(reason)
        ok = self.twin.place_order()
        return {"drill_id": drill_id, "run_id": run_id, "label": label, "verdict": "PASS" if ok else "FAIL",
                "journey_passed": ok, "last_step": "confirmed" if ok else "place-order",
                "error": "" if ok else "order was not placed", "orders_persisted": int(ok),
                "payment_auths_persisted": int(ok), "duration_s": 0, "trace_url": None, "browser": "fake",
                "simulated": True, "journey_commit": os.environ.get("JOURNEY_COMMIT", "local")}
