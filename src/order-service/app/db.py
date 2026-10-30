"""SQL access as the order_app user. The password comes from the secret provider."""
import os
import uuid

import pyodbc


def _connect(password: str):
    return pyodbc.connect(
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{os.environ['SQL_SERVER_FQDN']},1433;Database={os.environ['SQL_DB_NAME']};"
        f"Uid={os.environ.get('SQL_USER', 'order_app')};Pwd={password};"
        f"Encrypt=yes;TrustServerCertificate={os.environ.get('SQL_TRUST_CERT', 'no')};"
        "Connection Timeout=15;",
        autocommit=False,
    )


def ping(password: str) -> None:
    with _connect(password) as conn:
        conn.cursor().execute("SELECT 1").fetchone()


def place_order(password: str, sku: str, amount: float, drill_id: str | None) -> str:
    order_id, auth_id = str(uuid.uuid4()), str(uuid.uuid4())
    with _connect(password) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.orders (order_id, drill_id, sku, status) VALUES (?, ?, ?, 'confirmed')",
            order_id, drill_id, sku,
        )
        cur.execute(
            "INSERT INTO dbo.payment_authorizations (auth_id, order_id, amount) VALUES (?, ?, ?)",
            auth_id, order_id, amount,
        )
        conn.commit()
    return order_id


def get_order(password: str, order_id: str):
    with _connect(password) as conn:
        row = conn.cursor().execute(
            "SELECT order_id, drill_id, sku, status, created_at FROM dbo.orders WHERE order_id = ?",
            order_id,
        ).fetchone()
    if row is None:
        return None
    return {"order_id": str(row[0]), "drill_id": row[1], "sku": row[2],
            "status": row[3], "created_at": row[4].isoformat()}
