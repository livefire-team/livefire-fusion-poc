# WS4 G2 acceptance matrix — due 2026-11-09

> Fill in **Observed result** only after an actual run. Allowed status values: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`. The `NOT RUN` entries below are intentional; they are not certifications. Record a sanitized URL or local path for each proof. Do not commit real access tokens, private keys, .env files or secrets.

| ID | Acceptance item | Owner | Status | Observed result / evidence reference | Blocker / next action |
|---|---|---|---|---|---|
| G2-01 | WS4 test suite runs on Python 3.12 | WS4 | NOT RUN | | Execute `pytest -q` in `src/drill-runner` |
| G2-02 | Frozen schemas generated/consistent, v1.0 | WS4 | NOT RUN | | `export_schemas.py`, contract tests, diff |
| G2-03 | Offline T-01 stub concludes `VERIFIED` and package seal verifies | WS4 | NOT RUN | | `runner --stub`; `verify_package.py` |
| G2-04 | Azure project/model/quota/identity verified in CloudLabs | WS2+WS4 | NOT RUN | | Lab outputs and role check |
| G2-05 | WS3 MCP HTTP endpoint deployed and real Azure evidence backend works | WS3+WS4 | NOT RUN | | MCP URL, health, trace/evidence refs |
| G2-06 | Foundry Planner agent version created from YAML and verified | WS4 | NOT RUN | | Record `lf-planner:<pin>` and `--verify` |
| G2-07 | Foundry Engineer agent version created from YAML and verified | WS4 | NOT RUN | | Record `lf-engineer:<pin>` and `--verify` |
| G2-08 | Planner alone returns valid options+brief via real WS3 evidence | WS4+WS3 | NOT RUN | | `agent-smoke.py`, structured-output checks, MCP trace |
| G2-09 | Cross-role Planner key on Engineer MCP returns HTTP 403, logged | WS3+WS4 | NOT RUN | | Scripted 403; redacted tool-call deny event |
| G2-10 | Engineer alone creates branch/test/runbook patch with valid ChangeReport | WS4+WS3+WS1 | NOT RUN | | Requires WS1 approval and real GitHub backend |
| G2-11 | Candidate branch triggers passing WS1 CI and GHCR publishes image | WS1+WS4 | NOT RUN | | Record branch SHA, image and CI run URL |
| G2-12 | Full SHA image-tag mismatch resolved by WS1/WS2/WS4 | WS1+WS2+WS4 | BLOCKED | Uploaded WS1 CI `:sha-<7>`; WS4 runner + Ops contract `:sha-<40>` | Team decides/publishes compatible tag or approves contract update |
| G2-13 | WS2 Ops Service reachable with validated action/result contract | WS2+WS4 | NOT RUN | | Ops endpoint/status unknown in uploaded material |
| G2-14 | WS4 Docker image builds and WS4 Actions succeeds | WS4 | NOT RUN | | Docker host / Actions CI required |
| G2-15 | WS5 shares WS4's event source and displays live stages/approvals | WS5+WS4 | NOT RUN | | Confirm directory/Blob and schema |
| G2-16 | Evidence package redaction and integrity checks pass | WS4 | NOT RUN | | `verify_package.py`, review secret-free package |
| G2-17 | Runner Job Bicep integrated into WS2 root and validates | WS2+WS4 | NOT RUN | | WS2 final outputs, principal, Key Vault secrets |
| G2-18 | Runner job receives a unique `DRILL_ID` at invocation | WS2+WS4 | NOT RUN | | Confirm job start command / execution |
| G2-19 | PR to `ws4-new` opened, reviewed, and CI green | WS4+reviewer | NOT RUN | | Requires GitHub Write access |
| G2-20 | G3 dependencies, owners and fallback path documented | WS4 lead | NOT RUN | | Use `G2-HANDOFFS.md` |

## Sign-off

- G2 status: **NOT YET ASSESSED**
- WS4 owner: ______________________
- Reviewer: ______________________
- Signed on (UTC): ______________________
- WS4 commit SHA / PR: ______________________
- Azure subscription/resource group (non-secret identifiers): ______________________
- Foundry Planner pin: ______________________
- Foundry Engineer pin: ______________________
- Real MCP trace ID(s): ______________________
- Candidate branch / CI URL (if authorized): ______________________
- Known BLOCKED/FAIL entries accepted for limited G2 demo by: ______________________

A PASS for **the live-agent portion** of G2 requires observed independent real Planner and Engineer calls; an offline runner passing on stubs is useful but does not meet that claim.
