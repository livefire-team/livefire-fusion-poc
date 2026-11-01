#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"
LABEL="${1:-run}"
N=$(( $(find "evidence/$DRILL_ID" -maxdepth 1 -type d -name 'r*' | wc -l) + 1 ))
export RUN_ID="$DRILL_ID-r$N" OUTDIR="evidence/$DRILL_ID/r$N-$LABEL"
mkdir -p "$OUTDIR"; STARTED="$(date -u +%FT%TZ)"

J=0; pytest journeys/test_order_journey.py --browser chromium \
  --tracing retain-on-failure --output "$OUTDIR/playwright" -q || J=$?   # plugin wipes --output at start
S=0; SQL="$(python referee/assert_order.py)" || S=$?
[ -n "$SQL" ] || SQL='{"orders_persisted":null,"payment_auths_persisted":null}'
VERDICT=FAIL; [ "$J" -eq 0 ] && [ "$S" -eq 0 ] && VERDICT=PASS

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
[ "$VERDICT" = PASS ]
