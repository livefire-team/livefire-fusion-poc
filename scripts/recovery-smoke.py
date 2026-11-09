"""Smoke test of /recovery/mcp against a running server and Ops Service (scripts/fake-ops.py locally).

Calls execute_recovery with a valid grant (ok), the same grant again (refused, as a result the agent can read, not
an error), then check_recovery (ok or drift). Proves the Planner's key can't open /recovery.
Usage: MCP_URL=http://127.0.0.1:8100 RECOVERY_KEY=... PLANNER_KEY=... GRANT=grt-local-1 \
         python scripts/recovery-smoke.py drill-local-0001
"""
import asyncio
import json
import os
import sys

import httpx
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8100").rstrip("/")
DRILL = sys.argv[1] if len(sys.argv) > 1 else "drill-local-0001"
ACTION = os.environ.get("ACTION", "restore_kv_secrets_user")


def client(key):
    return Client(streamable_http_client(f"{URL}/recovery/mcp",
                                         http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {key}"})))


def body(result):
    return json.loads(result.content[0].text)


async def main():
    grant = os.environ["GRANT"]
    async with client(os.environ["RECOVERY_KEY"]) as c:
        first = body(await c.call_tool("execute_recovery", {"drill_id": DRILL, "action": ACTION, "grant": grant}))
        assert first["data"]["result"] == "ok", first
        print("execute_recovery with its grant:", first["summary"])
        again = body(await c.call_tool("execute_recovery", {"drill_id": DRILL, "action": ACTION, "grant": grant}))
        assert again["data"]["result"] == "refused", again
        print("the same grant again: refused:", again["data"]["details"]["reason"])
        drift = body(await c.call_tool("check_recovery", {"drill_id": DRILL}))
        assert drift["data"]["result"] in ("ok", "drift"), drift
        print("check_recovery:", drift["data"]["result"])
    r = httpx.post(f"{URL}/recovery/mcp", headers={"Authorization": f"Bearer {os.environ['PLANNER_KEY']}",
                                                   "Content-Type": "application/json", "Accept": "application/json"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403, r.status_code
    print("the Planner's key on /recovery: 403")
    print("RECOVERY SMOKE TEST PASSED")


asyncio.run(main())
