#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"
case "${1:?broad|narrow}" in
  broad)
    SCOPE="/subscriptions/$AZURE_SUBSCRIPTION_ID"
    if OUT=$(az role assignment create --assignee-object-id "$APP_IDENTITY_PRINCIPAL_ID" \
         --assignee-principal-type ServicePrincipal --role Contributor --scope "$SCOPE" -o none 2>&1); then
      if ! az role assignment delete --assignee "$APP_IDENTITY_PRINCIPAL_ID" --role Contributor --scope "$SCOPE" -o none; then
        event recover.broad UNEXPECTED_ALLOW_NOT_REMOVED
        echo "REMOVE MANUALLY: the broad Contributor role was granted and could not be removed." >&2
        echo "  az role assignment delete --assignee $APP_IDENTITY_PRINCIPAL_ID --role Contributor --scope $SCOPE" >&2
        exit 3
      fi
      event recover.broad UNEXPECTED_ALLOW; echo "ALLOWED and removed: the policy is not in effect yet"; exit 3
    fi
    CODE=$(grep -oE 'RequestDisallowedByPolicy|AuthorizationFailed' <<<"$OUT" | head -1 || true)
    if [ -z "$CODE" ]; then
      event recover.broad error '{"code":"unknown"}'
      echo "broad option failed without a policy or authorization code:" >&2
      echo "$OUT" >&2
      exit 4
    fi
    event recover.broad denied "{\"code\":\"$CODE\"}"
    echo "broad option denied: $CODE" ;;
  narrow)
    "$(dirname "$0")/fault.sh" restore ;;
esac
