// Microsoft Foundry for LiveFire (WS4): one resource, one project, one pinned model, two MCP connections.
param location string
@description('Model from the day-1 probe, e.g. gpt-5.1')
param modelName string
@description('Exact model version from the probe; pinned, never auto-upgraded')
param modelVersion string
@description('Capacity in thousands of tokens per minute; within the quota the probe showed')
param modelCapacity int = 50
@description('MCP server base URL (WS3 mcp.bicep output mcpUrl)')
param mcpUrl string
@secure()
param plannerMcpKey string
@secure()
param engineerMcpKey string
@description('Object ID of whoever runs create_agents.py')
param principalId string
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'
@description('v1.1 (guide 7.2): Prompt Shields on the model deployment. off only if the lab rejects the policy')
@allowed(['on', 'off'])
param promptShields string = 'on'

var suffix = uniqueString(resourceGroup().id)
var azureAiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'ais-lf-${suffix}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'ais-lf-${suffix}'
    allowProjectManagement: true
    disableLocalAuth: true // Entra sign-in only: no account keys to leak
    publicNetworkAccess: 'Enabled' // Agent Service must reach the public MCP endpoint (basic setup)
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'proj-livefire'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'LiveFire Fusion'
    description: 'Planner and Engineer agents for LiveFire drills. Synthetic data only.'
  }
}

// Prompt Shields (blueprint 7.2): the jailbreak and indirect-attack filters block, alongside the default content
// filters at their default thresholds. A blocked call ends the drill ESCALATED_SECURITY (guardrail.blocked).
var harmFilters = [for f in ['Hate', 'Sexual', 'Violence', 'Selfharm']: [
  { name: f, blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Prompt' }
  { name: f, blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Completion' }
]]

// An AI Services account takes one change at a time. Created side by side, the project failed with RequestConflict
// ("another operation is in progress on the resource"), so every child waits for the one before it:
// account, project, the two connections, Prompt Shields, the model.
resource shields 'Microsoft.CognitiveServices/accounts/raiPolicies@2025-06-01' = if (promptShields == 'on') {
  parent: foundry
  name: 'lf-shields'
  properties: {
    basePolicyName: 'Microsoft.DefaultV2'
    mode: 'Blocking'
    contentFilters: concat(flatten(harmFilters), [
      { name: 'Jailbreak', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Indirect Attack', blocking: true, enabled: true, source: 'Prompt' }
    ])
  }
  dependsOn: [plannerConnection, engineerConnection]
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: promptShields == 'on' ? shields.name : null
  }
  dependsOn: [engineerConnection]   // and, through raiPolicyName, after Prompt Shields
}

// One connection per MCP endpoint. Each holds only its own endpoint's key, sent as the Authorization header.
resource plannerConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'livefire-planner-mcp'
  properties: {
    category: 'RemoteTool'
    authType: 'CustomKeys'
    target: '${mcpUrl}/planner/mcp'
    credentials: { keys: { Authorization: 'Bearer ${plannerMcpKey}' } }
    metadata: { type: 'generic_mcp' }
  }
}

resource engineerConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'livefire-engineer-mcp'
  properties: {
    category: 'RemoteTool'
    authType: 'CustomKeys'
    target: '${mcpUrl}/engineer/mcp'
    credentials: { keys: { Authorization: 'Bearer ${engineerMcpKey}' } }
    metadata: { type: 'generic_mcp' }
  }
  dependsOn: [plannerConnection]
}

// The person running create_agents.py creates agent versions in this project only.
resource deployerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, principalId, azureAiUserRoleId)
  scope: project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: principalId
    principalType: principalType
  }
}

output foundryName string = foundry.name
output projectName string = project.name
output projectEndpoint string = 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}'
output modelDeployment string = model.name
output promptShields string = promptShields
