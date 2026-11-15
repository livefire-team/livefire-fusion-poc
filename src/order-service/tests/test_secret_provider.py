import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pytest  # noqa: E402

import secret_provider as sp  # noqa: E402
from secret_provider import SecretProvider, SecretUnavailable, fresh_check  # noqa: E402


class Source:
    def __init__(self, *results):
        self.results, self.calls = list(results), 0

    def __call__(self):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_returns_cached_value_inside_refresh_window():
    src = Source("pw1")
    provider = SecretProvider(src, refresh_seconds=60)
    assert provider.get() == "pw1"
    assert provider.get() == "pw1"
    assert src.calls == 1


def test_refreshes_after_window():
    src = Source("pw1", "pw2")
    provider = SecretProvider(src, refresh_seconds=0)
    assert provider.get() == "pw1"
    assert provider.get() == "pw2"


def test_auth_failure_without_cached_value_is_backed_off_and_recovers(monkeypatch):
    # First call sees an auth failure; subsequent calls within the refresh window
    # should not hammer the source, but a later call should retry and succeed.
    src = Source(PermissionError("403"), "pw1")
    provider = SecretProvider(src, refresh_seconds=60)

    fake_time = [0.0]

    def fake_monotonic():
        return fake_time[0]

    monkeypatch.setattr(sp.time, "monotonic", fake_monotonic)

    with pytest.raises(SecretUnavailable):
        provider.get()
    assert src.calls == 1

    fake_time[0] = 1.0
    with pytest.raises(SecretUnavailable):
        provider.get()
    # Still only one Key Vault call during the backoff window.
    assert src.calls == 1

    fake_time[0] = 61.0
    assert provider.get() == "pw1"
    assert src.calls == 2


def test_auth_failure_after_cached_value_uses_cached_and_recovers(monkeypatch):
    # Once a secret has been cached, an auth failure should not permanently
    # lock the provider into SecretUnavailable; it should serve the cached
    # value during backoff and eventually refresh when access is restored.
    src = Source("pw1", PermissionError("403"), "pw2")
    provider = SecretProvider(src, refresh_seconds=60)

    fake_time = [0.0]

    def fake_monotonic():
        return fake_time[0]

    monkeypatch.setattr(sp.time, "monotonic", fake_monotonic)

    # Initial successful read caches the secret.
    assert provider.get() == "pw1"
    assert src.calls == 1

    # Move past the refresh window so the provider will try to re-fetch.
    fake_time[0] = 61.0
    assert provider.get() == "pw1"
    # Second call tried to refresh, saw a 403, and continued to serve the cache.
    assert src.calls == 2

    # During the backoff window we keep serving the cached value without
    # further calls to the source.
    fake_time[0] = 62.0
    assert provider.get() == "pw1"
    assert src.calls == 2

    # After the backoff expires, the provider should retry and accept a
    # working secret again.
    fake_time[0] = 122.0
    assert provider.get() == "pw2"
    assert src.calls == 3


def test_fresh_check_reports_forbidden_then_ok(tmp_path, monkeypatch):
    # Health uses fresh_check; ensure it reports forbidden when reads fail
    # and ok once secrets are readable again.
    secret_file = tmp_path / "secret.txt"

    secret_file.write_text("forbidden")
    monkeypatch.setattr(sp, "SECRET_SOURCE", f"file:{secret_file}")
    status, value = fresh_check()
    assert status == "forbidden"
    assert value is None

    secret_file.write_text("pw1")
    status, value = fresh_check()
    assert status == "ok"
    assert value == "pw1"
