import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import AGENT, BASE, CANDIDATE, DRILL, GRANT_KEY, REPO, RUNNER

from ops.livefire_events import DirEventStore
from ops.main import create_app
from ops.referee import FakeReferee
from ops.service import OpsService, Stopped
from ops.settings import Settings
from ops.twin import FakeTwin


@pytest.mark.parametrize("image", [
    "ghcr.io/livefire-team/order-service:sha-" + "a" * 40,        # another registry
    "acrother0001.azurecr.io/order-service:sha-" + "a" * 40,      # another registry of ours
    f"{REPO.replace('order-service', 'mcp-server')}:sha-" + "a" * 40,  # another repository
    f"{REPO}:latest", f"{REPO}:g1", f"{REPO}:sha-abc1234",        # movable or short tags
    f"{REPO}@sha256:" + "a" * 64,                                 # callers pass a tag; the service resolves it
    None, 42,
])
def test_deploy_refuses_anything_but_a_full_sha_tag_from_the_configured_repo(call, twin, image):
    status, body = call("deploy_revision", image=image)
    assert status == 422 and twin.image == BASE


def test_deploy_refuses_an_image_missing_from_the_registry(call, twin):
    twin.missing_tags.add(CANDIDATE.split(":")[1])
    status, body = call("deploy_revision", image=CANDIDATE)
    assert status == 422 and "not in the registry" in body["details"]["reason"] and twin.image == BASE


def test_deploy_is_by_digest_and_recorded(call, events):
    body = call("deploy_revision", image=CANDIDATE)[1]
    e = events()[-1]
    assert e["action"] == "deploy.revision" and e["details"]["image"] == CANDIDATE
    assert e["details"]["digest"] == body["details"]["digest"] and e["details"]["revision"]


@pytest.mark.parametrize("timeout", [0, 181, "10", 1.5, True])
def test_wait_timeout_is_bounded(call, timeout):
    assert call("wait_for", state="ok", timeout_s=timeout)[0] == 422


def test_wait_counts_seconds_from_since(call, events):
    since = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    call("inject_fault")
    body = call("wait_for", state="forbidden", timeout_s=5, since=since)[1]
    assert body["result"] == "ok" and 29 <= body["details"]["seconds"] <= 32
    assert events()[-1]["action"] == "wait.forbidden"


def test_wait_times_out_without_an_event(call, events):
    status, body = call("wait_for", state="forbidden", timeout_s=1)
    assert status == 200 and body["result"] == "timeout" and body["details"]["last"]["keyvault"] == "ok"
    assert events() == []


def test_wait_conformant_and_drifted(call, events):
    assert call("wait_for", state="conformant", timeout_s=2)[1]["result"] == "ok"
    call("inject_fault")
    assert call("wait_for", state="drifted", timeout_s=2)[1]["result"] == "ok"
    assert [e["action"] for e in events()] == ["wait.ok", "fault.inject", "wait.drifted"]


@pytest.mark.parametrize("label", ["Baseline", "1st", "a" * 33, "after fix", "", None, "baseline\n"])
def test_bad_labels_are_refused(call, label):
    assert call("run_referee", label=label)[0] == 422


def test_inconclusive_referee_is_503_not_fail(call, service, events):
    service.referee.fail_with = "job start refused"
    status, body = call("run_referee", label="baseline")
    assert status == 503 and body["result"] == "error"
    assert events()[-1]["result"] == "INCONCLUSIVE"
    assert call("run_referee", label="baseline")[1]["details"]["run_id"].endswith("-r2")


def test_reset_restores_access_and_restarts_on_the_base_image(call, twin, events):
    call("inject_fault")
    body = call("reset_twin")[1]
    assert body["details"]["access_restored"] is True and "restarted" in body["details"]
    assert twin.entries == 1 and twin.restarts == 1 and twin.image == BASE


def test_reset_fails_cleanly_when_the_base_image_is_gone(call, twin):
    twin.missing_tags.add(BASE.split(":")[1])
    status, body = call("reset_twin")
    assert status == 503 and "not in the registry" in body["details"]["reason"]


class SlowReferee:
    def __init__(self, seconds=0.5):
        self.started, self.seconds = asyncio.Event(), seconds

    async def run(self, drill_id, run_id, label, run_dir, timeout_s):
        self.started.set()
        await asyncio.sleep(self.seconds)
        return {"verdict": "PASS"}


def test_kill_stops_an_action_in_flight_and_resets(service, twin, events):
    service.referee = SlowReferee()
    app = create_app(service)
    headers = {"Authorization": f"Bearer {RUNNER}"}

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as c:
            run = asyncio.create_task(c.post("/actions/run_referee", json={"drill_id": DRILL, "label": "baseline"},
                                             headers=headers))
            await service.referee.started.wait()
            busy = await c.post("/actions/inject_fault", json={"drill_id": DRILL}, headers=headers)
            kill = await c.post("/actions/kill", json={"drill_id": DRILL}, headers=headers)
            return busy, kill, await run

    busy, kill, run = asyncio.run(go())
    assert busy.status_code == 409 and busy.json()["result"] == "busy"
    assert kill.status_code == 200 and kill.json()["details"]["by"] == "kill"
    assert run.status_code == 409 and run.json()["details"]["reason"] == "stopped by the kill switch"
    assert [e["action"] for e in events()] == ["reset"] and events()[0]["details"]["by"] == "kill"
    assert twin.entries == 1


def test_the_twin_is_free_right_after_kill(service):
    service.referee = SlowReferee(seconds=30)

    async def go():
        run = asyncio.create_task(service.handle("run_referee", {"drill_id": DRILL, "label": "baseline"}, "runner"))
        await service.referee.started.wait()
        await service.handle("kill", {"drill_id": DRILL}, "runner")
        reset = await service.handle("reset_twin", {"drill_id": DRILL}, "runner")
        with pytest.raises(Stopped):
            await run
        return reset

    assert asyncio.run(asyncio.wait_for(go(), 5)).result == "ok"


class SlowTwin(FakeTwin):
    """Each change is still in flight for a moment after it is asked for, like an ARM call."""

    async def remove_access(self):
        await asyncio.sleep(0.2)
        await super().remove_access()

    async def deploy_image(self, ref, timeout_s):
        if ref not in self.base_refs:
            await asyncio.sleep(0.2)
        return await super().deploy_image(ref, timeout_s)


@pytest.fixture
def slow(evidence):
    twin = SlowTwin(BASE)
    s = Settings(backend="fake", runner_key=RUNNER, agent_key=AGENT, grant_key=GRANT_KEY,
                 event_source=f"dir:{evidence}", base_image=BASE)
    return OpsService(s, twin, FakeReferee(twin), DirEventStore(str(evidence)), poll_s=0.01), twin


def kill_during(service, action, body, kill_drill=DRILL):
    """Starts an action, presses kill while it is in flight; returns the kill reply and how the action ended."""
    async def go():
        running = asyncio.create_task(service.handle(action, {"drill_id": DRILL, **body}, "runner"))
        await asyncio.sleep(0.05)
        kill = await service.handle("kill", {"drill_id": kill_drill}, "runner")
        try:
            await running
        except Stopped:
            return kill, "stopped"
        return kill, "finished"
    return asyncio.run(go())


@pytest.mark.parametrize("kill_drill", [DRILL, "drill-other-0002"])
def test_kill_during_a_fault_leaves_access_in_place(slow, kill_drill):
    service, twin = slow
    kill, ended = kill_during(service, "inject_fault", {}, kill_drill)
    assert kill.result == "ok" and ended == "stopped" and twin.entries == 1


def test_kill_during_a_deploy_leaves_the_base_image(slow):
    service, twin = slow
    kill, ended = kill_during(service, "deploy_revision", {"image": CANDIDATE})
    assert kill.result == "ok" and ended == "stopped" and twin.image in twin.base_refs
