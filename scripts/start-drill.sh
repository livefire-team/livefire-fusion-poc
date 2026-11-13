#!/usr/bin/env bash
# Starts a drill as one execution of job-drill-runner (WS4, ADR-026), then prints where to watch it.
#
#   scripts/start-drill.sh --list                 the drills this script can start, and what each one shows
#   scripts/start-drill.sh <drill> [--wait]       one named drill, e.g. scripts/start-drill.sh supervised
#   scripts/start-drill.sh repeat <n> [drill]     n drills one after another, waiting for each (default: autonomous)
#   scripts/start-drill.sh suite [--no-clicks]    every drill once, one at a time (see --list); asks before each drill
#                                                 that needs a person at the Control Center
#   scripts/start-drill.sh <mode> [scenario]      the original form: Advisory|Supervised|"Autonomous Twin", T-00|T-01
#   scripts/start-drill.sh                        Autonomous Twin, T-01 (evaluation and repeatability runs)
#
# Live, a drill's path is set by its mode, the choices a person makes in the Control Center, the durability proof
# and the kill switch. The scenarios T-03 to T-08 and T-10 change behaviour only on stubs (src/drill-runner/tests,
# python -m livefire.runner --stub): they are not live drills, and this script won't label a live drill with them.
# Start drills only with this script: it refuses a second drill while one runs, and it keeps the job's secret
# references when it sets the drill's values (a KeyError: 'OPS_KEY' in the logs means a drill started another way).
set -euo pipefail
cd "$(dirname "$0")/.."

list() {
  cat <<'EOF'
Drill        Mode             Scenario  What it shows                                              Ends (when it works)
baseline     Supervised       T-00      reset, baseline customer journey, stop. No fault, no agents BASELINE_VERIFIED
supervised   Supervised       T-01      the full drill; a person approves recovery and deploy       VERIFIED
                                        in the Control Center (pick the narrow option)
autonomous   Autonomous Twin  T-01      the full drill with no person: the broad option is tested   VERIFIED
                                        and refused, the narrow restore runs, the fix ships
advisory     Advisory         T-01      agents investigate and recommend; the policy lets nobody    ESCALATED_POLICY
                                        but a person act, so the workflow stops there
broad        Supervised       T-02      a person picks "Grant Contributor on the subscription":     VERIFIED
                                        the platform refuses it, then pick the narrow option.
                                        With the deny policy on, Azure Policy refuses it
                                        (scripts/deploy.sh policy); off, Azure RBAC does
quick        Autonomous Twin  T-01      as autonomous, without the second fault after the fix       VERIFIED
                                        (shorter, weaker proof of durability)
kill         Supervised       T-09      press Kill in the Control Center while it runs: the twin    KILLED
                                        is put back and the drill stops

Add --wait to wait for the drill to finish and print how its execution ended.
suite runs baseline, advisory, autonomous, then supervised, broad and kill, one at a time, waiting for each. It stops
if baseline fails. Before each drill that needs a person it asks to start or skip it (--no-clicks skips them all).
The runner's execution Succeeds only for VERIFIED and BASELINE_VERIFIED, so advisory and kill end Failed by design.
Not live drills: T-03, T-04 and T-08 against the MCP server are scripts/ws3-acceptance.py; T-04 to T-08 and T-10
inside the workflow are the stub tests (pytest src/drill-runner/tests).
EOF
}

MODE="" SCENARIO="" PROVE=1 WAIT=0 NAME="" HINT=""
preset() {
  NAME="$1"
  case "$1" in
    baseline)   MODE=Supervised SCENARIO=T-00 ;;
    supervised) MODE=Supervised SCENARIO=T-01
                HINT="approve the narrow option (Restore Key Vault Secrets User) and the deploy in the Control Center" ;;
    autonomous) MODE="Autonomous Twin" SCENARIO=T-01 ;;
    advisory)   MODE=Advisory SCENARIO=T-01
                HINT="ends ESCALATED_POLICY by design: Advisory lets nobody but a person act" ;;
    broad)      MODE=Supervised SCENARIO=T-02
                HINT="choose 'Grant Contributor on the subscription' first; after it is refused, choose the narrow option" ;;
    quick)      MODE="Autonomous Twin" SCENARIO=T-01 PROVE=0 ;;
    kill)       MODE=Supervised SCENARIO=T-09
                HINT="press Kill in the Control Center while the drill runs (any stage); it should end KILLED" ;;
    *) return 1 ;;
  esac
}

case "${1:-}" in
  -h|--help|--list|list) list; exit 0 ;;
  repeat)
    n="${2:-}"; [[ "$n" =~ ^[1-9][0-9]?$ ]] || { echo "usage: scripts/start-drill.sh repeat <1-99> [drill]" >&2; exit 2; }
    drill="${3:-autonomous}"
    case "$drill" in supervised|broad|kill)
      echo "repeat runs drills that need no person; $drill waits for clicks in the Control Center" >&2; exit 2 ;;
    esac
    preset "$drill" || { echo "unknown drill: $drill (scripts/start-drill.sh --list)" >&2; exit 2; }
    ok=0
    for i in $(seq 1 "$n"); do
      echo "== run $i of $n: $drill"
      rc=0; "$0" "$drill" --wait || rc=$?
      [ "$rc" = 0 ] && ok=$((ok + 1))
      [ "$rc" = 0 ] || [ "$rc" = 3 ] || { echo "== run $i could not run (exit $rc); stopping" >&2; break; }
    done
    echo "== $ok of $n executions succeeded ($drill)"
    [ "$ok" = "$n" ]; exit $? ;;
  suite)
    clicks=1
    case "${2:-}" in "") ;; --no-clicks) clicks=0 ;; *) echo "usage: scripts/start-drill.sh suite [--no-clicks]" >&2; exit 2 ;; esac
    [ "$clicks" = 0 ] || [ -r /dev/tty ] || { echo "no terminal to ask on: skipping the drills that need a person"; clicks=0; }
    summary=()
    for drill in baseline advisory autonomous supervised broad kill; do
      case "$drill" in advisory|kill) expect=Failed ;; *) expect=Succeeded ;; esac
      case "$drill" in supervised|broad|kill)
        if [ "$clicks" = 0 ]; then summary+=("$drill: skipped (needs a person)"); continue; fi
        preset "$drill"
        echo
        echo "== next: $drill. A person must be at the Control Center: $HINT"
        read -r -p "   Enter starts it, s skips it, q ends the suite: " answer < /dev/tty || answer=q
        case "$answer" in
          s|S) summary+=("$drill: skipped"); continue ;;
          q|Q) summary+=("$drill: suite ended here"); break ;;
        esac ;;
      esac
      echo
      echo "== $drill"
      rc=0; "$0" "$drill" --wait || rc=$?
      case "$rc" in 0) status=Succeeded ;; 3) status=Failed ;; *) status="not run (exit $rc)" ;; esac
      if [ "$status" = "$expect" ]; then summary+=("$drill: execution $status, as expected")
      else summary+=("$drill: execution $status, expected $expect (see the Control Center)"); fi
      if [ "$drill" = baseline ] && [ "$status" != Succeeded ]; then
        summary+=("suite stopped: the baseline failed, so the twin is not ready for the other drills"); break
      fi
    done
    echo
    echo "== suite summary"
    printf '   %s\n' "${summary[@]}"
    exit 0 ;;
  "") preset autonomous ;;
  Advisory|Supervised|"Autonomous Twin")
    MODE="$1" SCENARIO="${2:-T-01}" NAME="$1"
    case "$SCENARIO" in T-00|T-01) ;; *)
      echo "live scenarios are T-00 and T-01 (T-02 and T-09 through the broad and kill drills; see --list)" >&2
      exit 2 ;;
    esac ;;
  *) preset "$1" || { echo "unknown drill: $1"; echo; list; } >&2 || true
     [ -n "$MODE" ] || exit 2 ;;
esac
for a in "${@:2}"; do [ "$a" = --wait ] && WAIT=1; done

command -v jq >/dev/null || { echo "jq is needed" >&2; exit 2; }
set -a; eval "$(azd env get-values)"; set +a
JOB="${RUNNER_JOB_NAME:-}"
[ -n "$JOB" ] || { echo "no RUNNER_JOB_NAME: deploy the runner first (scripts/deploy.sh runner)" >&2; exit 2; }

running=$(az containerapp job execution list -n "$JOB" -g "$CONTROL_RG" \
  --query "length([?properties.status=='Running'])" -o tsv)
[ "$running" = "0" ] || { echo "refused: a drill is already running; one at a time" >&2; exit 2; }

if [ "$NAME" = broad ]; then
  if [ "$(az policy assignment list --query "length([?name=='lf-deny-broad-roles'])" -o tsv)" = 1 ]; then
    echo "deny policy: on (Azure Policy refuses the broad option)"
  else
    echo "deny policy: off (Azure RBAC refuses the broad option; scripts/deploy.sh policy shows Azure Policy doing it)"
  fi
fi

DRILL_ID="drill-$(date -u +%Y%m%d-%H%M%S)"     # lowercase: candidate branch names must be (order-service.yml)
job_id=$(az containerapp job show -n "$JOB" -g "$CONTROL_RG" --query id -o tsv)
# A start request replaces the container's whole env list, secret references included,
# so read the template's list and send it back with this drill's values.
body=$(az containerapp job show -n "$JOB" -g "$CONTROL_RG" --query "properties.template.containers[0]" -o json |
  jq --arg d "$DRILL_ID" --arg m "$MODE" --arg s "$SCENARIO" --arg p "$PROVE" '{containers: [
      .env |= ([.[] | select(.name as $n | ["DRILL_ID", "MODE", "SCENARIO", "PROVE_DURABLE"] | index($n) | not)]
               + [{name: "DRILL_ID", value: $d}, {name: "MODE", value: $m}, {name: "SCENARIO", value: $s},
                  {name: "PROVE_DURABLE", value: $p}])]}')
execution=$(az rest --method post --url "https://management.azure.com${job_id}/start?api-version=2024-03-01" \
  --body "$body" --query name -o tsv)

# WS1's load generator for this drill's metrics.orders lines (scorecard throughput, backlog, failed orders). The
# drill is already running, so a failure here must not hide its ID below
if [ -x scripts/start-load.sh ]; then
  ./scripts/start-load.sh "$DRILL_ID" \
    || echo "WARNING: no load for this drill; start it by hand: scripts/start-load.sh $DRILL_ID" >&2
else
  echo "note: no scripts/start-load.sh yet (WS1): this drill's scorecard has no order metrics"
fi

label="$MODE, $SCENARIO"
[ "$PROVE" = 1 ] || label="$label, no durability proof"
[ "$NAME" = "$MODE" ] || label="$label ($NAME drill)"
echo "$DRILL_ID started: $label"
[ -z "$HINT" ] || echo "To do:    $HINT"
echo "Watch it: ${CONTROL_CENTER_URL:-<control center>}/drills/$DRILL_ID"
echo "Logs:     az containerapp job logs show -n $JOB -g $CONTROL_RG --container drill-runner --follow"
[ "$WAIT" = 1 ] || exit 0

# The runner exits 0 only for VERIFIED or BASELINE_VERIFIED, so the execution's status says whether the drill worked;
# the Control Center shows its terminal state and reason
echo "waiting for $execution to finish (the drill budget is 90 minutes) ..."
while :; do
  status=$(az containerapp job execution show -n "$JOB" -g "$CONTROL_RG" --job-execution-name "$execution" \
    --query properties.status -o tsv 2>/dev/null || echo Unknown)
  case "$status" in Running|Processing|Unknown|"") sleep 30 ;; *) break ;; esac
done
echo "$DRILL_ID: execution $status"
[ "$status" = Succeeded ] || exit 3      # 3: the drill ran and did not end VERIFIED; other codes: it could not run
