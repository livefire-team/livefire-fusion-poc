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

@description('G2: the subscription-wide deny of new Owner, Contributor and User Access Administrator assignments')
@allowed(['on', 'off'])
param denyBroadPolicy string = 'off'
@description('G2: lets id-lf-ops attempt Contributor, so Azure Policy is what refuses it. Needs denyBroadPolicy on')
@allowed(['on', 'off'])
param broadAttemptRole string = 'off'

@description('G2: <registry>/ops-service:sha-<40 hex>. With refereeImage set, deploys ca-ops and the jobs')
param opsImage string = ''
@description('G2: <registry>/referee:sha-<40 hex>')
param refereeImage string = ''
@description('Comma-separated repos whose acr-push GitHub environment may push images, one entry per repo: owner@ownerId/name@repoId (immutable subjects) or owner/name')
param githubRepos string = 'livefire-team@349630330/livefire-fusion-poc@1437908536'
@description('Days each evidence version stays immutable (unlocked policy)')
param evidenceRetentionDays string = '1'

// ---- WS3: the MCP server (ca-mcp) and AI Search. Deployed once mcpImage is set and the Ops Service is deployed ----
@description('WS3: <registry>/mcp-server:sha-<40 hex>. Empty: no ca-mcp')
param mcpImage string = ''
@description('WS3: owner/name of the repo the Planner reads and the Engineer branches in')
param mcpGithubRepo string = 'livefire-team/livefire-fusion-poc'
@description('WS3: app (GitHub Apps, the target) or token (fine-grained tokens, the fallback)')
@allowed(['app', 'token'])
param mcpGithubAuth string = 'app'
param githubPlannerAppId string = ''
@description('A number, from the installation\'s URL; not the App\'s Client ID')
param githubPlannerInstallationId string = ''
param githubEngineerAppId string = ''
param githubEngineerInstallationId string = ''
@description('WS3: the branch or commit the tools read and branch from: main until code freeze, then the base commit')
param mcpRepoRef string = 'main'
@description('WS3: the files a candidate may change, comma-separated patterns. Kept in the azd environment (MCP_ENGINEER_WRITE_PATHS), never in this repo (ADR-004)')
param mcpEngineerWritePaths string = ''
@description('WS3: key (per-endpoint keys) or entra (each agent\'s own identity; needs the four values below)')
@allowed(['key', 'entra'])
param mcpAuthMode string = 'key'
param mcpClientId string = ''
param plannerAgentObjectId string = ''
param engineerAgentObjectId string = ''
param recoveryAgentObjectId string = ''
@description('WS3: AI Search region; empty: location. For when a region is out of Search capacity')
param searchLocation string = ''
@description('WS3: content_vector once WS4\'s embedding model exists; empty keeps keyword search')
param searchVectorField string = ''

var tags = { 'azd-env-name': environmentName, app: 'livefire' }
// Computed here, not in a module, so other modules can reference the vault with existing and getSecret
var controlKeyVaultName = 'kv-lfc-${take(uniqueString(subscription().id, environmentName), 13)}'
var deployOps = !empty(opsImage) && !empty(refereeImage)
// /recovery calls the Ops Service, so ca-mcp follows it
var deployMcp = deployOps && !empty(mcpImage)

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

module control 'modules/control.bicep' = { // WS2: identities, registry, environment, control vault, evidence
  scope: controlRg
  name: 'control'
  params: {
    location: location
    principalId: principalId
    principalType: principalType
    keyVaultName: controlKeyVaultName
    githubRepos: filter(map(split(githubRepos, ','), r => trim(r)), r => !empty(r))
    evidenceRetentionDays: int(evidenceRetentionDays)
  }
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
    registryServer: control.outputs.registryServer
    pullIdentityId: control.outputs.pullIdentityId
  }
}

// ---- the live platform refusal: Azure Policy denies the broad roles for everyone in the lab ----
resource denyBroad 'Microsoft.Authorization/policyDefinitions@2023-04-01' = if (denyBroadPolicy == 'on') {
  name: 'lf-deny-broad-role-assignments'
  properties: {
    displayName: 'LiveFire: deny Owner, Contributor and User Access Administrator assignments'
    policyType: 'Custom'
    mode: 'All'
    policyRule: loadJsonContent('../policy/deny-broad-role-assignments.json')
  }
}

resource denyBroadAssign 'Microsoft.Authorization/policyAssignments@2023-04-01' = if (denyBroadPolicy == 'on') {
  name: 'lf-deny-broad-roles'
  properties: {
    displayName: 'LiveFire: deny broad role assignments'
    policyDefinitionId: denyBroad.id
  }
}

module broadAttempt 'modules/broad-attempt-access.bicep' = if (denyBroadPolicy == 'on' && broadAttemptRole == 'on') {
  name: 'broad-attempt-access'
  params: { opsPrincipalId: control.outputs.opsPrincipalId, appPrincipalId: twin.outputs.appIdentityPrincipalId }
  dependsOn: [denyBroadAssign]
}

// ---- the Ops Service and the Referee job, once their images are in the private registry ----
module opsTwinAccess 'modules/ops-twin-access.bicep' = if (deployOps) {
  scope: twinRg
  name: 'ops-twin-access'
  params: {
    opsPrincipalId: control.outputs.opsPrincipalId
    vaultName: twin.outputs.keyVaultName
    kvPermissionModel: kvPermissionModel
  }
}

module ops 'modules/ops.bicep' = if (deployOps) {
  scope: controlRg
  name: 'ops'
  params: {
    location: location
    environmentId: control.outputs.environmentId
    registryServer: control.outputs.registryServer
    pullIdentityId: control.outputs.pullIdentityId
    pullIdentityName: control.outputs.pullIdentityName
    opsIdentityName: control.outputs.opsIdentityName
    refereeIdentityName: control.outputs.refereeIdentityName
    keyVaultName: control.outputs.keyVaultName
    evidenceAccountName: control.outputs.evidenceAccountName
    evidenceBlobUrl: control.outputs.evidenceBlobUrl
    opsImage: opsImage
    refereeImage: refereeImage
    imageRepo: '${control.outputs.registryServer}/order-service'
    baseImage: orderImage
    twinRg: twinRg.name
    orderAppName: twin.outputs.orderAppName
    orderAppUrl: twin.outputs.orderAppUrl
    keyVaultId: twin.outputs.keyVaultId
    appIdentityPrincipalId: twin.outputs.appIdentityPrincipalId
    appAccessAssignmentName: twin.outputs.appAccessAssignmentName
    kvPermissionModel: kvPermissionModel
    sqlServerFqdn: twin.outputs.sqlServerFqdn
    sqlDbName: twin.outputs.sqlDbName
    expectRefusal: broadAttemptRole == 'on' ? 'RequestDisallowedByPolicy' : 'AuthorizationFailed'
  }
  dependsOn: [opsTwinAccess]
}

// ---- WS3: the agents' tools. Secrets come from the control vault (scripts/postprovision.sh, create-secrets.sh) ----
module mcp 'modules/mcp.bicep' = if (deployMcp) {
  scope: controlRg
  name: 'mcp'
  params: {
    location: location
    searchLocation: searchLocation
    environmentId: control.outputs.environmentId
    image: mcpImage
    principalId: principalId
    principalType: principalType
    registryServer: control.outputs.registryServer
    pullIdentityId: control.outputs.pullIdentityId
    keyVaultName: control.outputs.keyVaultName
    evidenceAccountName: control.outputs.evidenceAccountName
    evidenceBlobUrl: control.outputs.evidenceBlobUrl
    opsUrl: ops!.outputs.opsUrl
    repoRef: mcpRepoRef
    engineerWritePaths: mcpEngineerWritePaths
    authMode: mcpAuthMode
    mcpClientId: mcpClientId
    plannerAgentObjectId: plannerAgentObjectId
    engineerAgentObjectId: engineerAgentObjectId
    recoveryAgentObjectId: recoveryAgentObjectId
    twinKeyVaultId: twin.outputs.keyVaultId
    appIdentityPrincipalId: twin.outputs.appIdentityPrincipalId
    logAnalyticsCustomerId: twin.outputs.logAnalyticsCustomerId
    orderAppName: twin.outputs.orderAppName
    twinSqlServerName: split(twin.outputs.sqlServerFqdn, '.')[0]
    desiredSqlDbName: twin.outputs.sqlDbName
    githubRepo: mcpGithubRepo
    githubAuth: mcpGithubAuth
    githubPlannerAppId: githubPlannerAppId
    githubPlannerInstallationId: githubPlannerInstallationId
    githubEngineerAppId: githubEngineerAppId
    githubEngineerInstallationId: githubEngineerInstallationId
    searchVectorField: searchVectorField
  }
}

// Read roles on the twin. After the twin module, so on an access-policy vault its entry survives the twin's redeploy
module mcpTwinAccess 'modules/mcp-twin-access.bicep' = if (deployMcp) {
  scope: twinRg
  name: 'mcp-twin-access'
  params: {
    mcpPrincipalId: mcp!.outputs.mcpIdentityPrincipalId
    twinKeyVaultName: twin.outputs.keyVaultName
    logAnalyticsWorkspaceName: twin.outputs.logAnalyticsWorkspaceName
    sqlServerName: split(twin.outputs.sqlServerFqdn, '.')[0]
    orderAppName: twin.outputs.orderAppName
    kvPermissionModel: kvPermissionModel
  }
}

output TWIN_RG string = twinRg.name
output CONTROL_RG string = controlRg.name
output AZURE_TENANT_ID string = tenant().tenantId
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
output OPS_PRINCIPAL_ID string = control.outputs.opsPrincipalId
output REFEREE_CLIENT_ID string = control.outputs.refereeClientId
// G2 platform outputs for WS3, WS4 and WS5
output CONTAINER_APPS_ENVIRONMENT_ID string = control.outputs.environmentId
output CONTROL_LOG_ANALYTICS_CUSTOMER_ID string = control.outputs.logAnalyticsCustomerId
output CONTROL_KEYVAULT_NAME string = control.outputs.keyVaultName
output EVIDENCE_ACCOUNT_NAME string = control.outputs.evidenceAccountName
output EVIDENCE_BLOB_URL string = control.outputs.evidenceBlobUrl
output REGISTRY_NAME string = control.outputs.registryName
output REGISTRY_SERVER string = control.outputs.registryServer
output IMAGE_REPO string = '${control.outputs.registryServer}/order-service'
output PULL_IDENTITY_ID string = control.outputs.pullIdentityId
output CI_CLIENT_ID string = control.outputs.ciClientId
output OPS_URL string = deployOps ? ops!.outputs.opsUrl : ''
output REFEREE_JOB_NAME string = deployOps ? ops!.outputs.refereeJobName : ''
output SMOKE_JOB_NAME string = deployOps ? ops!.outputs.smokeJobName : ''
// WS3 outputs for WS4 (the agents' MCP connections) and the post-provision index load
output MCP_URL string = deployMcp ? mcp!.outputs.mcpUrl : ''
output MCP_PRINCIPAL_ID string = deployMcp ? mcp!.outputs.mcpIdentityPrincipalId : ''
output SEARCH_ENDPOINT string = deployMcp ? mcp!.outputs.searchEndpoint : ''
output SEARCH_NAME string = deployMcp ? mcp!.outputs.searchName : ''
