"""Entra token check for AUTH_MODE=entra (WS3): each hosted agent calls with its own Entra Agent ID.

A token is accepted only if its signature verifies against the tenant's published keys, and its issuer, audience
and expiry are valid. The caller is then 'planner', 'engineer' or (v2.1) 'recovery' only if BOTH its object ID and its app role match
that endpoint's agent. The app role is assigned in Entra, so Entra itself won't issue a role-bearing token to any
other identity; the object ID check means a mis-assigned role still can't open the other endpoint.
"""
import os

import jwt
from jwt import PyJWKClient

ROLES = {"planner": "MCP.Planner", "engineer": "MCP.Engineer", "recovery": "MCP.Recovery"}


class EntraVerifier:
    def __init__(self, tenant_id: str, client_id: str, planner_oid: str, engineer_oid: str, jwks_client=None,
                 recovery_oid: str = ""):
        if not all((tenant_id, client_id, planner_oid, engineer_oid)) or planner_oid == engineer_oid:
            raise RuntimeError("Entra mode needs the tenant, the MCP client ID and two different agent object IDs")
        if recovery_oid and recovery_oid in (planner_oid, engineer_oid):
            raise RuntimeError("the Recovery agent needs its own object ID")
        # v2 tokens carry the bare client ID as aud; v1 tokens carry the api:// URI.
        self.audiences = [f"api://{client_id}", client_id]
        self.issuers = [f"https://login.microsoftonline.com/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"]
        self.callers = {"planner": planner_oid, "engineer": engineer_oid}
        if recovery_oid:                          # v2.1: without it, nobody can open /recovery in Entra mode
            self.callers["recovery"] = recovery_oid
        self.jwks = jwks_client or PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True)

    @classmethod
    def from_env(cls) -> "EntraVerifier":
        e = os.environ
        return cls(e["ENTRA_TENANT_ID"], e["MCP_CLIENT_ID"], e["PLANNER_AGENT_OBJECT_ID"], e["ENGINEER_AGENT_OBJECT_ID"],
                   recovery_oid=e.get("RECOVERY_AGENT_OBJECT_ID", ""))

    def caller_role(self, token: str) -> str | None:
        """The endpoint role for a valid token from that agent; None for anything else, never an exception."""
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=self.audiences, issuer=self.issuers,
                                options={"require": ["exp", "iat", "aud", "iss", "oid"]}, leeway=60)
        except (jwt.InvalidTokenError, jwt.PyJWKClientError):
            return None
        roles = set(claims.get("roles") or [])
        return next((who for who, oid in self.callers.items()
                     if claims["oid"] == oid and ROLES[who] in roles), None)
