#!/usr/bin/env bash
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

APP_PW="$(openssl rand -base64 24)"; REF_PW="$(openssl rand -base64 24)"
q -Q "IF USER_ID('order_app') IS NULL CREATE USER order_app WITH PASSWORD = '$APP_PW' ELSE ALTER USER order_app WITH PASSWORD = '$APP_PW';
      GRANT SELECT, INSERT ON dbo.orders TO order_app;
      GRANT SELECT, INSERT ON dbo.payment_authorizations TO order_app;
      GRANT SELECT ON dbo.products TO order_app;"
q -Q "IF USER_ID('referee_ro') IS NULL CREATE USER referee_ro WITH PASSWORD = '$REF_PW' ELSE ALTER USER referee_ro WITH PASSWORD = '$REF_PW';
      GRANT SELECT ON dbo.orders TO referee_ro;
      GRANT SELECT ON dbo.payment_authorizations TO referee_ro;"

az keyvault secret set --vault-name "$KEYVAULT_NAME" -n db-password --value "$APP_PW" -o none
azd env set REFEREE_SQL_PASSWORD "$REF_PW"          # local for G1; control Key Vault in week 2

az containerapp revision restart -g "$TWIN_RG" -n "$ORDER_APP_NAME" \
  --revision "$(az containerapp show -g "$TWIN_RG" -n "$ORDER_APP_NAME" --query properties.latestRevisionName -o tsv)"
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID   # the baseline gets its own drill ID
./scripts/wait-for.sh ok
./scripts/referee.sh baseline                     # a failed baseline fails azd provision
