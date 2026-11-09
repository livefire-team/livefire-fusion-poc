#!/usr/bin/env bash
# Entra mode (Build Steps section 6): registers the MCP server as an Entra-protected API with one app role per
# endpoint, and assigns each role to one agent identity. Afterwards deploy mcp.bicep with authMode=entra,
# mcpClientId=<printed client ID> and the three object IDs: the server then accepts only those three identities.
#   scripts/setup-entra.sh                                   register (or find) livefire-mcp; print its client ID
#   scripts/setup-entra.sh <planner-oid> <engineer-oid> <recovery-oid>   also assign the three app roles
# Needs: az signed in with rights to create an app registration and to assign app roles (Graph), jq, python3.
set -euo pipefail
NAME="${MCP_APP_NAME:-livefire-mcp}"
uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }

client=$(az ad app list --display-name "$NAME" --query "[0].appId" -o tsv)
if [ -z "$client" ]; then
  roles=$(mktemp)
  jq -n --arg p "$(uuid)" --arg e "$(uuid)" --arg r "$(uuid)" '[
    {allowedMemberTypes: ["Application"], description: "Planner evidence tools (read-only)",
     displayName: "MCP.Planner", isEnabled: true, value: "MCP.Planner", id: $p},
    {allowedMemberTypes: ["Application"], description: "Engineer repository tools (branch-only)",
     displayName: "MCP.Engineer", isEnabled: true, value: "MCP.Engineer", id: $e},
    {allowedMemberTypes: ["Application"], description: "Recovery tools (grant-gated execution)",
     displayName: "MCP.Recovery", isEnabled: true, value: "MCP.Recovery", id: $r}]' > "$roles"
  client=$(az ad app create --display-name "$NAME" --sign-in-audience AzureADMyOrg --app-roles "@$roles" \
    --query appId -o tsv)
  az ad app update --id "$client" --identifier-uris "api://$client"
  az ad app update --id "$client" --set api.requestedAccessTokenVersion=2
  az ad sp create --id "$client" -o none
  az ad sp update --id "$client" --set appRoleAssignmentRequired=true    # only assigned identities get a token
  rm -f "$roles"
  echo "registered $NAME"
fi
echo "MCP_CLIENT_ID=$client   (token audience api://$client)"

[ $# -eq 3 ] || { echo "next: rerun with the Planner, Engineer and Recovery agent object IDs (from WS4)"; exit 0; }
sp=$(az ad sp show --id "$client" --query id -o tsv)
for pair in "$1:MCP.Planner" "$2:MCP.Engineer" "$3:MCP.Recovery"; do
  oid="${pair%%:*}" role="${pair#*:}"
  role_id=$(az ad sp show --id "$client" --query "appRoles[?value=='$role'].id" -o tsv)
  [ -n "$role_id" ] || { echo "$NAME has no $role app role" >&2; exit 1; }
  if ! az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/$sp/appRoleAssignedTo" \
       --query "value[?principalId=='$oid' && appRoleId=='$role_id'] | length(@)" -o tsv | grep -q '^1$'; then
    az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/$sp/appRoleAssignedTo" \
      --body "{\"principalId\": \"$oid\", \"resourceId\": \"$sp\", \"appRoleId\": \"$role_id\"}" -o none
  fi
  echo "$role assigned to $oid"
done
echo "now deploy mcp.bicep with authMode=entra, mcpClientId=$client and plannerAgentObjectId / engineerAgentObjectId / recoveryAgentObjectId"
