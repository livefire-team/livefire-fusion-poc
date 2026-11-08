"""A local stand-in for WS2's Ops Service, only for what /recovery/mcp calls: recover, attempt_unsafe, check_drift.

It speaks the same wire contract as the real one (contracts/ops-actions.md): Bearer OPS_AGENT_KEY, POST
/actions/<action> with a JSON body, 200 {"result", "details"} on success, 422 with details.reason on a refusal.
A grant is accepted once, for one drill and one action; FAKE_GRANTS lists the valid ones as
"<drill_id>:<action>:<grant>" separated by commas. Never deploy this: it changes nothing and checks no signature.

Usage: OPS_AGENT_KEY=... FAKE_GRANTS=drill-local-0001:restore_kv_secrets_user:grt-local-1 \
         uvicorn --app-dir scripts fake-ops:app --port 8200   (or: python scripts/fake-ops.py)
"""
import hmac
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

KEY = os.environ.get("OPS_AGENT_KEY", "")
GRANTS = {tuple(g.split(":", 2)) for g in os.environ.get("FAKE_GRANTS", "").split(",") if g.count(":") >= 2}
USED: set[str] = set()
NARROW = {"restore_kv_secrets_user", "restore_db_secret", "rollback_app_config", "restore_sql_network_rule"}
BROAD = {"grant_contributor_subscription", "open_sql_firewall_to_internet"}


def refused(reason: str) -> JSONResponse:
    return JSONResponse({"result": "refused", "details": {"reason": reason}}, status_code=422)


async def action(request: Request) -> JSONResponse:
    auth = request.headers.get("authorization", "")
    if not KEY or not hmac.compare_digest(auth, f"Bearer {KEY}"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    name = request.path_params["name"]
    body = await request.json()
    drill = str(body.get("drill_id", ""))
    if name == "check_drift":
        return JSONResponse({"result": "ok", "details": {"identity": "ok", "secret": "ok", "config": "ok",
                                                         "network": "ok"}})
    if name not in ("recover", "attempt_unsafe"):
        return JSONResponse({"error": f"the agent key can't call {name}"}, status_code=403)
    act, grant = str(body.get("action", "")), str(body.get("grant", ""))
    if (name == "recover") != (act in NARROW) or act not in NARROW | BROAD:
        return refused(f"{act} is not a {name} action")
    if grant in USED:
        return refused("grant already used")
    if (drill, act, grant) not in GRANTS:
        return refused("no valid grant for this drill and action")
    USED.add(grant)
    if name == "attempt_unsafe":                    # the real service: Azure Policy denies the broad action
        return JSONResponse({"result": "denied", "details": {"action": act, "by": "Azure Policy (fake)"}})
    return JSONResponse({"result": "ok", "details": {"action": act, "grant_id": grant[:16]}})


app = Starlette(routes=[Route("/actions/{name}", action, methods=["POST"]),
                        Route("/health", lambda r: JSONResponse({"status": "up", "fake": True}))])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8200")))   # 0.0.0.0 in a container
