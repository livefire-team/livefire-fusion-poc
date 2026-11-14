import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pytest  # noqa: E402

import secret_provider  # noqa: E402
from secret_provider import SecretProvider, SecretUnavailable  # noqa: E402


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


def test_first_read_failure_is_not_cached():
    src = Source(PermissionError("403"), "pw1")
    provider = SecretProvider(src, refresh_seconds=60)
    with pytest.raises(SecretUnavailable):
        provider.get()
    assert provider.get() == "pw1"


def test_auth_failure_with_cached_value_recovers(monkeypatch):
    class Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(secret_provider.time, "monotonic", clock)

    src = Source("pw1", PermissionError("403"), "pw2")
    provider = SecretProvider(src, refresh_seconds=10)

    # First call succeeds and caches the value.
    assert provider.get() == "pw1"
    assert src.calls == 1

    # Advance beyond the refresh window so that a refetch is attempted.
    clock.now = 11.0
    with pytest.raises(SecretUnavailable):
        provider.get()
    assert src.calls == 2

    # Within the failure window we should not call the source again.
    with pytest.raises(SecretUnavailable):
        provider.get()
    assert src.calls == 2

    # After the failure window, a successful fetch clears the failure state.
    clock.now = 22.0
    assert provider.get() == "pw2"
    assert src.calls == 3
    assert provider.get() == "pw2"
    assert src.calls == 3


def test_file_secret_recovers_after_forbidden(tmp_path, monkeypatch):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("forbidden\n")

    monkeypatch.setattr(secret_provider, "SECRET_SOURCE", f"file:{secret_file}")
    fetch = secret_provider.build_fetch()
    provider = SecretProvider(fetch, refresh_seconds=60)

    with pytest.raises(SecretUnavailable):
        provider.get()

    secret_file.write_text("pw1\n")
    assert provider.get() == "pw1"
    assert provider.get() == "pw1"
