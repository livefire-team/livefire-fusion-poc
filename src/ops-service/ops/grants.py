"""Recovery grants: lfg1.<payload>.<signature>, HMAC-SHA256 with RECOVERY_GRANT_KEY.

The Drill Runner signs one grant per approved action; the Ops Service verifies it. Both must use this exact module.
The payload is base64url JSON (no padding):
  {"v": 1, "gid": "grt-<12 hex>", "drill_id": ..., "action": ..., "purpose": "recover" | "policy_test",
   "exp": <unix seconds>, "approved_by": <who or which policy approved>}
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

PREFIX = "lfg1"
MAX_LENGTH = 2048
TTL_SECONDS = 600
PURPOSES = ("recover", "policy_test")


class GrantRefused(ValueError):
    pass


@dataclass(frozen=True)
class Grant:
    gid: str
    drill_id: str
    action: str
    purpose: str
    exp: int
    approved_by: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(key: str, signed_part: str) -> str:
    return _b64(hmac.new(key.encode(), signed_part.encode(), hashlib.sha256).digest())


def sign(key: str, drill_id: str, action: str, purpose: str, approved_by: str,
         ttl_s: int = TTL_SECONDS, now: float | None = None) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    payload = {"v": 1, "gid": f"grt-{secrets.token_hex(6)}", "drill_id": drill_id, "action": action,
               "purpose": purpose, "exp": int((now or time.time()) + ttl_s), "approved_by": approved_by}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signed_part = f"{PREFIX}.{body}"
    return f"{signed_part}.{_sign(key, signed_part)}"


def verify(key: str, grant: str, drill_id: str, action: str, purpose: str, now: float | None = None) -> Grant:
    """Checks signature, drill, action, purpose and expiry. Single use is the caller's job (it needs the log)."""
    if not isinstance(grant, str) or not grant or len(grant) > MAX_LENGTH:
        raise GrantRefused("missing or oversized grant")
    parts = grant.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise GrantRefused("not a recovery grant")
    signed_part = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_sign(key, signed_part), parts[2]):
        raise GrantRefused("bad grant signature")
    try:
        payload = json.loads(_unb64(parts[1]))
        g = Grant(gid=str(payload["gid"]), drill_id=str(payload["drill_id"]), action=str(payload["action"]),
                  purpose=str(payload["purpose"]), exp=int(payload["exp"]),
                  approved_by=str(payload.get("approved_by", ""))[:120])
    except (ValueError, KeyError, TypeError) as exc:
        raise GrantRefused("unreadable grant payload") from exc
    if g.drill_id != drill_id:
        raise GrantRefused("grant is for another drill")
    if g.action != action:
        raise GrantRefused("grant is for another action")
    if g.purpose != purpose:
        raise GrantRefused("grant purpose does not match this call")
    if g.exp < (now or time.time()):
        raise GrantRefused("grant expired")
    return g
