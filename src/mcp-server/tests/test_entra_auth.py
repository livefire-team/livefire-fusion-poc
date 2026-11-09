"""AUTH_MODE=entra: real RS256 tokens signed with a local key, checked exactly as the server checks Entra's."""
import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from entra_auth import EntraVerifier

TENANT, CLIENT = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
PLANNER, ENGINEER, STRANGER = "oid-planner", "oid-engineer", "oid-someone-else"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class LocalJwks:
    """Stands in for PyJWKClient: serves the public half of KEY under kid 'k1'."""

    def get_signing_key_from_jwt(self, token):
        if jwt.get_unverified_header(token).get("kid") != "k1":
            raise jwt.PyJWKClientError("unknown kid")
        return type("K", (), {"key": KEY.public_key()})()


def token(oid=PLANNER, roles=("MCP.Planner",), aud=None, iss=None, exp_in=600, key=KEY, kid="k1"):
    now = int(time.time())
    claims = {"oid": oid, "roles": list(roles), "aud": aud or CLIENT,
              "iss": iss or f"https://login.microsoftonline.com/{TENANT}/v2.0", "iat": now, "exp": now + exp_in}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def verifier():
    return EntraVerifier(TENANT, CLIENT, PLANNER, ENGINEER, jwks_client=LocalJwks())


def test_each_agent_maps_to_its_own_endpoint(verifier):
    assert verifier.caller_role(token()) == "planner"
    assert verifier.caller_role(token(oid=ENGINEER, roles=["MCP.Engineer"])) == "engineer"
    assert verifier.caller_role(token(aud=f"api://{CLIENT}", iss=f"https://sts.windows.net/{TENANT}/")) == "planner"


@pytest.mark.parametrize("bad", [
    {"aud": "api://some-other-api"},                               # a token for another API
    {"iss": "https://login.microsoftonline.com/other-tenant/v2.0"},
    {"exp_in": -3600},                                             # expired
    {"key": OTHER_KEY},                                            # forged: signed with another key
    {"kid": "unknown"},
    {"oid": STRANGER, "roles": ["MCP.Planner"]},                    # the right role, the wrong identity
    {"oid": PLANNER, "roles": []},                                 # the right identity, no role
    {"oid": PLANNER, "roles": ["MCP.Engineer"]},                   # the planner holding the engineer's role
])
def test_everything_else_is_nobody(verifier, bad):
    assert verifier.caller_role(token(**bad)) is None


def test_garbage_is_nobody_not_an_exception(verifier):
    assert verifier.caller_role("not-a-jwt") is None


def test_refuses_to_start_without_two_distinct_agents():
    with pytest.raises(RuntimeError):
        EntraVerifier(TENANT, CLIENT, PLANNER, PLANNER, jwks_client=LocalJwks())
    with pytest.raises(RuntimeError):
        EntraVerifier(TENANT, "", PLANNER, ENGINEER, jwks_client=LocalJwks())


def test_guard_in_entra_mode_401_403_and_records_the_cross_role_call(server, verifier):
    """The real KeyGuard, with the Entra verifier deciding who the caller is."""
    import main

    async def ok(request):
        return JSONResponse({"ok": True})

    inner = Starlette(routes=[Route("/planner/mcp", ok, methods=["POST"]), Route("/engineer/mcp", ok, methods=["POST"])])
    guard = main.KeyGuard(inner, holder=lambda presented: verifier.caller_role(presented) if presented else None)
    drill = "drill-entra-0001"
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "create_candidate_branch", "arguments": {"drill_id": drill, "attempt": 1}}}

    async def post(path, tok):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guard), base_url="http://t") as c:
            return await c.post(path, json=call, headers={"authorization": f"Bearer {tok}"} if tok else {})

    assert asyncio.run(post("/planner/mcp", token())).status_code == 200
    assert asyncio.run(post("/planner/mcp", None)).status_code == 401
    assert asyncio.run(post("/planner/mcp", token(oid=STRANGER))).status_code == 401
    cross = asyncio.run(post("/engineer/mcp", token()))                   # the Planner on the Engineer's endpoint
    assert cross.status_code == 403 and "planner credential" in cross.json()["error"]
    events = [json.loads(line) for line in (server["evidence"] / drill / "events.jsonl").read_text().splitlines()]
    assert events[-1]["action"] == "planner.tool_call" and events[-1]["result"] == "deny"
