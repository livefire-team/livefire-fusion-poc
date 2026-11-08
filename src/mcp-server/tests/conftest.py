import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))

PLANNER_KEY = "p" * 40
ENGINEER_KEY = "e" * 40
RECOVERY_KEY = "r" * 40
# Placeholder write paths: the drill's real list is set through azd, never in this public repo (ADR-004)
WRITE_PATHS = ("src/order-service/app/example.py", "src/order-service/tests/test_*.py", "runbooks/*.md")


OPS_AGENT_KEY = "a" * 40
OPS_CALLS: list[dict] = []          # what the fake Ops Service received, for the v2.1 recovery tests


def fake_ops_app():
    """v2.1: the Ops Service's agent-facing actions, reduced to what the recovery tools need."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def action(request):
        name = request.path_params["name"]
        if request.headers.get("authorization") != f"Bearer {OPS_AGENT_KEY}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        OPS_CALLS.append({**body, "route": name})
        if name == "check_drift":
            return JSONResponse({"action": name, "result": "drift",
                                 "details": {"identity": "ok", "secret": "drift", "config": "ok", "network": "ok"}})
        if body.get("grant") != "lfg1.good.sig":
            return JSONResponse({"action": name, "result": "refused",
                                 "details": {"reason": "the grant's signature is not valid"}}, status_code=422)
        result = "denied" if name == "attempt_unsafe" else "ok"
        return JSONResponse({"action": name, "result": result,
                             "details": {"action": body["action"], "executed_by": "agent", "grant_id": "grt-0123456789ab"}})

    return Starlette(routes=[Route("/actions/{name}", action, methods=["POST"])])


def _serve(app):
    import uvicorn
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    return srv, thread, port


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    evidence = tmp_path_factory.mktemp("evidence")
    ops, ops_thread, ops_port = _serve(fake_ops_app())
    os.environ.update({"OPS_URL": f"http://127.0.0.1:{ops_port}", "OPS_AGENT_KEY": OPS_AGENT_KEY})
    os.environ.update({"PLANNER_KEY": PLANNER_KEY, "ENGINEER_KEY": ENGINEER_KEY, "RECOVERY_KEY": RECOVERY_KEY,
                       "BACKEND": "fixtures", "ENGINEER_WRITE_PATHS": ",".join(WRITE_PATHS),
                       "EVENT_SOURCE": f"dir:{evidence}", "MCP_ALLOWED_HOSTS": "127.0.0.1:*"})
    import uvicorn
    import main
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield {"url": f"http://127.0.0.1:{port}", "evidence": evidence}
    srv.should_exit = ops.should_exit = True
    thread.join(timeout=5)
    ops_thread.join(timeout=5)
