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
        self._failed = False
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._failed:
                raise SecretUnavailable("secret unavailable (cached failure)")
            if self._value is not None and time.monotonic() - self._fetched_at < self._refresh:
                return self._value
            try:
                self._value = self._fetch()
                self._fetched_at = time.monotonic()
                return self._value
            except Exception as exc:
                # Cache auth failures so we stop hammering Key Vault after it refuses us.
                if self._value is not None and is_auth_failure(exc):
                    self._failed = True
                raise SecretUnavailable(str(exc)) from exc
