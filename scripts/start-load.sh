#!/usr/bin/env bash
# Starts one run of WS1's load generator (caj-loadgen) for one drill, so orders keep flowing through the fault and
# its metrics.orders lines land in that drill's event log (ADR-021). scripts/start-drill.sh calls it.
#   scripts/start-load.sh <drill-id>     stops a run left from an earlier drill, then starts one for this drill
#   scripts/start-load.sh --stop         stops the running load, e.g. after a drill ends
set -euo pipefail
cd "$(dirname "$0")/.."
command -v jq >/dev/null || { echo "jq is needed" >&2; exit 2; }
ARG="${1:-}"
# The event log's rule for a drill ID, which the load generator also enforces at start
if [ "$ARG" != --stop ] && ! [[ "$ARG" =~ ^drill-[A-Za-z0-9-]{1,58}$ ]]; then
  echo "usage: scripts/start-load.sh <drill-id> | --stop (a drill ID is drill-<letters, digits, hyphens>)" >&2
  exit 2
fi
set -a; eval "$(azd env get-values)"; set +a
JOB="${LOADGEN_JOB_NAME:-}"
[ -n "$JOB" ] || { echo "no load generator in this environment (LOADGEN_IMAGE unset): no load started"; exit 0; }

# One run at a time: a run for an earlier drill would keep writing to that drill's log
for e in $(az containerapp job execution list -n "$JOB" -g "$TWIN_RG" \
  --query "[?properties.status=='Running'].name" -o tsv); do
  az containerapp job stop -n "$JOB" -g "$TWIN_RG" --job-execution-name "$e" -o none
  echo "stopped load run $e"
done
[ "$ARG" != --stop ] || exit 0

job_id=$(az containerapp job show -n "$JOB" -g "$TWIN_RG" --query id -o tsv)
template=$(az containerapp job show -n "$JOB" -g "$TWIN_RG" --query "properties.template.containers[0]" -o json)
jq -e '[.env[] | select(.name == "EVENT_SOURCE")] | length > 0' <<<"$template" >/dev/null \
  || echo "WARNING: $JOB writes no metrics.orders lines (its LOADGEN_DRILL_ID must start with drill-): load only" >&2
# A start request replaces the container's whole env list, secret references included, so send the template's list
# back with this drill's ID (the same way start-drill.sh starts the runner)
body=$(jq --arg d "$ARG" '{containers: [.env |= ([.[] | select(.name != "DRILL_ID")] + [{name: "DRILL_ID", value: $d}])]}' \
  <<<"$template")
name=$(az rest --method post --url "https://management.azure.com${job_id}/start?api-version=2024-03-01" --body "$body" \
  --query name -o tsv)
echo "load for $ARG started ($name)"
