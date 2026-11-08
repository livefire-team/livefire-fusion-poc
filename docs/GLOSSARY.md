# Glossary

One-sentence definitions of terms used in this project, added the first time each comes up. Alphabetical.

| Term | Meaning |
|---|---|
| Access policy (Key Vault) | The older way to grant Key Vault access: a list on the vault itself saying which identity may do what (e.g. get and list secrets); the alternative is RBAC. |
| ACR (Azure Container Registry) | Azure's private container registry; the lab's `acrlf<suffix>` holds every image the lab runs, pulled with the AcrPull-only `id-lf-acrpull` identity. |
| ADR | Architecture Decision Record: a short note in `docs/ADR.md` saying what we decided, why, and what else we considered. |
| Architecture note | `docs/architecture.md`: a one-page description of the order service's parts, request flow, settings and telemetry. |
| Azure Policy | Rules Azure checks on every create or change request, after the role check; a `deny` rule refuses the request even for an Owner (error `RequestDisallowedByPolicy`). |
| Backlog (load generator) | The load generator's in-memory list of orders that failed and will be tried again later, with growing waits between tries. |
| Bicep | Microsoft's language for describing Azure resources as code; `az bicep build` checks it compiles. |
| Bicep module | A reusable Bicep file that another Bicep file calls with parameters and reads outputs from; ours is `infra/modules/twin.bicep`, called by WS2's `main.bicep`. |
| Branch | A separate line of work in git, so `main` stays untouched until a change is reviewed and merged. |
| CA bundle (certificate bundle) | A file listing the certificate authorities a program trusts for secure (HTTPS) connections; `az` uses its own, so on a network with SSL inspection we point `REQUESTS_CA_BUNDLE` at `.local/az-ca-bundle.pem`, which adds the company's inspection certificate. |
| Cache | A copy of a value kept in memory so the app doesn't fetch it again every time; our secret provider caches the DB password. |
| Candidate branch | A branch named `candidate/<drill-id>-<attempt>` holding a proposed change; CI builds it and publishes a `candidate-<drill-id>-<attempt>` image for a trial deploy. |
| CI (continuous integration) | Automatically testing and building every change on a server (for us, GitHub Actions) so problems show up before merging. |
| Clone | Download a linked local copy of a GitHub repo, so you can work on it and push changes back. |
| CodeQL | GitHub's code-security scanner that reads our Python code for security bugs; free on public repos, runs in `security.yml`. |
| Commit | A saved snapshot of changes in git, with a message describing it. |
| Container Apps Job | An Azure Container Apps resource that runs a container to completion when started (by hand or on a schedule) instead of serving traffic; our load generator is one. |
| Container registry | An online store for container images that platforms pull from; ours is GHCR. |
| Conventional commit | A commit message that starts with its type, e.g. `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`. |
| Coverage (test coverage) | The share of code lines that the tests actually run, measured with `pytest --cov`; we require at least 80% on `src/order-service/app`. |
| Custom role (Azure) | A role we define ourselves with only the actions it lists, e.g. "restart this one order app"; used so `id-lf-ops` gets no broader right than it needs. |
| CVE | Common Vulnerabilities and Exposures: the public ID (like `CVE-2026-12345`) given to a known security flaw in a piece of software. |
| Dependency override | A FastAPI feature (`app.dependency_overrides`) that swaps a dependency for a test stand-in; our tests use pytest's monkeypatch instead because `main.py` uses module-level objects. |
| Digest (image digest) | An image's `sha256:...` fingerprint; unlike a tag it can never point at different contents, so the Ops Service deploys by digest. |
| Docker / container | A way to package an app with everything it needs so it runs the same everywhere; Docker Desktop runs them on Windows. |
| Docker Compose | A file (`docker-compose.yml`) describing several containers to start together with `docker compose up`. |
| Docker Compose service | One named container entry in `docker-compose.yml` (ours are `sql` and `orders`) that you can start, restart or stop by name. |
| Drill | A planned practice run of an incident, where you change one thing on purpose and record what the system reports; `scripts/local-access-drill.ps1` is our local one. |
| Endpoint | One URL path plus method that the app answers, like `GET /health` or `POST /api/orders`. |
| `.env` file | A git-ignored file of local settings (like a generated password) that Docker Compose reads automatically. |
| Exponential backoff | Waiting longer after each failed retry (2 s, 4 s, 8 s ... up to a cap) so a struggling service is not flooded. |
| Fake twin | An in-memory stand-in for the Azure twin inside the Ops Service (`TWIN_BACKEND=fake`), for tests and local runs without Azure. |
| Federated credential (OIDC) | A trust set up on an Azure identity so a GitHub Actions job can sign in with a short-lived token GitHub issues, with no stored password. |
| `gh` | The GitHub command-line tool: log in, create repos, open and merge PRs from the terminal. |
| GHCR | GitHub Container Registry (`ghcr.io`): where our order-service container image is stored; names must be lowercase. |
| GitHub Actions | GitHub's built-in CI service: it runs the workflows in `.github/workflows/` on GitHub's machines. |
| gitleaks | A scanner that searches the whole git history for committed secrets such as passwords and keys; runs in `security.yml`. |
| Health check | An endpoint that reports whether the app (`/health`) or what it depends on (`/health/dependencies`) is working. |
| HMAC | A signature made from a message and a secret key; anyone without the key can't make a valid one. The Ops Service's grants use HMAC-SHA256. |
| Idempotent | Safe to run more than once: the second run changes nothing and doesn't fail. Our SQL scripts must be. |
| Image tag | The label after the colon in an image name (like `:g1` or `:sha-1a2b3c4`) that picks one version of the image (ADR-010). |
| Immutability policy (Blob) | A rule on a storage container or blob version that refuses deletes and changes for a set time; the evidence container uses one per version. |
| Internal ingress | A Container Apps setting that makes an app reachable only from inside its Container Apps environment (its address contains `.internal.`). |
| Jinja2 template | An HTML file with `{{ ... }}` placeholders and `{% ... %}` loops that FastAPI fills in to draw a page; ours are in `app/templates/`. |
| JMESPath | The small language the Azure CLI's `--query` flag uses to pick fields out of a command's JSON result before it is printed (like `tables[0].rows`). |
| Job | One group of steps in a workflow that runs on its own fresh machine; ours are `test` and `image`, and `image` waits for `test`. |
| KQL | Kusto Query Language: the language for searching App Insights and Log Analytics data (like `exceptions \| where timestamp > ago(1h)`); passed with `--analytics-query`. |
| Load generator | `src/load-generator/`: a small program that places orders at a steady rate so the order service has real traffic and throughput numbers. |
| Managed identity | An Azure-managed login for an app (no password to store) that can be granted access to other resources, like our app reading Key Vault. |
| Merge commit | A commit that joins a branch into `main` while keeping every original commit; we never squash (ADR-003). |
| Monkeypatch | A pytest helper that temporarily replaces a function or object during one test (like the database calls) and puts it back afterwards. |
| Noreply email | A private address GitHub gives you for commits, so your real email is not public. |
| OpenSSL | The library programs use for encrypted connections (TLS); ODBC Driver 18 needs version 1.0, 1.1 or 3, not 4. |
| OpenTelemetry | An open standard and library for traces, metrics and logs; `azure-monitor-opentelemetry` sends ours to Application Insights. |
| Ops Service | WS2's FastAPI service (`ca-ops`, `src/ops-service/`) that performs every drill action on the twin for the other workstreams, so they hold no Azure rights themselves. |
| Organisation (GitHub org) | A shared GitHub account that several people can own; ours is `livefire-team`. |
| Orphaned role assignment | A role assignment whose identity has been deleted; it grants nothing but stays listed ("Identity not found") until removed, and `azd down` never removes subscription-level ones. |
| PATH | The list of folders Windows searches when you type a command like `git`; programs started before an install keep the old list. |
| pip-audit | A tool that checks our pinned Python packages against databases of known vulnerabilities. |
| Playwright | A tool that drives a real browser from code; `journeys/test_order_journey.py` uses it to place an order like a customer. |
| Policy exemption | A record that switches an Azure Policy off for one scope (like a resource group) without deleting the policy; anyone who can manage policies, such as an Owner, can create one. |
| PR (pull request) | A request on GitHub to merge a branch into `main`, where changes are reviewed and checks run before merging. |
| Probe | A regular HTTP check the platform makes on a container (liveness: restart it if it fails; readiness: stop sending it traffic if it fails); ours both call `/health` (ADR-006). |
| Propagation | The delay between changing a setting in Azure (like removing access) and every part of Azure acting on it; `scripts/measure-propagation.sh` measures it for Key Vault access. |
| Public / private repo | Who can read the code: anyone (public) or only invited people (private). Ours is public (ADR-002). |
| pytest | Python's test runner: it finds functions named `test_...` and reports which pass or fail. |
| RBAC | Role-Based Access Control: Azure grants access by assigning a role (like "Key Vault Secrets User") to an identity on a resource. |
| Replica | One running copy of a container app; the twin runs exactly one (ADR-006), except for a few seconds during a rolling restart. |
| Revision | An immutable version of a Container App's settings and image; a new one is created when the app's template changes. |
| Rolling restart | A restart that starts the new replica first and stops the old one only once the new one is ready, so the app never goes down. `az containerapp revision restart` works this way and returns before the swap is done. |
| SARIF | A standard JSON format for scanner results; CodeQL uploads SARIF so findings show in GitHub's Security tab. |
| Seed data | Starting rows loaded into a fresh database; ours is the two products in `sql/seed.sql`. |
| ShellCheck | A checker that finds mistakes in shell scripts; run as `(cd scripts && shellcheck -x ./*.sh)`. |
| Signed grant | A short-lived, single-use permission slip (`lfg1....`) signed with HMAC that the agent key must present for a recovery action. |
| Smoke test | A quick check that something basically works, like starting the container and calling `/health`, before deeper testing or publishing. |
| Soft delete / purge (Key Vault) | A deleted vault is kept for a few days (soft delete) and its name stays taken; purging removes it for good, which `azd down --purge` does for the vaults it deletes. |
| Span | One timed step inside a trace (like `place_order`), which can carry attributes such as `drill_id`. |
| sqlcmd | Microsoft's command-line tool for running SQL against SQL Server; we run it inside the SQL container. |
| Squash merge | Merging a PR as one combined commit; forbidden here because it rewrites commit history (ADR-003). |
| SSL inspection | A company network feature that opens and re-signs secure traffic with the company's own certificate so it can be checked; programs that don't trust that certificate fail with `CERTIFICATE_VERIFY_FAILED`. |
| Stacked PR | A PR whose branch starts from another open PR's branch; it shows both PRs' commits until the first one merges. |
| Stand-in | A simple local replacement for a real service, used so the app can run without it; our local stand-in for Key Vault is the file `.local/secret.txt` (ADR-012). |
| Symlink (symbolic link) | A file that just points to another file or folder, like a shortcut; Homebrew's `opt/openssl` is one. |
| Teardown | Deleting a whole environment's Azure resources (`azd down`), rehearsed in a throwaway environment so the shared one is untouched. |
| TestClient | FastAPI's in-process test browser: it calls the app's endpoints without starting a server. |
| Token | A long secret string proving to a service that it is you; never pasted into chat or files. |
| Token subject (OIDC `sub`) | The line in GitHub's sign-in token that says which repo and environment the job runs in. Azure accepts the token only if it exactly matches a federated credential's subject. With GitHub's *immutable subject* format it also carries the org's and repo's permanent numeric IDs (`repo:livefire-team@349630330/livefire-fusion-poc@1437908536:environment:acr-push`). |
| Trivy | A scanner for known vulnerabilities and misconfigurations in files, Dockerfiles and container images. |
| TTL / refresh window | How long a cached value is trusted before it is fetched again; for the DB password it is `SECRET_REFRESH_SECONDS`. |
| UAC prompt | The Windows "Allow this app to make changes?" dialog; only you click it. |
| Virtual environment (venv) | A private folder of Python packages for one project (ours is the git-ignored `.venv`), so its pinned versions don't clash with other projects. |
| winget | Windows' built-in package installer (`winget install ...`). |
| Workflow | A YAML file in `.github/workflows/` that tells GitHub Actions when to run (triggers) and what to do (jobs); ours is `order-service.yml`. |
| Worktree (git) | A second folder checked out from the same repo, on its own branch, so two branches can be open at once (`git worktree add`). |
| WSL2 | A small Linux layer built into Windows that Docker Desktop runs on. |
