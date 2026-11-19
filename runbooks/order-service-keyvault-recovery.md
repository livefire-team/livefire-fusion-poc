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
4. Wait until `/health/dependencies` returns HTTP 200 with `"keyvault":"ok"` and `"sql":"ok"`.
   Role changes can take several minutes.
5. Validate end-to-end recovery by placing a test order:
   - Either walk a browser through the checkout flow, or
   - Call the JSON API, for example:
     `curl -X POST https://<order-app>/api/orders \
       -H 'Content-Type: application/json' \
       -d '{"sku":"<valid-sku>"}'`.
   The request must return HTTP 200/201 with an order confirmation, and the order
   should be visible in the database.
6. Recovery is complete only after the test order succeeds. If it still fails
   with `SecretUnavailable` or another 5xx error, continue troubleshooting
   identity / Key Vault access and application logs.
