import datetime

import pytest

import db


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, *params):
        self.conn.statements.append((sql, params))
        return self

    def fetchone(self):
        return self.conn.row


class FakeConnection:
    def __init__(self, row=None):
        self.row, self.statements, self.committed = row, [], False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True


@pytest.fixture
def sql_env(monkeypatch):
    monkeypatch.setenv("SQL_SERVER_FQDN", "sql-example.database.windows.net")
    monkeypatch.setenv("SQL_DB_NAME", "orders")


def _capture_connect(monkeypatch, conn):
    calls = []

    def fake_connect(conn_str, autocommit):
        calls.append((conn_str, autocommit))
        return conn

    monkeypatch.setattr(db.pyodbc, "connect", fake_connect)
    return calls


def test_connects_as_order_app_with_the_given_password(sql_env, monkeypatch):
    calls = _capture_connect(monkeypatch, FakeConnection(row=(1,)))
    db.ping("pw-test")
    conn_str, autocommit = calls[0]
    assert "Server=tcp:sql-example.database.windows.net,1433;" in conn_str
    assert "Database=orders;" in conn_str
    assert "Uid=order_app;Pwd=pw-test;" in conn_str
    assert "TrustServerCertificate=no;" in conn_str
    assert autocommit is False


def test_place_order_writes_order_and_payment_in_one_transaction(sql_env, monkeypatch):
    conn = FakeConnection()
    _capture_connect(monkeypatch, conn)
    order_id = db.place_order("pw-test", "SKU-001", 49.0, "drill-42")
    (order_sql, order_params), (pay_sql, pay_params) = conn.statements
    assert "INSERT INTO dbo.orders" in order_sql
    assert order_params == (order_id, "drill-42", "SKU-001")
    assert "INSERT INTO dbo.payment_authorizations" in pay_sql
    assert pay_params[1:] == (order_id, 49.0)
    assert conn.committed


def test_get_order_returns_the_row_as_a_dict(sql_env, monkeypatch):
    created = datetime.datetime(2026, 10, 29, 12, 0, 0)
    _capture_connect(monkeypatch, FakeConnection(row=("abc", "drill-1", "SKU-002", "confirmed", created)))
    assert db.get_order("pw-test", "abc") == {
        "order_id": "abc", "drill_id": "drill-1", "sku": "SKU-002",
        "status": "confirmed", "created_at": "2026-10-29T12:00:00",
    }


def test_get_order_returns_none_when_missing(sql_env, monkeypatch):
    _capture_connect(monkeypatch, FakeConnection(row=None))
    assert db.get_order("pw-test", "nope") is None
