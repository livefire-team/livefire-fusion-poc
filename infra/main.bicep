targetScope = 'subscription'

param environmentName string
param location string
param principalId string
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'
@allowed(['rbac', 'accessPolicy'])
param kvPermissionModel string = 'rbac'
param orderImage string
@secure()
param sqlAdminPassword string
@description('Seconds the order path caches the DB password: 10 while testing')
param refreshSeconds string = '10'
@description('Path A only, after the probe allows it: the deny policy and the limited recovery role')
@allowed(['on', 'off'])
param pathAControls string = 'off'

var tags = { 'azd-env-name': environmentName, app: 'livefire' }

resource twinRg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-lf-twin-${environmentName}'
  location: location
  tags: tags
}

resource controlRg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-lf-control-${environmentName}'
  location: location
  tags: tags
}

module twin 'modules/twin.bicep' = { // WS1
  scope: twinRg
  name: 'twin'
  params: {
    location: location
    principalId: principalId
    principalType: principalType
    kvPermissionModel: kvPermissionModel
    orderImage: orderImage
    sqlAdminPassword: sqlAdminPassword
    secretRefreshSeconds: int(refreshSeconds)
  }
}

module control 'modules/control.bicep' = { // WS2: ops and referee identities (G1); the Ops Service from G2
  scope: controlRg
  name: 'control'
  params: { location: location }
}

// ---- Path A only: the live policy refusal and the recovery identity's limited role ----
resource denyBroad 'Microsoft.Authorization/policyDefinitions@2023-04-01' = if (pathAControls == 'on') {
  name: 'lf-deny-broad-role-assignments'
  properties: {
    displayName: 'LiveFire: deny Owner, Contributor and User Access Administrator assignments'
    policyType: 'Custom'
    mode: 'All'
    policyRule: loadJsonContent('../policy/deny-broad-role-assignments.json')
  }
}

resource denyBroadAssign 'Microsoft.Authorization/policyAssignments@2023-04-01' = if (pathAControls == 'on') {
  name: 'lf-deny-broad-roles'
  properties: {
    displayName: 'LiveFire: deny broad role assignments'
    policyDefinitionId: denyBroad.id
  }
}

module opsAccess 'modules/ops-access.bicep' = if (pathAControls == 'on') {
  scope: twinRg
  name: 'ops-access'
  params: {
    vaultName: twin.outputs.keyVaultName
    opsPrincipalId: control.outputs.opsPrincipalId
  }
}

output TWIN_RG string = twinRg.name
output CONTROL_RG string = controlRg.name
output KEYVAULT_NAME string = twin.outputs.keyVaultName
output KEYVAULT_ID string = twin.outputs.keyVaultId
output APP_IDENTITY_PRINCIPAL_ID string = twin.outputs.appIdentityPrincipalId
output APP_ACCESS_ASSIGNMENT_NAME string = twin.outputs.appAccessAssignmentName
output ORDER_APP_NAME string = twin.outputs.orderAppName
output ORDER_APP_URL string = twin.outputs.orderAppUrl
output SQL_SERVER_FQDN string = twin.outputs.sqlServerFqdn
output SQL_DB_NAME string = twin.outputs.sqlDbName
output APPINSIGHTS_CONNECTION_STRING string = twin.outputs.appInsightsConnectionString
output LOG_ANALYTICS_WORKSPACE_NAME string = twin.outputs.logAnalyticsWorkspaceName
output LOG_ANALYTICS_CUSTOMER_ID string = twin.outputs.logAnalyticsCustomerId
output OPS_CLIENT_ID string = control.outputs.opsClientId
output REFEREE_CLIENT_ID string = control.outputs.refereeClientId
