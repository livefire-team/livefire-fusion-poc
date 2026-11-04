// WS2, G2: what id-lf-ops may do in the twin resource group, and nothing more.
// - read the twin (status checks)
// - operate the order app: read, update its template, restart a revision, list replicas
// - change only the order app identity's Key Vault access: on the rbac model, add or remove only
//   Key Vault Secrets User (conditional RBAC Administrator); on the accessPolicy model, write access policies
//   on the twin vault alone (a custom role scoped to that one vault)
param opsPrincipalId string
param vaultName string
@allowed(['rbac', 'accessPolicy'])
param kvPermissionModel string

var roles = {
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  rbacAdmin: 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: vaultName
}

resource opsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, opsPrincipalId, roles.reader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.reader)
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource appOperator 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'lf-order-app-operator')
  properties: {
    roleName: 'LiveFire order app operator (${resourceGroup().name})'
    description: 'Update and restart the twin order app. No delete, no secrets, no other resource types.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.App/containerApps/read'
          'Microsoft.App/containerApps/write'
          'Microsoft.App/containerApps/revisions/read'
          'Microsoft.App/containerApps/revisions/restart/action'
          'Microsoft.App/containerApps/revisions/replicas/read'
          'Microsoft.App/managedEnvironments/read'
          'Microsoft.App/managedEnvironments/join/action'
          'Microsoft.ManagedIdentity/userAssignedIdentities/assign/action'
        ]
      }
    ]
    assignableScopes: [resourceGroup().id]
  }
}

resource opsAppOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, opsPrincipalId, appOperator.id)
  properties: {
    roleDefinitionId: appOperator.id
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// rbac model: add or remove only Key Vault Secrets User, only on the twin vault
resource opsRbacAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (kvPermissionModel == 'rbac') {
  name: guid(kv.id, opsPrincipalId, roles.rbacAdmin)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.rbacAdmin)
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${roles.kvSecretsUser}})) AND ((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/delete\'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${roles.kvSecretsUser}}))'
  }
}

// accessPolicy model (ADR-016): write access policies on this one vault (assigned at the vault, below)
resource policyOperator 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (kvPermissionModel == 'accessPolicy') {
  name: guid(kv.id, 'lf-kv-access-policy-operator')
  properties: {
    roleName: 'LiveFire Key Vault access-policy operator (${resourceGroup().name})'
    description: 'Read the twin vault and change its access policies. No secret, key or certificate data.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.KeyVault/vaults/read'
          'Microsoft.KeyVault/vaults/accessPolicies/write'
        ]
      }
    ]
    assignableScopes: [resourceGroup().id] // custom roles can't name a single resource; the assignment does
  }
}

resource opsPolicyOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (kvPermissionModel == 'accessPolicy') {
  name: guid(kv.id, opsPrincipalId, 'lf-kv-access-policy-operator')
  scope: kv
  properties: {
    roleDefinitionId: policyOperator.id
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
  }
}
