// WS2 control resource group, G1 version: the two identities only.
// G2 adds the Container Apps environment, the control Key Vault, the evidence storage, the Ops Service and the
// referee job, and outputs environmentId, keyVaultName and evidenceAccountName for WS3, WS4 and WS5.
param location string

resource opsId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-ops'
  location: location
}

resource refereeId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-referee'
  location: location
}

output opsPrincipalId string = opsId.properties.principalId
output opsClientId string = opsId.properties.clientId
output refereePrincipalId string = refereeId.properties.principalId
output refereeClientId string = refereeId.properties.clientId
