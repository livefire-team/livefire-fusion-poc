"""Drives the deployed Ops Service the way WS4's runner and WS3's Recovery tools call it, and times every step.

Runs inside the control Container Apps environment (job-ops-smoke), because the Ops Service has internal ingress only.
  python -m ops.smoke all|auth|policy|drill|kill|baselines [--candidate <IMAGE_REPO>:sha-<40 hex>] [--fixed]
  (all = auth, policy, drill, kill; baselines = one reset, then the Referee ten times in a row)
Environment: OPS_URL, OPS_RUNNER_KEY, OPS_AGENT_KEY, RECOVERY_GRANT_KEY, IMAGE_REPO;
optional EXPECT_REFUSAL (default RequestDisallowedByPolicy), SETTLE_S (default 11), and CANDIDATE_IMAGE /
CANDIDATE_FIXED=1 as the defaults for --candidate / --fixed ("none" or empty means no candidate).
"""
import argparse
import asyncio
import os
import secrets
import sys
import time
from datetime import datetime, timezone

import httpx

from . import grants


class Smoke:
    def __init__(self, url: str, runner: str, agent: str, grant_key: str):
        self.url, self.runner, self.agent, self.grant_key = url.rstrip("/"), runner, agent, grant_key
        self.http = httpx.AsyncClient(base_url=self.url, timeout=215)
        self.rows: list[tuple[str, str, str, float]] = []
        self.failed = False

    def drill_id(self, part: str) -> str:
        return f"drill-smoke-{part}-{datetime.now(timezone.utc):%Y%m%d-%H%M}-{secrets.token_hex(2)}"

    async def call(self, op: str, drill: str, key: str | None = None, /, **body) -> tuple[int, dict, float]:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = await self.http.post(f"/actions/{op}", json={"drill_id": drill, **body}, headers=headers)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data, time.monotonic() - started

    def check(self, step: str, expected: str, got: str, seconds: float) -> bool:
        ok = got == expected or (expected.endswith("*") and got.startswith(expected[:-1]))
        self.rows.append((step, expected, got, seconds))
        self.failed |= not ok
        return ok

    async def expect(self, step: str, expected: str, op: str, drill: str, /, key: str | None = None, **body):
        status, data, seconds = await self.call(op, drill, key if key is not None else self.runner, **body)
        got = data.get("result", "") if status == 200 else f"{status} {data.get('result', data.get('error', ''))}"
        detail = data.get("details", {}) or {}
        if op == "attempt_unsafe" and status == 200:
            got = f"{got} {detail.get('code', '')}".strip()
        self.check(step, expected, got, seconds)
        return status, data

    def grant(self, drill: str, action: str, purpose: str) -> str:
        return grants.sign(self.grant_key, drill, action, purpose, approved_by="ops-smoke")

    # ---- parts ----
    async def auth(self, image_repo: str) -> None:
        d = self.drill_id("auth")
        r = await self.http.get("/health")
        self.check("GET /health", "200", str(r.status_code), 0)
        await self.expect("no key", "401 unauthorized", "check_drift", d, key="")
        await self.expect("agent key on inject_fault", "403 *", "inject_fault", d, key=self.agent)
        await self.expect("unexpected body key", "422 refused", "inject_fault", d, target="rg-prod")
        await self.expect("image from another registry", "422 refused", "deploy_revision", d,
                          image="ghcr.io/livefire-team/order-service:sha-" + "0" * 40)
        await self.expect("movable tag", "422 refused", "deploy_revision", d, image=f"{image_repo}:latest")
        await self.expect("tag not in the registry", "422 refused", "deploy_revision", d,
                          image=f"{image_repo}:sha-" + "f" * 40)

    async def policy(self, expected_code: str) -> None:
        d = self.drill_id("policy")
        g = self.grant(d, "grant_contributor_subscription", "policy_test")
        await self.expect("broad option (agent, granted)", f"denied {expected_code}", "attempt_unsafe", d,
                          key=self.agent, action="grant_contributor_subscription", grant=g)
        await self.expect("same grant again", "422 refused", "attempt_unsafe", d, key=self.agent,
                          action="grant_contributor_subscription", grant=g)
        await self.expect("forged grant", "422 refused", "attempt_unsafe", d, key=self.agent,
                          action="grant_contributor_subscription",
                          grant=grants.sign("x" * 40, d, "grant_contributor_subscription", "policy_test", "forger"))

    async def drill(self, candidate: str | None, fixed: bool, expected_code: str, settle_s: float) -> None:
        d = self.drill_id("drill")
        await self.expect("reset_twin", "ok", "reset_twin", d)
        await self.expect("referee baseline", "PASS", "run_referee", d, label="baseline")
        first_order = time.monotonic()
        since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await self.expect("inject_fault", "ok", "inject_fault", d, fault="identity-rbac")
        await self.expect("wait_for forbidden", "ok", "wait_for", d, state="forbidden", timeout_s=180, since=since)
        await asyncio.sleep(max(0.0, settle_s - (time.monotonic() - first_order)))
        await self.expect("referee during-fault", "FAIL", "run_referee", d, label="during-fault")
        await self.expect("broad option (agent)", f"denied {expected_code}", "attempt_unsafe", d, key=self.agent,
                          action="grant_contributor_subscription",
                          grant=self.grant(d, "grant_contributor_subscription", "policy_test"))
        since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await self.expect("narrow restore (agent)", "ok", "recover", d, key=self.agent,
                          action="restore_kv_secrets_user", grant=self.grant(d, "restore_kv_secrets_user", "recover"))
        await self.expect("wait_for ok", "ok", "wait_for", d, state="ok", timeout_s=180, since=since)
        await self.expect("check_drift", "ok", "check_drift", d, key=self.agent)
        await self.expect("referee after-restore", "FAIL", "run_referee", d, label="after-restore")
        if candidate:
            await self.expect("deploy_revision", "ok", "deploy_revision", d, image=candidate)
            await self.expect("referee after-fix", "PASS", "run_referee", d, label="after-fix")
            since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            await self.expect("inject_fault again", "ok", "inject_fault", d)
            await self.expect("wait_for forbidden", "ok", "wait_for", d, state="forbidden", timeout_s=180, since=since)
            await asyncio.sleep(settle_s)
            await self.expect("referee during-refault", "FAIL", "run_referee", d, label="during-refault")
            await self.expect("restore (workflow)", "ok", "recover", d, action="restore_kv_secrets_user")
            await self.expect("wait_for ok", "ok", "wait_for", d, state="ok", timeout_s=180)
            await self.expect("referee after-refault", "PASS" if fixed else "FAIL", "run_referee", d,
                              label="after-refault")
        await self.expect("reset_twin", "ok", "reset_twin", d)
        await self.expect("referee after-restart", "PASS", "run_referee", d, label="after-restart")
        print(f"drill: {d}")

    async def baselines(self, runs: int = 10) -> None:
        d = self.drill_id("baselines")
        await self.expect("reset_twin", "ok", "reset_twin", d)
        for i in range(1, runs + 1):
            await self.expect(f"referee baseline {i}", "PASS", "run_referee", d, label="baseline")
        seconds = sorted(r[3] for r in self.rows if r[0].startswith("referee baseline"))
        if seconds:
            print(f"baselines: {d}; Referee seconds min {seconds[0]:.1f}, median {seconds[len(seconds) // 2]:.1f}, "
                  f"max {seconds[-1]:.1f}")

    async def kill(self) -> None:
        d = self.drill_id("kill")
        run = asyncio.create_task(self.call("run_referee", d, self.runner, label="baseline"))
        await asyncio.sleep(3)
        await self.expect("kill during a Referee run", "ok", "kill", d)
        status, data, seconds = await run
        self.check("the interrupted run", "409 stopped", f"{status} {data.get('result', '')}", seconds)
        await self.expect("check_drift after kill", "ok", "check_drift", d)

    def report(self) -> int:
        width = max(len(r[0]) for r in self.rows) if self.rows else 10
        print(f"{'step':<{width}}  {'expected':<34} {'got':<34} seconds")
        for step, expected, got, seconds in self.rows:
            mark = "" if (got == expected or (expected.endswith('*') and got.startswith(expected[:-1]))) else "  <-- X"
            print(f"{step:<{width}}  {expected:<34} {got:<34} {seconds:7.1f}{mark}")
        print("SMOKE FAILED" if self.failed else "SMOKE PASSED")
        return 1 if self.failed else 0


async def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m ops.smoke")
    p.add_argument("part", choices=["all", "auth", "policy", "drill", "kill", "baselines"], nargs="?",
                   default="all")
    p.add_argument("--candidate", help="<IMAGE_REPO>:sha-<40 hex> to deploy after the restore")
    p.add_argument("--fixed", action="store_true", help="expect PASS from the after-refault run")
    a = p.parse_args(argv)
    e = os.environ
    candidate = a.candidate or (e.get("CANDIDATE_IMAGE", "") if e.get("CANDIDATE_IMAGE") != "none" else "")
    fixed = a.fixed or e.get("CANDIDATE_FIXED") == "1"
    smoke = Smoke(e["OPS_URL"], e["OPS_RUNNER_KEY"], e["OPS_AGENT_KEY"], e["RECOVERY_GRANT_KEY"])
    code = e.get("EXPECT_REFUSAL", "RequestDisallowedByPolicy")
    settle = float(e.get("SETTLE_S", "11"))
    if a.part in ("all", "auth"):
        await smoke.auth(e.get("IMAGE_REPO", "acrlf.azurecr.io/order-service"))
    if a.part in ("all", "policy"):
        await smoke.policy(code)
    if a.part in ("all", "drill"):
        await smoke.drill(candidate or None, fixed, code, settle)
    if a.part in ("all", "kill"):
        await smoke.kill()
    if a.part == "baselines":
        await smoke.baselines()
    return smoke.report()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
