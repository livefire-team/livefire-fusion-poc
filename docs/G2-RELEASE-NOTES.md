# WS4 G2 preparation release notes — 2026-11-05

**Package status:** prepared and statically checked; **not published to GitHub** and **not live-Azure verified**.

## Files from original WS4 v2 starter (retained)

- `src/drill-runner/livefire/` workflow, policies, ports, contracts, evidence, adapters and stubs.
- `src/drill-runner/agents/`, fixtures, evaluations and all original tests.
- `infra/modules/foundry.bicep`, `infra/modules/drill-runner.bicep`, `infra/main.ws4-snippet.bicep`.
- `contracts/`, `.github/workflows/drill-runner.yml`, existing `scripts/`, `README-WS4.md`.

## Additions/changes in this G2 preparation

1. **Added** `docs/WS4-G2-BUILD-STEPS.md`: 48 detailed numbered steps, commands, acceptance and troubleshooting (Windows and lab).
2. **Added** `docs/G2-ACCEPTANCE-MATRIX.md`: 20 auditable G2 requirements, owners and explicit NOT RUN/BLOCKED statuses.
3. **Added** `docs/G2-HANDOFFS.md`: WS1, WS2, WS3 and WS5 owner coordination, concrete repo and integration seams.
4. **Added** `scripts/g2-preflight.py`: offline files/tool-catalog/schema-version checks, optional WS1 image tag mismatch detection, optional environment variable-name readiness (no secret contents printed).
5. **Added** `tests/test_g2_preflight.py`: five new standard-library unit tests of static preflight.
6. **Added** `.env.g2.example`: placeholders and repository separation reminders, no actual credentials.
7. **Updated** `scripts/agent-smoke.py`: Planner options/brief and Engineer secret-validation failure cause exit code 2; Engineer is not called after invalid Planner outputs. This is a G2 fail-closed safety improvement, **not** a claim that live Foundry is tested.
8. **Updated** `README-WS4.md`: links to G2 work package.
9. **Updated** `.gitignore`: ignore local `.env`, `.env.*`, `.g2-output/` and logs; allow the empty placeholder `.env.g2.example`.

## Preparation-time verification (not live lab)

- `python scripts/g2-preflight.py --repo-root . --ws1-root <uploaded-WS1-root>`: file, frozen v1.0 and six-tool assertions **PASS**; SHA image tag mismatch **WARN**; Azure smoke status **WARN/NOT VERIFIED**.
- `python -m unittest discover -s tests -p test_g2_preflight.py -v`: **5 tests passed** in the preparation environment.
- `python -m py_compile scripts/g2-preflight.py scripts/agent-smoke.py tests/test_g2_preflight.py`: passed in the preparation environment.
- No real Foundry/model, WS3 MCP, GitHub candidate branch, WS2 Ops, Blob, runner container build, Azure job or GitHub Actions run performed during package preparation.
- The original starter README reports its author's **33 passing G1 tests** as of Oct 23. That result has **not** been reproduced by this package preparation environment because `agent_framework` and Azure packages were not installed there.

## Known cross-team blockers

- WS1 CI uses 7-character SHA image tags; the WS4 runner generates a 40-character SHA tag and the Ops contract expects 40.
- Uploaded WS2 source/report does not confirm a deployed live `/actions/*` Ops Service endpoint.
- The user mentioned `mdfiles.zip` and `ws3-mcp-server-main.zip`, neither of which appears among the current mounted uploads; available WS3 starter was reviewed instead.
- No GitHub write connector is enabled in this chat environment; the GitHub integration is disabled by the user's organization. Use your authorized GitHub Desktop/CLI clone and open a PR into `livefire-team/ws4-new`.

**Release criteria:** Do not represent this package as a passed G2 gate until real agent-level tests and owner sign-off populate `docs/G2-ACCEPTANCE-MATRIX.md`.
