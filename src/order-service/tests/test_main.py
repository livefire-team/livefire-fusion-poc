import importlib.util
import logging
import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import main
from secret_provider import SecretUnavailable

ORDER_ID = "0a1b2c3d-4e5f-6789-abcd-ef0123456789"


class StubSecrets:
    def __init__(self, value="pw-test", error=None):
        self.value, self.error = value, error

    def get(self):
        if self.error is not None:
            raise self.error
        return self.value


class Counter:
    def __init__(self):
        self.calls = []

    def add(self, amount, attributes=None):
        self.calls.append((amount, attributes))


class RecordingSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class RecordingTracer:
    def __init__(self):
        self.spans = []

    @contextmanager
    def start_as_current_span(self, name):
        span = RecordingSpan()
        self.spans.append((name, span))
        yield span


class StubDb:
    def __init__(self):
        self.order_id, self.error, self.order = ORDER_ID, None, None
        self.placed, self.pings = [], []

    def place_order(self, password, sku, amount, drill_id):
        self.placed.append((password, sku, amount, drill_id))
        if self.error is not None:
            raise self.error
        return self.order_id

    def get_order(self, password, order_id):
        return self.order

    def ping(self, password):
        self.pings.append(password)
        if self.error is not None:
            raise self.error


class Stubs:
    def __init__(self):
        self.db = StubDb()
        self.completed, self.failed = Counter(), Counter()
        self.tracer = RecordingTracer()


@pytest.fixture
def stubs(monkeypatch):
    s = Stubs()
    monkeypatch.setattr(main, "secrets", StubSecrets())
    monkeypatch.setattr(main.db, "place_order", s.db.place_order)
    monkeypatch.setattr(main.db, "get_order", s.db.get_order)
    monkeypatch.setattr(main.db, "ping", s.db.ping)
    monkeypatch.setattr(main, "orders_completed", s.completed)
    monkeypatch.setattr(main, "orders_failed", s.failed)
    monkeypatch.setattr(main, "tracer", s.tracer)
    monkeypatch.setattr(main, "_last_good", {})
    return s


@pytest.fixture
def client(stubs):
    return TestClient(main.app)


# ---- health ----

def test_health_reports_the_process_is_up(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "up"}


def test_dependencies_ok_when_key_vault_and_sql_answer(client, stubs, monkeypatch):
    monkeypatch.setattr(main, "fresh_check", lambda: ("ok", "pw-fresh"))
    response = client.get("/health/dependencies")
    assert response.status_code == 200
    assert response.json() == {"keyvault": "ok", "sql": "ok"}
    assert stubs.db.pings == ["pw-fresh"]


def test_dependencies_check_key_vault_on_every_call(client, monkeypatch):
    calls = []

    def check():
        calls.append(1)
        return "ok", "pw"

    monkeypatch.setattr(main, "fresh_check", check)
    client.get("/health/dependencies")
    client.get("/health/dependencies")
    assert len(calls) == 2


def test_dependencies_forbidden_without_any_password_reports_sql_unknown(client, monkeypatch):
    monkeypatch.setattr(main, "fresh_check", lambda: ("forbidden", None))
    response = client.get("/health/dependencies")
    assert response.status_code == 503
    assert response.json() == {"keyvault": "forbidden", "sql": "unknown"}


def test_dependencies_forbidden_still_pings_sql_with_last_good_password(client, stubs, monkeypatch):
    results = [("ok", "pw-earlier"), ("forbidden", None)]
    monkeypatch.setattr(main, "fresh_check", lambda: results.pop(0))
    client.get("/health/dependencies")
    response = client.get("/health/dependencies")
    assert response.status_code == 503
    assert response.json() == {"keyvault": "forbidden", "sql": "ok"}
    assert stubs.db.pings == ["pw-earlier", "pw-earlier"]


def test_dependencies_report_key_vault_error(client, monkeypatch):
    monkeypatch.setattr(main, "fresh_check", lambda: ("error", None))
    response = client.get("/health/dependencies")
    assert response.status_code == 503
    assert response.json() == {"keyvault": "error", "sql": "unknown"}


def test_dependencies_report_sql_error(client, stubs, monkeypatch):
    stubs.db.error = RuntimeError("login failed")
    monkeypatch.setattr(main, "fresh_check", lambda: ("ok", "pw"))
    response = client.get("/health/dependencies")
    assert response.status_code == 503
    assert response.json() == {"keyvault": "ok", "sql": "error"}


# ---- pages ----

def test_shop_lists_every_product_with_add_to_cart(client):
    html = client.get("/").text
    for sku in main.PRODUCTS:
        assert f'data-testid="product-{sku}"' in html
        assert f'href="/cart?sku={sku}"' in html
    assert html.count('data-testid="add-to-cart"') == len(main.PRODUCTS)


def test_cart_links_to_checkout(client):
    html = client.get("/cart", params={"sku": "SKU-001"}).text
    assert "Recovery Kit: $49.00" in html
    assert 'data-testid="checkout" href="/checkout?sku=SKU-001"' in html


def test_checkout_page_has_place_order_button(client):
    html = client.get("/checkout", params={"sku": "SKU-002"}).text
    assert 'name="sku" value="SKU-002"' in html
    assert 'data-testid="place-order"' in html


def test_placing_an_order_shows_a_confirmation_number(client, stubs):
    response = client.post("/checkout", data={"sku": "SKU-001"})
    assert response.status_code == 200
    match = re.search(r'data-testid="confirmation-number">([^<]+)<', response.text)
    assert match.group(1) == "LF-0A1B2C3D"
    assert re.fullmatch(r"LF-[0-9A-F]{8}", match.group(1))
    assert stubs.db.placed == [("pw-test", "SKU-001", 49.0, None)]


def test_drill_id_header_is_passed_to_the_database_and_span(client, stubs):
    client.post("/checkout", data={"sku": "SKU-002"}, headers={"x-drill-id": "drill-7"})
    assert stubs.db.placed == [("pw-test", "SKU-002", 89.0, "drill-7")]
    name, span = stubs.tracer.spans[0]
    assert name == "place_order"
    assert span.attributes == {"drill_id": "drill-7", "sku": "SKU-002"}


def test_order_success_is_counted_and_logged(client, stubs, caplog):
    with caplog.at_level(logging.INFO, logger="orders"):
        client.post("/checkout", data={"sku": "SKU-001"}, headers={"x-drill-id": "drill-8"})
    assert stubs.completed.calls == [(1, None)]
    record = next(r for r in caplog.records if r.getMessage() == "order placed")
    assert record.drill_id == "drill-8"
    assert record.order_id == ORDER_ID


def test_order_failure_shows_error_and_returns_503(client, stubs, monkeypatch):
    monkeypatch.setattr(main, "secrets", StubSecrets(error=SecretUnavailable("403")))
    response = client.post("/checkout", data={"sku": "SKU-001"})
    assert response.status_code == 503
    assert 'data-testid="order-error"' in response.text
    assert "SecretUnavailable" in response.text
    assert 'data-testid="confirmation-number"' not in response.text
    assert stubs.db.placed == []


def test_order_failure_is_counted_and_logged_with_drill_id(client, stubs, caplog):
    stubs.db.error = RuntimeError("sql down")
    with caplog.at_level(logging.INFO, logger="orders"):
        client.post("/checkout", data={"sku": "SKU-002"}, headers={"x-drill-id": "drill-9"})
    assert stubs.failed.calls == [(1, {"reason": "RuntimeError"})]
    assert stubs.completed.calls == []
    record = next(r for r in caplog.records if r.getMessage() == "order failed")
    assert record.drill_id == "drill-9"
    assert record.sku == "SKU-002"
    assert record.exc_info is not None


def test_unknown_sku_on_checkout_returns_503_error_page(client, stubs):
    response = client.post("/checkout", data={"sku": "SKU-999"})
    assert response.status_code == 503
    assert 'data-testid="order-error"' in response.text
    assert stubs.db.placed == []


# ---- JSON API ----

def test_api_creates_an_order(client, stubs):
    response = client.post("/api/orders", json={"sku": "SKU-002"}, headers={"x-drill-id": "drill-3"})
    assert response.status_code == 201
    assert response.json() == {"order_id": ORDER_ID, "confirmation": "LF-0A1B2C3D"}
    assert stubs.db.placed == [("pw-test", "SKU-002", 89.0, "drill-3")]


def test_api_order_failure_returns_503_with_reason(client, monkeypatch):
    monkeypatch.setattr(main, "secrets", StubSecrets(error=SecretUnavailable("403")))
    response = client.post("/api/orders", json={"sku": "SKU-001"})
    assert response.status_code == 503
    assert response.json() == {"error": "SecretUnavailable"}


def test_api_reads_an_order(client, stubs):
    stubs.db.order = {"order_id": "abc", "status": "confirmed"}
    response = client.get("/api/orders/abc")
    assert response.status_code == 200
    assert response.json() == {"order_id": "abc", "status": "confirmed"}


def test_api_read_returns_404_for_unknown_order(client):
    response = client.get("/api/orders/missing")
    assert response.status_code == 404
    assert response.json() == {"error": "not found"}


def test_api_read_returns_503_when_secret_unavailable(client, monkeypatch):
    monkeypatch.setattr(main, "secrets", StubSecrets(error=SecretUnavailable("403")))
    response = client.get("/api/orders/abc")
    assert response.status_code == 503


# ---- telemetry setup ----

def test_telemetry_targets_the_orders_logger_when_connection_string_is_set(monkeypatch):
    import azure.monitor.opentelemetry as distro

    calls = []
    monkeypatch.setattr(distro, "configure_azure_monitor", lambda **kw: calls.append(kw))
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING",
                       "InstrumentationKey=00000000-0000-0000-0000-000000000000")
    spec = importlib.util.spec_from_file_location("main_with_telemetry", main.__file__)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert calls == [{"logger_name": "orders"}]
