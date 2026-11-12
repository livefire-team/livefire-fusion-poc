#!/usr/bin/env python3
"""Runs each pinned agent once through its real MCP connection, outside a drill (build steps 5C).

  python scripts/agent-smoke.py drill-agent-smoke-1112              Planner: options, then a brief
  python scripts/agent-smoke.py drill-agent-smoke-1112 --engineer   also the Engineer (writes a candidate branch)

Needs FOUNDRY_PROJECT_ENDPOINT, PLANNER_AGENT, ENGINEER_AGENT and ENGINEER_WRITE_PATHS (or MCP_ENGINEER_WRITE_PATHS).
The checks are the workflow's own (livefire.policy), so a pass here means a drill would accept the same output.
Prints only pass/fail lines and counts: never the agents' text, which can quote tool output.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "drill-runner"))

from livefire.agents import FoundryAgents  # noqa: E402
from livefire.contracts import AutonomyPolicy  # noqa: E402
from livefire.policy import check_brief, check_options, check_secrets  # noqa: E402
from livefire.ports import DependencyError, GuardrailBlocked  # noqa: E402

AFTER_RESTORE = {"label": "after-restore", "verdict": "FAIL", "last_step": "place-order",
                 "orders_persisted": 0, "payment_auths_persisted": 0}


def line(name: str, problem: str | None, usage) -> bool:
    print(f"{name:<22} {'ok' if problem is None else 'FAIL: ' + problem}  "
          f"(tool calls {usage.tool_calls}, tokens {usage.tokens}, response {usage.response_id})")
    return problem is None


async def main(drill: str, engineer: bool) -> int:
    os.environ.setdefault("ENGINEER_WRITE_PATHS", os.environ.get("MCP_ENGINEER_WRITE_PATHS", ""))
    if not os.environ["ENGINEER_WRITE_PATHS"]:
        sys.exit("set ENGINEER_WRITE_PATHS (or MCP_ENGINEER_WRITE_PATHS)")
    agents = FoundryAgents(os.environ["FOUNDRY_PROJECT_ENDPOINT"], os.environ["PLANNER_AGENT"],
                           os.environ["ENGINEER_AGENT"])
    policy = AutonomyPolicy(expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    out, usage = await agents.planner({
        "task": "investigate", "drill_id": drill, "output_stage": "options",
        "goal": "Customers cannot place orders. Find the cause from evidence and propose recovery options.",
        "observed": {"baseline": "PASS", "during_fault": "FAIL at place-order"}})
    problem = ("returned a brief" if out.recovery_options is None else
               check_secrets(out.model_dump()) or check_options(out.recovery_options, policy, drill))
    if not line("planner options", problem, usage) or usage.tool_calls == 0:
        return 2

    hypothesis = out.recovery_options.hypothesis
    out, usage = await agents.planner({
        "task": "remediation_brief", "drill_id": drill, "output_stage": "brief",
        "goal": "Infrastructure is green but the customer journey still fails. Explain why from evidence and write "
                "the brief the Engineer will implement.",
        "failed_journey": AFTER_RESTORE, "earlier_hypothesis": hypothesis})
    problem = ("returned options" if out.remediation_brief is None else
               check_secrets(out.model_dump()) or check_brief(out.remediation_brief, policy, drill))
    if not line("planner brief", problem, usage):
        return 2

    if engineer:
        report, usage = await agents.engineer({
            "task": "candidate", "drill_id": drill, "attempt": 1, "base_ref": "main",
            "brief": out.remediation_brief.model_dump(), "ci_failure": None,
            "failed_journey_after_previous_candidate": None})
        problem = check_secrets(report.model_dump()) or (None if report.drill_id == drill else "wrong drill")
        if not line("engineer change report", problem, usage) or usage.tool_calls == 0:
            return 2
        print(f"candidate branch: {report.branch} ({len(report.commits)} commits)")
    print("AGENT SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "drill-agent-smoke",
                                  "--engineer" in sys.argv)))
    except (DependencyError, GuardrailBlocked) as exc:
        print(f"AGENT SMOKE TEST FAILED: {type(exc).__name__}")
        sys.exit(2)
