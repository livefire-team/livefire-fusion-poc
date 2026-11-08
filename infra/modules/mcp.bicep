// LiveFire MCP server (WS3): one Container App serving /planner/mcp and /engineer/mcp, plus the incident search.
param location string
@description('Region for the AI Search service; empty: location. Azure sometimes runs out of Search capacity in a region')
param searchLocation string = ''
@description('Resource ID of the control Container Apps environment (WS2)')
param environmentId string
@description('Image, e.g. <registry>/mcp-server:sha-<hash>')
param image string
@description('Object ID of whoever runs azd; gets rights to load the search index')
param principalId string
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'
param keyVaultName string
param evidenceAccountName string
param evidenceContainer string = 'evidence'
@description('https://<account>.blob.core.windows.net/evidence, from control.bicep')
param evidenceBlobUrl string
@description('The commit the tools read and branch from: main until code freeze, then the pinned base commit')
param repoRef string = 'main'
@description('Comma-separated patterns of the files a candidate may change (ENGINEER_WRITE_PATHS). Set through azd, never in this repo (ADR-004); empty refuses every write')
param engineerWritePaths string = ''
@description('key: per-endpoint keys (the fallback). entra: each hosted agent calls with its own Entra Agent ID')
@allowed(['key', 'entra'])
param authMode string = 'key'
@description('Entra mode: client ID of the livefire-mcp app registration (the token audience)')
param mcpClientId string = ''
@description('Entra mode: object IDs of the three agent identities (from WS4)')
param plannerAgentObjectId string = ''
param engineerAgentObjectId string = ''
param recoveryAgentObjectId string = ''                  // v2.1
@description('v2.1: the Ops Service internal URL (same Container Apps environment). /recovery/mcp calls it with ops-agent-key')
param opsUrl string = ''
@description('Twin outputs from WS1')
param twinKeyVaultId string
param appIdentityPrincipalId string
param logAnalyticsCustomerId string
@description('v2.0: the twin resources the Planner\'s configuration and network evidence tools read, and the desired database name')
param orderAppName string = ''
param twinSqlServerName string = ''
param desiredSqlDbName string = 'orders'
@description('owner/name of the GitHub repo')
param githubRepo string
@allowed(['app', 'token'])
param githubAuth string = 'app'
param githubPlannerAppId string = ''
param githubPlannerInstallationId string = ''
param githubEngineerAppId string = ''
param githubEngineerInstallationId string = ''
@allowed(['basic', 'free'])
param searchSku string = 'basic'
@description('content_vector once the index is hybrid (WS4 deploys the embedding model); empty keeps keyword search')
param searchVectorField string = ''

@description('The private registry login server, e.g. acrlfxxxx.azurecr.io (control.bicep)')
param registryServer string
@description('id-lf-acrpull: the identity that pulls images from the registry, and nothing else')
param pullIdentityId string

var suffix = uniqueString(resourceGroup().id)
var appName = 'ca-mcp'
var vaultUri = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'
var roles = {
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  searchIndexReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchIndexContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lf-mcp'
  location: location
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: last(split(environmentId, '/'))
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource evidenceAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: evidenceAccountName
}

resource evidenceBlobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: evidenceAccount
  name: 'default'
}

resource evidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: evidenceBlobs
  name: evidenceContainer
}

// In another region, another name: a failed attempt in the main region can leave Azure holding the name there.
// Everything else reads the name and endpoint from the outputs.
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: empty(searchLocation) || searchLocation == location ? 'srch-lf-${suffix}' : 'srch-lf-${suffix}-${searchLocation}'
  location: empty(searchLocation) ? location : searchLocation
  sku: { name: searchSku }
  identity: { type: 'SystemAssigned' }   // calls the embedding model to vectorize queries (hybrid retrieval); no keys
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'enabled'
    authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
  }
}

// ---- least privilege for id-lf-mcp: only the secrets it uses, never the whole control vault ----
// v2.1: ops-agent-key lets the Recovery agent's two tools call the Ops Service; each execution still needs a grant
var secretNames = concat(['ops-agent-key'], authMode == 'key' ? ['mcp-planner-key', 'mcp-engineer-key', 'mcp-recovery-key'] : [],
  githubAuth == 'app' ? ['gh-planner-private-key', 'gh-engineer-private-key'] : ['gh-planner-token', 'gh-engineer-token'])

resource secretRefs 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = [for s in secretNames: {
  parent: kv
  name: s
}]

resource secretsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (s, i) in secretNames: {
  name: guid(kv.id, s, identity.id, roles.kvSecretsUser)
  scope: secretRefs[i]
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource evidenceAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(evidence.id, identity.id, roles.blobContributor)
  scope: evidence
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, identity.id, roles.searchIndexReader)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexReader)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The person running azd can create and load the index (scripts/load-incidents.py)
resource loaderIndex 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, principalId, roles.searchIndexContributor)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexContributor)
    principalId: principalId
    principalType: principalType
  }
}

resource loaderService 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, principalId, roles.searchServiceContributor)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
    principalId: principalId
    principalType: principalType
  }
}

// ---- secrets come from Key Vault; nothing secret is in this file ----
var keySecrets = authMode == 'key' ? [
  { name: 'planner-key', keyVaultUrl: '${vaultUri}/secrets/mcp-planner-key', identity: identity.id }
  { name: 'engineer-key', keyVaultUrl: '${vaultUri}/secrets/mcp-engineer-key', identity: identity.id }
  { name: 'recovery-key', keyVaultUrl: '${vaultUri}/secrets/mcp-recovery-key', identity: identity.id }
] : []
var opsSecrets = [
  { name: 'ops-agent-key', keyVaultUrl: '${vaultUri}/secrets/ops-agent-key', identity: identity.id }
]
var authEnv = authMode == 'key' ? [
  { name: 'AUTH_MODE', value: 'key' }
  { name: 'PLANNER_KEY', secretRef: 'planner-key' }
  { name: 'ENGINEER_KEY', secretRef: 'engineer-key' }
  { name: 'RECOVERY_KEY', secretRef: 'recovery-key' }
] : [
  { name: 'AUTH_MODE', value: 'entra' }
  { name: 'ENTRA_TENANT_ID', value: tenant().tenantId }
  { name: 'MCP_CLIENT_ID', value: mcpClientId }
  { name: 'PLANNER_AGENT_OBJECT_ID', value: plannerAgentObjectId }
  { name: 'ENGINEER_AGENT_OBJECT_ID', value: engineerAgentObjectId }
  { name: 'RECOVERY_AGENT_OBJECT_ID', value: recoveryAgentObjectId }
]
var opsEnv = [
  { name: 'OPS_URL', value: opsUrl }
  { name: 'OPS_AGENT_KEY', secretRef: 'ops-agent-key' }
]
var githubSecrets = githubAuth == 'app' ? [
  { name: 'gh-planner', keyVaultUrl: '${vaultUri}/secrets/gh-planner-private-key', identity: identity.id }
  { name: 'gh-engineer', keyVaultUrl: '${vaultUri}/secrets/gh-engineer-private-key', identity: identity.id }
] : [
  { name: 'gh-planner', keyVaultUrl: '${vaultUri}/secrets/gh-planner-token', identity: identity.id }
  { name: 'gh-engineer', keyVaultUrl: '${vaultUri}/secrets/gh-engineer-token', identity: identity.id }
]
var githubEnv = githubAuth == 'app' ? [
  { name: 'GITHUB_PLANNER_APP_ID', value: githubPlannerAppId }
  { name: 'GITHUB_PLANNER_INSTALLATION_ID', value: githubPlannerInstallationId }
  { name: 'GITHUB_PLANNER_PRIVATE_KEY', secretRef: 'gh-planner' }
  { name: 'GITHUB_ENGINEER_APP_ID', value: githubEngineerAppId }
  { name: 'GITHUB_ENGINEER_INSTALLATION_ID', value: githubEngineerInstallationId }
  { name: 'GITHUB_ENGINEER_PRIVATE_KEY', secretRef: 'gh-engineer' }
] : [
  { name: 'GITHUB_PLANNER_TOKEN', secretRef: 'gh-planner' }
  { name: 'GITHUB_ENGINEER_TOKEN', secretRef: 'gh-engineer' }
]
var fqdn = '${appName}.${env.properties.defaultDomain}'

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {}, '${pullIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      registries: [ { server: registryServer, identity: pullIdentityId } ]
      activeRevisionsMode: 'Single'
      secrets: concat(keySecrets, opsSecrets, githubSecrets)
      // Public HTTPS: Foundry calls MCP servers from Microsoft's network. The caller check (Entra agent identity,
      // or the per-endpoint key as the fallback) and the host check guard it.
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'mcp-server'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat([
            { name: 'BACKEND', value: 'azure' }
            { name: 'MCP_ALLOWED_HOSTS', value: fqdn }
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'EVENT_SOURCE', value: 'blob:${evidenceBlobUrl}' }
            { name: 'LOG_ANALYTICS_WORKSPACE_ID', value: logAnalyticsCustomerId }
            { name: 'TWIN_KEYVAULT_ID', value: twinKeyVaultId }
            { name: 'APP_IDENTITY_PRINCIPAL_ID', value: appIdentityPrincipalId }
            { name: 'ORDER_APP_NAME', value: orderAppName }
            { name: 'TWIN_SQL_SERVER_NAME', value: twinSqlServerName }
            { name: 'DESIRED_SQL_DB_NAME', value: desiredSqlDbName }
            { name: 'SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
            { name: 'SEARCH_INDEX', value: 'incidents' }
            { name: 'SEARCH_VECTOR_FIELD', value: searchVectorField }
            { name: 'GITHUB_REPO', value: githubRepo }
            { name: 'REPO_REF', value: repoRef }
            { name: 'ENGINEER_WRITE_PATHS', value: engineerWritePaths }
          ], authEnv, opsEnv, githubEnv)
          probes: [
            { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 10, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 10, failureThreshold: 3 }
          ]
        }
      ]
      // Stateless, so more than one replica is safe.
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
  dependsOn: [secretsAccess, evidenceAccess, searchRead]
}

output mcpUrl string = 'https://${fqdn}'
output mcpIdentityPrincipalId string = identity.properties.principalId
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchPrincipalId string = search.identity.principalId
output searchName string = search.name
