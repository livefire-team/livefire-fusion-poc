#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"
WANT="${1:?ok|forbidden}"; TIMEOUT="${2:-2100}"; START=$(date +%s)
while :; do
  KV=$(curl -s -m 10 "$ORDER_APP_URL/health/dependencies" | jq -r '.keyvault // "unreachable"' 2>/dev/null || echo unreachable)
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$KV" = "$WANT" ]; then
    event "wait.$WANT" ok "{\"seconds\":$ELAPSED}"; echo "keyvault=$WANT after ${ELAPSED}s"; exit 0
  fi
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    event "wait.$WANT" timeout "{\"seconds\":$ELAPSED,\"last\":\"$KV\"}"; echo "timeout, last=$KV"; exit 1
  fi
  sleep 5
done
