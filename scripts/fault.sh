#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"
ROLE_ID=4633458b-17de-408a-b874-0445c86b69e6          # Key Vault Secrets User
ASSIGNMENT_ID="$KEYVAULT_ID/providers/Microsoft.Authorization/roleAssignments/$APP_ACCESS_ASSIGNMENT_NAME"

status() {
  if [ "$KV_PERMISSION_MODEL" = rbac ]; then
    az role assignment list --scope "$KEYVAULT_ID" --assignee "$APP_IDENTITY_PRINCIPAL_ID" \
      --role "$ROLE_ID" --query 'length(@)' -o tsv
  else
    az keyvault show -n "$KEYVAULT_NAME" \
      --query "length(properties.accessPolicies[?objectId=='$APP_IDENTITY_PRINCIPAL_ID'])" -o tsv
  fi
}

case "$KV_PERMISSION_MODEL:${1:?inject|restore|status}" in
  rbac:inject)
    az role assignment delete --ids "$ASSIGNMENT_ID" -o none ;;
  rbac:restore)
    az role assignment create --name "$APP_ACCESS_ASSIGNMENT_NAME" --scope "$KEYVAULT_ID" --role "$ROLE_ID" \
      --assignee-object-id "$APP_IDENTITY_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal -o none ;;
  accessPolicy:inject)
    az keyvault delete-policy -n "$KEYVAULT_NAME" --object-id "$APP_IDENTITY_PRINCIPAL_ID" -o none ;;
  accessPolicy:restore)
    az keyvault set-policy -n "$KEYVAULT_NAME" --object-id "$APP_IDENTITY_PRINCIPAL_ID" \
      --secret-permissions get list -o none ;;
  *:status) echo "app access entries: $(status)"; exit 0 ;;
  *) echo "usage: fault.sh inject|restore|status"; exit 2 ;;
esac
event "fault.$1" ok "{\"model\":\"$KV_PERMISSION_MODEL\",\"entries_after\":$(status)}"
echo "fault.$1 done; app access entries: $(status)"
