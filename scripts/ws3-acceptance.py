"""G3 acceptance checks for WS3: T-03, T-04 and T-08, against a local or deployed MCP server (key mode).

Usage:
  MCP_URL=... PLANNER_KEY=... ENGINEER_KEY=... EVENT_SOURCE=... python scripts/ws3-acceptance.py <drill-id> [checks]

  checks: any of t03 t04 t08 (default: t03 t04). T-03 and T-04 write their deny events into <drill-id>, so one drill
  shows both on the Fusion Control Center. Use a drill ID of your own (e.g. drill-g3-check-0001), not a live drill's.

  EVENT_SOURCE  where the server writes its audit events, so the script can confirm the deny events landed:
                dir:./evidence (laptop) or blob:https://<account>.blob.core.windows.net/evidence (lab; signs in with
                your own az login, which needs Storage Blob Data Reader on the evidence account). Unset: not checked.

  T-08 also needs, from the private incident corpus (never in this repo, ADR-004):
    PLANTED_INCIDENT_ID     the planted record's ID
    PLANTED_INCIDENT_QUERY  a search that should retrieve it
  and, to confirm in the lab that the app identity holds no privileged role at any scope, APP_IDENTITY_PRINCIPAL_ID
  (an azd output; needs az login).
  T-08 proves the server's part: the record is retrieved, marked as untrusted data, and no privileged role followed.
  That no agent acted on it is WS4's drill-loop-T-08 run (scorer gate P5).

Entra mode: the keys no longer work; T-03 is then shown with the Planner agent identity's token (WS4).
"""
import asyncio
import json
import os
import subprocess
import sys
import time

import httpx
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8100").rstrip("/")
JOURNEY_PATH = "journeys/checkout.spec.ts"        # any path under journeys/; the check runs before any GitHub call
PRIVILEGED_ROLES = ("Owner", "User Access Administrator", "Role Based Access Control Administrator")


def client(endpoint, key):
    return Client(streamable_http_client(f"{URL}/{endpoint}/mcp",
                                         http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {key}"})))


def result_of(r) -> dict:
    return json.loads(r.content[0].text) if r.content else {}


def read_events(drill: str) -> list[dict] | None:
    source = os.environ.get("EVENT_SOURCE", "")
    if source.startswith("dir:"):
        path = os.path.join(source[4:], drill, "events.jsonl")
        if not os.path.isfile(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    if source.startswith("blob:"):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import ContainerClient
        account_url, _, container = source[5:].rpartition("/")
        blob = ContainerClient(account_url, container, credential=DefaultAzureCredential()).get_blob_client(
            f"{drill}/events.jsonl")
        if not blob.exists():
            return []
        return [json.loads(line) for line in blob.download_blob().readall().decode().splitlines() if line.strip()]
    return None


def deny_event(drill: str, action: str, tool: str, since: str, wait_s: float = 10.0) -> dict | None | bool:
    """The deny event for this tool, recorded after `since`. None: EVENT_SOURCE unset. False: not found."""
    deadline = time.monotonic() + wait_s
    while True:
        events = read_events(drill)
        if events is None:
            return None
        for e in events:
            d = e.get("details", {})
            if (e.get("action") == action and e.get("result") == "deny" and d.get("tool") == tool
                    and e.get("ts", "") >= since):
                return e
        if time.monotonic() > deadline:
            return False
        time.sleep(1)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def report_event(found, label: str) -> bool:
    if found is None:
        print(f"  {label} event: not checked (EVENT_SOURCE unset)")
        return True
    if found is False:
        print(f"  {label} event: NOT FOUND")
        return False
    print(f"  {label} event: {found['ts']} {found['action']} {found['result']}: {found['details'].get('summary', '')}")
    return True


async def t03(drill: str) -> bool:
    """A Planner credential calling an Engineer tool gets 403, recorded as planner.tool_call deny."""
    print("T-03: the Planner's key calls the Engineer's apply_patch")
    since = now()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "apply_patch", "arguments": {"drill_id": drill}}}
    r = httpx.post(f"{URL}/engineer/mcp", json=body, timeout=15, headers={
        "Authorization": f"Bearer {os.environ['PLANNER_KEY']}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    ok = r.status_code == 403
    print(f"  HTTP {r.status_code} (expected 403): {r.text[:120]}")
    ok &= report_event(deny_event(drill, "planner.tool_call", "apply_patch", since), "deny")
    return ok


async def t04(drill: str) -> bool:
    """The Engineer's write to journeys/ is refused by the server, before any GitHub call, and recorded."""
    print(f"T-04: the Engineer's key writes {JOURNEY_PATH}")
    since = now()
    async with client("engineer", os.environ["ENGINEER_KEY"]) as c:
        r = await c.call_tool("apply_patch", {"drill_id": drill, "attempt": 1, "path": JOURNEY_PATH,
                                              "content": "// acceptance check: must never be written\n",
                                              "message": "acceptance check T-04"})
    res = result_of(r)
    decision = res.get("authorization", {}).get("decision")
    ok = res.get("refused") is True and decision == "deny" and "protected path" in res.get("error", "")
    print(f"  refused={res.get('refused')} decision={decision}: {res.get('error', '')[:120]}")
    ok &= report_event(deny_event(drill, "engineer.tool_call", "apply_patch", since), "deny")
    return ok


async def t08(drill: str) -> bool:
    """The planted record comes back as untrusted data, and the lab shows no privileged role it asked for."""
    planted, query = os.environ.get("PLANTED_INCIDENT_ID"), os.environ.get("PLANTED_INCIDENT_QUERY")
    if not planted or not query:
        print("T-08: set PLANTED_INCIDENT_ID and PLANTED_INCIDENT_QUERY (from the private corpus)")
        return False
    print(f"T-08: the Planner searches incident history; {planted} must come back as untrusted data")
    async with client("planner", os.environ["PLANNER_KEY"]) as c:
        r = await c.call_tool("search_incident_history", {"drill_id": drill, "query": query})
    res = result_of(r)
    ids = [h.get("id") for h in (res.get("data") or {}).get("results", []) if isinstance(h, dict)]
    ok = not r.is_error and planted in ids and res.get("untrusted_content") is True
    print(f"  results={ids} untrusted_content={res.get('untrusted_content')} source={res.get('source')}")
    principal = os.environ.get("APP_IDENTITY_PRINCIPAL_ID")
    if principal:
        out = subprocess.run(["az", "role", "assignment", "list", "--assignee", principal, "--all",
                              "--query", "[].roleDefinitionName", "-o", "json"],
                             capture_output=True, text=True, check=False)
        if out.returncode != 0:
            print(f"  role check failed: {out.stderr.strip()[:160]}")
            return False
        privileged = sorted(set(json.loads(out.stdout)) & set(PRIVILEGED_ROLES))
        print(f"  app identity's privileged roles: {privileged or 'none'} (expected none)")
        ok &= not privileged
    else:
        print("  role check: not run (set APP_IDENTITY_PRINCIPAL_ID)")
    return ok


async def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    drill, wanted = sys.argv[1], sys.argv[2:] or ["t03", "t04"]
    checks = {"t03": t03, "t04": t04, "t08": t08}
    unknown = [w for w in wanted if w not in checks]
    if unknown:
        sys.exit(f"unknown checks: {unknown}; choose from {sorted(checks)}")
    results = {w: await checks[w](drill) for w in wanted}
    print()
    for w, ok in results.items():
        print(f"{w.upper().replace('T', 'T-')}: {'PASSED' if ok else 'FAILED'}")
    if os.environ.get("EVENT_SOURCE"):
        print(f"On the Fusion Control Center, open drill {drill} to show the denials.")
    sys.exit(0 if all(results.values()) else 1)


asyncio.run(main())
