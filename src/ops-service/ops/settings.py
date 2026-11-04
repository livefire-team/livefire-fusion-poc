"""Configuration from the environment, checked once at startup.

The service never takes a target from a caller: every resource it touches comes from here, and startup fails unless
each one sits inside this lab's twin resource group.
"""
import os
import re
from dataclasses import dataclass, field

GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
IMAGE_REPO = re.compile(r"^[a-z0-9]{5,50}\.azurecr\.io/order-service$")
SHA_TAG = re.compile(r"^sha-[0-9a-f]{40}$")
MIN_KEY_LENGTH = 32


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    backend: str                      # azure | fake
    runner_key: str
    agent_key: str
    grant_key: str
    event_source: str
    kv_model: str = "rbac"            # rbac | accessPolicy
    subscription_id: str = ""
    tenant_id: str = ""
    twin_rg: str = ""
    control_rg: str = ""
    order_app_name: str = ""
    order_app_url: str = ""
    keyvault_id: str = ""
    app_principal_id: str = ""
    app_assignment_name: str = ""
    image_repo: str = ""
    base_image: str = ""
    referee_job_name: str = ""
    client_id: str = ""
    sql_server_fqdn: str = ""
    sql_db_name: str = ""
    cleanup_sql_password: str = field(default="", repr=False)
    auth: str = "managed-identity"    # managed-identity | cli (a laptop run against the lab)

    @property
    def keyvault_name(self) -> str:
        return self.keyvault_id.rstrip("/").rsplit("/", 1)[-1]

    @property
    def order_app_id(self) -> str:
        return (f"/subscriptions/{self.subscription_id}/resourceGroups/{self.twin_rg}"
                f"/providers/Microsoft.App/containerApps/{self.order_app_name}")

    @property
    def referee_job_id(self) -> str:
        return (f"/subscriptions/{self.subscription_id}/resourceGroups/{self.control_rg}"
                f"/providers/Microsoft.App/jobs/{self.referee_job_name}")

    @property
    def registry_server(self) -> str:
        return self.image_repo.split("/", 1)[0]


def _keys_ok(*keys: str) -> None:
    if any(len(k) < MIN_KEY_LENGTH for k in keys):
        raise SettingsError(f"OPS_RUNNER_KEY, OPS_AGENT_KEY and RECOVERY_GRANT_KEY must each be at least "
                            f"{MIN_KEY_LENGTH} characters")
    if len(set(keys)) != len(keys):
        raise SettingsError("OPS_RUNNER_KEY, OPS_AGENT_KEY and RECOVERY_GRANT_KEY must all differ")


def validate(s: Settings) -> Settings:
    _keys_ok(s.runner_key, s.agent_key, s.grant_key)
    if s.backend == "fake":
        return s
    if s.backend != "azure":
        raise SettingsError("TWIN_BACKEND must be azure or fake")
    problems = []
    if not s.twin_rg.startswith("rg-lf-twin-"):
        problems.append(f"TWIN_RG {s.twin_rg!r} is not a twin resource group")
    if not s.control_rg.startswith("rg-lf-control-"):
        problems.append(f"CONTROL_RG {s.control_rg!r} is not a control resource group")
    prefix = f"/subscriptions/{s.subscription_id}/resourceGroups/{s.twin_rg}/providers/Microsoft.KeyVault/vaults/"
    if not GUID.match(s.subscription_id) or not s.keyvault_id.lower().startswith(prefix.lower()):
        problems.append("KEYVAULT_ID must be a vault inside TWIN_RG, in AZURE_SUBSCRIPTION_ID")
    if not GUID.match(s.app_principal_id):
        problems.append("APP_IDENTITY_PRINCIPAL_ID must be a GUID")
    if s.kv_model not in ("rbac", "accessPolicy"):
        problems.append("KV_PERMISSION_MODEL must be rbac or accessPolicy")
    if s.kv_model == "rbac" and not GUID.match(s.app_assignment_name):
        problems.append("APP_ACCESS_ASSIGNMENT_NAME must be a GUID on the rbac model")
    if s.kv_model == "accessPolicy" and not GUID.match(s.tenant_id):
        problems.append("AZURE_TENANT_ID must be a GUID on the accessPolicy model")
    if not s.order_app_name or not s.order_app_url.startswith("https://"):
        problems.append("ORDER_APP_NAME and an https ORDER_APP_URL are required")
    if not IMAGE_REPO.match(s.image_repo):
        problems.append("IMAGE_REPO must be <registry>.azurecr.io/order-service")
    base_repo, _, base_tag = s.base_image.partition(":")
    if base_repo != s.image_repo or not SHA_TAG.match(base_tag):
        problems.append("BASE_IMAGE must be <IMAGE_REPO>:sha-<40 hex>")
    if not s.referee_job_name:
        problems.append("REFEREE_JOB_NAME is required")
    if not s.event_source.startswith(("blob:", "dir:")):
        problems.append("EVENT_SOURCE must be blob:<account-url>/<container> or dir:<path>")
    if s.auth not in ("managed-identity", "cli"):
        problems.append("OPS_AUTH must be managed-identity or cli")
    if s.auth == "managed-identity" and not GUID.match(s.client_id):
        problems.append("AZURE_CLIENT_ID (the Ops identity's client ID) is required")
    if problems:
        raise SettingsError("; ".join(problems))
    return s


def from_env(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    return validate(Settings(
        backend=e.get("TWIN_BACKEND", "azure"),
        runner_key=e.get("OPS_RUNNER_KEY", ""),
        agent_key=e.get("OPS_AGENT_KEY", ""),
        grant_key=e.get("RECOVERY_GRANT_KEY", ""),
        event_source=e.get("EVENT_SOURCE", "dir:./evidence"),
        kv_model=e.get("KV_PERMISSION_MODEL", "rbac"),
        subscription_id=e.get("AZURE_SUBSCRIPTION_ID", ""),
        tenant_id=e.get("AZURE_TENANT_ID", ""),
        twin_rg=e.get("TWIN_RG", ""),
        control_rg=e.get("CONTROL_RG", ""),
        order_app_name=e.get("ORDER_APP_NAME", ""),
        order_app_url=e.get("ORDER_APP_URL", "").rstrip("/"),
        keyvault_id=e.get("KEYVAULT_ID", ""),
        app_principal_id=e.get("APP_IDENTITY_PRINCIPAL_ID", ""),
        app_assignment_name=e.get("APP_ACCESS_ASSIGNMENT_NAME", ""),
        image_repo=e.get("IMAGE_REPO", ""),
        base_image=e.get("BASE_IMAGE", ""),
        referee_job_name=e.get("REFEREE_JOB_NAME", ""),
        client_id=e.get("AZURE_CLIENT_ID", ""),
        sql_server_fqdn=e.get("SQL_SERVER_FQDN", ""),
        sql_db_name=e.get("SQL_DB_NAME", ""),
        cleanup_sql_password=e.get("OPS_CLEANUP_SQL_PASSWORD", ""),
        auth=e.get("OPS_AUTH", "managed-identity"),
    ))
