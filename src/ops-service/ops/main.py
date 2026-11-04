"""HTTP front of the Ops Service: POST /actions/<action> with a Bearer key (contracts/ops-actions.md)."""
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import livefire_events
from .service import (AGENT_ACTIONS, CONTRACT, ENABLED_FAULTS, Busy, Forbidden, OpsService, Refused, Stopped,
                      Unavailable)
from .settings import Settings, from_env

log = logging.getLogger("ops")


def build_service(s: Settings) -> OpsService:
    store = _store(s.event_source)
    if s.backend == "fake":
        from .referee import FakeReferee
        from .twin import FakeTwin
        twin = FakeTwin(s.base_image) if s.base_image else FakeTwin()
        return OpsService(s, twin, FakeReferee(twin), store)
    from .arm import Arm, TokenCache, credential_for
    from .referee import EvidenceFiles, JobReferee
    from .twin import AzureTwin
    tokens = TokenCache(credential_for(s.auth, s.client_id))
    arm = Arm(tokens)
    twin = AzureTwin(s, arm, tokens)
    return OpsService(s, twin, JobReferee(s, arm, EvidenceFiles(s.event_source, s.client_id, s.auth)), store)


def _store(source: str):
    if source.startswith("dir:"):
        return livefire_events.DirEventStore(source[4:])
    account_url, _, container = source[5:].rpartition("/")
    return livefire_events.BlobEventStore(account_url, container)


def create_app(service: OpsService | None = None) -> FastAPI:
    holder: dict = {"service": service}

    def svc() -> OpsService:
        if holder["service"] is None:
            holder["service"] = build_service(from_env())
        return holder["service"]

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        svc()                              # fail fast: a bad allowlist or a short key stops the container
        yield

    app = FastAPI(title="LiveFire Ops Service", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        s = svc().s
        return {"status": "up", "backend": s.backend, "contract": CONTRACT, "faults": list(ENABLED_FAULTS),
                "model": svc().twin.model}

    @app.post("/actions/{action}")
    async def action(action: str, request: Request) -> JSONResponse:
        service = svc()
        auth = request.headers.get("authorization", "")
        if hmac.compare_digest(auth, f"Bearer {service.s.runner_key}"):
            caller = "runner"
        elif hmac.compare_digest(auth, f"Bearer {service.s.agent_key}"):
            caller = "agent"
        else:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return _reply(action, "refused", {"reason": "the body must be a JSON object"}, 422)
        try:
            reply = await service.handle(action, body, caller)
        except Forbidden as exc:
            return JSONResponse({"error": str(exc), "allowed": list(AGENT_ACTIONS)}, status_code=403)
        except Refused as exc:
            return _reply(action, "refused", {"reason": str(exc)}, 422)
        except (Busy, Stopped) as exc:
            return _reply(action, "busy" if isinstance(exc, Busy) else "stopped", {"reason": str(exc)}, 409)
        except Unavailable as exc:
            log.warning("action %s unavailable: %s", action, exc)
            return _reply(action, "error", {"reason": str(exc)[:500]}, 503)
        return _reply(reply.action, reply.result, reply.details, 200)

    return app


def _reply(action: str, result: str, details: dict, status: int) -> JSONResponse:
    return JSONResponse({"action": action, "result": result, "details": details}, status_code=status)


app = create_app()
