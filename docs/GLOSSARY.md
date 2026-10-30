# Glossary

One-sentence definitions of terms used in this project, added the first time each comes up. Alphabetical.

| Term | Meaning |
|---|---|
| ADR | Architecture Decision Record: a short note in `docs/ADR.md` saying what we decided, why, and what else we considered. |
| Bicep | Microsoft's language for describing Azure resources as code; `az bicep build` checks it compiles. |
| Bicep module | A reusable Bicep file that another Bicep file calls with parameters and reads outputs from; ours is `infra/modules/twin.bicep`, called by WS2's `main.bicep`. |
| Branch | A separate line of work in git, so `main` stays untouched until a change is reviewed and merged. |
| Clone | Download a linked local copy of a GitHub repo, so you can work on it and push changes back. |
| CodeQL | GitHub's code-security scanner; free on public repos. |
| Commit | A saved snapshot of changes in git, with a message describing it. |
| Conventional commit | A commit message that starts with its type, e.g. `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`. |
| Docker Compose | A file (`docker-compose.yml`) describing several containers to start together with `docker compose up`. |
| `.env` file | A git-ignored file of local settings (like a generated password) that Docker Compose reads automatically. |
| Docker / container | A way to package an app with everything it needs so it runs the same everywhere; Docker Desktop runs them on Windows. |
| GHCR | GitHub Container Registry (`ghcr.io`): where our order-service container image is stored; names must be lowercase. |
| `gh` | The GitHub command-line tool: log in, create repos, open and merge PRs from the terminal. |
| Idempotent | Safe to run more than once: the second run changes nothing and doesn't fail. Our SQL scripts must be. |
| Managed identity | An Azure-managed login for an app (no password to store) that can be granted access to other resources, like our app reading Key Vault. |
| Merge commit | A commit that joins a branch into `main` while keeping every original commit; we never squash (ADR-003). |
| Noreply email | A private address GitHub gives you for commits, so your real email is not public. |
| Organisation (GitHub org) | A shared GitHub account that several people can own; ours is `livefire-team`. |
| PATH | The list of folders Windows searches when you type a command like `git`; programs started before an install keep the old list. |
| PR (pull request) | A request on GitHub to merge a branch into `main`, where changes are reviewed and checks run before merging. |
| Probe | A regular HTTP check the platform makes on a container (liveness: restart it if it fails; readiness: stop sending it traffic if it fails); ours both call `/health` (ADR-006). |
| Public / private repo | Who can read the code: anyone (public) or only invited people (private). Ours is public (ADR-002). |
| RBAC | Role-Based Access Control: Azure grants access by assigning a role (like "Key Vault Secrets User") to an identity on a resource. |
| Replica | One running copy of a container app; the twin runs exactly one (ADR-006). |
| Revision | An immutable version of a Container App's settings and image; a new one is created when the app's template changes. |
| Seed data | Starting rows loaded into a fresh database; ours is the two products in `sql/seed.sql`. |
| sqlcmd | Microsoft's command-line tool for running SQL against SQL Server; we run it inside the SQL container. |
| Squash merge | Merging a PR as one combined commit; forbidden here because it rewrites commit history (ADR-003). |
| Token | A long secret string proving to a service that it is you; never pasted into chat or files. |
| UAC prompt | The Windows "Allow this app to make changes?" dialog; only you click it. |
| WSL2 | A small Linux layer built into Windows that Docker Desktop runs on. |
| winget | Windows' built-in package installer (`winget install ...`). |
