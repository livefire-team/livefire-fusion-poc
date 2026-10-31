#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"
case "${1:?broad|narrow}" in
  broad)
    SCOPE="/subscriptions/$AZURE_SUBSCRIPTION_ID"
    if OUT=$(az role assignment create --assignee-object-id "$APP_IDENTITY_PRINCIPAL_ID" \
         --assignee-principal-type ServicePrincipal --role Contributor --scope "$SCOPE" -o none 2>&1); then
      az role assignment delete --assignee "$APP_IDENTITY_PRINCIPAL_ID" --role Contributor --scope "$SCOPE" -o none
      event recover.broad UNEXPECTED_ALLOW; echo "ALLOWED and removed: the policy is not in effect yet"; exit 3
    fi
    CODE=$(grep -oE 'RequestDisallowedByPolicy|AuthorizationFailed' <<<"$OUT" | head -1 || true)
    event recover.broad denied "{\"code\":\"${CODE:-unknown}\"}"
    echo "broad option denied: ${CODE:-unknown}" ;;
  narrow)
    "$(dirname "$0")/fault.sh" restore ;;
esac
