"""A small Azure Resource Manager REST client: explicit URLs and API versions, so tests can check every call."""
import asyncio
import time

import httpx

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
API = {
    "containerApps": "2024-03-01",
    "jobs": "2024-03-01",
    "keyVault": "2023-07-01",
    "roleAssignments": "2022-04-01",
}


class ArmError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class TokenCache:
    """Wraps an azure-identity credential (sync) and refreshes tokens a few minutes before they expire."""

    def __init__(self, credential):
        self.credential = credential
        self._tokens: dict[str, tuple[str, float]] = {}

    async def get(self, scope: str) -> str:
        token, expires = self._tokens.get(scope, ("", 0.0))
        if time.time() > expires - 300:
            access = await asyncio.to_thread(self.credential.get_token, scope)
            token, expires = access.token, float(access.expires_on)
            self._tokens[scope] = (token, expires)
        return token


def credential_for(auth: str, client_id: str):
    from azure.identity import AzureCliCredential, ManagedIdentityCredential
    return AzureCliCredential() if auth == "cli" else ManagedIdentityCredential(client_id=client_id)


class Arm:
    def __init__(self, tokens: TokenCache, transport: httpx.AsyncBaseTransport | None = None):
        self.tokens = tokens
        self.http = httpx.AsyncClient(base_url=ARM, timeout=60, transport=transport)

    async def request(self, method: str, path: str, api: str, body: dict | None = None,
                      ok: tuple[int, ...] = (200, 201, 202, 204), query: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {await self.tokens.get(ARM_SCOPE)}"}
        params = {"api-version": API[api], **(query or {})}
        for attempt in range(3):
            r = await self.http.request(method, path, params=params, json=body, headers=headers)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                retry_after = r.headers.get("Retry-After", "3")
                await asyncio.sleep(min(float(retry_after), 20) if retry_after.isdigit() else 3)
                continue
            break
        if r.status_code not in ok:
            try:
                err = r.json().get("error") or {}
            except ValueError:
                err = {}
            raise ArmError(r.status_code, str(err.get("code", "")), str(err.get("message", r.text[:300])))
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {}

    async def get(self, path: str, api: str, query: dict | None = None) -> dict:
        return await self.request("GET", path, api, ok=(200,), query=query)
