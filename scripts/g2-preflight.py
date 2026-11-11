#!/usr/bin/env python3
"""Static WS4 G2 guardrails. No network calls; does not print secrets or claim live integration.

Examples:
  python scripts/g2-preflight.py --repo-root .
  python scripts/g2-preflight.py --repo-root . --ws1-root ../livefire-fusion-poc-main
  python scripts/g2-preflight.py --repo-root . --require-live-config agent
  python scripts/g2-preflight.py --repo-root . --json

PASS: check definitely satisfied. WARN: cross-team decision/live verification needed.
FAIL: a required local file/configuration is absent or unsafe.
"""
import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REQUIRED = (
    "README-WS4.md",
    "src/drill-runner/requirements.txt",
    "src/drill-runner/requirements-dev.txt",
    "src/drill-runner/Dockerfile",
    "src/drill-runner/livefire/workflow.py",
    "src/drill-runner/livefire/runner.py",
    "src/drill-runner/livefire/contracts.py",
    "src/drill-runner/livefire/policy.py",
    "src/drill-runner/livefire/events.py",
    "src/drill-runner/livefire/ports.py",
    "src/drill-runner/agents/planner.yaml",
    "src/drill-runner/agents/engineer.yaml",
    "scripts/create_agents.py",
    "scripts/agent-smoke.py",
    "scripts/export_schemas.py",
    "scripts/verify_package.py",
    "contracts/ops-actions.md",
    "contracts/schemas/Event.schema.json",
    "contracts/schemas/PlannerOutput.schema.json",
    "contracts/schemas/ChangeReport.schema.json",
    "infra/modules/foundry.bicep",
    "infra/modules/drill-runner.bicep",
    "infra/main.ws4-snippet.bicep",
    ".github/workflows/drill-runner.yml",
    "docs/WS4-G2-BUILD-STEPS.md",
    "docs/G2-ACCEPTANCE-MATRIX.md",
    "docs/G2-HANDOFFS.md",
)
PLANNER_TOOLS = (
    "query_incident_telemetry", "get_identity_snapshot", "search_incident_history", "read_runbook",
    "read_repository_context", "get_commit_history",
)
ENGINEER_TOOLS = (
    "read_allowed_files", "create_candidate_branch", "apply_patch", "write_regression_test",
    "update_runbook", "get_ci_results",
)
AGENT_ENV = ("FOUNDRY_PROJECT_ENDPOINT", "MODEL_DEPLOYMENT", "MCP_URL", "PLANNER_AGENT", "ENGINEER_AGENT")
WORKFLOW_ENV = ("OPS_URL", "OPS_KEY", "GITHUB_REPO", "IMAGE_REPO", "EVENT_SOURCE")


@dataclass(frozen=True)
class Check:
    code: str
    status: str  # PASS, WARN, FAIL
    note: str


def yaml_block(filename: Path, key: str) -> str:
    """Extract one simple YAML top-level role definition section; no YAML library needed."""
    contents = filename.read_text(encoding="utf-8")
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*\n((?:\s{{4,}}.*\n?)*)", contents)
    return match.group(1) if match else ""


def checks(root: Path, ws1_root: Path | None, live_phase: str, env: dict[str, str]) -> list[Check]:
    out: list[Check] = []
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    out.append(Check("REQUIRED_FILES", "FAIL" if missing else "PASS",
                     "missing: " + ", ".join(missing) if missing else f"{len(REQUIRED)} WS4 files present"))

    contract = root / "src/drill-runner/livefire/contracts.py"
    if contract.exists():
        data = contract.read_text(encoding="utf-8")
        match = re.search(r'CONTRACT_VERSION\s*=\s*["\']([^"\']+)', data)
        out.append(Check("CONTRACT_VERSION", "PASS" if match and match.group(1) == "1.0" else "WARN",
                         f"observed: {match.group(1) if match else 'unknown'} (G1 frozen v1.0; changes require approval)"))

    for role, expected, conn in (("planner", PLANNER_TOOLS, "livefire-planner-mcp"),
                                 ("engineer", ENGINEER_TOOLS, "livefire-engineer-mcp")):
        path = root / f"src/drill-runner/agents/{role}.yaml"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            found = yaml_block(path, "allowed_tools")
            found_tools = re.findall(r"(?m)^\s+-\s+([a-z_]+)\s*$", found)
            correct = sorted(found_tools) == sorted(expected) and conn in content
            out.append(Check(f"{role.upper()}_TOOLS", "PASS" if correct else "FAIL",
                             f"{len(found_tools)} exact allowed tools and expected MCP connection" if correct else
                             "unexpected/missing tool or MCP connection; review YAML"))

    invalid_env = [p for p in (".env", "local.env") if (root / p).is_file()]
    out.append(Check("SECRETS_REVIEW", "WARN" if invalid_env else "PASS",
                     "Local env file exists; ensure it is gitignored and never staged" if invalid_env else
                     "No top-level local secret env file detected (does not replace secret scanning)"))

    ws4_ci = root / ".github/workflows/drill-runner.yml"
    if ws4_ci.exists():
        content = ws4_ci.read_text(encoding="utf-8")
        out.append(Check("RUNNER_CI", "PASS" if "pytest -q" in content and "docker/build-push-action" in content else "WARN",
                         "WS4 CI references tests and Docker build" if "pytest -q" in content and "docker/build-push-action" in content else
                         "review WS4 CI test/build jobs"))

    if ws1_root is not None:
        ws1_ci = ws1_root / ".github/workflows/order-service.yml"
        if not ws1_ci.is_file():
            out.append(Check("WS1_IMAGE_TAG", "WARN", "WS1 CI not found; verify --ws1-root is repository root"))
        else:
            ws1_source = ws1_ci.read_text(encoding="utf-8")
            ws4_source = (root / "src/drill-runner/livefire/workflow.py").read_text(encoding="utf-8") if (root / "src/drill-runner/livefire/workflow.py").exists() else ""
            ws1_short = "GITHUB_SHA::7" in ws1_source
            ws4_full = ":sha-{commit}" in ws4_source
            if ws1_short and ws4_full:
                out.append(Check("WS1_IMAGE_TAG", "WARN", "Confirmed mismatch: WS1 CI publishes short SHA tags; WS4 runner constructs full SHA tag"))
            else:
                out.append(Check("WS1_IMAGE_TAG", "WARN", "Tag format requires human comparison to Ops contract and actual GHCR images"))

    if live_phase != "none":
        needed = AGENT_ENV if live_phase == "agent" else AGENT_ENV + WORKFLOW_ENV
        absent = [key for key in needed if not env.get(key) or "<" in env.get(key, "")]
        out.append(Check("LIVE_CONFIG", "FAIL" if absent else "PASS",
                         "missing/unfilled environment variable names: " + ", ".join(absent) if absent else
                         f"{len(needed)} variable names configured; values and network/Azure access NOT validated"))
        if env.get("GITHUB_REPO", "").lower().rstrip("/") == "livefire-team/ws4-new":
            out.append(Check("ENGINEER_REPO", "FAIL", "GITHUB_REPO must be livefire-team/livefire-fusion-poc (WS1), never ws4-new"))
        elif live_phase == "workflow" and env.get("GITHUB_REPO") != "livefire-team/livefire-fusion-poc":
            out.append(Check("ENGINEER_REPO", "WARN", "Verify GITHUB_REPO points at the actual WS1 order-service repository"))

    out.append(Check("AZURE_LIVE_PROOF", "WARN", "Not tested by this static script: Foundry, real MCP, Ops, GHCR, Blob, WS5, CI run"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--ws1-root", type=Path)
    parser.add_argument("--require-live-config", choices=("agent", "workflow"), default="none")
    parser.add_argument("--json", action="store_true", help="print JSON with statuses, never environment secret values")
    args = parser.parse_args(argv)
    result = checks(args.repo_root.resolve(), args.ws1_root.resolve() if args.ws1_root else None,
                    args.require_live_config, dict(os.environ))
    if args.json:
        print(json.dumps([asdict(x) for x in result], indent=2))
    else:
        for x in result:
            print(f"{x.status:<4}  {x.code:<21} {x.note}")
        print("Static preflight only — WARN is not an Azure PASS.")
    return 1 if any(c.status == "FAIL" for c in result) else 0


if __name__ == "__main__":
    raise SystemExit(main())
