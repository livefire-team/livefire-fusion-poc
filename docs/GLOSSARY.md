# Glossary

One-sentence definitions of terms used in this project, added the first time each comes up. Alphabetical.

| Term | Meaning |
|---|---|
| ADR | Architecture Decision Record: a short note in `docs/ADR.md` saying what we decided, why, and what else we considered. |
| Bicep | Microsoft's language for describing Azure resources as code; `az bicep build` checks it compiles. |
| Bicep module | A reusable Bicep file that another Bicep file calls with parameters and reads outputs from; ours is `infra/modules/twin.bicep`, called by WS2's `main.bicep`. |
| Branch | A separate line of work in git, so `main` stays untouched until a change is reviewed and merged. |
| Cache | A copy of a value kept in memory so the app doesn't fetch it again every time; our secret provider caches the DB password. |
| CI (continuous integration) | Automatically testing and building every change on a server (for us, GitHub Actions) so problems show up before merging. |
| Clone | Download a linked local copy of a GitHub repo, so you can work on it and push changes back. |
| CodeQL | GitHub's code-security scanner; free on public repos. |
| Commit | A saved snapshot of changes in git, with a message describing it. |
| Container registry | An online store for container images that platforms pull from; ours is GHCR. |
| Conventional commit | A commit message that starts with its type, e.g. `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`. |
| Coverage (test coverage) | The share of code lines that the tests actually run, measured with `pytest --cov`; we require at least 80% on `src/order-service/app`. |
| Dependency override | A FastAPI feature (`app.dependency_overrides`) that swaps a dependency for a test stand-in; our tests use pytest's monkeypatch instead because `main.py` uses module-level objects. |
| Docker / container | A way to package an app with everything it needs so it runs the same everywhere; Docker Desktop runs them on Windows. |
| Docker Compose | A file (`docker-compose.yml`) describing several containers to start together with `docker compose up`. |
| Endpoint | One URL path plus method that the app answers, like `GET /health` or `POST /api/orders`. |
| `.env` file | A git-ignored file of local settings (like a generated password) that Docker Compose reads automatically. |
| `gh` | The GitHub command-line tool: log in, create repos, open and merge PRs from the terminal. |
| GHCR | GitHub Container Registry (`ghcr.io`): where our order-service container image is stored; names must be lowercase. |
| GitHub Actions | GitHub's built-in CI service: it runs the workflows in `.github/workflows/` on GitHub's machines. |
| Health check | An endpoint that reports whether the app (`/health`) or what it depends on (`/health/dependencies`) is working. |
| Idempotent | Safe to run more than once: the second run changes nothing and doesn't fail. Our SQL scripts must be. |
| Image tag | The label after the colon in an image name (like `:g1` or `:sha-1a2b3c4`) that picks one version of the image (ADR-010). |
| Jinja2 template | An HTML file with `{{ ... }}` placeholders and `{% ... %}` loops that FastAPI fills in to draw a page; ours are in `app/templates/`. |
| Job | One group of steps in a workflow that runs on its own fresh machine; ours are `test` and `image`, and `image` waits for `test`. |
| Managed identity | An Azure-managed login for an app (no password to store) that can be granted access to other resources, like our app reading Key Vault. |
| Merge commit | A commit that joins a branch into `main` while keeping every original commit; we never squash (ADR-003). |
| Monkeypatch | A pytest helper that temporarily replaces a function or object during one test (like the database calls) and puts it back afterwards. |
| Noreply email | A private address GitHub gives you for commits, so your real email is not public. |
| OpenTelemetry | An open standard and library for traces, metrics and logs; `azure-monitor-opentelemetry` sends ours to Application Insights. |
| Organisation (GitHub org) | A shared GitHub account that several people can own; ours is `livefire-team`. |
| PATH | The list of folders Windows searches when you type a command like `git`; programs started before an install keep the old list. |
| PR (pull request) | A request on GitHub to merge a branch into `main`, where changes are reviewed and checks run before merging. |
| Probe | A regular HTTP check the platform makes on a container (liveness: restart it if it fails; readiness: stop sending it traffic if it fails); ours both call `/health` (ADR-006). |
| Public / private repo | Who can read the code: anyone (public) or only invited people (private). Ours is public (ADR-002). |
| pytest | Python's test runner: it finds functions named `test_...` and reports which pass or fail. |
| RBAC | Role-Based Access Control: Azure grants access by assigning a role (like "Key Vault Secrets User") to an identity on a resource. |
| Replica | One running copy of a container app; the twin runs exactly one (ADR-006). |
| Revision | An immutable version of a Container App's settings and image; a new one is created when the app's template changes. |
| Seed data | Starting rows loaded into a fresh database; ours is the two products in `sql/seed.sql`. |
| Smoke test | A quick check that something basically works, like starting the container and calling `/health`, before deeper testing or publishing. |
| Span | One timed step inside a trace (like `place_order`), which can carry attributes such as `drill_id`. |
| sqlcmd | Microsoft's command-line tool for running SQL against SQL Server; we run it inside the SQL container. |
| Squash merge | Merging a PR as one combined commit; forbidden here because it rewrites commit history (ADR-003). |
| TestClient | FastAPI's in-process test browser: it calls the app's endpoints without starting a server. |
| Token | A long secret string proving to a service that it is you; never pasted into chat or files. |
| TTL / refresh window | How long a cached value is trusted before it is fetched again; for the DB password it is `SECRET_REFRESH_SECONDS`. |
| UAC prompt | The Windows "Allow this app to make changes?" dialog; only you click it. |
| Virtual environment (venv) | A private folder of Python packages for one project (ours is the git-ignored `.venv`), so its pinned versions don't clash with other projects. |
| winget | Windows' built-in package installer (`winget install ...`). |
| Workflow | A YAML file in `.github/workflows/` that tells GitHub Actions when to run (triggers) and what to do (jobs); ours is `order-service.yml`. |
| WSL2 | A small Linux layer built into Windows that Docker Desktop runs on. |
