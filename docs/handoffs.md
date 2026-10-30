# Hand-offs from WS1 (Twin and order service)

What WS1 delivers to the other workstreams: names, paths and tags, in one place. The shared contract is
[`contracts/twin-interface.md`](../contracts/twin-interface.md); if this page and the contract ever disagree, the
contract wins and WS1 fixes this page.

## WS2 (lab and deployment)

### Image
- Image: `ghcr.io/livefire-team/order-service:g1` (the G1 tag).
- Immutable tags: `ghcr.io/livefire-team/order-service:sha-<short commit>` (7 characters), pushed by
  `.github/workflows/order-service.yml` on every push to `main`. Use a `sha-` tag for rehearsals so a later
  build can't change what runs.
- The package is made public after the first successful `main` run (ADR-002); from then on pulls need no
  credentials.
- Select the image for a deployment with:

  ```
  azd env set ORDER_IMAGE ghcr.io/livefire-team/order-service:g1
  ```

### Bicep module
- Path: `infra/modules/twin.bicep`. Parameters and outputs are listed in the contract.
- New output for `main.bicep`:

  ```bicep
  output APPINSIGHTS_CONNECTION_STRING string = twin.outputs.appInsightsConnectionString
  ```

- Two optional pass-through parameters: `principalType` (default `User`) and `secretRefreshSeconds`
  (default `30`; `10` while testing).

### Local stack (no Azure needed)
- `docker-compose.yml`: SQL Server (`sql`) and the order service (`orders`, on `http://127.0.0.1:8000`).
- `scripts/local-sql.ps1`: starts SQL, runs `sql/schema.sql` and `sql/seed.sql`, and creates the app's database
  user. Safe to run more than once. Generated local passwords go to git-ignored files (ADR-005, ADR-012).
- `scripts/local-access-drill.ps1`: walks the local stack through Key Vault access stages and prints what
  `/health`, `/health/dependencies` and `POST /api/orders` report at each one.

### SQL reset order
`payment_authorizations` references `orders`, so a reset deletes `payment_authorizations` first, then `orders`.
The `products` seed rows stay.

## WS3 (agents and evidence)

- Runbook: `runbooks/order-service-keyvault-recovery.md`.
- Commit references are shared directly.
- Telemetry in Application Insights:

| Kind | Name | Notes |
|---|---|---|
| Table | `requests` | Carries `customDimensions.drill_id` |
| Table | `exceptions` | Failed orders; carries `customDimensions.drill_id` when an `x-drill-id` header was sent |
| Log message | `order placed` | Info, with `drill_id` and `order_id` |
| Log message | `order failed` | Error with the exception, with `drill_id` and `sku` |
| Metric | `orders_completed` | Counter, +1 per placed order |
| Metric | `orders_failed` | Counter, +1 per failed order, tagged `reason` (the exception type) |

The drill ID comes from the `x-drill-id` request header (see the contract).

## WS4 (agent briefs)
WS4 engineer brief details are shared directly.

## WS5 (Control Center)

| View | Metric |
|---|---|
| Throughput | `orders_completed` |
| Failed orders | `orders_failed`, split by its `reason` tag |
