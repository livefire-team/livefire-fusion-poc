"""Referee SQL check: counts the rows one run left in the database and prints them as JSON on stdout.

Exit codes:
  0  exactly one order and one payment authorization
  1  any other counts
  2  the check could not run (no driver, no connection, query error, missing setting); both counts are null
"""
import json
import os
import sys

EXIT_COUNTS_MATCH = 0
EXIT_COUNTS_WRONG = 1
EXIT_INCONCLUSIVE = 2


def read_counts() -> tuple[int, int]:
    import pyodbc  # imported here so a missing driver library is reported like any other failure to connect

    conn = pyodbc.connect(
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{os.environ['SQL_SERVER_FQDN']},1433;Database={os.environ['SQL_DB_NAME']};"
        f"Uid=referee_ro;Pwd={os.environ['REFEREE_SQL_PASSWORD']};Encrypt=yes;"
        f"TrustServerCertificate={os.environ.get('SQL_TRUST_CERT', 'no')};",
        timeout=15,
    )
    run_id = os.environ["RUN_ID"]
    cur = conn.cursor()
    orders = cur.execute("SELECT COUNT(*) FROM dbo.orders WHERE drill_id = ?", run_id).fetchval()
    auths = cur.execute(
        "SELECT COUNT(*) FROM dbo.payment_authorizations pa "
        "JOIN dbo.orders o ON o.order_id = pa.order_id WHERE o.drill_id = ?", run_id
    ).fetchval()
    return orders, auths


def main() -> int:
    try:
        orders, auths = read_counts()
    except Exception as exc:
        # Only the first argument: the SQLSTATE for a pyodbc error, the setting's name for a missing one.
        detail = exc.args[0] if exc.args else ""
        print(f"assert_order: {type(exc).__name__}: {detail}", file=sys.stderr)
        print(json.dumps({"orders_persisted": None, "payment_auths_persisted": None}))
        return EXIT_INCONCLUSIVE
    print(json.dumps({"orders_persisted": orders, "payment_auths_persisted": auths}))
    return EXIT_COUNTS_MATCH if orders == 1 and auths == 1 else EXIT_COUNTS_WRONG


if __name__ == "__main__":
    sys.exit(main())
