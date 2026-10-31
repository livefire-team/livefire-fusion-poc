import json, os, sys
import pyodbc

conn = pyodbc.connect(
    "Driver={ODBC Driver 18 for SQL Server};"
    f"Server=tcp:{os.environ['SQL_SERVER_FQDN']},1433;Database={os.environ['SQL_DB_NAME']};"
    f"Uid=referee_ro;Pwd={os.environ['REFEREE_SQL_PASSWORD']};Encrypt=yes;TrustServerCertificate=no;",
    timeout=15,
)
run_id = os.environ["RUN_ID"]
cur = conn.cursor()
orders = cur.execute("SELECT COUNT(*) FROM dbo.orders WHERE drill_id = ?", run_id).fetchval()
auths = cur.execute(
    "SELECT COUNT(*) FROM dbo.payment_authorizations pa "
    "JOIN dbo.orders o ON o.order_id = pa.order_id WHERE o.drill_id = ?", run_id
).fetchval()
print(json.dumps({"orders_persisted": orders, "payment_auths_persisted": auths}))
sys.exit(0 if orders == 1 and auths == 1 else 1)
