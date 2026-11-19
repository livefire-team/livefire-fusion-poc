import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as order_app_main  # noqa: E402
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


def test_auth_failure_after_success_does_not_permanently_cache_failure():
    src = Source("pw1", PermissionError("403"), "pw2")
    provider = SecretProvider(src, refresh_seconds=0)

    assert provider.get() == "pw1"
    with pytest.raises(SecretUnavailable):
        provider.get()
    assert provider.get() == "pw2"
    assert src.calls == 3


def test_order_recovers_after_auth_failure_without_restart(monkeypatch):
    src = Source(PermissionError("403"), "pw-ok")
    provider = SecretProvider(src, refresh_seconds=0)

    def fake_place_order(password, sku, price, drill_id):
        assert password == "pw-ok"
        return "order-123"

    monkeypatch.setattr(order_app_main, "secrets", provider)
    monkeypatch.setattr(order_app_main.db, "place_order", fake_place_order)

    client = TestClient(order_app_main.app)
    sku = next(iter(order_app_main.PRODUCTS))

    first = client.post("/api/orders", json={"sku": sku})
    assert first.status_code == 503

    second = client.post("/api/orders", json={"sku": sku})
    assert second.status_code == 201
    body = second.json()
    assert body["order_id"] == "order-123"
    assert "confirmation" in body


def test_health_dependencies_non_200_when_db_unavailable_even_if_keyvault_ok(monkeypatch):
    def ok_fresh_check():
        return "ok", "pw-from-kv"

    def failing_ping(password):
        raise SecretUnavailable("db cannot use secret")

    monkeypatch.setattr(order_app_main, "fresh_check", ok_fresh_check)
    monkeypatch.setattr(order_app_main.db, "ping", failing_ping)

    client = TestClient(order_app_main.app)
    resp = client.get("/health/dependencies")
    assert resp.status_code != 200
    body = resp.json()
    assert body["keyvault"] == "ok"
    assert body["sql"] == "error"
