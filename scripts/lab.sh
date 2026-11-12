#!/usr/bin/env bash
# Lab tools for G3, next to deploy.sh. Run from the repo root, signed in to the lab (az and azd), with .venv active.
#   scripts/lab.sh sync [--apply]                 compares this machine's azd values with the selected environment's
#                                                 last successful provision, from any machine; --apply takes the lab's.
#                                                 Run it before any provision from this machine (ADR-025)
#   scripts/lab.sh state                          read-only: is the twin back at its baseline? Before a drill, and
#                                                 after one ends (T-07, T-09). Exits 1 and names each difference
#   scripts/lab.sh new-env <name> [--from <env>]  a second azd environment with the source's settings (default: the
#                                                 selected one), for the clean-lab rebuild (ADR-025); then
#                                                 time scripts/deploy.sh all
#   scripts/lab.sh teardown <name> --yes          deletes a second environment, its evidence included, then selects
#                                                 lf-eh again. Never the team's environment (PROTECTED_ENVS)
set -euo pipefail
cd "$(dirname "$0")/.."
GHCR_OWNER="${GHCR_OWNER:-livefire-team}"
PROTECTED_ENVS="${PROTECTED_ENVS:-lf-eh}"

load() { set -a; eval "$(azd env get-values)"; set +a; }
say() { printf '\n== %s\n' "$*"; }
selected_env() { azd env list | awk '$2 == "true" { print $1 }'; }
usage() { sed -n '2,/^set -euo pipefail$/{/^set -euo/!p;}' "$0"; exit 2; }

# Each machine keeps its own copy of an azd environment, and every team signs in to the lab as the same user. The
# deployment history is the one record they share: the last successful provision's parameters (mapped back to azd
# names through main.parameters.json) and its outputs. Secure parameters carry no value there, so no secret is read.
phase_sync() {
  local apply="" name dep params outputs k v here n=0
  [ "${1:-}" != --apply ] || apply=1
  load
  name="$(az deployment sub list --query "sort_by([?starts_with(name, '${AZURE_ENV_NAME}-') \
    && properties.provisioningState == 'Succeeded'], &properties.timestamp)[-1].name" -o tsv)"
  [ -n "$name" ] || { echo "no successful provision of $AZURE_ENV_NAME in this subscription"; exit 1; }
  dep="$(az deployment sub show -n "$name" --query "{p: properties.parameters, o: properties.outputs}" -o json)"
  # One assignment each, so a failed jq stops here (bash 3.2 ignores all but the last command inside one $(...))
  params="$(jq -r --argjson d "$dep" '.parameters | to_entries[]
    | ((.value.value | tostring | capture("^\\$\\{(?<k>[A-Z0-9_]+)")) // {k: null}).k as $k
    | select($k != null and $d.p[.key].value != null)
    | "\($k)\t\($d.p[.key].value | tostring)"' infra/main.parameters.json)"
  # ARM changes the case of output names (twiN_RG), so they are upper-cased back
  outputs="$(jq -r '.o // {} | to_entries[] | "\(.key | ascii_upcase)\t\(.value.value | tostring)"' <<<"$dep")"
  say "$AZURE_ENV_NAME on this machine, against its last successful provision ($name)"
  # a value pasted from a chat: deploy.sh refuses to provision with one, so name it here too
  azd env get-values | { LC_ALL=C grep '[^ -~]' || true; } | cut -d= -f1 | while read -r k; do
    echo "WARNING: $k holds curly quotes or other non-ASCII characters (pasted from a chat?)"
  done
  while IFS=$'\t' read -r k v; do
    case "$k" in AZURE_*|SQL_ADMIN_PASSWORD) continue ;; esac  # azd's own, and the one secure value
    here="${!k:-}"
    [ "$here" != "$v" ] || continue
    if [ -z "$v" ]; then
      echo "info  $k is set here, empty in the lab: a provision from here would deploy it"
      continue
    fi
    if [ -z "$here" ]; then echo "missing here  $k"; else echo "differs       $k"; fi
    n=$((n + 1))
    [ -z "$apply" ] || azd env set "$k" "$v"
  done <<<"$params"$'\n'"$outputs"
  if [ "$n" -eq 0 ]; then echo "in step with the lab"
  elif [ -n "$apply" ]; then echo "$n value(s) taken from the lab"
  else echo "$n value(s) differ: rerun with --apply to take the lab's"; return 1; fi
}

phase_state() {
  load
  local bad=0 n image digest revisions scale deps
  ok() { echo "ok    $*"; }
  no() { echo "NOT   $*"; bad=1; }

  if [ "${KV_PERMISSION_MODEL:-rbac}" = accessPolicy ]; then
    n="$(az keyvault show -n "$KEYVAULT_NAME" \
      --query "length(properties.accessPolicies[?objectId=='$APP_IDENTITY_PRINCIPAL_ID'])" -o tsv)"
  else
    n="$(az role assignment list --scope "$KEYVAULT_ID" --assignee "$APP_IDENTITY_PRINCIPAL_ID" \
      --role "Key Vault Secrets User" --query "length(@)" -o tsv)"
  fi
  if [ "$n" = 1 ]; then ok "the app has one Key Vault access entry"
  else no "the app has $n Key Vault access entries (want 1)"; fi

  # reset_twin restarts the base image when it is already running, by tag or by digest, and redeploys it by digest
  image="$(az containerapp show -g "$TWIN_RG" -n "$ORDER_APP_NAME" --query "properties.template.containers[0].image" -o tsv)"
  digest="$(az acr repository show -n "$REGISTRY_NAME" --image "${ORDER_IMAGE##*/}" --query digest -o tsv 2>/dev/null || true)"
  if [ "$image" = "$ORDER_IMAGE" ] || { [ -n "$digest" ] && [ "$image" = "${ORDER_IMAGE%%:*}@$digest" ]; }; then
    ok "the order app runs the base image"
  else no "the order app runs $image, not the base image $ORDER_IMAGE"; fi

  revisions="$(az containerapp revision list -g "$TWIN_RG" -n "$ORDER_APP_NAME" \
    --query "length([?properties.active])" -o tsv)"
  if [ "$revisions" = 1 ]; then ok "one active revision"; else no "$revisions active revisions (want 1)"; fi
  scale="$(az containerapp show -g "$TWIN_RG" -n "$ORDER_APP_NAME" \
    --query "join('/', [to_string(properties.template.scale.minReplicas), to_string(properties.template.scale.maxReplicas)])" -o tsv)"
  if [ "$scale" = 1/1 ]; then ok "replicas min/max 1/1"; else no "replicas min/max $scale (want 1/1)"; fi

  deps="$(curl -s -m 10 "$ORDER_APP_URL/health/dependencies" | jq -r '"\(.keyvault)/\(.sql)"' 2>/dev/null || true)"
  if [ "$deps" = ok/ok ]; then ok "dependencies keyvault/sql: ok/ok"
  else no "dependencies keyvault/sql: ${deps:-unreachable}"; fi

  if [ -n "${RUNNER_JOB_NAME:-}" ]; then
    n="$(az containerapp job execution list -g "$CONTROL_RG" -n "$RUNNER_JOB_NAME" \
      --query "length([?properties.status=='Running'])" -o tsv)"
    if [ "$n" = 0 ]; then ok "no drill is running"; else no "$n drill execution(s) still running"; fi
  fi

  if [ "$(az policy assignment list --query "length([?name=='lf-deny-broad-roles'])" -o tsv)" = 1 ]; then
    echo "info  deny policy: on"
  else echo "info  deny policy: off"; fi
  echo "info  candidate branches on GitHub: $(git ls-remote origin 'refs/heads/candidate/*' 2>/dev/null | wc -l | tr -d ' ')"

  if [ "$bad" -eq 0 ]; then echo "twin at baseline"; else echo "twin NOT at baseline"; return 1; fi
}

# Settings a clean lab copies. Not copied: secrets (a new SQL password is generated; the post-provision hook makes
# the rest, and copies the GitHub App keys from the source's control vault), the images in the source's registry
# (deploy.sh images imports them again), the agents' pinned versions (deploy.sh all creates agents in the new Foundry
# project), Entra-mode identities, and every Bicep output.
COPY="KV_PERMISSION_MODEL SECRET_REFRESH_SECONDS AZURE_PRINCIPAL_TYPE DENY_BROAD_POLICY BROAD_ATTEMPT_ROLE
  EVIDENCE_RETENTION_DAYS GITHUB_REPOS MCP_GITHUB_REPO MCP_GITHUB_AUTH GITHUB_PLANNER_APP_ID
  GITHUB_PLANNER_INSTALLATION_ID GITHUB_ENGINEER_APP_ID GITHUB_ENGINEER_INSTALLATION_ID MCP_REPO_REF
  MCP_ENGINEER_WRITE_PATHS MCP_AUTH_MODE SEARCH_LOCATION SEARCH_VECTOR_FIELD INCIDENT_CORPUS GITHUB_APP_KEYS
  LOADGEN_DRILL_ID MODEL_NAME MODEL_VERSION MODEL_CAPACITY PROMPT_SHIELDS RUNNER_GITHUB_AUTH RUNNER_GITHUB_APP_ID
  RUNNER_GITHUB_INSTALLATION_ID TARGET_RECOVERY_S RUNNER_DEFAULT_MODE CONTROL_CENTER_SOURCE CONTROL_CENTER_AUTH_MODE
  CONTROL_CENTER_ALLOWED_IPS CONTROL_CENTER_TARGET_RECOVERY_S"

phase_new_env() {
  local name="" from="" values k v
  while [ $# -gt 0 ]; do
    case "$1" in --from) from="${2:?--from needs an environment}"; shift ;; *) name="$1" ;; esac
    shift
  done
  [ -n "$name" ] || usage
  if azd env list | awk 'NR > 1 { print $1 }' | grep -qx "$name"; then echo "$name already exists"; exit 1; fi
  from="${from:-$(selected_env)}"
  values="$(azd env get-values -e "$from")"
  get() { sed -n "s/^$1=\"\(.*\)\"$/\1/p" <<<"$values"; }

  say "azd environment $name, settings from $from"
  azd env new "$name" --subscription "$(get AZURE_SUBSCRIPTION_ID)" --location "$(get AZURE_LOCATION)"
  for k in $COPY; do
    v="$(get "$k")"
    [ -z "$v" ] || azd env set -e "$name" "$k" "$v"
  done
  # the hook copies the GitHub App keys from here, so nobody handles the .pem files (ADR-025)
  azd env set -e "$name" SECRETS_SOURCE_VAULT "$(get CONTROL_KEYVAULT_NAME)"
  azd env set -e "$name" SQL_ADMIN_PASSWORD "$(openssl rand -base64 24 | tr -d ';}!')"
  # the new registry is empty until deploy.sh images, so the first provision pulls the same build from GHCR
  azd env set -e "$name" ORDER_IMAGE \
    "$(get ORDER_IMAGE | sed -E "s#^[^/]+/order-service:sha-([0-9a-f]{7}).*#ghcr.io/$GHCR_OWNER/order-service:sha-\1#")"
  v="$(get INCIDENT_CORPUS)"
  [ -z "$v" ] || [ -d "$v" ] || echo "WARNING: INCIDENT_CORPUS is not a folder here ($v): the index won't load" >&2
  echo "$name is selected. Next: time scripts/deploy.sh all"
}

phase_teardown() {
  local name="" yes="" a before v
  for a in "$@"; do case "$a" in --yes) yes=1 ;; *) name="$a" ;; esac; done
  [ -n "$name" ] || usage
  case " $PROTECTED_ENVS " in *" $name "*) echo "refused: $name is the team's environment"; exit 1 ;; esac
  [ -n "$yes" ] || { echo "this deletes every resource in $name, its evidence included; rerun with --yes"; exit 1; }
  before="$(selected_env)"
  [ "$before" != "$name" ] || before="${PROTECTED_ENVS%% *}"
  azd env select "$name"
  # whatever happens below, the next command must not land in the half-deleted environment. Expanded now: the trap
  # runs after this function has returned, when its locals are gone
  # shellcheck disable=SC2064
  trap "azd env select '$before'; echo '$before selected'" EXIT
  load

  say "1. $name's id-lf-ops: its subscription-scope role goes (the deny policy is shared with lf-eh, so it stays)"
  az role assignment delete --assignee "$OPS_PRINCIPAL_ID" --role "Role Based Access Control Administrator" \
    --scope "/subscriptions/$AZURE_SUBSCRIPTION_ID" -o none || true

  say "2. evidence: the unlocked immutability policies go, then azd down"
  python scripts/evidence_unlock.py --yes
  if ! azd down --force --purge; then
    echo "azd down failed: unlocking the evidence again (new versions may have been written) and retrying once" >&2
    python scripts/evidence_unlock.py --yes
    azd down --force --purge
  fi

  say "3. anything a failed down left soft-deleted"
  for v in "${KEYVAULT_NAME:-}" "${CONTROL_KEYVAULT_NAME:-}"; do
    [ -n "$v" ] || continue
    if [ -n "$(az keyvault list-deleted --resource-type vault --query "[?name=='$v'].name" -o tsv)" ]; then
      az keyvault purge -n "$v" -o none
      echo "purged vault $v"
    fi
  done
  # a soft-deleted Foundry account keeps its model quota until it is purged
  if [ -n "${FOUNDRY_NAME:-}" ] && [ -n "$(az cognitiveservices account list-deleted \
    --query "[?name=='$FOUNDRY_NAME'].name" -o tsv)" ]; then
    az cognitiveservices account purge -g "$CONTROL_RG" -n "$FOUNDRY_NAME" -l "$AZURE_LOCATION" -o none
    echo "purged Foundry account $FOUNDRY_NAME"
  fi

  rm -rf ".azure/$name"
  echo "$name removed. If CI's acr-push still names its registry: azd env select lf-eh && scripts/deploy.sh github"
}

case "${1:-}" in
  sync) shift; phase_sync "$@" ;;
  state) phase_state ;;
  new-env|teardown) p="${1//-/_}"; shift; "phase_$p" "$@" ;;
  *) usage ;;
esac
