#!/usr/bin/env bash
# azd postprovision hook: SQL schema and users, the twin's DB secret, the control-plane secrets, then a baseline.
set -euo pipefail
set -a; eval "$(azd env get-values)"; set +a                       # Bicep outputs + env values
SQL_SERVER="${SQL_SERVER_FQDN%%.*}"

# Let this machine reach SQL (WS1's Bicep adds the Allow Azure services rule for the app)
MYIP="$(curl -s https://api.ipify.org)"
az sql server firewall-rule create -g "$TWIN_RG" -s "$SQL_SERVER" -n bootstrap-client \
  --start-ip-address "$MYIP" --end-ip-address "$MYIP" -o none

q() { sqlcmd -S "$SQL_SERVER_FQDN" -d "$SQL_DB_NAME" -U lfadmin -P "$SQL_ADMIN_PASSWORD" -b "$@"; }
q -i sql/schema.sql
q -i sql/seed.sql

# The app password changes on every provision (the app re-reads it from Key Vault). The Referee and cleanup
# passwords are generated once and reused: their copies in the control vault are only re-read every 30 minutes.
APP_PW="$(openssl rand -base64 24)"
REF_PW="${REFEREE_SQL_PASSWORD:-$(openssl rand -base64 24)}"
CLEAN_PW="${OPS_CLEANUP_SQL_PASSWORD:-$(openssl rand -base64 24)}"
q -Q "IF USER_ID('order_app') IS NULL CREATE USER order_app WITH PASSWORD = '$APP_PW' ELSE ALTER USER order_app WITH PASSWORD = '$APP_PW';
      GRANT SELECT, INSERT ON dbo.orders TO order_app;
      GRANT SELECT, INSERT ON dbo.payment_authorizations TO order_app;
      GRANT SELECT ON dbo.products TO order_app;"
q -Q "IF USER_ID('referee_ro') IS NULL CREATE USER referee_ro WITH PASSWORD = '$REF_PW' ELSE ALTER USER referee_ro WITH PASSWORD = '$REF_PW';
      GRANT SELECT ON dbo.orders TO referee_ro;
      GRANT SELECT ON dbo.payment_authorizations TO referee_ro;"
q -Q "IF USER_ID('ops_cleanup') IS NULL CREATE USER ops_cleanup WITH PASSWORD = '$CLEAN_PW' ELSE ALTER USER ops_cleanup WITH PASSWORD = '$CLEAN_PW';
      GRANT SELECT, DELETE ON dbo.orders TO ops_cleanup;
      GRANT SELECT, DELETE ON dbo.payment_authorizations TO ops_cleanup;"

az keyvault secret set --vault-name "$KEYVAULT_NAME" -n db-password --value "$APP_PW" -o none
azd env set REFEREE_SQL_PASSWORD "$REF_PW"
azd env set OPS_CLEANUP_SQL_PASSWORD "$CLEAN_PW"

# ---- control-plane secrets (G2). A new role assignment on the vault can take a few minutes to apply. ----
if [ -n "${CONTROL_KEYVAULT_NAME:-}" ]; then
  kv_try() {  # kv_try <az keyvault args...>: retries for up to 5 minutes while the data-plane role propagates
    local i
    for i in $(seq 30); do
      if az keyvault "$@" 2>/dev/null; then return 0; fi
      [ "$i" -eq 1 ] && echo "waiting for Key Vault Secrets Officer on $CONTROL_KEYVAULT_NAME to apply..." >&2
      sleep 10
    done
    az keyvault "$@"
  }
  kv_try secret list --vault-name "$CONTROL_KEYVAULT_NAME" --query "[].name" -o tsv > /dev/null
  existing="$(az keyvault secret list --vault-name "$CONTROL_KEYVAULT_NAME" --query "[].name" -o tsv)"
  for name in ops-runner-key ops-agent-key recovery-grant-key; do       # random once; rotated only by hand
    if ! grep -qx "$name" <<<"$existing"; then
      kv_try secret set --vault-name "$CONTROL_KEYVAULT_NAME" -n "$name" --value "$(openssl rand -hex 32)" -o none
      echo "created $name"
    fi
  done
  set_if_changed() {  # set_if_changed <name> <value>: no new version when nothing changed
    local current
    current="$(az keyvault secret show --vault-name "$CONTROL_KEYVAULT_NAME" -n "$1" --query value -o tsv 2>/dev/null || true)"
    [ "$current" = "$2" ] || kv_try secret set --vault-name "$CONTROL_KEYVAULT_NAME" -n "$1" --value "$2" -o none
  }
  set_if_changed referee-sql-password "$REF_PW"
  set_if_changed ops-cleanup-sql-password "$CLEAN_PW"
fi

az containerapp revision restart -g "$TWIN_RG" -n "$ORDER_APP_NAME" \
  --revision "$(az containerapp show -g "$TWIN_RG" -n "$ORDER_APP_NAME" --query properties.latestRevisionName -o tsv)"
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID   # the baseline gets its own drill ID
./scripts/wait-for.sh ok
./scripts/referee.sh baseline                     # a failed baseline fails azd provision
