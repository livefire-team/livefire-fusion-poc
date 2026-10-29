# LiveFire Fusion PoC — WS1 (Twin and order service)

Read at the start of EVERY session: this file, then `docs/BUILD_STATUS.md`, then `docs/ADR.md`.

## Who I'm working with
A beginner developer. Guide every step: explain what/why in plain English, one small step at a time, define new terms
(add to `docs/GLOSSARY.md`), use AskUserQuestion for choices, never ask for or store passwords/tokens.

## Repo facts
- GitHub: https://github.com/livefire-team/livefire-fusion-poc (org `livefire-team`, public; shared by WS1 and WS2)
- Local path: `C:\Users\venka\projects\livefire-fusion-poc` (Windows 11, PowerShell)
- Image: `ghcr.io/livefire-team/order-service`

## Stack (fixed by the hackathon plan)
Python 3.12, FastAPI, Jinja2, pyodbc (ODBC 18), pytest; Azure Container Apps, Azure SQL, Key Vault, App Insights;
Bicep; azure-monitor-opentelemetry; GitHub Actions + GHCR; Docker Compose for local dev.
Specs (NOT in git, see ADR-004): `C:\Users\venka\projects\livefire-ws1-kit\reference\ws1-build-guide.txt` (the spec)
and `...\livefire-ws1-kit\reference\livefire-poc-plan.txt`. Never copy them into this repo.

## Workflow rules
1. TDD always: failing test first (show RED), minimal code (show GREEN), refactor. Coverage ≥ 80% on `src/order-service/app`.
   Non-Python: SQL runs twice locally; `az bicep build`; `docker build` + `/health` smoke test.
2. Never commit to `main`. Branch per concern, conventional commits, small PRs, PR template filled with real test output.
3. Merge gate: local tests pass + CI green + code-reviewer run + plain-English summary + the user explicitly approves
   ("Merge") -> `gh pr merge <N> --merge`. NEVER squash or rebase-merge (ADR-003). Never force-push.
   Ask before deleting branches or closing PRs.
4. Every architectural decision -> entry in `docs/ADR.md` before/with the code.
5. Update `docs/BUILD_STATUS.md` after every step/PR and before any session ends; commit and push it.
6. Use the git-lifecycle skill, superpowers skills (brainstorming, writing-plans, test-driven-development,
   systematic-debugging, verification-before-completion) and ECC agents (tdd-guide, code-reviewer, python-reviewer,
   security-reviewer, fastapi-reviewer) proactively. If a session does not have them loaded, follow the same
   discipline by hand and run a separate review pass (subagent) before asking to merge.

## Guardrails (do not violate)
- Also read `CLAUDE.local.md` (git-ignored, on the owner's PC): it holds the demo-specific guardrails.
  If it is missing, restore it from the kit's `templates/CLAUDE.md` before writing any order-service code.
- Never add demo-specific notes to tracked files (code comments, tests, docs, commit messages) — ADR-004.
- One replica (min=max=1); probes on `/health` only.
- `configure_azure_monitor(logger_name="orders")` at the very top of `main.py`, before FastAPI import.
- `catalog.py` and `sql/seed.sql` change together.
- Dockerfile base `python:3.12-slim-bookworm`; rehearse with `sha-` tags, not `:g1`.
- Contract changes -> update `contracts/twin-interface.md` and tell WS2/WS3/WS4/WS5 the same day.

## Security
No secrets in git, chat, or logs. `.local/` is git-ignored. DB passwords must not contain `;` `}` or `!`.
