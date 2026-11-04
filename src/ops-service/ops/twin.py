"""The twin as the Ops Service sees it: one interface, an Azure implementation and an in-memory fake.

Every resource comes from Settings (resolved at startup and checked against the twin allowlist); no method takes a
resource ID from a caller.
"""
import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from . import acr
from .arm import Arm, ArmError, TokenCache
from .settings import Settings

KV_SECRETS_USER = "4633458b-17de-408a-b874-0445c86b69e6"
CONTRIBUTOR = "b24988ac-6180-42a0-ab88-20f7382dd24c"
REFUSAL_CODES = ("RequestDisallowedByPolicy", "AuthorizationFailed")
RUNNING = ("Running", "RunningAtMaxScale")


class TwinError(RuntimeError):
    """An Azure call the action needed did not succeed; the drill can't continue on this step."""


@dataclass(frozen=True)
class BroadOutcome:
    allowed: bool
    code: str = ""            # RequestDisallowedByPolicy, AuthorizationFailed, or "" when allowed
    removed: bool | None = None
    simulated: bool = False
    message: str = ""


class Twin(Protocol):
    model: str
    simulated: bool

    async def access_entries(self) -> int: ...
    async def remove_access(self) -> None: ...
    async def add_access(self) -> None: ...
    async def attempt_contributor(self) -> BroadOutcome: ...
    async def dependencies(self) -> dict: ...
    async def current_image(self) -> str: ...
    async def deploy_image(self, ref: str, timeout_s: float) -> dict: ...
    async def restart(self, timeout_s: float) -> dict: ...
    async def delete_drill_rows(self) -> int | None: ...
    async def resolve_digest(self, tag: str) -> str | None: ...


async def _poll(check, timeout_s: float, every_s: float, what: str):
    deadline = time.monotonic() + timeout_s
    while True:
        result = await check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise TwinError(f"timed out after {int(timeout_s)} s waiting for {what}")
        await asyncio.sleep(every_s)


class AzureTwin:
    simulated = False

    def __init__(self, s: Settings, arm: Arm, tokens: TokenCache, health: httpx.AsyncClient | None = None,
                 registry_transport: httpx.AsyncBaseTransport | None = None, poll_s: float = 3.0):
        self.s, self.arm, self.tokens = s, arm, tokens
        self.model = s.kv_model
        self.health = health or httpx.AsyncClient(timeout=8)
        self.registry_transport = registry_transport
        self.poll_s = poll_s

    # ---- Key Vault access for the order app's identity ----
    @property
    def _assignment_path(self) -> str:
        return f"{self.s.keyvault_id}/providers/Microsoft.Authorization/roleAssignments/{self.s.app_assignment_name}"

    async def _policy_entries(self) -> list[dict]:
        vault = await self.arm.get(self.s.keyvault_id, "keyVault")
        entries = vault.get("properties", {}).get("accessPolicies", []) or []
        pid = self.s.app_principal_id.lower()
        return [e for e in entries if str(e.get("objectId", "")).lower() == pid]

    async def access_entries(self) -> int:
        if self.model == "accessPolicy":
            return sum(1 for e in await self._policy_entries()
                       if "get" in [p.lower() for p in e.get("permissions", {}).get("secrets", [])])
        data = await self.arm.get(f"{self.s.keyvault_id}/providers/Microsoft.Authorization/roleAssignments",
                                  "roleAssignments", query={"$filter": f"principalId eq '{self.s.app_principal_id}'"})
        vault = self.s.keyvault_id.lower()
        return sum(1 for a in data.get("value", [])
                   if a.get("properties", {}).get("scope", "").lower() == vault
                   and a.get("properties", {}).get("roleDefinitionId", "").lower().endswith(KV_SECRETS_USER))

    async def remove_access(self) -> None:
        if self.model == "accessPolicy":
            for entry in await self._policy_entries():
                body = {"properties": {"accessPolicies": [{"tenantId": self.s.tenant_id,
                                                           "objectId": self.s.app_principal_id,
                                                           "permissions": entry.get("permissions", {})}]}}
                await self.arm.request("PUT", f"{self.s.keyvault_id}/accessPolicies/remove", "keyVault", body)
            return
        await self.arm.request("DELETE", self._assignment_path, "roleAssignments")

    async def add_access(self) -> None:
        if self.model == "accessPolicy":
            body = {"properties": {"accessPolicies": [{"tenantId": self.s.tenant_id,
                                                       "objectId": self.s.app_principal_id,
                                                       "permissions": {"secrets": ["get", "list"]}}]}}
            await self.arm.request("PUT", f"{self.s.keyvault_id}/accessPolicies/add", "keyVault", body)
            return
        body = {"properties": {
            "roleDefinitionId": f"/subscriptions/{self.s.subscription_id}/providers/Microsoft.Authorization"
                                f"/roleDefinitions/{KV_SECRETS_USER}",
            "principalId": self.s.app_principal_id, "principalType": "ServicePrincipal"}}
        try:
            await self.arm.request("PUT", self._assignment_path, "roleAssignments", body)
        except ArmError as exc:
            if exc.code != "RoleAssignmentExists":
                raise

    # ---- the broad option: Contributor on the subscription for the app identity ----
    async def attempt_contributor(self) -> BroadOutcome:
        path = (f"/subscriptions/{self.s.subscription_id}/providers/Microsoft.Authorization/roleAssignments/"
                f"{uuid.uuid4()}")
        body = {"properties": {
            "roleDefinitionId": f"/subscriptions/{self.s.subscription_id}/providers/Microsoft.Authorization"
                                f"/roleDefinitions/{CONTRIBUTOR}",
            "principalId": self.s.app_principal_id, "principalType": "ServicePrincipal"}}
        try:
            await self.arm.request("PUT", path, "roleAssignments", body, ok=(200, 201))
        except ArmError as exc:
            if exc.code in REFUSAL_CODES:
                return BroadOutcome(allowed=False, code=exc.code, message=exc.message[:300])
            raise TwinError(f"broad attempt failed without a refusal code: {exc}") from exc
        try:
            await self.arm.request("DELETE", path, "roleAssignments")
            removed = True
        except ArmError:
            removed = False
        return BroadOutcome(allowed=True, removed=removed)

    # ---- the order app ----
    async def dependencies(self) -> dict:
        try:
            r = await self.health.get(f"{self.s.order_app_url}/health/dependencies")
            data = r.json()
            if isinstance(data, dict) and "keyvault" in data:
                return {k: str(v) for k, v in data.items() if k in ("keyvault", "sql")}
        except (httpx.HTTPError, ValueError):
            pass
        return {"keyvault": "unreachable", "sql": "unreachable"}

    async def _app(self) -> dict:
        return await self.arm.get(self.s.order_app_id, "containerApps")

    async def current_image(self) -> str:
        app = await self._app()
        return app["properties"]["template"]["containers"][0]["image"]

    async def _replicas(self, revision: str) -> list[str]:
        try:
            data = await self.arm.get(f"{self.s.order_app_id}/revisions/{revision}/replicas", "containerApps")
        except ArmError as exc:
            if exc.status == 404:
                return []
            raise
        return sorted(r.get("name", "") for r in data.get("value", []))

    async def _revision_running(self, revision: str) -> bool:
        rev = await self.arm.get(f"{self.s.order_app_id}/revisions/{revision}", "containerApps")
        p = rev.get("properties", {})
        return p.get("runningState") in RUNNING and p.get("healthState") != "Unhealthy"

    async def deploy_image(self, ref: str, timeout_s: float) -> dict:
        started = time.monotonic()
        app = await self._app()
        props = app["properties"]
        old = props.get("latestRevisionName", "")
        template = props["template"]
        if template["containers"][0]["image"] == ref:
            return {"revision": old, "changed": False, "seconds": 0}
        template["containers"][0]["image"] = ref
        await self.arm.request("PATCH", self.s.order_app_id, "containerApps", {"properties": {"template": template}})

        async def new_revision_ready():
            p = (await self._app())["properties"]
            if p.get("provisioningState") == "Failed":
                raise TwinError("the new revision failed to provision")
            latest = p.get("latestRevisionName", "")
            if latest and latest != old and p.get("latestReadyRevisionName") == latest \
                    and await self._revision_running(latest):
                return latest
            return None

        revision = await _poll(new_revision_ready, timeout_s, self.poll_s, "the new revision to be ready")
        remaining = max(10.0, timeout_s - (time.monotonic() - started))
        await _poll(lambda: self._gone(old), remaining, self.poll_s, "the previous revision's replicas to stop")
        return {"revision": revision, "changed": True, "seconds": round(time.monotonic() - started)}

    async def _gone(self, revision: str) -> bool:
        return not await self._replicas(revision)

    async def restart(self, timeout_s: float) -> dict:
        started = time.monotonic()
        props = (await self._app())["properties"]
        revision = props.get("latestReadyRevisionName") or props.get("latestRevisionName")
        old = set(await self._replicas(revision))
        await self.arm.request("POST", f"{self.s.order_app_id}/revisions/{revision}/restart", "containerApps")

        async def replaced():
            now = set(await self._replicas(revision))
            return bool(now) and not (now & old)

        await _poll(replaced, timeout_s, self.poll_s, "the restarted replica")
        return {"revision": revision, "seconds": round(time.monotonic() - started)}

    async def delete_drill_rows(self) -> int | None:
        if not (self.s.cleanup_sql_password and self.s.sql_server_fqdn and self.s.sql_db_name):
            return None
        return await asyncio.to_thread(_delete_rows, self.s)

    async def resolve_digest(self, tag: str) -> str | None:
        repo = self.s.image_repo.split("/", 1)[1]
        try:
            return await acr.resolve_digest(self.tokens, self.s.registry_server, repo, tag, self.registry_transport)
        except acr.RegistryError as exc:
            raise TwinError(str(exc)) from exc


def _delete_rows(s: Settings) -> int:
    import pyodbc  # only in the image; tests never reach this
    conn = pyodbc.connect(
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{s.sql_server_fqdn},1433;Database={s.sql_db_name};"
        f"Uid=ops_cleanup;Pwd={s.cleanup_sql_password};Encrypt=yes;TrustServerCertificate=no;", timeout=15)
    try:
        cur = conn.cursor()
        cur.execute("DELETE pa FROM dbo.payment_authorizations pa JOIN dbo.orders o ON o.order_id = pa.order_id "
                    "WHERE o.drill_id LIKE 'drill-%'")
        auths = cur.rowcount
        cur.execute("DELETE FROM dbo.orders WHERE drill_id LIKE 'drill-%'")
        orders = cur.rowcount
        conn.commit()
        return max(auths, 0) + max(orders, 0)
    finally:
        conn.close()


class FakeTwin:
    """In-memory twin for laptop runs and tests: access entries, dependencies, image, revisions, restarts and
    orders, as the Ops Service observes them on the real twin."""
    model = "fake"
    simulated = True

    def __init__(self, base_image: str = "acrlffake01.azurecr.io/order-service:sha-" + "0" * 40):
        self.base_image = base_image
        repo, _, tag = base_image.partition(":")
        self.base_refs = {base_image, f"{repo}@{_fake_digest(tag)}"}
        self.entries = 1
        self.stuck = False
        self.image = base_image
        self.revision = 1
        self.restarts = 0
        self.broad_code = "RequestDisallowedByPolicy"
        self.missing_tags: set[str] = set()
        self.calls: list[str] = []

    async def access_entries(self) -> int:
        return self.entries

    async def remove_access(self) -> None:
        self.calls.append("remove_access")
        self.entries = 0

    async def add_access(self) -> None:
        self.calls.append("add_access")
        self.entries = 1

    async def attempt_contributor(self) -> BroadOutcome:
        self.calls.append("attempt_contributor")
        if not self.broad_code:
            return BroadOutcome(allowed=True, removed=True, simulated=True)
        return BroadOutcome(allowed=False, code=self.broad_code, simulated=True)

    async def dependencies(self) -> dict:
        return {"keyvault": "ok" if self.entries else "forbidden", "sql": "ok"}

    async def current_image(self) -> str:
        return self.image

    async def deploy_image(self, ref: str, timeout_s: float) -> dict:
        self.calls.append(f"deploy:{ref}")
        if ref == self.image:
            return {"revision": f"ca-order--{self.revision}", "changed": False, "seconds": 0}
        self.image, self.stuck = ref, False
        self.revision += 1
        return {"revision": f"ca-order--{self.revision}", "changed": True, "seconds": 1}

    async def restart(self, timeout_s: float) -> dict:
        self.calls.append("restart")
        self.stuck, self.restarts = False, self.restarts + 1
        return {"revision": f"ca-order--{self.revision}", "seconds": 1}

    async def delete_drill_rows(self) -> int | None:
        return 0

    async def resolve_digest(self, tag: str) -> str | None:
        if tag in self.missing_tags:
            return None
        return _fake_digest(tag)

    def place_order(self) -> bool:
        """What one customer order does on the fake twin."""
        if self.entries == 0:
            self.stuck = self.stuck or self.image in self.base_refs
            return False
        return not self.stuck


def _fake_digest(tag: str) -> str:
    return "sha256:" + hashlib.sha256(tag.encode()).hexdigest()
