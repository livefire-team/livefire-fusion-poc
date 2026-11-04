"""Resolves a tag in the private registry to its digest with only the pull right (AcrPull).

Flow: Entra token -> ACR refresh token (/oauth2/exchange) -> repository pull token (/oauth2/token) ->
HEAD /v2/<repo>/manifests/<tag>, whose Docker-Content-Digest header is the immutable digest.
"""
import re

import httpx

from .arm import TokenCache

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])
SCOPES = ("https://containerregistry.azure.net/.default", "https://management.azure.com/.default")


class RegistryError(RuntimeError):
    pass


async def resolve_digest(tokens: TokenCache, server: str, repo: str, tag: str,
                         transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    """The digest of <server>/<repo>:<tag>, or None when the tag is not in the registry."""
    async with httpx.AsyncClient(base_url=f"https://{server}", timeout=30, transport=transport) as http:
        refresh = ""
        for scope in SCOPES:                      # newer registries want the ACR audience; older ones accept ARM
            aad = await tokens.get(scope)
            r = await http.post("/oauth2/exchange", data={"grant_type": "access_token", "service": server,
                                                          "access_token": aad})
            if r.status_code == 200:
                refresh = r.json().get("refresh_token", "")
                break
        if not refresh:
            raise RegistryError(f"token exchange with {server} failed ({r.status_code})")
        r = await http.post("/oauth2/token", data={"grant_type": "refresh_token", "service": server,
                                                   "scope": f"repository:{repo}:pull", "refresh_token": refresh})
        if r.status_code != 200:
            raise RegistryError(f"pull token for {repo} refused ({r.status_code})")
        access = r.json().get("access_token", "")
        r = await http.head(f"/v2/{repo}/manifests/{tag}",
                            headers={"Authorization": f"Bearer {access}", "Accept": ACCEPT})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RegistryError(f"manifest lookup for {repo}:{tag} failed ({r.status_code})")
        digest = r.headers.get("Docker-Content-Digest", "")
        if not DIGEST.match(digest):
            raise RegistryError("registry returned no valid digest")
        return digest
