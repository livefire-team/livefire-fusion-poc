# Order service: Key Vault access recovery
Version 2. Owner: order-service team.

## When to use
Orders fail and the order service logs `SecretUnavailable`, or
`/health/dependencies` reports `"keyvault":"forbidden"`.

## Background
The order service reads its database password from Azure Key Vault via a
SecretProvider that caches successful reads for a short refresh window and
throttles retries after authentication failures. Once access to the vault is
restored, the service will automatically recover; a process restart should not
be required.

Key Vaults can use either RBAC or access policies for data-plane permissions.
The `kv-lf-4hvw4x4zd6qc2` vault currently uses access policies, where the
order-service principal needs secret permissions `get` and `list`.

## Steps
1. Confirm the symptom: `curl https://<order-app>/health/dependencies`
   shows `"keyvault":"forbidden"`, and orders are failing with
   `SecretUnavailable`.
2. Check the app identity's access on the vault.
   - If the vault uses access policies:
     - In the Azure Portal, open the Key Vault and review **Access policies**.
     - Ensure the order-service principal has secret permissions `get` and
       `list`.
   - If the vault uses RBAC:
     - Run `az role assignment list --scope <vault-id> --assignee
       <app-principal-id>`.
     - Ensure a suitable role such as `Key Vault Secrets User` is assigned.
3. Restore access if it is missing:
   - For access policies, add or update an access policy granting `get` and
     `list` for secrets to the order-service principal.
   - For RBAC, create the `Key Vault Secrets User` role assignment on the
     vault scope for the order-service principal.
4. Wait until `/health/dependencies` reports `"keyvault":"ok"`.
   Permission changes can take several minutes to propagate.
5. Verify recovery of the order path without restarting the process:
   - Once `"keyvault":"ok"` is reported, place a test order.
   - The order should succeed; SecretProvider will either use a cached secret
     value or refresh the secret once Key Vault allows access again.
6. If `/health/dependencies` reports `"keyvault":"ok"` but orders still
   fail with `SecretUnavailable`, capture logs and escalate to the
   order-service team; this indicates a behavior change not covered by this
   runbook.
