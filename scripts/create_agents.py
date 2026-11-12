#!/usr/bin/env python3
"""Creates a new version of the Planner and the Engineer in the Foundry project, from agents/*.yaml.

  python scripts/create_agents.py --dry-run     print both definitions; call nothing
  python scripts/create_agents.py               create versions; print the pins for azd env
  python scripts/create_agents.py --verify lf-planner:3 lf-engineer:2
                                                check that pinned versions still match the YAML

Needs FOUNDRY_PROJECT_ENDPOINT, MODEL_DEPLOYMENT, MCP_URL and ENGINEER_WRITE_PATHS, and Azure AI User on the project.
Agents are only ever changed here, never in the portal, so every version is in git. The instructions in git carry
an {allowed_paths} placeholder: the write paths are filled in from ENGINEER_WRITE_PATHS (the azd value
MCP_ENGINEER_WRITE_PATHS) when a version is created, so they live in Foundry and never in this repo (ADR-004).
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "src" / "drill-runner"
sys.path.insert(0, str(RUNNER))
from livefire import contracts  # noqa: E402
from livefire.agents import strict_schema  # noqa: E402

ROLES = {"planner": "planner.yaml", "engineer": "engineer.yaml"}


def tool_names(allowed) -> list[str]:
    """The service returns allowed_tools as an MCPToolFilter ({'tool_names': [...]}), not the plain list sent."""
    if allowed is None:
        return []
    if isinstance(allowed, (list, tuple)):
        return list(allowed)
    names = allowed.get("tool_names") if hasattr(allowed, "get") else getattr(allowed, "tool_names", None)
    return list(names or [])


def load(role: str, write_paths: str) -> tuple[dict, str]:
    spec = yaml.safe_load((RUNNER / "agents" / ROLES[role]).read_text())
    text = (RUNNER / "agents" / spec["instructions_file"]).read_text()
    return spec, text.replace("{allowed_paths}", write_paths)


def write_paths_from_env() -> str:
    os.environ.setdefault("ENGINEER_WRITE_PATHS", os.environ.get("MCP_ENGINEER_WRITE_PATHS", ""))
    patterns = contracts.engineer_write_paths()      # refuses unsafe or protected patterns
    if not patterns:
        sys.exit("set ENGINEER_WRITE_PATHS (or MCP_ENGINEER_WRITE_PATHS): the files a candidate may change")
    return ", ".join(patterns)


def definition(spec: dict, instructions: str, model: str, mcp_url: str, connection_id: str):
    from azure.ai.projects.models import (MCPTool, PromptAgentDefinition, PromptAgentDefinitionTextOptions, Reasoning,
                                          TextResponseFormatJsonSchema)
    output = getattr(contracts, spec["output_model"])
    tool = MCPTool(
        server_label=spec["mcp"]["server_label"],
        server_url=mcp_url.rstrip("/") + spec["mcp"]["path"],
        allowed_tools=spec["mcp"]["allowed_tools"],      # exact list: a tool added to the server later stays hidden
        require_approval="never",                        # approvals that matter are the workflow's, not per tool call
        project_connection_id=connection_id,             # the key lives in the connection, never in this definition
    )
    return PromptAgentDefinition(
        model=model,
        instructions=instructions,
        tools=[tool],
        reasoning=Reasoning(effort=spec.get("reasoning_effort", "medium")),
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
            name=spec["output_model"], schema=strict_schema(output), strict=True)),
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verify", nargs=2, metavar=("PLANNER", "ENGINEER"))
    args = p.parse_args()
    model = os.environ.get("MODEL_DEPLOYMENT", "gpt-5.1")
    mcp_url = os.environ.get("MCP_URL", "https://ca-mcp.example.azurecontainerapps.io")

    if args.dry_run:
        for role in ROLES:
            spec, instructions = load(role, "<ENGINEER_WRITE_PATHS>")
            d = definition(spec, instructions, model, mcp_url, f"<id of {spec['mcp']['connection']}>")
            print(json.dumps({"agent_name": spec["name"], "definition": d.as_dict()}, indent=2)[:4000])
        return 0

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
    paths = write_paths_from_env()
    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())

    if args.verify:
        ok = True
        for role, pin in zip(ROLES, args.verify):
            spec, instructions = load(role, paths)
            name, _, version = pin.partition(":")
            got = project.agents.get_version(agent_name=name, agent_version=version).definition
            tool = got.tools[0]
            checks = {
                "instructions": hashlib.sha256((got.instructions or "").encode()).hexdigest()
                == hashlib.sha256(instructions.encode()).hexdigest(),
                "one tool only": len(got.tools) == 1,
                "allowed_tools": tool_names(tool.allowed_tools) == spec["mcp"]["allowed_tools"],
                "require_approval never": tool.require_approval == "never",
                "model": got.model == model,
            }
            for check, passed in checks.items():
                print(f"{pin:<16} {check:<24} {'ok' if passed else 'MISMATCH'}")
                ok &= passed
        return 0 if ok else 1

    for role in ROLES:
        spec, instructions = load(role, paths)
        connection = project.connections.get(spec["mcp"]["connection"])
        version = project.agents.create_version(
            agent_name=spec["name"], description=spec["description"],
            definition=definition(spec, instructions, model, mcp_url, connection.id))
        print(f"{role.upper()}_AGENT={version.name}:{version.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
