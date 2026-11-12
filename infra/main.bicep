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

// ---- WS4: Foundry and the Drill Runner (ADR-026). Two passes: Foundry once the model is set, the runner once the
// agents are pinned and its image is in the registry. Empty values leave WS4 out, so it never fails a provision ----
@description('WS4: the GPT-5.x model and exact version (e.g. gpt-5.1 / 2025-11-13). Empty: no Foundry')
param modelName string = ''
param modelVersion string = ''
@description('WS4: model capacity in thousands of tokens per minute')
param modelCapacity string = '50'
@description('WS4: Prompt Shields on the model deployment (guide 7.2)')
@allowed(['on', 'off'])
param promptShields string = 'on'
@description('WS4 second pass: pinned agents (name:version, from scripts/deploy.sh agents) and the runner image')
param plannerAgent string = ''
param engineerAgent string = ''
@description('WS4: <registry>/drill-runner:sha-<40 hex>. Empty: no job-drill-runner')
param runnerImage string = ''
@description('WS4: the runner\'s GitHub credential: app (livefire-runner GitHub App) or token (fallback)')
@allowed(['app', 'token'])
param runnerGithubAuth string = 'app'
param runnerGithubAppId string = ''
param runnerGithubInstallationId string = ''
@description('WS4: the scenario recovery target in seconds (blueprint 1.6); change only with the lead')
param targetRecoveryS string = '1800'
@allowed(['Advisory', 'Supervised', 'Autonomous Twin'])
param runnerDefaultMode string = 'Autonomous Twin'

@description('WS1: <registry>/load-generator:sha-<40 hex>. Empty: no caj-loadgen')
param loadgenImage string = ''
@description('WS1: the drill-<id> whose event log gets the metrics.orders lines. Empty or no drill- prefix: none')
param loadgenDrillId string = ''

var tags = { 'azd-env-name': environmentName, app: 'livefire' }
// Computed here, not in a module, so other modules can reference the vault with existing and getSecret
var controlKeyVaultName = 'kv-lfc-${take(uniqueString(subscription().id, environmentName), 13)}'
var deployOps = !empty(opsImage) && !empty(refereeImage)
// /recovery calls the Ops Service, so ca-mcp follows it
var deployMcp = deployOps && !empty(mcpImage)
var deployLoadgen = !empty(loadgenImage)
// WS4's agents call ca-mcp, and the runner calls the Ops Service, so both follow ca-mcp
var deployFoundry = deployMcp && !empty(modelName) && !empty(modelVersion)
var deployRunner = deployFoundry && !empty(runnerImage) && !empty(plannerAgent) && !empty(engineerAgent)

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

// ---- WS4: Foundry (account, project, pinned model, Prompt Shields, one MCP connection per agent) ----
resource controlKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  scope: controlRg
  name: controlKeyVaultName
}

module foundry 'modules/foundry.bicep' = if (deployFoundry) {
  scope: controlRg
  name: 'foundry'
  params: {
    location: location
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: int(modelCapacity)
    promptShields: promptShields
    mcpUrl: mcp!.outputs.mcpUrl
    plannerMcpKey: controlKv.getSecret('mcp-planner-key')   // read at deploy time; never in a file or the history
    engineerMcpKey: controlKv.getSecret('mcp-engineer-key')
    principalId: principalId
    principalType: principalType
  }
}

// ---- WS4: the Drill Runner job, one execution per drill (scripts/start-drill.sh) ----
module drillRunner 'modules/drill-runner.bicep' = if (deployRunner) {
  scope: controlRg
  name: 'drill-runner'
  params: {
    location: location
    environmentId: control.outputs.environmentId
    image: runnerImage
    registryServer: control.outputs.registryServer
    pullIdentityId: control.outputs.pullIdentityId
    keyVaultName: control.outputs.keyVaultName
    evidenceAccountName: control.outputs.evidenceAccountName
    evidenceBlobUrl: control.outputs.evidenceBlobUrl
    foundryName: foundry!.outputs.foundryName
    projectName: foundry!.outputs.projectName
    projectEndpoint: foundry!.outputs.projectEndpoint
    modelDeployment: foundry!.outputs.modelDeployment
    plannerAgent: plannerAgent
    engineerAgent: engineerAgent
    opsUrl: ops!.outputs.opsUrl
    githubRepo: mcpGithubRepo
    githubAuth: runnerGithubAuth
    githubAppId: runnerGithubAppId
    githubInstallationId: runnerGithubInstallationId
    imageRepo: '${control.outputs.registryServer}/order-service'
    baseRef: mcpRepoRef
    engineerWritePaths: mcpEngineerWritePaths
    targetRecoveryS: targetRecoveryS
    defaultMode: runnerDefaultMode
  }
}

// ---- WS1: the load generator (ADR-015, ADR-021). Replaces the hand-deployed caj-loadgen of the same name ----
module loadgenIdentity 'modules/loadgen-identity.bicep' = if (deployLoadgen) {
  scope: controlRg
  name: 'loadgen-identity'
  params: { location: location, evidenceAccountName: control.outputs.evidenceAccountName }
}

module loadgen 'modules/loadgen.bicep' = if (deployLoadgen) {
  scope: twinRg
  name: 'loadgen'
  params: {
    location: location
    loadgenImage: loadgenImage
    registryServer: control.outputs.registryServer
    pullIdentityId: control.outputs.pullIdentityId
    orderAppUrl: twin.outputs.orderAppUrl
    appInsightsConnectionString: twin.outputs.appInsightsConnectionString
    identityId: loadgenIdentity!.outputs.identityId
    identityClientId: loadgenIdentity!.outputs.identityClientId
    // with an event log the job needs a drill- ID or it exits at start, so any other ID gets the load but no lines
    eventSource: startsWith(loadgenDrillId, 'drill-') ? loadgenIdentity!.outputs.eventSource : ''
    drillId: loadgenDrillId
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
// WS4 outputs: create_agents.py and agent-smoke.py read the first three; start-drill.sh the job name
output FOUNDRY_NAME string = deployFoundry ? foundry!.outputs.foundryName : ''
output FOUNDRY_PROJECT_ENDPOINT string = deployFoundry ? foundry!.outputs.projectEndpoint : ''
output MODEL_DEPLOYMENT string = deployFoundry ? foundry!.outputs.modelDeployment : ''
output RUNNER_JOB_NAME string = deployRunner ? drillRunner!.outputs.jobName : ''
output RUNNER_PRINCIPAL_ID string = deployRunner ? drillRunner!.outputs.runnerPrincipalId : ''
output LOADGEN_JOB_NAME string = deployLoadgen ? loadgen!.outputs.loadgenJobName : ''
output LOADGEN_PRINCIPAL_ID string = deployLoadgen ? loadgenIdentity!.outputs.identityPrincipalId : ''

// WS5: the Fusion Control Center (modules/control-center.bicep), the only internet-facing app.
// Skipped while CONTROL_CENTER_IMAGE is empty; WS5's scripts/deploy-cc.sh deploys the same module with the same names.
@description('WS5: <registry>/control-center:sha-<40 hex>; empty skips the Control Center')
param controlCenterImage string = ''
@allowed(['passcode', 'easyauth'])
param controlCenterAuthMode string = 'passcode'
@description('WS5, easyauth only: the Entra app registration client ID')
param controlCenterEntraClientId string = ''
@description('WS5: comma-separated CIDR ranges allowed to reach the Control Center; empty allows any address')
param controlCenterAllowedIps string = ''
@description('WS5: the team\'s recovery target in seconds for the scorecard, when a drill carries none; 0 means none')
param controlCenterTargetRecoveryS string = '0'

module controlCenter 'modules/control-center.bicep' = if (!empty(controlCenterImage)) { // WS5
  scope: controlRg
  name: 'control-center'
  params: {
    location: location
    environmentId: control.outputs.environmentId
    image: controlCenterImage
    registryServer: control.outputs.registryServer
    pullIdentityId: control.outputs.pullIdentityId
    authMode: controlCenterAuthMode
    keyVaultName: control.outputs.keyVaultName
    evidenceAccountName: control.outputs.evidenceAccountName
    entraClientId: controlCenterEntraClientId
    allowedIpRanges: empty(controlCenterAllowedIps) ? [] : split(controlCenterAllowedIps, ',')
    targetRecoverySeconds: int(controlCenterTargetRecoveryS)
  }
}

output CONTROL_CENTER_URL string = controlCenter.?outputs.url ?? ''
