# Order service: Key Vault access recovery
Version 2. Owner: order-service team.

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
5. When `/health/dependencies` returns HTTP 200 with body `{"keyvault":"ok","sql":"ok"}`,
   run a synthetic order-placement check (for example, the referee journey or
   a `POST /api/orders` call with a valid `sku`).
6. Recovery is complete only when both `/health/dependencies` reports
   `"keyvault":"ok"` and the order-placement check returns HTTP 201
   with a non-empty confirmation.
