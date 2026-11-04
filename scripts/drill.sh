#!/usr/bin/env bash
# One manual drill: runs the referee at four stages and prints what each one observed.
#   for i in 1 2 3; do ./scripts/drill.sh || break; done
# Exit code: 0 when every stage produced a PASS or FAIL; 2 when any stage was INCONCLUSIVE; 1 when a step between
# stages could not finish.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID
set -a; eval "$(azd env get-values)"; set +a
verdict() {
  local rc=0
  ./scripts/referee.sh "$1" >&2 || rc=$?
  case "$rc" in
    0) echo PASS ;;
    1) echo FAIL ;;
    *) echo INCONCLUSIVE ;;
  esac
}

./scripts/reset.sh || exit 1
A=$(verdict baseline); A_DONE=$(date +%s)
./scripts/fault.sh inject && ./scripts/wait-for.sh forbidden || exit 1
# Let the app's secret refresh window pass, so the next order makes a fresh Key Vault read.
WAIT=$(( A_DONE + ${SECRET_REFRESH_SECONDS:-10} + 1 - $(date +%s) )); [ "$WAIT" -le 0 ] || sleep "$WAIT"
B=$(verdict during-fault)
./scripts/fault.sh restore && ./scripts/wait-for.sh ok || exit 1
curl -s "$ORDER_APP_URL/health/dependencies" > "evidence/$DRILL_ID/health-after-restore.json"
C=$(verdict after-restore)
./scripts/reset.sh || exit 1
D=$(verdict after-restart)

echo "$DRILL_ID: baseline=$A during-fault=$B after-restore=$C after-restart=$D"
case "$A $B $C $D" in
  *INCONCLUSIVE*) exit 2 ;;
  *) exit 0 ;;
esac
