"""LiveFire MCP server: /planner/mcp (read-only evidence), /engineer/mcp (branch-only repo) and, v2.1,
/recovery/mcp (grant-gated recovery through the Ops Service), one app."""
import contextlib
import hmac
import json
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor()

from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Mount, Route  # noqa: E402

import engineer_tools  # noqa: E402
import planner_tools  # noqa: E402
import recovery_tools  # noqa: E402
from guard import DRILL_ID_PATTERN, record, set_callers  # noqa: E402
from livefire_events import store_from_env  # noqa: E402

log = logging.getLogger("mcp")
logging.basicConfig(level=logging.INFO)

AUTH_MODE = os.environ.get("AUTH_MODE", "key")               # key (the fallback) | entra (the target)
if AUTH_MODE == "key":
    KEYS = {"planner": os.environ.get("PLANNER_KEY", ""), "engineer": os.environ.get("ENGINEER_KEY", ""),
            "recovery": os.environ.get("RECOVERY_KEY", "")}                 # v2.1
    if any(len(k) < 32 for k in KEYS.values()) or len(set(KEYS.values())) != len(KEYS):
        raise RuntimeError("PLANNER_KEY, ENGINEER_KEY and RECOVERY_KEY must be different and at least 32 characters")
elif AUTH_MODE == "entra":
    from entra_auth import EntraVerifier
    VERIFIER = EntraVerifier.from_env()
else:
    raise RuntimeError("AUTH_MODE must be key or entra")

# The audit trail's caller: each endpoint accepts exactly one credential, the agent identity in Entra mode.
if AUTH_MODE == "entra":
    set_callers({r: f"entra:{os.environ.get(f'{r.upper()}_AGENT_OBJECT_ID', '') or 'unset'}"
                 for r in ("planner", "engineer", "recovery")})
else:
    set_callers({r: f"key:{r}" for r in ("planner", "engineer", "recovery")})


def holder_of(presented: str) -> str | None:
    """Which endpoint this credential belongs to: 'planner', 'engineer', 'recovery', or None."""
    if not presented:
        return None
    if AUTH_MODE == "key":
        return next((r for r, k in KEYS.items() if hmac.compare_digest(presented, k)), None)
    return VERIFIER.caller_role(presented)

BACKEND = os.environ.get("BACKEND", "fixtures")              # fixtures | azure
REPO_REF = os.environ.get("REPO_REF", "main")                 # the drill's pinned commit or branch
store = store_from_env()


def build_backends():
    if BACKEND == "fixtures":
        from backends.fixtures import FixtureEvidence, FixtureRepo
        evidence = FixtureEvidence(os.environ.get("FIXTURES", str(Path(__file__).parent.parent / "fixtures" / "planner.json")),
                                   store)
        return evidence, FixtureRepo(evidence.data["repo"])
    from backends.azure import AzureEvidence
    from backends.github import AppTokens, GitHub
    repo = os.environ["GITHUB_REPO"]                           # owner/name

    def tokens(role, permissions):
        if os.environ.get(f"GITHUB_{role}_APP_ID"):
            return AppTokens(os.environ[f"GITHUB_{role}_APP_ID"], os.environ[f"GITHUB_{role}_INSTALLATION_ID"],
                             os.environ[f"GITHUB_{role}_PRIVATE_KEY"], repo.split("/")[1], permissions)
        token = os.environ[f"GITHUB_{role}_TOKEN"]
        return lambda: token

    reader = GitHub(repo, tokens("PLANNER", {"contents": "read", "metadata": "read"}))
    writer = GitHub(repo, tokens("ENGINEER", {"contents": "write", "actions": "read", "metadata": "read"}))
    return AzureEvidence(reader), writer


WRITE_PATHS = engineer_tools.write_paths()                 # which files a candidate may change
if not WRITE_PATHS:
    log.warning("ENGINEER_WRITE_PATHS is not set: the Engineer can't change any file")
evidence, repo = build_backends()
planner = planner_tools.build(evidence, store, REPO_REF)
engineer = engineer_tools.build(repo, store, REPO_REF, WRITE_PATHS)
recovery = recovery_tools.build(recovery_tools.ops_from_env(), store)   # v2.1; unconfigured without OPS_URL

# Only requests addressed to our own host name get through, and no browser origin is accepted.
security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*").split(",") if h.strip()],
    allowed_origins=[],
)
planner_app = planner.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
engineer_app = engineer.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
recovery_app = recovery.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)


class KeyGuard:
    """Each endpoint accepts only its own caller (key or Entra agent identity). A caller valid for the other
    endpoint is refused with 403 and recorded as a deny event (T-03); anything else gets 401."""

    def __init__(self, app, holder=None):
        self.app, self.holder = app, holder or holder_of

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        role = next((r for r in ("planner", "engineer", "recovery") if path.startswith(f"/{r}/")), None)
        if scope["type"] != "http" or role is None:
            return await self.app(scope, receive, send)
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        presented = auth[7:] if auth.lower().startswith("bearer ") else ""
        holder = self.holder(presented)
        if holder == role:
            return await self.app(scope, receive, send)
        if holder:                                   # a valid key, but for the other endpoint
            await self._record_cross_role(receive, holder, role)
            status, msg = 403, f"the {holder} credential can't call /{role}"
        else:
            status, msg = 401, "missing or unknown credential"
        body = json.dumps({"error": msg}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def _record_cross_role(self, receive, holder, role):
        raw, more = b"", True
        while more and len(raw) < 65536:
            message = await receive()
            raw += message.get("body", b"")
            more = message.get("more_body", False)
        try:
            params = json.loads(raw).get("params", {})
            drill_id = str(params.get("arguments", {}).get("drill_id", ""))
            tool = str(params.get("name", "unknown"))[:64]
        except (ValueError, AttributeError):
            return
        if re.fullmatch(DRILL_ID_PATTERN, drill_id):
            import time
            record(store, holder, tool, drill_id, "deny", f"{holder} credential refused on /{role}", "", time.monotonic())


@contextlib.asynccontextmanager
async def lifespan(app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(planner.session_manager.run())
        await stack.enter_async_context(engineer.session_manager.run())
        await stack.enter_async_context(recovery.session_manager.run())
        yield


async def health(request):
    return JSONResponse({"status": "up", "backend": BACKEND, "auth": AUTH_MODE})


app = KeyGuard(Starlette(
    routes=[Route("/health", health), Mount("/planner", app=planner_app), Mount("/engineer", app=engineer_app),
            Mount("/recovery", app=recovery_app)],
    lifespan=lifespan,
))
