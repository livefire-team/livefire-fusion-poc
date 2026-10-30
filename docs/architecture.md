# Order service architecture

The order service is a small web shop: customers pick a product, check out and get a confirmation number. It runs in
Azure as one container app and stores orders in Azure SQL. Everything in Azure is defined in
`infra/modules/twin.bicep`.

## Components

| Component | Azure resource | Role |
|---|---|---|
| Order service | Container Apps app `ca-order` in environment `cae-lf-twin`, exactly one replica | Python 3.12 FastAPI app (`src/order-service/app/`): HTML pages and a JSON API |
| Database | Azure SQL server `sql-lf-<suffix>`, Basic tier | Tables `products`, `orders`, `payment_authorizations` (`sql/schema.sql`, `sql/seed.sql`) |
| Secrets | Key Vault `kv-lf-<suffix>` | Holds `db-password`, the password of the `order_app` database user |
| Identity | User-assigned managed identity `id-order-app` | The app's identity for reading Key Vault; no credentials in configuration |
| Telemetry | Application Insights `appi-lf-twin-<suffix>` on Log Analytics `log-lf-twin-<suffix>` | Requests, dependencies, logs, exceptions and metrics |
| Load generator | Container Apps Job in the same environment (`src/load-generator/`, `infra/modules/loadgen.bicep`) | Places a steady stream of orders through the JSON API |

## Request flow

1. A browser or client calls the app over HTTPS ingress. Pages: `GET /`, `GET /cart`, `GET /checkout`,
   `POST /checkout`. API: `POST /api/orders` with `{"sku": "..."}` returns `201` with `order_id` and
   `confirmation` (`LF-` plus 8 characters); `GET /api/orders/{order_id}` reads one back.
2. To place an order the app gets the database password from its secret provider, then writes an `orders` row and a
   `payment_authorizations` row in one transaction (`db.py`, pyodbc with ODBC Driver 18, encrypted connection).
3. If the password or the database is not available, the API answers `503` with the error type and the page shows a
   "couldn't place your order" message.

An optional `x-drill-id` request header (letters, digits and `._:-`, up to 64 characters) tags a request: it is
stored in `orders.drill_id` and added to the request's telemetry.

## Secrets and configuration

The app reads Key Vault with its managed identity (`AZURE_CLIENT_ID`, `KEYVAULT_URL`, `SECRET_NAME`). The secret
provider (`secret_provider.py`) keeps the password in memory and reads it again from Key Vault once
`SECRET_REFRESH_SECONDS` have passed since the last read (default `30`). Other settings: `SQL_SERVER_FQDN`,
`SQL_DB_NAME`, `SQL_USER`, `APPLICATIONINSIGHTS_CONNECTION_STRING`. For local runs, `SECRET_SOURCE=file:<path>`
reads the password from a file instead of Key Vault (`docker-compose.yml`).

## Health endpoints

| Endpoint | Checks | Answer |
|---|---|---|
| `/health` | The process only | `200 {"status":"up"}`. Used by the liveness and readiness probes |
| `/health/dependencies` | A new Key Vault read on every call, then a SQL ping | `200 {"keyvault":"ok","sql":"ok"}`, otherwise `503` with `forbidden`, `error` or `unknown` |

## Telemetry

Azure Monitor OpenTelemetry (`configure_azure_monitor(logger_name="orders")`) sends to Application Insights.

| Kind | Name |
|---|---|
| Tables | `requests`, `dependencies`, `exceptions`, `traces`; `customDimensions.drill_id` when the header is set |
| Span | `place_order` |
| Log messages | `order placed` (info), `order failed` (error, with the exception) |
| Metrics | `orders_completed`; `orders_failed` tagged `reason` (exception type) |

## CI/CD and images

GitHub Actions (`.github/workflows/`): `order-service.yml` runs unit tests, builds the image and smoke-tests
`/health`; `security.yml` runs gitleaks, pip-audit, CodeQL and Trivy. Images go to
`ghcr.io/livefire-team/order-service`:

- `sha-<7-character commit>`: immutable, every published build.
- `g1`: the current release from `main`.
- `candidate-<drill-id>-<attempt>`: builds of `candidate/<drill-id>-<attempt>` branches.

A deployment selects an image tag and creates a new Container Apps revision.

## Operations

Recovery steps for Key Vault access problems are in `runbooks/order-service-keyvault-recovery.md`.
