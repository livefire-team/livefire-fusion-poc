// Load generator: a Container Apps Job in the twin's Container Apps environment that places a steady stream of
// orders through the order service's JSON API and retries failed ones from an in-memory backlog (ADR-015).
// Deploy it in the same resource group as twin.bicep, after it, e.g. from WS2's main.bicep:
//
//   module loadgen 'modules/loadgen.bicep' = {
//     name: 'loadgen'
//     params: {
//       location: location
//       loadgenImage: 'ghcr.io/livefire-team/load-generator:g2'
//       orderAppUrl: twin.outputs.orderAppUrl
//       appInsightsConnectionString: twin.outputs.appInsightsConnectionString
//     }
//   }
//
// Start a manual run with: az containerapp job start -g <rg> -n <jobName>

@description('Azure region; use the same one as twin.bicep.')
param location string

@description('Name of the existing Container Apps environment created by twin.bicep, in this resource group.')
param containerAppsEnvironmentName string = 'cae-lf-twin'

@description('Name of the Container Apps Job.')
@maxLength(32)
param jobName string = 'caj-loadgen'

@description('Load generator image, e.g. ghcr.io/livefire-team/load-generator:sha-<commit>. Public on GHCR, so no registry credentials.')
param loadgenImage string

@description('Base URL of the order service (twin.bicep output orderAppUrl), e.g. https://ca-order.<env>.azurecontainerapps.io.')
param orderAppUrl string

@description('Application Insights connection string (twin.bicep output appInsightsConnectionString). Empty disables telemetry export.')
@secure()
param appInsightsConnectionString string = ''

@description('New orders per minute (RATE_PER_MINUTE). Retries from the backlog come on top.')
@minValue(1)
@maxValue(600)
param ratePerMinute int = 30

@description('Comma-separated SKUs to order, in turn (SKUS).')
param skus string = 'SKU-001,SKU-002'

@description('Optional x-drill-id header value (DRILL_ID): 1-64 letters, digits or . _ : -. Empty sends no header.')
param drillId string = ''

@description('How long one job execution places orders, in seconds (DURATION_SECONDS).')
@minValue(60)
@maxValue(86000)
param durationSeconds int = 3600

@description('Manual: start each run with `az containerapp job start`. Schedule: run on cronExpression.')
@allowed(['Manual', 'Schedule'])
param triggerType string = 'Manual'

@description('Cron expression (UTC) used when triggerType is Schedule.')
param cronExpression string = '0 * * * *'

// Time for the job to stop cleanly after DURATION_SECONDS before the platform ends the replica.
var shutdownGraceSeconds = 300
var connectionStringSecretName = 'appinsights-connection-string'
var hasTelemetry = !empty(appInsightsConnectionString)

var baseEnv = [
  { name: 'ORDER_APP_URL', value: orderAppUrl }
  { name: 'RATE_PER_MINUTE', value: string(ratePerMinute) }
  { name: 'SKUS', value: skus }
  { name: 'DURATION_SECONDS', value: string(durationSeconds) }
]
var drillEnv = empty(drillId) ? [] : [{ name: 'DRILL_ID', value: drillId }]
var telemetryEnv = hasTelemetry
  ? [{ name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: connectionStringSecretName }]
  : []

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  properties: {
    environmentId: cae.id
    configuration: {
      triggerType: triggerType
      replicaTimeout: durationSeconds + shutdownGraceSeconds
      replicaRetryLimit: 0
      manualTriggerConfig: triggerType == 'Manual' ? { parallelism: 1, replicaCompletionCount: 1 } : null
      scheduleTriggerConfig: triggerType == 'Schedule'
        ? { cronExpression: cronExpression, parallelism: 1, replicaCompletionCount: 1 }
        : null
      secrets: hasTelemetry ? [{ name: connectionStringSecretName, value: appInsightsConnectionString }] : []
    }
    template: {
      containers: [
        {
          name: 'load-generator'
          image: loadgenImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: concat(baseEnv, drillEnv, telemetryEnv)
        }
      ]
    }
  }
}

output loadgenJobName string = job.name
output loadgenJobId string = job.id
