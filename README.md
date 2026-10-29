# livefire-fusion-poc
LiveFire Fusion PoC - twin, order service, governed repair loop

Shared repo for WS1 (twin and order service) and WS2 (platform and deployment).

## Where things live
| Path | What | Owner |
|---|---|---|
| `src/order-service/` | FastAPI order service, templates, tests, Dockerfile | WS1 |
| `sql/` | Database schema and seed data | WS1 |
| `infra/modules/twin.bicep` | Disposable twin module (deployed by WS2's `azd up`) | WS1 |
| `runbooks/` | Order-service recovery runbook | WS1 |
| `contracts/twin-interface.md` | Names, paths, outputs and image tag other workstreams rely on | WS1 + WS2 |
| `.github/workflows/` | CI: tests, scans, image to `ghcr.io/livefire-team/order-service` | WS1 |
| `docs/` | ADRs, build status, glossary | all |

## Working here
Branch per change, PR for everything, merge commits only (never squash). See `CLAUDE.md` and `docs/ADR.md`.
