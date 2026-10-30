// Compile-only harness for infra/modules/twin.bicep: instantiates the module with sample parameters.
// Build it with `az bicep build --file infra/tests/twin.test.bicep --stdout`. Not meant to be deployed.

@secure()
param sqlAdminPassword string

module twin '../modules/twin.bicep' = {
  name: 'twin-test'
  params: {
    location: resourceGroup().location
    principalId: '00000000-0000-0000-0000-000000000000'
    principalType: 'User'
    kvPermissionModel: 'rbac'
    orderImage: 'ghcr.io/livefire-team/order-service:g1'
    sqlAdminPassword: sqlAdminPassword
    secretRefreshSeconds: 10
  }
}

output keyVaultName string = twin.outputs.keyVaultName
output keyVaultId string = twin.outputs.keyVaultId
output appIdentityPrincipalId string = twin.outputs.appIdentityPrincipalId
output appAccessAssignmentName string = twin.outputs.appAccessAssignmentName
output orderAppName string = twin.outputs.orderAppName
output orderAppUrl string = twin.outputs.orderAppUrl
output sqlServerFqdn string = twin.outputs.sqlServerFqdn
output sqlDbName string = twin.outputs.sqlDbName
output appInsightsConnectionString string = twin.outputs.appInsightsConnectionString
