#!/usr/bin/env bash
# One drill by hand (G1): the referee runs at baseline, during the fault, after restore and after restart.
#   for i in 1 2 3; do ./scripts/drill.sh || break; done
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID
set -a; eval "$(azd env get-values)"; set +a
verdict() { if ./scripts/referee.sh "$1" >&2; then echo PASS; else echo FAIL; fi; }

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

echo "$DRILL_ID: $A $B $C $D"
[ "$A $B $C $D" = "PASS FAIL FAIL PASS" ]
