"""The Ops Service's actions (contracts/ops-actions.md, v2.1 wire format; this twin enables one fault).

Rules every action follows:
- The caller never names a resource; the twin's targets come from Settings.
- Mutating actions run one at a time (409 otherwise); wait_for, check_drift and kill never wait for that lock.
- Every action writes its events to the drill's append-only log. After a kill, an action that started earlier
  writes nothing more and returns 409.
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import grants
from .referee import Referee, RefereeError
from .settings import Settings
from .twin import Twin, TwinError

CONTRACT = "2.1"
DRILL = re.compile(r"^drill-[A-Za-z0-9-]{1,64}$")
LABEL = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
FAULTS = ("identity-rbac", "secret-drift", "config-drift", "network-drift")
ENABLED_FAULTS = ("identity-rbac",)
NARROW = {"restore_kv_secrets_user": "identity-rbac", "restore_db_secret": "secret-drift",
          "rollback_app_config": "config-drift", "restore_sql_network_rule": "network-drift"}
BROAD = {"grant_contributor_subscription": "identity-rbac", "open_sql_firewall_to_internet": "network-drift"}
ENABLED_NARROW = ("restore_kv_secrets_user",)
ENABLED_BROAD = ("grant_contributor_subscription",)
WAIT_STATES = {"ok": "wait.ok", "forbidden": "wait.forbidden", "conformant": "wait.ok", "drifted": "wait.drifted"}
BODY_KEYS = {
    "inject_fault": {"fault"}, "recover": {"action", "grant"}, "attempt_unsafe": {"action", "grant"},
    "check_drift": set(), "restore_access": set(), "attempt_broad_recovery": set(),
    "wait_for": {"state", "timeout_s", "since"}, "run_referee": {"label"}, "deploy_revision": {"image"},
    "reset_twin": set(), "kill": set(),
}
AGENT_ACTIONS = ("recover", "attempt_unsafe", "check_drift")
LOCKED = ("inject_fault", "recover", "restore_access", "attempt_unsafe", "attempt_broad_recovery", "run_referee",
          "deploy_revision", "reset_twin")
REFUSED_BY = {"RequestDisallowedByPolicy": "Azure Policy", "AuthorizationFailed": "Azure RBAC"}
REFEREE_TIMEOUT_S = 190
DEPLOY_TIMEOUT_S = 180
RESET_STEP_TIMEOUT_S = 150
READY_TIMEOUT_S = 40


class Refused(Exception):
    """422: the request is outside the contract or the allowlist."""


class Forbidden(Exception):
    """403: this key may not call this action."""


class Busy(Exception):
    """409: another mutating action is running."""


class Stopped(Exception):
    """409: the kill switch ran while this action was in flight."""


class Unavailable(Exception):
    """503: a dependency (Azure, the Referee) did not answer, so there is no result."""


@dataclass
class Reply:
    action: str
    result: str
    details: dict = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class OpsService:
    def __init__(self, s: Settings, twin: Twin, referee: Referee, store, poll_s: float = 2.0):
        self.s, self.twin, self.referee, self.store, self.poll_s = s, twin, referee, store, poll_s
        self.base_image = s.base_image or getattr(twin, "base_image", "")
        self.image_repo = s.image_repo or self.base_image.split(":", 1)[0]
        self.lock = asyncio.Lock()
        self.generation: dict[str, int] = {}
        self.used_grants: set[str] = set()

    # ---- plumbing ----
    async def handle(self, action: str, body: dict, caller: str) -> Reply:
        if action not in BODY_KEYS:
            raise Refused(f"unknown action {action}")
        if caller == "agent" and action not in AGENT_ACTIONS:
            raise Forbidden(f"the agent key can't call {action}")
        drill = body.get("drill_id")
        if not isinstance(drill, str) or not DRILL.match(drill):
            raise Refused("drill_id must match ^drill-[A-Za-z0-9-]{1,64}$")
        extra = set(body) - BODY_KEYS[action] - {"drill_id"}
        if extra:
            raise Refused(f"unexpected key(s) for {action}: {', '.join(sorted(extra))}")
        if action == "kill":
            return await self.kill(drill)
        if action not in LOCKED:
            return await getattr(self, action)(drill, body, caller, self.generation.get(drill, 0))
        if self.lock.locked():
            raise Busy("another action is running on the twin")
        async with self.lock:
            return await getattr(self, action)(drill, body, caller, self.generation.get(drill, 0))

    def _live(self, drill: str, gen: int) -> None:
        if self.generation.get(drill, 0) != gen:
            raise Stopped("stopped by the kill switch")

    async def _event(self, drill: str, gen: int | None, action: str, result: str, details: dict) -> None:
        if gen is not None:
            self._live(drill, gen)
        event = {"ts": now_iso(), "drill_id": drill, "action": action, "result": result, "details": details}
        await asyncio.to_thread(self.store.append, drill, event)

    async def _events(self, drill: str) -> list[dict]:
        return await asyncio.to_thread(self.store.read, drill)

    async def _twin(self, call):
        try:
            return await call
        except TwinError as exc:
            raise Unavailable(str(exc)) from exc

    # ---- grants ----
    async def _authority(self, drill: str, gen: int, body: dict, caller: str, action: str, purpose: str) -> dict:
        token = body.get("grant")
        if caller != "agent" and token is None:
            return {"executed_by": "workflow"}
        try:
            g = grants.verify(self.s.grant_key, token, drill, action, purpose)
            if g.gid in self.used_grants or any(e.get("details", {}).get("grant_id") == g.gid
                                                for e in await self._events(drill)):
                raise grants.GrantRefused("grant already used")
        except grants.GrantRefused as exc:
            await self._event(drill, gen, "grant.refused", "refused", {"action": action, "reason": str(exc)})
            raise Refused(str(exc)) from exc
        self.used_grants.add(g.gid)
        return {"executed_by": "agent" if caller == "agent" else "workflow", "grant_id": g.gid,
                "approved_by": g.approved_by}

    # ---- faults and recovery ----
    async def inject_fault(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        fault = body.get("fault", "identity-rbac")
        if fault not in FAULTS:
            raise Refused(f"unknown fault {fault!r}")
        if fault not in ENABLED_FAULTS:
            raise Refused(f"fault {fault} is not enabled on this twin")
        if await self._twin(self.twin.access_entries()) > 0:
            self._live(drill, gen)
            await self._twin(self.twin.remove_access())
        details = {"fault": fault, "model": self.twin.model,
                   "entries_after": await self._twin(self.twin.access_entries())}
        await self._event(drill, gen, "fault.inject", "ok", details)
        return Reply("inject_fault", "ok", details)

    async def recover(self, drill: str, body: dict, caller: str, gen: int, alias: str = "") -> Reply:
        action = body.get("action")
        if action in BROAD:
            raise Refused(f"{action} is not a recover action")
        if action not in NARROW:
            raise Refused(f"unknown recovery action {action!r}")
        if action not in ENABLED_NARROW:
            raise Refused(f"{action} is not enabled on this twin")
        authority = await self._authority(drill, gen, body, caller, action, "recover")
        noop = await self._twin(self.twin.access_entries()) > 0
        if not noop:
            self._live(drill, gen)
            await self._twin(self.twin.add_access())
        details = {"fault": NARROW[action], "action": action, "model": self.twin.model, "noop": noop,
                   "entries_after": await self._twin(self.twin.access_entries()), **authority}
        await self._event(drill, gen, "fault.restore", "ok", details)
        return Reply(alias or "recover", "ok", details)

    async def restore_access(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        return await self.recover(drill, {"action": "restore_kv_secrets_user"}, caller, gen, alias="restore_access")

    async def attempt_unsafe(self, drill: str, body: dict, caller: str, gen: int, alias: str = "") -> Reply:
        action = body.get("action")
        if action in NARROW:
            raise Refused(f"{action} is not an attempt_unsafe action")
        if action not in BROAD:
            raise Refused(f"unknown action {action!r}")
        if action not in ENABLED_BROAD:
            raise Refused(f"{action} is not enabled on this twin")
        authority = await self._authority(drill, gen, body, caller, action, "policy_test")
        self._live(drill, gen)
        try:
            outcome = await self.twin.attempt_contributor()
        except TwinError as exc:
            await self._event(drill, gen, "recover.broad", "error", {"action": action, "reason": str(exc)[:300],
                                                                     **authority})
            raise Unavailable(str(exc)) from exc
        details = {"action": action, "fault": BROAD[action], **authority}
        if outcome.simulated:
            details["simulated"] = True
        if outcome.allowed:
            result = "UNEXPECTED_ALLOW"
            details["removed"] = outcome.removed
        else:
            result = "denied"
            details.update(code=outcome.code, refused_by=REFUSED_BY.get(outcome.code, "the platform"))
        await self._event(drill, gen, "recover.broad", result, details)
        return Reply(alias or "attempt_unsafe", result, details)

    async def attempt_broad_recovery(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        return await self.attempt_unsafe(drill, {"action": "grant_contributor_subscription"}, caller, gen,
                                         alias="attempt_broad_recovery")

    async def check_drift(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        identity = "ok" if await self._twin(self.twin.access_entries()) > 0 else "drift"
        details = {"identity": identity, "secret": "not_checked", "config": "not_checked",
                   "network": "not_checked"}
        result = "drift" if identity == "drift" else "ok"
        await self._event(drill, gen, "drift.check", result, details)
        return Reply("check_drift", result, details)

    # ---- waiting ----
    async def _met(self, state: str) -> tuple[bool, dict]:
        deps = await self.twin.dependencies()
        if state == "ok":
            return deps.get("keyvault") == "ok", deps
        if state == "forbidden":
            return deps.get("keyvault") == "forbidden", deps
        healthy = bool(deps) and all(v == "ok" for v in deps.values())
        if state == "drifted":
            return not healthy, deps
        return healthy and await self._twin(self.twin.access_entries()) > 0, deps

    async def wait_for(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        state, timeout = body.get("state"), body.get("timeout_s", 60)
        if state not in WAIT_STATES:
            raise Refused(f"state must be one of {', '.join(WAIT_STATES)}")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 180:
            raise Refused("timeout_s must be an integer from 1 to 180")
        try:
            since = parse_iso(body["since"]) if body.get("since") else time.time()
        except (TypeError, ValueError) as exc:
            raise Refused("since must be an ISO 8601 time") from exc
        deadline = time.monotonic() + timeout
        while True:
            met, deps = await self._met(state)
            if met:
                details = {"state": state, "seconds": max(0, round(time.time() - since)), "dependencies": deps}
                await self._event(drill, gen, WAIT_STATES[state], "ok", details)
                return Reply("wait_for", "ok", details)
            if time.monotonic() >= deadline:
                return Reply("wait_for", "timeout", {"state": state, "last": deps})
            await asyncio.sleep(self.poll_s)

    # ---- the Referee ----
    async def run_referee(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        label = body.get("label")
        if not isinstance(label, str) or not LABEL.match(label):
            raise Refused("label must match ^[a-z][a-z0-9-]{0,31}$")
        n = 1 + sum(1 for e in await self._events(drill) if str(e.get("action", "")).startswith("referee."))
        run_id, run_dir = f"{drill}-r{n}", f"r{n}-{label}"
        try:
            result = await self.referee.run(drill, run_id, label, run_dir, REFEREE_TIMEOUT_S)
        except RefereeError as exc:
            await self._event(drill, gen, f"referee.{label}", "INCONCLUSIVE", {"run_id": run_id,
                                                                            "reason": str(exc)[:300]})
            raise Unavailable(f"the Referee gave no verdict: {exc}") from exc
        verdict = result.get("verdict")
        if verdict not in ("PASS", "FAIL"):
            await self._event(drill, gen, f"referee.{label}", "INCONCLUSIVE", {"run_id": run_id,
                                                                            "reason": f"verdict {verdict!r}"})
            raise Unavailable(f"the Referee gave no verdict ({verdict!r})")
        result.update(label=label, run_id=run_id)
        await self._event(drill, gen, f"referee.{label}", verdict, result)
        return Reply("run_referee", verdict, result)

    # ---- deployments ----
    async def deploy_revision(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        image = body.get("image")
        match = re.fullmatch(re.escape(self.image_repo) + r":(sha-[0-9a-f]{40})", image or "") \
            if isinstance(image, str) else None
        if not match:
            raise Refused(f"image must be {self.image_repo}:sha-<40 hex>")
        digest = await self._twin(self.twin.resolve_digest(match.group(1)))
        if digest is None:
            raise Refused(f"{image} is not in the registry")
        self._live(drill, gen)
        info = await self._twin(self.twin.deploy_image(f"{self.image_repo}@{digest}", DEPLOY_TIMEOUT_S))
        details = {"image": image, "digest": digest, "revision": info["revision"], "seconds": info["seconds"]}
        await self._event(drill, gen, "deploy.revision", "ok", details)
        return Reply("deploy_revision", "ok", details)

    async def _ready(self) -> dict:
        deadline = time.monotonic() + READY_TIMEOUT_S
        while True:
            deps = await self.twin.dependencies()
            if deps and all(v == "ok" for v in deps.values()):
                return deps
            if time.monotonic() >= deadline:
                raise Unavailable(f"the twin did not report healthy dependencies: {deps}")
            await asyncio.sleep(self.poll_s)

    async def _reset(self, drill: str, gen: int, by: str) -> Reply:
        started = time.monotonic()
        restored = await self._twin(self.twin.access_entries()) == 0
        if restored:
            self._live(drill, gen)
            await self._twin(self.twin.add_access())
        repo, _, tag = self.base_image.partition(":")
        digest = await self._twin(self.twin.resolve_digest(tag))
        if digest is None:
            raise Unavailable(f"the base image {self.base_image} is not in the registry")
        base_ref = f"{repo}@{digest}"
        current = await self._twin(self.twin.current_image())
        self._live(drill, gen)
        if current in (self.base_image, base_ref):
            info, step = await self._twin(self.twin.restart(RESET_STEP_TIMEOUT_S)), "restarted"
        else:
            info, step = await self._twin(self.twin.deploy_image(base_ref, RESET_STEP_TIMEOUT_S)), "redeployed"
        try:
            rows = await self.twin.delete_drill_rows()
        except Exception as exc:                       # cleanup is housekeeping; never block a reset on it
            rows = f"not deleted: {type(exc).__name__}"
        deps = await self._ready()
        details = {"by": by, "access_restored": restored, step: info["revision"], "image": self.base_image,
                   "rows_deleted": rows, "dependencies": deps, "seconds": round(time.monotonic() - started)}
        await self._event(drill, gen, "reset", "ok", details)
        return Reply("kill" if by == "kill" else "reset_twin", "ok", details)

    async def reset_twin(self, drill: str, body: dict, caller: str, gen: int) -> Reply:
        return await self._reset(drill, gen, "workflow")

    async def kill(self, drill: str) -> Reply:
        self.generation[drill] = self.generation.get(drill, 0) + 1
        return await self._reset(drill, self.generation[drill], "kill")
