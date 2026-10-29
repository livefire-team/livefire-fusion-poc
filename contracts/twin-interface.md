# Twin interface contract (WS1 ⇄ WS2, also used by WS3/WS4/WS5)

The shared source of truth for names, paths, outputs and the image tag. WS1 builds to this version.
**Any change here must be told to WS2, WS3, WS4 and WS5 the same day.**

Version: 1 (2026-10-28) — copied from the WS2 guide's Phase 2 contract via the WS1 Build Guide Phase 1.

## Azure resources (`infra/modules/twin.bicep`)

| Item | Contract | Delivered in |
|---|---|---|
| Resource group | `rg-lf-twin-<env>`, created by WS2's `main.bicep` | WS2 |
| `twin.bicep` parameters | `location`, `principalId`, `kvPermissionModel` (`rbac` or `accessPolicy`), `orderImage`, `sqlAdminPassword`; optional `secretRefreshSeconds` (default `30`) and `principalType` (default `User`) | `twin.bicep` |
| `twin.bicep` outputs | `keyVaultName`, `keyVaultId`, `appIdentityPrincipalId`, `appAccessAssignmentName`, `orderAppName`, `orderAppUrl`, `sqlServerFqdn`, `sqlDbName`, `appInsightsConnectionString` | `twin.bicep` |
| SQL admin login | `lfadmin` | `twin.bicep` |
| App database user | `order_app`, created by WS2's hook; its password lives in Key Vault secret `db-password` | WS2 hook; `db.py` reads it |
| Replicas and probes | One replica minimum and maximum; liveness and readiness probes on `/health` only | `twin.bicep` |
| Refresh window | `SECRET_REFRESH_SECONDS`: `30` by default, `10` while testing | `twin.bicep` parameter |

## Order service endpoints and telemetry (`src/order-service/app/main.py`)

| Item | Contract | Delivered in |
|---|---|---|
| `/health` | `200 {"status":"up"}`; checks the process only | `main.py` |
| `/health/dependencies` | `200 {"keyvault":"ok","sql":"ok"}`, or `503` with `forbidden`, `error` or `unknown` values. A fresh Key Vault client is created on every call | `main.py`, `secret_provider.py` |
| Drill ID | `x-drill-id` header, stored in `orders.drill_id`, set as span attribute `drill_id`, and added to failure logs so it shows in `exceptions.customDimensions` | `main.py` |
| Test IDs (journey selectors) | `product-<sku>` containing `add-to-cart`; then `checkout`, `place-order`, `confirmation-number` (format `LF-` plus 8 characters) and `order-error` | `templates/` |

## Database (`sql/`)

| Item | Contract | Delivered in |
|---|---|---|
| Tables | `products(sku, name, price)`, `orders(order_id, drill_id, sku, status, created_at)`, `payment_authorizations(auth_id, order_id, amount, created_at)` | `schema.sql` |
| Seed data | `SKU-001` Recovery Kit, `SKU-002` Backup Drive | `seed.sql`, `catalog.py` (change together) |

## Image (GitHub Actions)

| Item | Contract | Delivered in |
|---|---|---|
| Image | `ghcr.io/livefire-team/order-service:g1` (org name lowercase); immutable `sha-<commit>` tags for rehearsals; package public (ADR-002) | `.github/workflows/order-service.yml` |

## Additions WS2 needs to know about
1. New output `appInsightsConnectionString`. WS2 adds to `main.bicep`:
   `output APPINSIGHTS_CONNECTION_STRING string = twin.outputs.appInsightsConnectionString`
2. The `principalType` and `secretRefreshSeconds` pass-through parameters (both optional, defaults above).

## Change log
| Date | Change | Told WS2/3/4/5? |
|---|---|---|
| 2026-10-28 | Version 1; repo is `livefire-team/livefire-fusion-poc`, image owner `livefire-team` | pending |
