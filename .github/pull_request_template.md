## What and why
<!-- One or two plain-English sentences. -->

## Changes
-

## How I tested it locally (paste real output)
```
pytest -q ...
```
- [ ] Failing test written first (RED) and now passing (GREEN)
- [ ] Coverage >= 80% on touched app code
- [ ] Non-Python check run (SQL twice / `az bicep build` / `docker build` + smoke test) if relevant

## Checklist
- [ ] ADR entry added or updated (`docs/ADR.md`) if this is an architectural decision
- [ ] `docs/BUILD_STATUS.md` updated
- [ ] Demo guardrails respected (no bug comments/tests, 1 replica, `/health` probes, no squash)
- [ ] Contract change? If yes, `contracts/twin-interface.md` updated and other workstreams told
- [ ] Code review (code-reviewer / security-reviewer) findings addressed
- [ ] No secrets in the diff

## Rollback
<!-- How to undo: e.g. revert this PR's merge commit. -->

## Merge
Merge with a **merge commit** (not squash), only after the owner approves.
