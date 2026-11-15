"""Database password from Key Vault, cached for a short refresh window."""
import os
import threading
import time
from pathlib import Path

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient

SECRET_SOURCE = os.environ.get("SECRET_SOURCE", "keyvault")   # "keyvault" or "file:<path>" for local runs
SECRET_NAME = os.environ.get("SECRET_NAME", "db-password")


class SecretUnavailable(Exception):
    pass


def is_auth_failure(exc: Exception) -> bool:
    if isinstance(exc, (ClientAuthenticationError, PermissionError)):
        return True
    return isinstance(exc, HttpResponseError) and exc.status_code in (401, 403)


def _read_file(path: str) -> str:
    text = Path(path).read_text().strip()
    if text == "forbidden":                       # local stand-in for a Key Vault 403
        raise PermissionError("403 Forbidden (simulated)")
    return text


def _new_client() -> SecretClient:
    credential = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
    return SecretClient(os.environ["KEYVAULT_URL"], credential)


def build_fetch():
    """The function the order path uses to read the secret."""
    if SECRET_SOURCE.startswith("file:"):
        path = SECRET_SOURCE[5:]
        return lambda: _read_file(path)
    client = _new_client()
    return lambda: client.get_secret(SECRET_NAME).value


def fresh_check():
    """A brand-new read on every call: what Key Vault allows right now."""
    try:
        if SECRET_SOURCE.startswith("file:"):
            value = _read_file(SECRET_SOURCE[5:])
        else:
            value = _new_client().get_secret(SECRET_NAME).value
        return "ok", value
    except Exception as exc:
        return ("forbidden" if is_auth_failure(exc) else "error"), None


class SecretProvider:
    def __init__(self, fetch, refresh_seconds: float):
        self._fetch = fetch
        self._refresh = refresh_seconds
        self._value = None
        self._fetched_at = 0.0
        self._auth_failure = False
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            now = time.monotonic()

            # Serve a healthy cached value inside the refresh window.
            if self._value is not None and not self._auth_failure and now - self._fetched_at < self._refresh:
                return self._value

            # After an auth failure, limit retries so we don't hammer Key Vault.
            if self._auth_failure and now - self._fetched_at < self._refresh:
                if self._value is not None:
                    # Continue serving the last known good secret while backing off.
                    return self._value
                raise SecretUnavailable("secret unavailable (recent auth failure)")

            try:
                value = self._fetch()
                self._value = value
                self._fetched_at = now
                self._auth_failure = False
                return self._value
            except Exception as exc:
                if is_auth_failure(exc):
                    # Remember the failure time so we stop hammering Key Vault after it refuses us.
                    self._auth_failure = True
                    self._fetched_at = now
                    if self._value is not None:
                        # Keep serving the cached secret and let a later refresh retry.
                        return self._value
                raise SecretUnavailable(str(exc)) from exc
