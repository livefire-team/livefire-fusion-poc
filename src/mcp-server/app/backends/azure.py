"""Real evidence: Log Analytics (fixed queries), Azure Resource Manager, Key Vault metadata and Azure AI Search."""
import logging
import os
import re
from datetime import timedelta

from azure.identity import ManagedIdentityCredential

KV_SECRETS_USER = "4633458b-17de-408a-b874-0445c86b69e6"
KNOWN_ROLES = {KV_SECRETS_USER: "Key Vault Secrets User",
               "b86a8fe4-44ce-4948-aee5-eccb2c155cd7": "Key Vault Secrets Officer",
               "00482a5a-887f-4fb3-b363-3b7fe8e74483": "Key Vault Administrator"}

# Fixed query templates. drill_id is validated against ^drill-[A-Za-z0-9-]{1,64}$ and minutes is
# an integer from 1 to 120 before either reaches a template, so nothing else can be injected.
KQL = {
    "exceptions": """AppExceptions
| where TimeGenerated > ago({minutes}m)
| extend run_id = tostring(Properties["drill_id"])
| where run_id startswith "{drill_id}"
| summarize events = count(), last_seen = max(TimeGenerated) by ExceptionType, OuterMessage
| order by last_seen desc
| take 20""",
    "requests": """AppRequests
| where TimeGenerated > ago({minutes}m)
| extend run_id = tostring(Properties["drill_id"])
| where run_id startswith "{drill_id}"
| summarize events = count(), failures = countif(Success == false) by Name, ResultCode
| order by events desc
| take 20""",
    "dependencies": """AppDependencies
| where TimeGenerated > ago({minutes}m)
| summarize events = count(), failures = countif(Success == false), last_seen = max(TimeGenerated)
    by Target, DependencyType = Type, ResultCode
| order by failures desc, events desc
| take 20""",
    # v2.0: failed orders by SQL Server error number and SQLSTATE (the order service logs both on "order failed")
    "sql_errors": """AppExceptions
| where TimeGenerated > ago({minutes}m)
| extend run_id = tostring(Properties["drill_id"]), sql_error = tostring(Properties["sql_error"]),
    sqlstate = tostring(Properties["sqlstate"])
| where run_id startswith "{drill_id}" and (isnotempty(sql_error) or isnotempty(sqlstate))
| summarize events = count(), first_seen = min(TimeGenerated), last_seen = max(TimeGenerated)
    by sql_error, sqlstate, ExceptionType
| order by events desc
| take 20""",
    "metrics": """AppMetrics
| where TimeGenerated > ago({minutes}m)
| where Name in ("orders_completed", "orders_failed")
| summarize total = sum(Sum) by Name, minute = bin(TimeGenerated, 1m)
| order by minute asc
| take 120""",
}


# Settings whose names suggest a secret, and every secretRef, are dropped from configuration evidence.
SECRET_LIKE = re.compile(r"(?i)(password|pwd|secret_value|token|key$|_key|connection_string|connstr|credential)")


def safe_env(env) -> dict:
    """Non-secret settings only: no secret references, and nothing whose name looks like a secret."""
    out = {}
    for v in env or []:
        if getattr(v, "secret_ref", None) or SECRET_LIKE.search(v.name or ""):
            continue
        out[v.name] = v.value
    return out


def _iso(t) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t else None


def _credential():
    return ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))


log = logging.getLogger("mcp.azure")


class AzureEvidence:
    def __init__(self, repo):
        from azure.mgmt.authorization import AuthorizationManagementClient
        from azure.mgmt.keyvault import KeyVaultManagementClient
        from azure.monitor.query import LogsQueryClient
        from azure.search.documents import SearchClient

        cred = _credential()
        self.repo = repo                                   # GitHub backend with the read-only token
        self.workspace_id = os.environ["LOG_ANALYTICS_WORKSPACE_ID"]
        self.vault_id = os.environ["TWIN_KEYVAULT_ID"]
        self.principal_id = os.environ["APP_IDENTITY_PRINCIPAL_ID"]
        sub = self.vault_id.split("/")[2]
        self.logs = LogsQueryClient(cred)
        self.auth = AuthorizationManagementClient(cred, sub)
        self.vaults = KeyVaultManagementClient(cred, sub)
        self.search = SearchClient(os.environ["SEARCH_ENDPOINT"], os.environ.get("SEARCH_INDEX", "incidents"), cred)
        # v2.0: secret metadata, app configuration and network rules, created on first use
        self.cred, self.sub, self.twin_rg = cred, sub, self.vault_id.split("/")[4]
        self.vault_name = self.vault_id.split("/")[8]
        self.secret_name = os.environ.get("TWIN_SECRET_NAME", "db-password")
        self.order_app = os.environ.get("ORDER_APP_NAME", "")
        self.sql_server = os.environ.get("TWIN_SQL_SERVER_NAME", "")
        self.desired = {"SQL_DB_NAME": os.environ.get("DESIRED_SQL_DB_NAME", "orders")}
        self._secrets = self._aca = self._sql = None

    def telemetry(self, drill_id, signal, minutes):
        query = KQL[signal].format(drill_id=drill_id, minutes=int(minutes))
        result = self.logs.query_workspace(self.workspace_id, query, timespan=timedelta(minutes=int(minutes)))
        tables = getattr(result, "tables", None) or getattr(result, "partial_data", None) or []
        rows = []
        for table in tables:
            for row in table.rows:
                rows.append({col: str(val) for col, val in zip(table.columns, row)})
        return rows

    def identity_snapshot(self, drill_id=None):
        parts = self.vault_id.split("/")
        rg, name = parts[4], parts[8]
        assignments = [
            {"role": KNOWN_ROLES.get(a.role_definition_id.rsplit("/", 1)[-1], "other"), "scope": a.scope}
            for a in self.auth.role_assignments.list_for_scope(self.vault_id, filter=f"principalId eq '{self.principal_id}'")
        ]
        vault = self.vaults.vaults.get(rg, name)
        rbac = bool(vault.properties.enable_rbac_authorization)
        policy = next((p for p in (vault.properties.access_policies or []) if p.object_id == self.principal_id), None)
        return {
            "vault": name, "principal_id": self.principal_id,
            "permission_model": "rbac" if rbac else "accessPolicy",
            "role_assignments": assignments,
            "has_secrets_user_role": any(a["role"] == "Key Vault Secrets User" for a in assignments),
            "access_policy_secret_permissions": list(policy.permissions.secrets or []) if policy else [],
        }

    # ---------------------------------------------------------------- v2.0 evidence

    def _need(self, value, name):
        if not value:
            raise RuntimeError(f"{name} is not configured for the MCP server")
        return value

    def secret_metadata(self, drill_id=None):
        """list_properties_of_secret_versions needs Key Vault Reader (secrets/readMetadata); values are never read."""
        if self._secrets is None:
            from azure.keyvault.secrets import SecretClient
            self._secrets = SecretClient(f"https://{self.vault_name}.vault.azure.net/", self.cred)
        versions = sorted(self._secrets.list_properties_of_secret_versions(self.secret_name),
                          key=lambda v: v.created_on or 0, reverse=True)
        current = next((v.version for v in versions if v.enabled), None)   # what an unversioned read returns
        return {"vault": self.vault_name, "secret": self.secret_name, "versions": [
            {"version": (v.version or "")[:6], "created": _iso(v.created_on), "updated": _iso(v.updated_on),
             "enabled": bool(v.enabled), "current": v.version == current} for v in versions[:10]]}

    def app_configuration(self, drill_id=None):
        if self._aca is None:
            from azure.mgmt.appcontainers import ContainerAppsAPIClient
            self._aca = ContainerAppsAPIClient(self.cred, self.sub)
        name = self._need(self.order_app, "ORDER_APP_NAME")
        app = self._aca.container_apps.get(self.twin_rg, name)
        revisions = sorted(self._aca.container_apps_revisions.list_revisions(self.twin_rg, name),
                           key=lambda r: r.properties.created_time or 0, reverse=True)[:5]
        current = app.properties.latest_revision_name
        shown = []
        for r in revisions:
            container = r.properties.template.containers[0]
            shown.append({"name": r.name, "created": _iso(r.properties.created_time), "active": bool(r.properties.active),
                          "image": container.image, "env": safe_env(container.env)})
        env = safe_env(app.properties.template.containers[0].env)
        diff = [{"name": k, "desired": v, "current": env.get(k)} for k, v in self.desired.items() if env.get(k) != v]
        return {"app": name, "desired": self.desired, "current_revision": current, "revisions": shown,
                "differences_from_desired": diff}

    def network_rules(self, drill_id=None):
        if self._sql is None:
            from azure.mgmt.sql import SqlManagementClient
            self._sql = SqlManagementClient(self.cred, self.sub)
        server = self._need(self.sql_server, "TWIN_SQL_SERVER_NAME")
        props = self._sql.servers.get(self.twin_rg, server)
        rules = [{"name": r.name, "start_ip": r.start_ip_address, "end_ip": r.end_ip_address}
                 for r in self._sql.firewall_rules.list_by_server(self.twin_rg, server)]
        return {"server": server, "public_network_access": str(props.public_network_access or "unknown"),
                "firewall_rules": rules,
                # B104 is a false positive: this compares firewall rule addresses (0.0.0.0 means Azure services)
                "allows_azure_services": any(r["start_ip"] == r["end_ip"] == "0.0.0.0" for r in rules)}  # nosec B104

    def search_incidents(self, query, top, from_date=None, to_date=None):
        """Hybrid retrieval when the index has vectors (SEARCH_VECTOR_FIELD): the keyword query and a vector query,
        which the index's vectorizer embeds, fused by AI Search. Falls back to keyword-only, and says so.
        from_date and to_date (YYYY-MM-DD, validated by the tool) bound occurred_at."""
        select = ["id", "title", "occurred_at", "summary", "resolution", "source"]
        where = ["service eq 'order-service'"]
        if from_date:
            where.append(f"occurred_at ge {from_date}T00:00:00Z")
        if to_date:
            where.append(f"occurred_at le {to_date}T23:59:59Z")
        common = {"search_text": query, "filter": " and ".join(where), "top": top, "select": select}
        field = os.environ.get("SEARCH_VECTOR_FIELD", "")
        mode = "keyword"
        results = None
        if field:
            from azure.search.documents.models import VectorizableTextQuery
            try:
                results = list(self.search.search(**common, vector_queries=[
                    VectorizableTextQuery(text=query, k_nearest_neighbors=top, fields=field)]))
                mode = "hybrid"
            except Exception as exc:                        # vectorizer unavailable: degrade, never fail the tool
                log.warning("hybrid search failed, using keyword only: %s", type(exc).__name__)
                mode = "keyword (hybrid unavailable)"
        if results is None:
            results = list(self.search.search(**common))
        return [{**{k: str(v) for k, v in doc.items() if not k.startswith("@")}, "retrieval": mode,
                 "score": round(float(doc.get("@search.score") or 0), 4)} for doc in results]

    def read_file(self, path, ref):
        return self.repo.read_file(path, ref)

    def commit_history(self, path, limit, ref):
        return self.repo.commit_history(path, limit, ref)
