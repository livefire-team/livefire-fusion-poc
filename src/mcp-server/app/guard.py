"""Rules every tool call passes through: IDs, paths, redaction, size caps and the audit trail."""
import functools
import hashlib
import json
import logging
import posixpath
import re
import time
from datetime import datetime, timezone

from mcp.server.mcpserver.exceptions import ToolError
from opentelemetry import trace

log = logging.getLogger("mcp.guard")
tracer = trace.get_tracer("livefire.mcp")

DRILL_ID_PATTERN = r"^drill-[A-Za-z0-9-]{1,64}$"
TOOL_VERSION = "2.4"         # contracts/mcp-tools.md: every result and audit event carries it
MAX_TEXT = 20_000            # characters of any single file or document returned
MAX_RESULT = 32_000          # characters of a whole tool result

# Paths no tool may ever write, whatever an allowlist says.
PROTECTED = ("journeys/", "infra/", ".github/", "sql/", "policy/", "contracts/", "scripts/",
             "src/control-center/", "src/mcp-server/", "src/drill-runner/", "src/ops-service/", "referee/", "docs/",
             "azure.yaml", ".gitleaks.toml")

# (kind, pattern, replacement): the kind is reported in each result's redaction metadata, never what was replaced
_SECRETS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[redacted private key]"),
    ("token", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[redacted token]"),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
     "[redacted github token]"),
    ("credential", re.compile(r"(?i)\b(AccountKey|SharedAccessKey|InstrumentationKey|Password|Pwd|client_secret|"
                              r"api[_-]?key)\s*[=:]\s*[^;\s,\"']+"), r"\1=[redacted]"),
    ("sas_signature", re.compile(r"(?i)\bsig=[A-Za-z0-9%/+=]{10,}"), "sig=[redacted]"),
]

# Who each endpoint's caller is, for the audit trail: set by main.py from the authentication mode. In Entra mode an
# endpoint accepts exactly one agent identity, so the identity is known from the endpoint alone.
CALLERS: dict[str, str] = {}


def set_callers(callers: dict[str, str]) -> None:
    CALLERS.clear()
    CALLERS.update(callers)


def redact(value, hits: dict | None = None):
    """Scrubs secrets from every string in a result, however deeply nested. With hits, counts replacements by kind."""
    if isinstance(value, str):
        for kind, pattern, replacement in _SECRETS:
            value, n = pattern.subn(replacement, value)
            if n and hits is not None:
                hits[kind] = hits.get(kind, 0) + n
        return value
    if isinstance(value, dict):
        return {k: redact(v, hits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, hits) for v in value]
    return value


def clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[truncated {len(text) - limit} characters]"


def redact_clip(text: str, hits: dict, limit: int = MAX_TEXT) -> str:
    """A file's text for a result: redacted first, then cut to size, so a secret the cut would split is still caught.
    Pass the same hits to envelope() so the result's redaction metadata counts it."""
    return clip(redact(text, hits), limit)


def envelope(source: str, data, hits: dict | None = None) -> dict:
    """Wraps every result: it is data from outside, never instructions. hits: redactions already made (redact_clip)."""
    hits = dict(hits or {})
    clean = redact(data, hits)
    result = {"source": source, "untrusted_content": True,
              "redaction": {"applied": bool(hits), "count": sum(hits.values()), "kinds": sorted(hits)},
              "data": clean}
    if len(json.dumps(result, default=str)) > MAX_RESULT:
        result["data"] = clip(json.dumps(result["data"], default=str), MAX_RESULT)
        result["truncated"] = True
    return result


def safe_path(path: str) -> str:
    """A relative, normalised repository path with no tricks in it."""
    if not isinstance(path, str) or not path or len(path) > 200:
        raise ToolError("path is missing or longer than 200 characters")
    if "\\" in path or "\x00" in path or path.startswith("/") or ":" in path:
        raise ToolError("path must be a relative repository path")
    if posixpath.normpath(path) != path or path == ".." or path.startswith("../") or "/../" in path:
        raise ToolError("path must be normalised and must not contain '..'")
    return path


def _glob(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def allowed(path: str, patterns) -> bool:
    return any(_glob(p).match(path) for p in patterns)


def require_allowed(path: str, patterns, *, write: bool) -> str:
    path = safe_path(path)
    if write and path.startswith(PROTECTED):
        raise ToolError(f"{path} is a protected path and can't be changed")
    if not allowed(path, patterns):
        raise ToolError(f"{path} is outside the paths this tool may {'change' if write else 'read'}")
    return path


def refusal(tool: str, reason: str) -> dict:
    """A refused or failed call, returned as a normal result the agent can read and act on. Foundry fails the whole
    agent turn (400 tool_user_error) when an MCP tool returns an error, so a refusal the agent should recover from,
    a protected path or a missing file, must not be one. The call is still recorded as deny or error."""
    return {"source": f"livefire:{tool}", "untrusted_content": False, "refused": True, "error": reason[:500]}


def audited(role: str, tool: str, store):
    """Records every call (allowed, denied or failed) as a drill event and an OpenTelemetry span. A denied or failed
    call returns refusal(), never an MCP error (see refusal)."""
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            drill_id = kwargs.get("drill_id", "")
            args_hash = hashlib.sha256(json.dumps(kwargs, sort_keys=True, default=str).encode()).hexdigest()[:16]
            started = time.monotonic()
            decision, summary = "allow", ""
            with tracer.start_as_current_span(f"mcp.{role}.{tool}") as span:
                span.set_attribute("drill_id", drill_id)
                span.set_attribute("mcp.endpoint", role)
                span.set_attribute("mcp.tool", tool)
                source, result = "", None
                try:
                    result = await fn(*args, **kwargs)
                    summary = (result or {}).get("summary", "") if isinstance(result, dict) else ""
                except ToolError as exc:
                    decision, summary = "deny", str(exc)
                    result = refusal(tool, str(exc))
                except Exception as exc:
                    decision, summary = "error", type(exc).__name__
                    log.exception("tool %s failed", tool)
                    result = refusal(tool, f"{tool} failed ({type(exc).__name__}); try again or use another tool")
                finally:
                    if isinstance(result, dict):         # every result says which version answered and the decision
                        result["tool_version"] = TOOL_VERSION
                        result["authorization"] = {"decision": decision, "endpoint": role}
                        source = str(result.get("source", ""))
                    span.set_attribute("mcp.decision", decision)
                    span.set_attribute("mcp.tool_version", TOOL_VERSION)
                    record(store, role, tool, drill_id, decision, summary, args_hash, started, source)
                return result
        return wrapper
    return decorate


def record(store, role, tool, drill_id, decision, summary, args_hash, started, source=""):
    if not re.fullmatch(DRILL_ID_PATTERN, drill_id or ""):
        log.warning("not recording %s call without a valid drill id", tool)
        return
    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "drill_id": drill_id, "action": f"{role}.tool_call", "result": decision,
        "details": {"tool": tool, "tool_version": TOOL_VERSION, "endpoint": role,
                    "caller": CALLERS.get(role, "unknown"), "decision": decision, "summary": summary[:160],
                    "source": source, "args_sha256": args_hash,
                    "latency_ms": round((time.monotonic() - started) * 1000)},
    }
    try:
        store.append(drill_id, event)
    except Exception:
        log.exception("could not record the %s call in the evidence store", tool)
