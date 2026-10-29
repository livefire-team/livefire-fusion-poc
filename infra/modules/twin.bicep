// LiveFire disposable twin: order service, SQL, Key Vault, telemetry (WS1)
// Contract: contracts/twin-interface.md. Plain Bicep resources, not Azure Verified Modules (ADR-008).

param location string

@description('Object ID of the person (or service principal) running azd')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@allowed(['rbac', 'accessPolicy'])
param kvPermissionModel string = 'rbac'

@description('Full image reference, e.g. ghcr.io/<org>/order-service:g1')
param orderImage string

@secure()
param sqlAdminPassword string

@description('How long the order path caches the DB password; 10 while testing')
param secretRefreshSeconds int = 30

var suffix = uniqueString(resourceGroup().id)
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var kvSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var dbName = 'orders'
var appPort = 8000

// ---- telemetry ----
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-lf-twin-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-lf-twin-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// ---- identity and Key Vault ----
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-order-app'
  location: location
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-lf-${take(suffix, 13)}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: kvPermissionModel == 'rbac'
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    accessPolicies: kvPermissionModel == 'accessPolicy'
      ? [
          {
            tenantId: subscription().tenantId
            objectId: appIdentity.properties.principalId
            permissions: { secrets: ['get', 'list'] }
          }
          {
            tenantId: subscription().tenantId
            objectId: principalId
            permissions: { secrets: ['get', 'list', 'set'] }
          }
        ]
      : []
  }
}

// The app identity reads secrets through Azure RBAC (Key Vault Secrets User).
// The deterministic name lets WS2's tooling find and recreate exactly this assignment.
resource appAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (kvPermissionModel == 'rbac') {
  name: guid(kv.id, appIdentity.id, kvSecretsUserRoleId)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The person running azd can write the DB secret in WS2's post-provision hook
resource deployerSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (kvPermissionModel == 'rbac') {
  name: guid(kv.id, principalId, kvSecretsOfficerRoleId)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficerRoleId)
    principalId: principalId
    principalType: principalType
  }
}

// ---- Azure SQL ----
resource sql 'Microsoft.Sql/servers@2021-11-01' = {
  name: 'sql-lf-${suffix}'
  location: location
  properties: {
    administratorLogin: 'lfadmin'
    administratorLoginPassword: sqlAdminPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// Basic tier: always on, so no cold start on the first request (ADR-007)
resource sqlDb 'Microsoft.Sql/servers/databases@2021-11-01' = {
  parent: sql
  name: dbName
  location: location
  sku: { name: 'Basic', tier: 'Basic' }
}

// Lets Container Apps reach SQL. WS2's hook adds a rule for the machine running azd.
resource allowAzure 'Microsoft.Sql/servers/firewallRules@2021-11-01' = {
  parent: sql
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ---- Container Apps ----
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-lf-twin'
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

// The image is public on GHCR (ADR-002), so no registry credentials are configured.
resource orderApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-order'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${appIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: appPort
        transport: 'auto'
      }
    }
    template: {
      containers: [
        {
          name: 'order-service'
          image: orderImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'KEYVAULT_URL', value: kv.properties.vaultUri }
            { name: 'SECRET_NAME', value: 'db-password' }
            { name: 'AZURE_CLIENT_ID', value: appIdentity.properties.clientId }
            { name: 'SQL_SERVER_FQDN', value: sql.properties.fullyQualifiedDomainName }
            { name: 'SQL_DB_NAME', value: dbName }
            { name: 'SQL_USER', value: 'order_app' }
            { name: 'SECRET_REFRESH_SECONDS', value: string(secretRefreshSeconds) }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
          ]
          // Probes check the process only (/health), so a dependency outage does not make
          // the platform restart the app (ADR-006).
          probes: [
            { type: 'Liveness', httpGet: { path: '/health', port: appPort }, periodSeconds: 10, failureThreshold: 3 }
            { type: 'Readiness', httpGet: { path: '/health', port: appPort }, periodSeconds: 10, failureThreshold: 3 }
          ]
        }
      ]
      // Exactly one replica (ADR-006)
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output keyVaultName string = kv.name
output keyVaultId string = kv.id
output appIdentityPrincipalId string = appIdentity.properties.principalId
output appAccessAssignmentName string = guid(kv.id, appIdentity.id, kvSecretsUserRoleId)
output orderAppName string = orderApp.name
output orderAppUrl string = 'https://${orderApp.properties.configuration.ingress.fqdn}'
output sqlServerFqdn string = sql.properties.fullyQualifiedDomainName
output sqlDbName string = dbName
output appInsightsConnectionString string = appi.properties.ConnectionString
