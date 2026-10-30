# Order service: Key Vault access recovery
Version 1. Owner: order-service team.

## When to use
Orders fail and the order service logs `SecretUnavailable`, or
`/health/dependencies` reports `"keyvault":"forbidden"`.

## Steps
1. Confirm the symptom: `curl https://<order-app>/health/dependencies`
   shows `"keyvault":"forbidden"`.
2. Check the app identity's access on the vault:
   `az role assignment list --scope <vault-id> --assignee <app-principal-id>`
3. If the Key Vault Secrets User assignment is missing, restore it on the vault only:
   `az role assignment create --role "Key Vault Secrets User" --scope <vault-id>
   --assignee-object-id <app-principal-id> --assignee-principal-type ServicePrincipal`
4. Wait until `/health/dependencies` reports `"keyvault":"ok"`.
   Role changes can take several minutes.
5. Recovery is complete when `/health/dependencies` returns HTTP 200.
