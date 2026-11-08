"""Writes contracts/mcp-tools.schema.json: every tool of the three endpoints, with its description, annotations and
JSON input schema, read from the server code itself (fixtures backend, nothing deployed). Rerun after any tool change;
tests/test_contract_schema.py fails while the file is stale.
Usage: python scripts/export-tool-schemas.py [--check]
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "mcp-tools.schema.json"


def build() -> dict:
    os.environ.setdefault("BACKEND", "fixtures")
    sys.path.insert(0, str(ROOT / "src" / "mcp-server" / "app"))
    import engineer_tools
    import planner_tools
    import recovery_tools
    from backends.fixtures import FixtureEvidence, FixtureRepo

    class NoStore:
        def append(self, *a, **k):
            pass

        def read(self, *a, **k):
            return []
    store = NoStore()
    evidence = FixtureEvidence(str(ROOT / "src" / "mcp-server" / "fixtures" / "planner.json"), store)
    servers = {"planner": planner_tools.build(evidence, store, "main"),
               "engineer": engineer_tools.build(FixtureRepo(evidence.data["repo"]), store, "main"),
               "recovery": recovery_tools.build(None, store)}

    async def tools():
        out = {}
        for endpoint, server in servers.items():
            listed = sorted(await server.list_tools(), key=lambda t: t.name)
            out[endpoint] = {"path": f"/{endpoint}/mcp", "tools": [
                {"name": t.name, "description": t.description,
                 "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else {},
                 "input_schema": t.input_schema} for t in listed]}
        return out
    return {"contract": "mcp-tools", "version": "2.3", "transport": "MCP streamable HTTP, stateless, JSON responses",
            "endpoints": asyncio.run(tools())}


if __name__ == "__main__":
    text = json.dumps(build(), indent=2, sort_keys=False) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text() == text else "contracts/mcp-tools.schema.json is stale: rerun")
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")
