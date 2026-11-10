
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from livefire.contracts import OpsResult
from livefire.ports import DependencyError, HttpOps
from livefire.workflow import Run


def test_stopped_action_is_not_retried():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            409,
            json={
                "action": "reset_twin",
                "result": "stopped",
                "details": {},
            },
        )

    ops = HttpOps(
        base_url="https://example.invalid",
        key="test-key",
        drill_id="drill-test-001",
        transport=httpx.MockTransport(handler),
    )

    async def check():
        try:
            with pytest.raises(DependencyError, match="stopped"):
                await ops.call("reset_twin")
        finally:
            await ops.http.aclose()

    asyncio.run(check())

    assert len(requests) == 1


@pytest.mark.parametrize("action", ["reset_twin", "kill"])
def test_failed_reset_or_kill_is_rejected(action):

    class FakeOps:
        async def call(self, action, **params):
            return OpsResult(
                action=action,
                result="refused",
                details={},
            )

    fake_run = SimpleNamespace(
        ops=FakeOps(),
        budgets=SimpleNamespace(wait_s=30),
    )

    with pytest.raises(DependencyError, match="returned refused"):
        asyncio.run(Run.op(fake_run, action))
