#!/usr/bin/env bash
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID
source "$(dirname "$0")/lib.sh"
RUNS="${1:-3}"; CSV="evidence/$DRILL_ID/propagation.csv"
echo "run,model,inject_to_forbidden_s,restore_to_ok_s" > "$CSV"
secs() { grep -o '[0-9]*s$' | tr -d s; }
for i in $(seq "$RUNS"); do
  ./scripts/fault.sh inject
  F=$(./scripts/wait-for.sh forbidden | secs)
  ./scripts/fault.sh restore
  R=$(./scripts/wait-for.sh ok | secs)
  echo "$i,$KV_PERMISSION_MODEL,$F,$R" | tee -a "$CSV"
done
./scripts/reset.sh
