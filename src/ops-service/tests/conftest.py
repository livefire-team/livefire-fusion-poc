import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import grants  # noqa: E402
from ops.livefire_events import DirEventStore  # noqa: E402
from ops.main import create_app  # noqa: E402
from ops.referee import FakeReferee  # noqa: E402
from ops.service import OpsService  # noqa: E402
from ops.settings import Settings  # noqa: E402
from ops.twin import FakeTwin  # noqa: E402

RUNNER = "r" * 40
AGENT = "a" * 40
GRANT_KEY = "g" * 40
DRILL = "drill-test-0001"
REPO = "acrlffake01.azurecr.io/order-service"
BASE = f"{REPO}:sha-{'0' * 40}"
CANDIDATE = f"{REPO}:sha-{'c' * 40}"


@pytest.fixture
def evidence(tmp_path):
    return tmp_path / "evidence"


@pytest.fixture
def twin():
    return FakeTwin(BASE)


@pytest.fixture
def service(twin, evidence):
    s = Settings(backend="fake", runner_key=RUNNER, agent_key=AGENT, grant_key=GRANT_KEY,
                 event_source=f"dir:{evidence}", base_image=BASE)
    return OpsService(s, twin, FakeReferee(twin), DirEventStore(str(evidence)), poll_s=0.01)


@pytest.fixture
def call(service):
    """call(action, key=RUNNER, **body) -> (status, json), over the real ASGI app."""
    app = create_app(service)

    def _call(op, /, key=RUNNER, drill=DRILL, **body):
        async def go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://ops") as c:
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                r = await c.post(f"/actions/{op}", json={"drill_id": drill, **body}, headers=headers)
                return r.status_code, r.json()
        return asyncio.run(go())
    return _call


@pytest.fixture
def events(evidence):
    def _events(drill=DRILL):
        f = evidence / drill / "events.jsonl"
        return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []
    return _events


def grant(action, purpose, drill=DRILL, **kw):
    return grants.sign(GRANT_KEY, drill, action, purpose, approved_by="test-approver", **kw)
