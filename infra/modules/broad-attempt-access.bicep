// WS2, G2: lets id-lf-ops ATTEMPT Contributor on the subscription for the order app's identity and nothing else,
// so the refusal of the broad option comes from Azure Policy (RequestDisallowedByPolicy) rather than from a missing
// right (AuthorizationFailed). main.bicep deploys it only with the deny policy on. If that policy were ever removed,
// this identity could grant Contributor to the order app's identity: the Ops Service removes any such grant at once
// and records UNEXPECTED_ALLOW.
targetScope = 'subscription'

param opsPrincipalId string
@description('The order app identity, the only principal the broad option names')
param appPrincipalId string

var rbacAdminRoleId = 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

resource opsBroadAttempt 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, opsPrincipalId, rbacAdminRoleId, 'broad-attempt')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rbacAdminRoleId)
    principalId: opsPrincipalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${contributorRoleId}} AND @Request[Microsoft.Authorization/roleAssignments:PrincipalId] ForAnyOfAnyValues:GuidEquals {${appPrincipalId}})) AND ((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/delete\'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${contributorRoleId}} AND @Resource[Microsoft.Authorization/roleAssignments:PrincipalId] ForAnyOfAnyValues:GuidEquals {${appPrincipalId}}))'
  }
}
