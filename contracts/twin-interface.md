# Twin interface contract (WS1 ⇄ WS2, also used by WS3/WS4/WS5)

The shared source of truth for names, paths, outputs and the image tag. WS1 builds to this version.
**Any change here must be told to WS2, WS3, WS4 and WS5 the same day.**

Version: 1 (2026-10-28) — copied from the WS2 guide's Phase 2 contract via the WS1 Build Guide Phase 1.

## Azure resources (`infra/modules/twin.bicep`)

| Item | Contract | Delivered in |
|---|---|---|
| Resource group | `rg-lf-twin-<env>`, created by WS2's `main.bicep` | WS2 |
| `twin.bicep` parameters | `location`, `principalId`, `kvPermissionModel` (`rbac` or `accessPolicy`), `orderImage`, `sqlAdminPassword`; optional `secretRefreshSeconds` (default `30`) and `principalType` (default `User`); WS2 addition (G2): optional `registryServer` and `pullIdentityId` (default empty) | `twin.bicep` |
| `twin.bicep` outputs | `keyVaultName`, `keyVaultId`, `appIdentityPrincipalId`, `appAccessAssignmentName`, `orderAppName`, `orderAppUrl`, `sqlServerFqdn`, `sqlDbName`, `appInsightsConnectionString`, `logAnalyticsWorkspaceName`, `logAnalyticsCustomerId` | `twin.bicep` |
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
| Image | `ghcr.io/livefire-team/order-service:g1` (org name lowercase) | `.github/workflows/order-service.yml` |
| Image (WS1 addition) | Immutable `sha-<commit>` tags for rehearsals; package public (ADR-002) | `.github/workflows/order-service.yml` |
| Image (WS1 addition, G2) | `candidate-<drill-id>-<attempt>` tags, pushed from `candidate/<drill-id>-<attempt>` branches (lowercase drill ID, attempt 1-99; ADR-014) | `.github/workflows/order-service.yml` |
| Candidate CI (WS1 addition, G2) | A candidate push passes CI only when `order-service` and `security` both end `success` for its head commit. `order-service` fails at `candidate-scope` if the candidate changed a file outside the allowed paths (repository variable `CANDIDATE_ALLOWED_PATHS`), and then publishes nothing (ADR-020) | `.github/workflows/order-service.yml`, `.github/workflows/security.yml` |
| Image (WS2 addition, G2) | The twin runs `<lab registry>/order-service:sha-<full commit>` from the lab's private registry, pulled by `id-lf-acrpull` (ADR-017). CI pushes the same tested image there from `main` and candidate branches once the `acr-push` environment is set up | `order-service.yml` `acr` job, `scripts/deploy.sh images` |

## Additions WS2 needs to know about
1. New output `appInsightsConnectionString`. WS2 adds to `main.bicep`:
   `output APPINSIGHTS_CONNECTION_STRING string = twin.outputs.appInsightsConnectionString`
2. The `principalType` and `secretRefreshSeconds` pass-through parameters (both optional, defaults above).
3. WS1 addition (G2): load generator module `infra/modules/loadgen.bicep` (Container Apps Job `caj-loadgen` in the
   existing environment `cae-lf-twin`; required params `location`, `loadgenImage`, `orderAppUrl`; optional
   `appInsightsConnectionString`, `ratePerMinute` (30), `skus`, `drillId`, `durationSeconds` (3000), `triggerType`
   (`Manual` or `Schedule`), `cronExpression`, `jobName`, `containerAppsEnvironmentName`; outputs `loadgenJobName`,
   `loadgenJobId`). Image `ghcr.io/livefire-team/load-generator:g2` (and `sha-<commit>`). Metrics in Application
   Insights: `loadgen_orders_sent` {`kind`, `result`}, `loadgen_orders_dropped` {`reason`}, `loadgen_backlog_size`.
   `twin.bicep` parameters and outputs are unchanged (ADR-015).

## Change log
| Date | Change | Told WS2/3/4/5? |
|---|---|---|
| 2026-10-28 | Version 1; repo is `livefire-team/livefire-fusion-poc`, image owner `livefire-team` | pending |
| 2026-10-29 | WS1 addition (G2): `candidate-<drill-id>-<attempt>` image tags (ADR-014) | pending |
| 2026-10-29 | WS1 addition (G2): load generator module, image and `loadgen_*` metrics (ADR-015) | pending |
| 2026-10-31 | WS2 addition: `twin.bicep` outputs `logAnalyticsWorkspaceName` and `logAnalyticsCustomerId` (used by WS2's `main.bicep`) | pending |
| 2026-11-05 | WS2 addition (G2): `twin.bicep` parameters `registryServer` and `pullIdentityId`; the twin's image comes from the lab's private registry (ADR-017) | pending |
| 2026-11-08 | WS1 addition (G2): candidate pushes run the security scans and bandit, and fail on files outside the allowed paths (ADR-020) | pending |
