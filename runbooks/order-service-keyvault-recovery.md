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
5. Once `/health/dependencies` reports `"keyvault":"ok"`, send a test `POST /api/orders`
   request and verify that it succeeds and persists an order.
6. If `/health/dependencies` or orders continue to return `SecretUnavailable` for
   longer than the SecretProvider refresh window, the service may still be running
   a build that cached an old auth failure. Redeploy or restart the order-service
   and re-check `/health/dependencies`.
7. Recovery is complete when `/health/dependencies` returns HTTP 200 and
   orders are being created successfully.
