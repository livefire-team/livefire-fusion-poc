import asyncio

import httpx
from conftest import AGENT, CANDIDATE, GRANT_KEY, REPO, RUNNER

from ops.main import create_app
from ops.smoke import Smoke


def smoke_against(service):
    s = Smoke("http://ops", RUNNER, AGENT, GRANT_KEY)
    s.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(service)), base_url="http://ops")
    return s


def test_smoke_passes_against_the_fake_twin(service, twin, capsys):
    twin.missing_tags.add("sha-" + "f" * 40)
    s = smoke_against(service)

    async def go():
        await s.auth(REPO)
        await s.policy("RequestDisallowedByPolicy")
        await s.drill(CANDIDATE, True, "RequestDisallowedByPolicy", 0)
        return s.report()
    assert asyncio.run(go()) == 0
    out = capsys.readouterr().out
    assert "SMOKE PASSED" in out and "<-- X" not in out


def test_smoke_fails_when_the_refusal_comes_from_rbac(service, twin, capsys):
    twin.broad_code = "AuthorizationFailed"
    s = smoke_against(service)

    async def go():
        await s.policy("RequestDisallowedByPolicy")
        return s.report()
    assert asyncio.run(go()) == 1
    assert "denied AuthorizationFailed" in capsys.readouterr().out


def test_ten_baselines_report_their_timing(service, capsys):
    s = smoke_against(service)

    async def go():
        await s.baselines()
        return s.report()
    assert asyncio.run(go()) == 0
    out = capsys.readouterr().out
    assert out.count("PASS") >= 10 and "Referee seconds min" in out
