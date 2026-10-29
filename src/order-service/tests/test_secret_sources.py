import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError  # noqa: E402

import secret_provider  # noqa: E402


class FakeClient:
    def __init__(self, value=None, error=None):
        self.value, self.error, self.names = value, error, []

    def get_secret(self, name):
        self.names.append(name)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(value=self.value)


def _http_error(status):
    return HttpResponseError(message=str(status), response=SimpleNamespace(status_code=status, reason=None))


def test_auth_errors_are_recognised():
    assert secret_provider.is_auth_failure(PermissionError("403"))
    assert secret_provider.is_auth_failure(ClientAuthenticationError("no token"))
    assert secret_provider.is_auth_failure(_http_error(401))
    assert secret_provider.is_auth_failure(_http_error(403))


def test_other_errors_are_not_auth_errors():
    assert not secret_provider.is_auth_failure(_http_error(500))
    assert not secret_provider.is_auth_failure(TimeoutError("slow"))


def test_file_source_reads_and_strips_the_password(tmp_path, monkeypatch):
    secret_file = tmp_path / "db-password"
    secret_file.write_text("pw-local\n")
    monkeypatch.setattr(secret_provider, "SECRET_SOURCE", f"file:{secret_file}")
    assert secret_provider.build_fetch()() == "pw-local"
    assert secret_provider.fresh_check() == ("ok", "pw-local")


def test_file_source_can_simulate_a_403(tmp_path, monkeypatch):
    secret_file = tmp_path / "db-password"
    secret_file.write_text("forbidden")
    monkeypatch.setattr(secret_provider, "SECRET_SOURCE", f"file:{secret_file}")
    assert secret_provider.fresh_check() == ("forbidden", None)


def test_fresh_check_reports_other_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_provider, "SECRET_SOURCE", f"file:{tmp_path / 'missing'}")
    assert secret_provider.fresh_check() == ("error", None)


def test_key_vault_source_reads_the_named_secret(monkeypatch):
    client = FakeClient(value="pw-kv")
    monkeypatch.setattr(secret_provider, "SECRET_SOURCE", "keyvault")
    monkeypatch.setattr(secret_provider, "_new_client", lambda: client)
    assert secret_provider.build_fetch()() == "pw-kv"
    assert secret_provider.fresh_check() == ("ok", "pw-kv")
    assert client.names == [secret_provider.SECRET_NAME] * 2


def test_fresh_check_uses_a_new_client_each_call(monkeypatch):
    clients = [FakeClient(error=_http_error(403)), FakeClient(value="pw-kv")]
    monkeypatch.setattr(secret_provider, "SECRET_SOURCE", "keyvault")
    monkeypatch.setattr(secret_provider, "_new_client", lambda: clients.pop(0))
    assert secret_provider.fresh_check() == ("forbidden", None)
    assert secret_provider.fresh_check() == ("ok", "pw-kv")


def test_new_client_uses_the_configured_vault(monkeypatch):
    monkeypatch.setenv("KEYVAULT_URL", "https://kv-example.vault.azure.net/")
    monkeypatch.setenv("AZURE_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
    client = secret_provider._new_client()
    assert client.vault_url == "https://kv-example.vault.azure.net"
