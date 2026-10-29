import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pytest  # noqa: E402

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
