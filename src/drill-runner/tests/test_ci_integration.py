
import asyncio

import httpx
import pytest

from livefire.ports import GitHubRepo


COMMIT = "a" * 40
BRANCH = "candidate/drill-ci-check-1"


@pytest.mark.parametrize(
    "order_state, security_state, expected",
    [
        ("pass", "pass", "pass"),
        ("pass", "fail", "fail"),
        ("fail", "pass", "fail"),
        ("pass", "pending", "pending"),
        ("pass", None, "pending"),
        (None, "pass", "pending"),
        ("pass", "stale", "pending"),
    ],
)
def test_both_ci_workflows(order_state, security_state, expected):
    states = {
        "order-service.yml": order_state,
        "security.yml": security_state,
    }
    checked = []

    def handler(request):
        workflow = request.url.path.split("/workflows/")[1].split("/runs")[0]
        checked.append(workflow)

        assert request.url.params["head_sha"] == COMMIT
        assert request.url.params["branch"] == BRANCH

        state = states[workflow]

        if state is None:
            runs = []
        else:
            runs = [{
                "head_sha": "b" * 40 if state == "stale" else COMMIT,
                "head_branch": BRANCH,
                "status": "in_progress" if state == "pending" else "completed",
                "conclusion": "failure" if state == "fail" else "success",
                "html_url": f"https://github.com/example/{workflow}",
            }]

        return httpx.Response(200, json={"workflow_runs": runs})

    repo = GitHubRepo(
        repo="livefire-team/livefire-fusion-poc",
        token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
    )

    async def run_check():
        try:
            return await repo.ci_status(BRANCH, COMMIT)
        finally:
            await repo.http.aclose()

    result = asyncio.run(run_check())

    assert result.state == expected
    assert result.commit == COMMIT
    assert checked == ["order-service.yml", "security.yml"]
