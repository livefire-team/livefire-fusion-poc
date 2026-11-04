#!/usr/bin/env bash
# One entry point for the G2 platform, in phases. Run from the repo root, signed in to the lab (az and azd).
#   scripts/deploy.sh all                     infra, images, apps, verify (a fresh lab)
#   scripts/deploy.sh infra                   azd provision: control plane and twin (the Ops Service waits for images)
#   scripts/deploy.sh images [--build] [ref]  order-service, ops-service and referee into the private registry
#                                             as :sha-<40 hex> of the last commit (at ref, default origin/main) that
#                                             changed each one: imported from GHCR, or built here with --build
#   scripts/deploy.sh apps                    azd provision with those images: ca-ops, job-referee, job-ops-smoke
#   scripts/deploy.sh policy                  the deny policy, proven as you, then the role that lets id-lf-ops try
#   scripts/deploy.sh policy-off              removes both (a provision never deletes them), e.g. before a lab ends
#   scripts/deploy.sh github [owner/repo]     a repo's acr-push environment and variables (repo admin only)
#   scripts/deploy.sh smoke [part] [--candidate <image>] [--fixed]
#                                             run job-ops-smoke (part: all, auth, policy, drill, kill, baselines)
#   scripts/deploy.sh verify                  internal ingress, the jobs, and the evidence store's write rules
set -euo pipefail
cd "$(dirname "$0")/.."
GHCR_OWNER="${GHCR_OWNER:-livefire-team}"

load() { set -a; eval "$(azd env get-values)"; set +a; }
say() { printf '\n== %s\n' "$*"; }

# component -> paths whose last change decides the image's commit, and how to build it
paths_for() {
  case "$1" in
    order-service) echo "src/order-service .github/workflows/order-service.yml" ;;
    ops-service)   echo "src/ops-service .github/workflows/ops-service.yml" ;;
    referee)       echo "referee journeys .github/workflows/referee.yml" ;;
  esac
}
build_args() {  # build_args <component>: docker context and Dockerfile, relative to a checkout
  case "$1" in
    order-service) echo "src/order-service -f src/order-service/Dockerfile" ;;
    ops-service)   echo "src/ops-service -f src/ops-service/Dockerfile" ;;
    referee)       echo ". -f referee/Dockerfile" ;;
  esac
}
env_name() {
  case "$1" in order-service) echo ORDER_IMAGE ;; ops-service) echo OPS_IMAGE ;; referee) echo REFEREE_IMAGE ;; esac
}

phase_infra() {
  say "azd provision (control plane and twin)"
  azd provision
}

phase_images() {
  load
  local build="" ref="origin/main"
  for a in "$@"; do case "$a" in --build) build=1 ;; *) ref="$a" ;; esac; done
  [ -n "${REGISTRY_NAME:-}" ] || { echo "no REGISTRY_NAME: run scripts/deploy.sh infra first"; exit 1; }
  git fetch -q origin
  for c in order-service ops-service referee; do
    local full
    # shellcheck disable=SC2046  # paths_for prints several paths on purpose
    full="$(git log -1 --first-parent --format=%H "$ref" -- $(paths_for "$c"))"
    [ -n "$full" ] || { echo "no commit at $ref touches $c"; exit 1; }
    local tag="sha-$full" short="sha-${full:0:7}" image="$REGISTRY_SERVER/$c:sha-$full"
    say "$c at ${full:0:7}"
    if az acr repository show -n "$REGISTRY_NAME" --image "$c:$tag" -o none 2>/dev/null; then
      echo "already in the registry: $image"
    elif [ -z "$build" ]; then
      local creds=()
      [ -z "${GHCR_TOKEN:-}" ] || creds=(--username "${GHCR_USER:?set GHCR_USER with GHCR_TOKEN}" --password "$GHCR_TOKEN")
      # ${creds[@]+...}: macOS bash 3.2 treats an empty array as unset under set -u
      az acr import -n "$REGISTRY_NAME" --source "ghcr.io/$GHCR_OWNER/$c:$short" --image "$c:$tag" \
        ${creds[@]+"${creds[@]}"} -o none
      echo "imported ghcr.io/$GHCR_OWNER/$c:$short -> $image"
    else
      local dir; dir="$(mktemp -d)"
      git worktree add -q --detach "$dir" "$full"
      az acr login -n "$REGISTRY_NAME"
      # shellcheck disable=SC2046
      (cd "$dir" && docker buildx build --platform linux/amd64 --build-arg "GIT_SHA=$full" -t "$image" --push \
        $(build_args "$c"))
      git worktree remove --force "$dir"
      echo "built and pushed $image"
    fi
    azd env set "$(env_name "$c")" "$image"
  done
}

phase_apps() {
  load
  [ -n "${OPS_IMAGE:-}" ] && [ -n "${REFEREE_IMAGE:-}" ] || { echo "run scripts/deploy.sh images first"; exit 1; }
  say "azd provision (ca-ops, job-referee, job-ops-smoke; twin on $ORDER_IMAGE)"
  azd provision
  load
  echo "OPS_URL=$OPS_URL"
  case "$OPS_URL" in *.internal.*) ;; *) echo "ca-ops is not internal-only"; exit 1 ;; esac
}

phase_policy() {
  load
  say "deny policy on"
  azd env set DENY_BROAD_POLICY on
  azd provision
  say "waiting until the broad option is refused by Azure Policy (a new assignment can take up to 30 minutes)"
  local out rc
  for i in $(seq 40); do
    DRILL_ID="drill-policy-check-$(date -u +%Y%m%d-%H%M%S)"; export DRILL_ID
    rc=0; out="$(./scripts/recover.sh broad 2>&1)" || rc=$?
    echo "attempt $i: $out"
    if [ "$rc" -eq 0 ] && grep -q RequestDisallowedByPolicy <<<"$out"; then break; fi
    [ "$i" -lt 40 ] || { echo "the policy never took effect"; exit 1; }
    sleep 60
  done
  say "let id-lf-ops attempt Contributor (so only Azure Policy can stop it)"
  azd env set BROAD_ATTEMPT_ROLE on
  azd provision
}

phase_policy_off() {
  load
  local scope="/subscriptions/$AZURE_SUBSCRIPTION_ID" role="Role Based Access Control Administrator"
  say "removing id-lf-ops's broad-attempt role, then the deny policy"
  az role assignment delete --assignee "$OPS_PRINCIPAL_ID" --role "$role" --scope "$scope" -o none || true
  # the policy is what refuses id-lf-ops's Contributor attempt, so it stays until the role is gone
  [ "$(az role assignment list --assignee "$OPS_PRINCIPAL_ID" --role "$role" --scope "$scope" --query 'length(@)' -o tsv)" = 0 ] \
    || { echo "id-lf-ops still holds $role on the subscription: the deny policy stays"; exit 1; }
  az policy assignment delete --name lf-deny-broad-roles --scope "$scope" -o none || true
  azd env set DENY_BROAD_POLICY off
  azd env set BROAD_ATTEMPT_ROLE off
  az policy assignment list --query "[?name=='lf-deny-broad-roles'].name" -o tsv
  echo "done: run scripts/deploy.sh apps so job-ops-smoke expects AuthorizationFailed again"
}

phase_github() {
  load
  local repo="${1:-livefire-team/livefire-fusion-poc}"
  say "acr-push environment on $repo (needs repo admin)"
  gh api -X PUT "repos/$repo/environments/acr-push" --input - <<'JSON' > /dev/null
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
  for b in main 'candidate/*'; do
    gh api -X POST "repos/$repo/environments/acr-push/deployment-branch-policies" -f "name=$b" -f type=branch \
      > /dev/null 2>&1 || true                                  # already there
  done
  gh variable set AZURE_CLIENT_ID --env acr-push --repo "$repo" --body "$CI_CLIENT_ID"
  gh variable set AZURE_TENANT_ID --env acr-push --repo "$repo" --body "$AZURE_TENANT_ID"
  gh variable set AZURE_SUBSCRIPTION_ID --env acr-push --repo "$repo" --body "$AZURE_SUBSCRIPTION_ID"
  gh variable set ACR_NAME --env acr-push --repo "$repo" --body "$REGISTRY_NAME"
  gh variable set ACR_SERVER --env acr-push --repo "$repo" --body "$REGISTRY_SERVER"
  echo "CI pushes now reach $REGISTRY_SERVER as :sha-<40 hex>"
}

phase_smoke() {
  load
  local part=all candidate=none fixed=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --candidate) candidate="${2:?--candidate needs an image}"; shift ;;
      --fixed) fixed=1 ;;
      *) part="$1" ;;
    esac
    shift
  done
  say "job-ops-smoke $part (candidate: $candidate, fixed: $fixed)"
  az containerapp job update -g "$CONTROL_RG" -n "$SMOKE_JOB_NAME" --args "$part" \
    --set-env-vars "CANDIDATE_IMAGE=$candidate" "CANDIDATE_FIXED=$fixed" -o none
  local name; name="$(az containerapp job start -g "$CONTROL_RG" -n "$SMOKE_JOB_NAME" --query name -o tsv)"
  echo "execution $name"
  local status=""
  for _ in $(seq 120); do
    status="$(az containerapp job execution show -g "$CONTROL_RG" -n "$SMOKE_JOB_NAME" --job-execution-name "$name" \
      --query properties.status -o tsv)"
    case "$status" in Succeeded|Failed|Stopped|Degraded) break ;; esac
    sleep 15
  done
  echo "status: $status (the console log reaches Log Analytics a minute or two after the end)"
  sleep 90
  az monitor log-analytics query -w "$CONTROL_LOG_ANALYTICS_CUSTOMER_ID" -o tsv --query "[].Log_s" \
    --analytics-query "ContainerAppConsoleLogs_CL | where ContainerGroupName_s startswith '$name'
                       | order by TimeGenerated asc | project Log_s" || true
  [ "$status" = Succeeded ]
}

phase_verify() {
  load
  say "ca-ops ingress"
  az containerapp show -g "$CONTROL_RG" -n ca-ops \
    --query "{fqdn:properties.configuration.ingress.fqdn, external:properties.configuration.ingress.external, replicas:properties.template.scale}" -o jsonc
  case "$OPS_URL" in *.internal.*) echo "internal only: yes" ;; *) echo "internal only: NO"; exit 1 ;; esac
  say "jobs"
  az containerapp job list -g "$CONTROL_RG" --query "[].{name:name, trigger:properties.configuration.triggerType}" -o table
  say "evidence store rules"
  python scripts/evidence_check.py
}

case "${1:-}" in
  all) phase_infra; phase_images origin/main; phase_apps; phase_verify ;;
  infra|images|apps|policy|github|smoke|verify) p="$1"; shift; "phase_$p" "$@" ;;
  policy-off) phase_policy_off ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
