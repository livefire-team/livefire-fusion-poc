#!/usr/bin/env bash
# Creates WS5's Control Center secrets in a control vault when they are missing (ADR-024): the session secret and,
# signed in by passcode, the passcode's hash. Values go through a private temporary folder, never a command line or a
# log, and a new passcode goes only to .local/cc-passcode-<env>.txt (mode 600) for the presenter; WS5 rotates it after
# each walkthrough (deploy-cc.sh rotate-passcode). Easy Auth's client secret comes from WS5's app registration and
# can't be made here.
#   scripts/cc-secrets.sh <control vault> <environment name> [passcode|easyauth]
# postprovision.sh calls it for a new environment, and deploy.sh before it provisions the Control Center.
set -euo pipefail
cd "$(dirname "$0")/.."
VAULT="${1:?usage: scripts/cc-secrets.sh <control vault> <environment name> [passcode|easyauth]}"
ENV_NAME="${2:?usage: scripts/cc-secrets.sh <control vault> <environment name> [passcode|easyauth]}"
MODE="${3:-passcode}"

existing="$(az keyvault secret list --vault-name "$VAULT" --query "[].name" -o tsv)"
tmp="$(umask 077 && mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if ! grep -qx cc-session-secret <<<"$existing"; then
  openssl rand -base64 48 | tr -d '\n' > "$tmp/session"
  az keyvault secret set --vault-name "$VAULT" -n cc-session-secret --file "$tmp/session" -o none
  echo "created cc-session-secret"
fi
if [ "$MODE" = passcode ] && ! grep -qx cc-passcode-sha256 <<<"$existing"; then
  mkdir -p .local
  pass_file=".local/cc-passcode-$ENV_NAME.txt"
  (umask 077 && openssl rand -base64 18 | tr '+/' '-_' | tr -d '\n' > "$pass_file")
  # the hash of exactly the passcode, as WS5's printf '%s' "$passcode" | sha256 makes it
  openssl dgst -sha256 -r < "$pass_file" | cut -d' ' -f1 | tr -d '\n' > "$tmp/hash"
  az keyvault secret set --vault-name "$VAULT" -n cc-passcode-sha256 --file "$tmp/hash" -o none
  echo "created cc-passcode-sha256; the passcode is in $pass_file (share it out of band)"
fi
