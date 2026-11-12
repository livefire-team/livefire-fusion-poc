#!/usr/bin/env bash
# Starts one drill as one execution of job-drill-runner (WS4, ADR-026), then prints where to watch it.
#   scripts/start-drill.sh                       Autonomous Twin, T-01 (evaluation and repeatability runs)
#   scripts/start-drill.sh Supervised            a person makes the recovery and deploy decisions
#   scripts/start-drill.sh Supervised T-00       baseline only
# Start drills only with this script: it refuses a second drill while one runs, and it keeps the job's secret
# references when it sets the drill's values (a KeyError: 'OPS_KEY' in the logs means a drill started another way).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v jq >/dev/null || { echo "jq is needed" >&2; exit 2; }
set -a; eval "$(azd env get-values)"; set +a
MODE="${1:-Autonomous Twin}"
SCENARIO="${2:-T-01}"
case "$MODE" in Advisory|Supervised|"Autonomous Twin") ;; *) echo "mode: Advisory, Supervised or Autonomous Twin" >&2; exit 2 ;; esac
JOB="${RUNNER_JOB_NAME:-}"
[ -n "$JOB" ] || { echo "no RUNNER_JOB_NAME: deploy the runner first (scripts/deploy.sh runner)" >&2; exit 2; }
DRILL_ID="drill-$(date -u +%Y%m%d-%H%M%S)"     # lowercase: candidate branch names must be (order-service.yml)

running=$(az containerapp job execution list -n "$JOB" -g "$CONTROL_RG" \
  --query "length([?properties.status=='Running'])" -o tsv)
[ "$running" = "0" ] || { echo "refused: a drill is already running; one at a time" >&2; exit 2; }

job_id=$(az containerapp job show -n "$JOB" -g "$CONTROL_RG" --query id -o tsv)
# A start request replaces the container's whole env list, secret references included,
# so read the template's list and send it back with this drill's three values.
body=$(az containerapp job show -n "$JOB" -g "$CONTROL_RG" --query "properties.template.containers[0]" -o json |
  jq --arg d "$DRILL_ID" --arg m "$MODE" --arg s "$SCENARIO" '{containers: [
      .env |= ([.[] | select(.name != "DRILL_ID" and .name != "MODE" and .name != "SCENARIO")]
               + [{name: "DRILL_ID", value: $d}, {name: "MODE", value: $m}, {name: "SCENARIO", value: $s}])]}')
az rest --method post --url "https://management.azure.com${job_id}/start?api-version=2024-03-01" --body "$body" -o none

# WS1's load generator for this drill's metrics.orders lines (scorecard throughput, backlog, failed orders)
if [ -x scripts/start-load.sh ]; then
  ./scripts/start-load.sh "$DRILL_ID"
else
  echo "note: no scripts/start-load.sh yet (WS1): this drill's scorecard has no order metrics"
fi

echo "$DRILL_ID started: $MODE, $SCENARIO"
echo "Watch it: ${CONTROL_CENTER_URL:-<control center>}/drills/$DRILL_ID"
echo "Logs:     az containerapp job logs show -n $JOB -g $CONTROL_RG --container drill-runner --follow"
