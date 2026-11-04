// WS2, G2: the Ops Service (ca-ops, internal ingress only), the Referee job and the smoke job, in the control
// resource group. Deployed once the control secrets exist and the three images are in the private registry.
param location string
param environmentId string
param registryServer string
param pullIdentityId string
param pullIdentityName string
param opsIdentityName string
param refereeIdentityName string
param keyVaultName string
param evidenceAccountName string
param evidenceBlobUrl string

@description('<registry>/ops-service:sha-<40 hex>')
param opsImage string
@description('<registry>/referee:sha-<40 hex>')
param refereeImage string

@description('<registry>/order-service: the only repository deploy_revision accepts')
param imageRepo string
@description('<registry>/order-service:sha-<40 hex>: what reset_twin puts back')
param baseImage string

// ---- the twin, from WS1's outputs ----
param twinRg string
param orderAppName string
param orderAppUrl string
param keyVaultId string
param appIdentityPrincipalId string
param appAccessAssignmentName string
@allowed(['rbac', 'accessPolicy'])
param kvPermissionModel string
param sqlServerFqdn string
param sqlDbName string

@description('What job-ops-smoke expects the broad option to be refused with')
@allowed(['RequestDisallowedByPolicy', 'AuthorizationFailed'])
param expectRefusal string = 'RequestDisallowedByPolicy'

var roles = {
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  managedIdentityOperator: 'f1a07417-d97a-45cb-824c-7a7467783830'
}
var opsSecretNames = ['ops-runner-key', 'ops-agent-key', 'recovery-grant-key', 'ops-cleanup-sql-password']

resource env 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: last(split(environmentId, '/'))
}
resource opsId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: opsIdentityName
}
resource refereeId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: refereeIdentityName
}
resource pullId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: pullIdentityName
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
  name: 'evidence'
}

// ---- least privilege on the control vault: each identity reads only its own secrets ----
resource opsSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = [for s in opsSecretNames: {
  parent: kv
  name: s
}]

resource opsSecretAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (s, i) in opsSecretNames: {
  name: guid(opsSecrets[i].id, opsId.id, roles.kvSecretsUser)
  scope: opsSecrets[i]
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
    principalId: opsId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource refereeSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = {
  parent: kv
  name: 'referee-sql-password'
}

resource refereeSecretAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(refereeSecret.id, refereeId.id, roles.kvSecretsUser)
  scope: refereeSecret
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
    principalId: refereeId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---- evidence: both append events and results; immutability stops either from rewriting ----
resource opsEvidence 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(evidence.id, opsId.id, roles.blobContributor)
  scope: evidence
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
    principalId: opsId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource refereeEvidence 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(evidence.id, refereeId.id, roles.blobContributor)
  scope: evidence
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
    principalId: refereeId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Deploying a revision PATCHes the order app, which carries id-lf-acrpull; Azure may check assign rights on it
resource opsAssignPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(pullId.id, opsId.id, roles.managedIdentityOperator)
  scope: pullId
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.managedIdentityOperator)
    principalId: opsId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---- the Ops Service may start the Referee and read its executions, nothing else ----
resource refereeStarter 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'lf-referee-starter')
  properties: {
    roleName: 'LiveFire Referee job starter (${resourceGroup().name})'
    description: 'Start job-referee and read its executions. Cannot change the job.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.App/jobs/read'
          'Microsoft.App/jobs/start/action'
          'Microsoft.App/jobs/execution/read'
          'Microsoft.App/jobs/executions/read'
        ]
      }
    ]
    assignableScopes: [resourceGroup().id]
  }
}

var secretUri = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets/'

resource referee 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-referee'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${refereeId.id}': {}, '${pullIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registryServer, identity: pullIdentityId }]
      secrets: [{ name: 'referee-sql-password', keyVaultUrl: '${secretUri}referee-sql-password', identity: refereeId.id }]
    }
    template: {
      containers: [
        {
          name: 'referee'
          image: refereeImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'ORDER_APP_URL', value: orderAppUrl }
            { name: 'SQL_SERVER_FQDN', value: sqlServerFqdn }
            { name: 'SQL_DB_NAME', value: sqlDbName }
            { name: 'REFEREE_SQL_PASSWORD', secretRef: 'referee-sql-password' }
            { name: 'EVIDENCE_URL', value: evidenceBlobUrl }
            { name: 'AZURE_CLIENT_ID', value: refereeId.properties.clientId }
            { name: 'DRILL_ID', value: 'unset' }
            { name: 'RUN_ID', value: 'unset' }
            { name: 'LABEL', value: 'unset' }
            { name: 'RUN_DIR', value: 'unset' }
          ]
        }
      ]
    }
  }
  dependsOn: [refereeSecretAccess, refereeEvidence]
}

resource opsStartsReferee 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(referee.id, opsId.id, refereeStarter.id)
  scope: referee
  properties: {
    roleDefinitionId: refereeStarter.id
    principalId: opsId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

var opsSecrets_ = [for s in opsSecretNames: { name: s, keyVaultUrl: '${secretUri}${s}', identity: opsId.id }]

resource ops 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-ops'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${opsId.id}': {}, '${pullIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{ server: registryServer, identity: pullIdentityId }]
      secrets: opsSecrets_
    }
    template: {
      containers: [
        {
          name: 'ops'
          image: opsImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'TWIN_BACKEND', value: 'azure' }
            { name: 'OPS_RUNNER_KEY', secretRef: 'ops-runner-key' }
            { name: 'OPS_AGENT_KEY', secretRef: 'ops-agent-key' }
            { name: 'RECOVERY_GRANT_KEY', secretRef: 'recovery-grant-key' }
            { name: 'OPS_CLEANUP_SQL_PASSWORD', secretRef: 'ops-cleanup-sql-password' }
            { name: 'EVENT_SOURCE', value: 'blob:${evidenceBlobUrl}' }
            { name: 'AZURE_CLIENT_ID', value: opsId.properties.clientId }
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'AZURE_TENANT_ID', value: subscription().tenantId }
            { name: 'TWIN_RG', value: twinRg }
            { name: 'CONTROL_RG', value: resourceGroup().name }
            { name: 'ORDER_APP_NAME', value: orderAppName }
            { name: 'ORDER_APP_URL', value: orderAppUrl }
            { name: 'KEYVAULT_ID', value: keyVaultId }
            { name: 'APP_IDENTITY_PRINCIPAL_ID', value: appIdentityPrincipalId }
            { name: 'APP_ACCESS_ASSIGNMENT_NAME', value: appAccessAssignmentName }
            { name: 'KV_PERMISSION_MODEL', value: kvPermissionModel }
            { name: 'IMAGE_REPO', value: imageRepo }
            { name: 'BASE_IMAGE', value: baseImage }
            { name: 'REFEREE_JOB_NAME', value: referee.name }
            { name: 'SQL_SERVER_FQDN', value: sqlServerFqdn }
            { name: 'SQL_DB_NAME', value: sqlDbName }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/health', port: 8080 }, periodSeconds: 10, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/health', port: 8080 }, periodSeconds: 10, failureThreshold: 3 }
          ]
        }
      ]
      // One replica: the action lock and the kill switch live in this process
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [opsSecretAccess, opsEvidence, opsStartsReferee]
}

var opsUrl = 'https://${ops.properties.configuration.ingress.fqdn}'

// Drives ca-ops from inside the environment, like WS4's runner: python -m ops.smoke all
resource smoke 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-ops-smoke'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${opsId.id}': {}, '${pullIdentityId}': {} }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registryServer, identity: pullIdentityId }]
      secrets: take(opsSecrets_, 3)
    }
    template: {
      containers: [
        {
          name: 'smoke'
          image: opsImage
          command: ['python', '-m', 'ops.smoke']
          args: ['all']
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'OPS_URL', value: opsUrl }
            { name: 'OPS_RUNNER_KEY', secretRef: 'ops-runner-key' }
            { name: 'OPS_AGENT_KEY', secretRef: 'ops-agent-key' }
            { name: 'RECOVERY_GRANT_KEY', secretRef: 'recovery-grant-key' }
            { name: 'IMAGE_REPO', value: imageRepo }
            { name: 'EXPECT_REFUSAL', value: expectRefusal }
            { name: 'SETTLE_S', value: '11' }
          ]
        }
      ]
    }
  }
  dependsOn: [opsSecretAccess]
}

output opsUrl string = opsUrl
output refereeJobName string = referee.name
output smokeJobName string = smoke.name
output environmentName string = env.name
