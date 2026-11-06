# Rebuild timing

How long the whole lab platform (twin and control plane) takes to rebuild from nothing with one command, and whether
it tears down cleanly. Measured in a throwaway azd environment, so the shared environment keeps its vaults and keys.

## 2026-11-06, `lf-rb` (eastus2, lab subscription)

Same settings as the shared environment: access-policy vault model, 10 s secret refresh, the deny policy and the
broad-attempt role on. The order service started from its GHCR image (`sha-<7>`); `images` then moved every image to
the new private registry as `sha-<40>`.

### Rebuild: `time scripts/deploy.sh all`: 10 min 23 s, first try (target: under 30)

| Phase | What it did | Minutes |
| --- | --- | --- |
| `infra` | `azd provision`: both resource groups, registry, vaults, evidence store, both Container Apps environments, SQL, the order app; then the postprovision hook (schema, users, secrets, a baseline Referee run: PASS) | 5.0 |
| `images` | three `az acr import` from GHCR | 1.6 |
| `apps` | `azd provision` again: `ca-ops`, `job-referee`, `job-ops-smoke`; the hook's baseline: PASS | 3.7 |
| `verify` | internal-only ingress, the jobs, the evidence check: passed | 0.1 |
| **Total** | | **10.4** |

- The slowest resources were the SQL server (1 min 10 s) and the control Container Apps environment (1 min 2 s).
- No waits were needed. The evidence check's data role and `id-lf-ops`'s broad-attempt role had both applied by the
  time they were used.
- Proof: `scripts/deploy.sh smoke all` passed on the first try right after (8 min 36 s), including the Azure Policy
  refusal for the new `id-lf-ops`.

### Teardown: completed, 41 minutes with one failed attempt (about 17 without)

| Step | Result | Minutes |
| --- | --- | --- |
| `python scripts/evidence_unlock.py --yes` | removed every version policy, but could not delete the 22 current versions (`403 OperationNotAllowedOnRootBlob`) | 1 |
| `azd down --force --purge` | failed on the evidence storage account: `AccountProtectedFromDeletion` | 21 |
| the fixed `evidence_unlock.py` (PR #28), then delete the empty `evidence` container | every version deleted; then the account could be deleted | 1 |
| `azd down --force --purge`, again | both resource groups deleted (the twin group took 15 min), twin vault purged | 16 |
| by hand | purged the control vault; removed `id-lf-ops`'s subscription-scope role assignment | 0.2 |

What the failures showed:
- **Current blob versions.** Azure refuses to delete a blob's current version by its version id. The unlock now
  deletes it through the blob itself (PR #28).
- **The empty container.** A container with version-level immutability blocks deleting its storage account, even
  when it is empty. The unlock now deletes the container once nothing is left (PR #28).
- **The control vault.** It was deleted during the failed run, before `azd down` reached its purge step. The second
  run purged only the vault it deleted itself, so the control vault stayed soft-deleted under its fixed name.
- **The subscription-scope role.** `azd down` deletes resource groups, so `id-lf-ops`'s Role Based Access Control
  Administrator assignment on the subscription stayed behind. It was orphaned, because its identity was gone.

Left in place on purpose: the subscription-wide deny policy. It is shared, and `scripts/deploy.sh policy-off`
removes it.

## Next teardown of a second environment

Select that environment first (`azd env select <name>`); the unlock reads the selected one.

1. If the environment had `BROAD_ATTEMPT_ROLE` on: `az role assignment delete --assignee "$(azd env get-value
   OPS_PRINCIPAL_ID)" --role "Role Based Access Control Administrator" --scope "/subscriptions/$(azd env get-value
   AZURE_SUBSCRIPTION_ID)"`. Do not use `policy-off` here: it also removes the deny policy every environment shares.
2. `python scripts/evidence_unlock.py --yes`
3. `azd down --force --purge`
4. If step 3 failed partway, `az keyvault list-deleted` and `az keyvault purge --name <vault>` for that
   environment's vaults before trying again.
5. `azd env select lf-eh && rm -rf .azure/<name>`
