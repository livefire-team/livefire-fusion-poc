// ---- WS4: paste into infra/main.bicep after the WS3 modules. Uses controlKeyVaultName from WS2's G2 main.bicep ----
@description('WS4: the model the lab probe deployed, e.g. gpt-5.1, and its version')
param modelName string
param modelVersion string
@description('WS4, second pass: pinned agents (name:version), runner image and Ops Service URL; empty skips the job')
param plannerAgent string = ''
param engineerAgent string = ''
param runnerImage string = ''
param opsUrl string = ''
@description('WS4: the repository candidate images come from, ghcr.io/<owner>/order-service')
param imageRepo string
@allowed(['app', 'token'])
param runnerGithubAuth string = 'app'
param runnerGithubAppId string = ''
param runnerGithubInstallationId string = ''

resource controlKv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  scope: controlRg
  name: controlKeyVaultName
}

module foundry 'modules/foundry.bicep' = { // WS4, first pass
  scope: controlRg
  name: 'foundry'
  params: {
    location: location
    modelName: modelName
    modelVersion: modelVersion
    mcpUrl: mcp.outputs.mcpUrl
    plannerMcpKey: controlKv.getSecret('mcp-planner-key') // read at deploy time; never in a file or the history
    engineerMcpKey: controlKv.getSecret('mcp-engineer-key')
    principalId: principalId
    principalType: principalType
  }
}

module drillRunner 'modules/drill-runner.bicep' = if (!empty(plannerAgent)) { // WS4, second pass
  scope: controlRg
  name: 'drill-runner'
  params: {
    location: location
    environmentId: control.outputs.environmentId
    image: runnerImage
    keyVaultName: controlKeyVaultName
    evidenceAccountName: control.outputs.evidenceAccountName
    foundryName: foundry.outputs.foundryName
    projectName: foundry.outputs.projectName
    projectEndpoint: foundry.outputs.projectEndpoint
    modelDeployment: foundry.outputs.modelDeployment
    plannerAgent: plannerAgent
    engineerAgent: engineerAgent
    opsUrl: opsUrl
    githubRepo: githubRepo
    githubAuth: runnerGithubAuth
    githubAppId: runnerGithubAppId
    githubInstallationId: runnerGithubInstallationId
    imageRepo: imageRepo
  }
}

output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output MODEL_DEPLOYMENT string = foundry.outputs.modelDeployment
output RUNNER_PRINCIPAL_ID string = drillRunner.?outputs.runnerPrincipalId ?? ''
