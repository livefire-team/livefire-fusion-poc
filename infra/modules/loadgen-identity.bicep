// WS1, G2: the load generator's identity for writing metrics.orders lines to the evidence store (ADR-021).
// Deploy it in the control resource group, next to the evidence account, then pass its outputs to loadgen.bicep:
//
//   module loadgenIdentity 'modules/loadgen-identity.bicep' = {
//     scope: controlRg
//     name: 'loadgen-identity'
//     params: { location: location, evidenceAccountName: control.outputs.evidenceAccountName }
//   }
//
// The identity gets a custom role on the evidence container alone that can create blobs and append to them, and
// nothing else: no reads, no deletes, no other containers. A condition limits those writes to drill event logs
// (drill-<id>/events.jsonl, one folder deep), so it cannot write any other evidence file. The container's
// version-level immutability keeps every earlier version of a log, so a rewrite cannot erase lines already written.
// Assigning this user-assigned identity to the job in the twin resource group needs Managed Identity Operator on it
// (the azd deployer, as Owner, has that).

@description('Azure region; use the same one as control.bicep.')
param location string

@description('Name of the evidence storage account (control.bicep output evidenceAccountName), in this resource group.')
param evidenceAccountName string

@description('Name of the user-assigned managed identity.')
param identityName string = 'id-lf-loadgen'

var blobActions = {
  write: 'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
  append: 'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action'
}
var pathAttribute = '@Resource[Microsoft.Storage/storageAccounts/blobServices/containers/blobs:path]'
// StringLike's * also matches '/', so the second test keeps the log one folder deep (drill-<id>/events.jsonl)
var eventLogsOnly = '((!(ActionMatches{\'${blobActions.write}\'}) AND !(ActionMatches{\'${blobActions.append}\'})) OR (${pathAttribute} StringLike \'drill-*/events.jsonl\' AND ${pathAttribute} StringNotLike \'*/*/*\'))'

resource evidenceAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: evidenceAccountName
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: evidenceAccount
  name: 'default'
}

resource evidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blobs
  name: 'evidence'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

resource appender 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'lf-evidence-event-appender')
  properties: {
    roleName: 'LiveFire evidence event appender (${resourceGroup().name}, ${take(uniqueString(resourceGroup().id), 6)})'
    description: 'Create and append to blobs in the evidence container. No read, no delete.'
    type: 'CustomRole'
    permissions: [
      {
        actions: []
        dataActions: [blobActions.write, blobActions.append]
      }
    ]
    assignableScopes: [resourceGroup().id]
  }
}

resource appendEvents 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(evidence.id, identity.id, appender.id)
  scope: evidence
  properties: {
    roleDefinitionId: appender.id
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    condition: eventLogsOnly
    conditionVersion: '2.0'
    description: 'Load generator: append metrics.orders lines to drill event logs only (ADR-021).'
  }
}

output identityId string = identity.id
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output eventSource string = 'blob:${evidenceAccount.properties.primaryEndpoints.blob}evidence'
