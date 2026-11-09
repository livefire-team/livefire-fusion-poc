#!/usr/bin/env bash
# Creates the Key Vault secrets mcp.bicep reads, before its first deployment. Idempotent: an existing secret is kept.
#   scripts/create-secrets.sh <control-vault-name> [planner-app-key.pem engineer-app-key.pem]
# - mcp-planner-key, mcp-engineer-key, mcp-recovery-key: the per-endpoint keys (key mode). WS4 reads them for its
#   Foundry connections; unused in Entra mode, but the module references them, so they must exist.
# - ops-agent-key: the key /recovery/mcp presents to WS2's Ops Service. Shared with WS2; created here only if missing.
# - gh-planner-private-key, gh-engineer-private-key: the two GitHub Apps' private keys, from the files given.
# Values are generated or read from files and go straight to Key Vault; nothing is printed or written elsewhere.
set -euo pipefail
VAULT="${1:?usage: create-secrets.sh <control-vault-name> [planner.pem engineer.pem]}"
has() { az keyvault secret show --vault-name "$VAULT" -n "$1" -o none 2>/dev/null; }

for name in mcp-planner-key mcp-engineer-key mcp-recovery-key ops-agent-key; do
  if has "$name"; then echo "  $name: exists"; continue; fi
  az keyvault secret set --vault-name "$VAULT" -n "$name" -o none \
    --value "$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  echo "  $name: created"
done

if [ $# -ge 3 ]; then
  for pair in "gh-planner-private-key:$2" "gh-engineer-private-key:$3"; do
    name="${pair%%:*}" file="${pair#*:}"
    [ -r "$file" ] || { echo "can't read $file" >&2; exit 1; }
    az keyvault secret set --vault-name "$VAULT" -n "$name" --file "$file" -o none
    echo "  $name: stored from $file"
  done
else
  echo "  GitHub App keys not given: pass the Planner and Engineer App .pem files to store them"
fi
