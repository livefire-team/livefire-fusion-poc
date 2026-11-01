#!/usr/bin/env bash
# Runs the customer journey and the SQL check once and records a verdict in referee-result.json.
#   PASS          journey passed and the SQL counts are right (exit 0)
#   FAIL          both checks ran and at least one of them failed (exit 1)
#   INCONCLUSIVE  a check could not run, so there is no answer (exit 2)
# Any abort before a verdict is written (refused by lib.sh, unset setting, jq error) also exits 2, so that an
# infrastructure problem can't read as FAIL.
VERDICT_WRITTEN=""
trap '[ -n "$VERDICT_WRITTEN" ] || exit 2' EXIT
source "$(dirname "$0")/lib.sh"
LABEL="${1:-run}"
N=$(( $(find "evidence/$DRILL_ID" -maxdepth 1 -type d -name 'r*' | wc -l) + 1 ))
export RUN_ID="$DRILL_ID-r$N" OUTDIR="evidence/$DRILL_ID/r$N-$LABEL"
mkdir -p "$OUTDIR"; STARTED="$(date -u +%FT%TZ)"
NULL_COUNTS='{"orders_persisted":null,"payment_auths_persisted":null}'

J=0; pytest journeys/test_order_journey.py --browser chromium \
  --tracing retain-on-failure --output "$OUTDIR/playwright" -q || J=$?   # plugin wipes --output at start
S=0; SQL="$(python referee/assert_order.py)" || S=$?
# assert_order.py always prints a JSON object; anything else means it did not finish
if ! jq -e 'type == "object"' >/dev/null 2>&1 <<<"$SQL"; then
  SQL="$NULL_COUNTS"; [ "$S" -ge 2 ] || S=2
fi

# pytest: 1 means a test failed; 2 and above mean interrupted, internal error, usage error or nothing collected
if [ "$J" -ge 2 ] || [ "$S" -ge 2 ]; then VERDICT=INCONCLUSIVE
elif [ "$J" -eq 0 ] && [ "$S" -eq 0 ]; then VERDICT=PASS
else VERDICT=FAIL
fi

jq -n --arg drill "$DRILL_ID" --arg run "$RUN_ID" --arg label "$LABEL" \
  --arg commit "$(git rev-parse --short HEAD)" --arg started "$STARTED" --arg ended "$(date -u +%FT%TZ)" \
  --arg step "$(cat "$OUTDIR/step.txt" 2>/dev/null)" --arg error "$(cat "$OUTDIR/error.txt" 2>/dev/null)" \
  --arg conf "$(cat "$OUTDIR/confirmation.txt" 2>/dev/null)" --arg verdict "$VERDICT" \
  --argjson jpass "$([ "$J" -eq 0 ] && echo true || echo false)" --argjson sql "$SQL" \
  '{drill_id:$drill, run_id:$run, label:$label, journey_commit:$commit,
    started_at:$started, ended_at:$ended, journey_passed:$jpass, last_step:$step,
    error:$error, confirmation_number:$conf} + $sql + {verdict:$verdict}' \
  > "$OUTDIR/referee-result.json"

event "referee.$LABEL" "$VERDICT" "$(jq -c . "$OUTDIR/referee-result.json")"
echo "referee $LABEL: $VERDICT ($OUTDIR)"
VERDICT_WRITTEN=1
case "$VERDICT" in
  PASS) exit 0 ;;
  FAIL) exit 1 ;;
  *)    exit 2 ;;
esac
