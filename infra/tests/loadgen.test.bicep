// Compile-only harness for infra/modules/loadgen.bicep, wired to twin.bicep the way WS2's main.bicep would be.
// Build it with `az bicep build --file infra/tests/loadgen.test.bicep --stdout`. Not meant to be deployed.

@secure()
param sqlAdminPassword string

module twin '../modules/twin.bicep' = {
  name: 'twin-test'
  params: {
    location: resourceGroup().location
    principalId: '00000000-0000-0000-0000-000000000000'
    kvPermissionModel: 'rbac'
    orderImage: 'ghcr.io/livefire-team/order-service:g1'
    sqlAdminPassword: sqlAdminPassword
  }
}

module loadgenManual '../modules/loadgen.bicep' = {
  name: 'loadgen-manual-test'
  params: {
    location: resourceGroup().location
    loadgenImage: 'ghcr.io/livefire-team/load-generator:g2'
    orderAppUrl: twin.outputs.orderAppUrl
    appInsightsConnectionString: twin.outputs.appInsightsConnectionString
  }
}

module loadgenScheduled '../modules/loadgen.bicep' = {
  name: 'loadgen-schedule-test'
  params: {
    location: resourceGroup().location
    jobName: 'caj-loadgen-sched'
    loadgenImage: 'ghcr.io/livefire-team/load-generator:g2'
    orderAppUrl: twin.outputs.orderAppUrl
    ratePerMinute: 60
    drillId: 'rehearsal-1'
    durationSeconds: 1800
    triggerType: 'Schedule'
    cronExpression: '*/30 * * * *'
  }
}

output loadgenJobName string = loadgenManual.outputs.loadgenJobName
output loadgenScheduledJobId string = loadgenScheduled.outputs.loadgenJobId
