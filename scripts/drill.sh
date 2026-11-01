#!/usr/bin/env bash
# One manual drill: runs the referee at four stages and prints what each one observed.
#   for i in 1 2 3; do ./scripts/drill.sh || break; done
# Exit code: 0 when every stage was observed; non-zero when a step between stages could not finish.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID
set -a; eval "$(azd env get-values)"; set +a
verdict() { if ./scripts/referee.sh "$1" >&2; then echo PASS; else echo FAIL; fi; }

./scripts/reset.sh || exit 1
A=$(verdict baseline)
./scripts/fault.sh inject && ./scripts/wait-for.sh forbidden || exit 1
B=$(verdict during-fault)
./scripts/fault.sh restore && ./scripts/wait-for.sh ok || exit 1
curl -s "$ORDER_APP_URL/health/dependencies" > "evidence/$DRILL_ID/health-after-restore.json"
C=$(verdict after-restore)
./scripts/reset.sh || exit 1
D=$(verdict after-restart)

echo "$DRILL_ID: baseline=$A during-fault=$B after-restore=$C after-restart=$D"
