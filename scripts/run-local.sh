#!/usr/bin/env bash
# Runs WS3 on a laptop, with no Azure and no GitHub: the MCP server on fixtures (BACKEND=fixtures), a stand-in Ops
# Service for the recovery endpoint, then both smoke tests. Build Steps section 2.
#   scripts/run-local.sh          run the smoke tests, then stop everything
#   scripts/run-local.sh --serve  leave the server running for your own client (Ctrl-C stops it)
# Needs Python 3.12 with src/mcp-server/requirements.txt installed (or set PYTHON to such an interpreter).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" -c 'import mcp, uvicorn' 2>/dev/null \
  || { echo "install the server's packages first: $PY -m pip install -r src/mcp-server/requirements.txt" >&2; exit 2; }

PORT="${PORT:-8100}" OPS_PORT="${OPS_PORT:-8200}" DRILL="${DRILL:-drill-local-0001}"
EVENTS="$PWD/evidence"                              # the drill event log: evidence/<drill_id>/events.jsonl
mkdir -p "$EVENTS"
key() { "$PY" -c 'import secrets; print(secrets.token_hex(24))'; }
export PLANNER_KEY ENGINEER_KEY RECOVERY_KEY OPS_AGENT_KEY GRANT="grt-local-$RANDOM"
PLANNER_KEY=$(key) ENGINEER_KEY=$(key) RECOVERY_KEY=$(key) OPS_AGENT_KEY=$(key)

FAKE_GRANTS="$DRILL:restore_kv_secrets_user:$GRANT" OPS_AGENT_KEY="$OPS_AGENT_KEY" PORT="$OPS_PORT" \
  "$PY" scripts/fake-ops.py >/tmp/ws3-fake-ops.log 2>&1 &
OPS_PID=$!
# Placeholder evidence and write paths. For a rehearsal with the drill's own, point FIXTURES at the private fixture
# file and set ENGINEER_WRITE_PATHS (both stay out of this public repo, ADR-004).
: "${ENGINEER_WRITE_PATHS:=src/order-service/app/example.py,src/order-service/tests/test_*.py,runbooks/*.md}"
export ENGINEER_WRITE_PATHS
BACKEND=fixtures EVENT_SOURCE="dir:$EVENTS" OPS_URL="http://127.0.0.1:$OPS_PORT" \
  "$PY" -m uvicorn --app-dir src/mcp-server/app main:app --port "$PORT" >/tmp/ws3-mcp.log 2>&1 &
MCP_PID=$!
trap 'kill $MCP_PID $OPS_PID 2>/dev/null || true' EXIT

for _ in $(seq 40); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT/health" || { echo "the server didn't start; see /tmp/ws3-mcp.log" >&2; exit 1; }
echo

export MCP_URL="http://127.0.0.1:$PORT"
"$PY" scripts/mcp-smoke.py "$DRILL"
"$PY" scripts/recovery-smoke.py "$DRILL"
echo "Audit trail: $EVENTS/$DRILL/events.jsonl ($(wc -l <"$EVENTS/$DRILL/events.jsonl") events)"

if [ "${1:-}" = --serve ]; then
  printf '\nServing on %s (Ctrl-C to stop). Keys for your client:\n' "$MCP_URL"
  printf '  PLANNER_KEY=%s\n  ENGINEER_KEY=%s\n  RECOVERY_KEY=%s\n' "$PLANNER_KEY" "$ENGINEER_KEY" "$RECOVERY_KEY"
  wait $MCP_PID
fi
