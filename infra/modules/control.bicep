// WS2 control resource group, G2: identities, private registry, Container Apps environment, control Key Vault and
// append-only evidence storage. Every workstream's control-plane app runs here; nothing here can reach production.
param location string

@description('Object ID of whoever runs azd: seeds the control secrets and checks the evidence store')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('Control Key Vault name, computed in main.bicep so other modules can reference it with existing')
param keyVaultName string

@description('Each GitHub repo whose acr-push environment may push images (OIDC, no secrets), as it appears in the token subject: owner@ownerId/name@repoId for repos on immutable subjects, otherwise owner/name')
param githubRepos array = ['livefire-team@349630330/livefire-fusion-poc@1437908536']

@description('Days each evidence blob version stays immutable. Kept short and unlocked so the lab can be torn down')
@minValue(1)
param evidenceRetentionDays int = 1

var suffix = uniqueString(resourceGroup().id)
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  kvSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  blobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
}

// ---- identities: one per job, never shared ----
resource opsId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-ops'
  location: location
}

resource refereeId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-referee'
  location: location
}

resource pullId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-acrpull'
  location: location
}

resource ciId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-ci'
  location: location
}

// GitHub Actions jobs in the acr-push environment sign in as id-lf-ci. Azure allows one write at a time here.
// The name drops the @ids, so it stays the same whichever subject format a repo uses.
@batchSize(1)
resource ciFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = [
  for repo in githubRepos: {
    parent: ciId
    name: 'gh-${replace(join(map(split(repo, '/'), part => first(split(part, '@'))), '-'), '.', '-')}'
    properties: {
      issuer: 'https://token.actions.githubusercontent.com'
      subject: 'repo:${repo}:environment:acr-push'
      audiences: ['api://AzureADTokenExchange']
    }
  }
]

// ---- private registry: no admin user, no passwords; pulls and pushes by identity only ----
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrlf${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource pullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, pullId.id, roles.acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: pullId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The Ops Service resolves tags to digests before it deploys
resource opsPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, opsId.id, roles.acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: opsId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ciPushRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, ciId.id, roles.acrPush)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
    principalId: ciId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---- Container Apps environment for the control plane ----
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-lf-control-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-lf-control'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

// ---- control Key Vault: RBAC, readable by templates for the key-mode fallbacks ----
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enabledForTemplateDeployment: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource deployerSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, principalId, roles.kvSecretsOfficer)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsOfficer)
    principalId: principalId
    principalType: principalType
  }
}

// ---- evidence: versioned, version-level immutable, appendable, never rewritable ----
resource evidenceAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stlfev${take(suffix, 13)}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: evidenceAccount
  name: 'default'
  properties: { isVersioningEnabled: true }
}

resource evidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'evidence'
  properties: {
    publicAccess: 'None'
    immutableStorageWithVersioning: { enabled: true }
  }
}

// Unlocked on purpose: still enforced for overwrites and deletes, but removable, so azd down works after
// scripts/evidence-unlock.sh. Locking it is a production step.
resource evidencePolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: evidence
  name: 'default'
  properties: {
    immutabilityPeriodSinceCreationInDays: evidenceRetentionDays
    allowProtectedAppendWrites: true
  }
}

// The lab owner checks the store and, before teardown, removes the unlocked policies (scripts/evidence-unlock.sh)
resource deployerEvidence 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(evidence.id, principalId, roles.blobDataOwner)
  scope: evidence
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataOwner)
    principalId: principalId
    principalType: principalType
  }
}

output environmentId string = cae.id
output environmentDomain string = cae.properties.defaultDomain
output logAnalyticsCustomerId string = law.properties.customerId
output keyVaultName string = kv.name
output keyVaultUri string = kv.properties.vaultUri
output evidenceAccountName string = evidenceAccount.name
output evidenceBlobUrl string = '${evidenceAccount.properties.primaryEndpoints.blob}evidence'
output registryName string = acr.name
output registryServer string = acr.properties.loginServer
output pullIdentityId string = pullId.id
output pullIdentityName string = pullId.name
output ciClientId string = ciId.properties.clientId
output opsIdentityName string = opsId.name
output opsPrincipalId string = opsId.properties.principalId
output opsClientId string = opsId.properties.clientId
output refereeIdentityName string = refereeId.name
output refereePrincipalId string = refereeId.properties.principalId
output refereeClientId string = refereeId.properties.clientId
