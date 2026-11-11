#!/usr/bin/env python3
"""Runs each pinned agent through its real MCP connection.

Planner: options, then a remediation brief.
Engineer: optionally creates a candidate branch.

Requires FOUNDRY_PROJECT_ENDPOINT, PLANNER_AGENT and ENGINEER_AGENT.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src" / "drill-runner"),
)

from livefire.agents import FoundryAgents  # noqa: E402
from livefire.policy import (  # noqa: E402
    check_brief,
    check_options,
    check_secrets,
)
from livefire.contracts import AutonomyPolicy  # noqa: E402


FAILED = {
    "label": "after-restore",
    "verdict": "FAIL",
    "last_step": "place-order",
    "error": "We couldn't place your order (SecretUnavailable). Please try again.",
    "orders_persisted": 0,
    "payment_auths_persisted": 0,
}


async def main(drill: str, engineer: bool) -> int:
    agents = FoundryAgents(
        os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        os.environ["PLANNER_AGENT"],
        os.environ["ENGINEER_AGENT"],
    )

    policy = AutonomyPolicy(expires_at="2099-01-01T00:00:00Z")

    out, _usage = await agents.planner({
        "task": "investigate",
        "drill_id": drill,
        "output_stage": "options",
        "goal": (
            "Customers cannot place orders. Find the cause from "
            "evidence and propose recovery options."
        ),
        "observed": {
            "baseline": "PASS",
            "during_fault": "FAIL at place-order",
        },
    })

    option_error = check_options(out.recovery_options, policy, drill)
    secret_error = check_secrets(out.model_dump())

    print(
        "Planner options:",
        "FAIL" if option_error or secret_error else "PASS",
    )

    if option_error or secret_error:
        print("Planner options validation failed; Engineer will not run.")
        return 2

    out, _usage = await agents.planner({
        "task": "remediation_brief",
        "drill_id": drill,
        "output_stage": "brief",
        "goal": "Infrastructure is green but the customer journey still fails.",
        "failed_journey": FAILED,
        "earlier_hypothesis": out.recovery_options.hypothesis,
    })

    brief_error = check_brief(out.remediation_brief, policy, drill)
    brief_secret_error = check_secrets(out.model_dump())

    print(
        "Planner remediation brief:",
        "FAIL" if brief_error or brief_secret_error else "PASS",
    )

    if brief_error or brief_secret_error:
        print("Planner brief validation failed; Engineer will not run.")
        return 2

    if engineer:
        report, _usage = await agents.engineer({
            "task": "candidate",
            "drill_id": drill,
            "attempt": 1,
            "base_ref": "main",
            "brief": out.remediation_brief.model_dump(),
        })

        report_secret_error = check_secrets(report.model_dump())

        print(
            "Engineer output secret check:",
            "FAIL" if report_secret_error else "PASS",
        )

        if report_secret_error:
            print("Engineer output validation failed.")
            return 2

    print("Agent smoke test completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(
        asyncio.run(
            main(
                sys.argv[1] if len(sys.argv) > 1 else "drill-agent-smoke",
                "--engineer" in sys.argv,
            )
        )
    )
