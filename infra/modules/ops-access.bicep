// Path A: the recovery identity may add or remove only Key Vault Secrets User on the twin vault (WS2).
param vaultName string
param opsPrincipalId string
var rbacAdminRoleId = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: vaultName }

resource opsRbacAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, opsPrincipalId, rbacAdminRoleId)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rbacAdminRoleId)
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${kvSecretsUserRoleId}})) AND ((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/delete\'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${kvSecretsUserRoleId}}))'
  }
}

// Reader on the twin resource group, so the Ops identity's status checks work
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource opsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, opsPrincipalId, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
  }
}
