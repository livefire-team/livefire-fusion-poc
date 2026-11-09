"""G1 demo and deploy smoke test: list each endpoint's tools, call every Planner tool, prove the keys are separate.

Usage: MCP_URL=http://127.0.0.1:8100 PLANNER_KEY=... ENGINEER_KEY=... RECOVERY_KEY=... python scripts/mcp-smoke.py [drill-id]
v2.1: also lists /recovery (execute_recovery, check_recovery) and proves the Planner's key can't open it. It never
calls execute_recovery: that is agent-smoke.py --recovery, with a forged grant.
"""
import asyncio
import json
import os
import sys

import httpx
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8100").rstrip("/")
DRILL = sys.argv[1] if len(sys.argv) > 1 else "drill-smoke-0001"
PLANNER_CALLS = [
    ("query_incident_telemetry", {"signal": "exceptions", "minutes": 30}),
    ("get_identity_snapshot", {}),
    ("search_incident_history", {"query": "restart"}),
    ("read_runbook", {"name": "order-service-keyvault-recovery"}),
    ("read_repository_context", {"path": "src/order-service/app/main.py"}),
    ("get_commit_history", {"path": "src/order-service/app/main.py", "limit": 5}),
]


def client(endpoint, key):
    return Client(streamable_http_client(f"{URL}/{endpoint}/mcp",
                                         http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {key}"})))


async def main():
    ok = True
    for endpoint, key in (("planner", os.environ["PLANNER_KEY"]), ("engineer", os.environ["ENGINEER_KEY"]),
                          ("recovery", os.environ["RECOVERY_KEY"])):
        async with client(endpoint, key) as c:
            print(f"/{endpoint}: {sorted(t.name for t in (await c.list_tools()).tools)}")
    async with client("planner", os.environ["PLANNER_KEY"]) as c:
        for name, args in PLANNER_CALLS:
            r = await c.call_tool(name, {"drill_id": DRILL, **args})
            text = r.content[0].text if r.content else ""
            status = "error" if r.is_error else "ok"
            ok &= not r.is_error
            print(f"  {name}: {status} ({len(text)} chars) {json.loads(text)['source'] if status == 'ok' else text[:80]}")
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "apply_patch", "arguments": {"drill_id": DRILL}}}
    cross = httpx.post(f"{URL}/engineer/mcp", json=body, timeout=10, headers={
        "Authorization": f"Bearer {os.environ['PLANNER_KEY']}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    print(f"planner key on /engineer: HTTP {cross.status_code} (expected 403)")
    ok &= cross.status_code == 403
    body["params"] = {"name": "execute_recovery", "arguments": {"drill_id": DRILL}}
    cross = httpx.post(f"{URL}/recovery/mcp", json=body, timeout=10, headers={
        "Authorization": f"Bearer {os.environ['PLANNER_KEY']}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    print(f"planner key on /recovery: HTTP {cross.status_code} (expected 403)")
    ok &= cross.status_code == 403
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
