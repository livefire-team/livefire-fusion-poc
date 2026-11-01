# shellcheck shell=bash
# Shared by every script: loads the azd values, enforces the twin allowlist, writes events.
set -euo pipefail
set -a; eval "$(azd env get-values)"; set +a      # export so pytest and Python see them
KV_PERMISSION_MODEL="${KV_PERMISSION_MODEL:-rbac}"
DRILL_ID="${DRILL_ID:?run: export DRILL_ID=\$(./scripts/new-drill.sh)}"

# Allowlist: only this environment's twin vault, in this subscription
[[ "$TWIN_RG" == rg-lf-twin-* ]]            || { echo "refused: $TWIN_RG is not a twin"; exit 2; }
[[ "$KEYVAULT_ID" == */resourceGroups/$TWIN_RG/* ]] || { echo "refused: vault outside twin"; exit 2; }
[[ "$(az account show --query id -o tsv)" == "$AZURE_SUBSCRIPTION_ID" ]] || { echo "refused: wrong subscription"; exit 2; }

mkdir -p "evidence/$DRILL_ID"
event() {  # event <action> <result> [json-details]; ts in whole seconds (macOS date has no %N)
  printf '{"ts":"%s","drill_id":"%s","action":"%s","result":"%s","details":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$DRILL_ID" "$1" "$2" "${3:-"{}"}" >> "evidence/$DRILL_ID/events.jsonl"
}
