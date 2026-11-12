#!/usr/bin/env bash
# azd postprovision hook: SQL schema and users, the twin's DB secret, the control-plane secrets, then a baseline.
set -euo pipefail
set -a; eval "$(azd env get-values)"; set +a                       # Bicep outputs + env values
SQL_SERVER="${SQL_SERVER_FQDN%%.*}"

kv_try() {  # kv_try <az keyvault args...>: retries for up to 5 minutes while a new data-plane role propagates
  local i err
  err="$(mktemp)"
  for i in $(seq 30); do
    if az keyvault "$@" 2>"$err"; then rm -f "$err"; return 0; fi
    grep -q CERTIFICATE_VERIFY_FAILED "$err" && break      # SSL inspection: retrying won't help
    [ "$i" -eq 1 ] && echo "waiting for Key Vault access to apply..." >&2
    sleep 10
  done
  rm -f "$err"
  az keyvault "$@"
}

# Stop before any change if this machine can't use the twin vault: the app password is changed in SQL below and
# the app only learns it from the vault, so a failed write there would leave the app unable to sign in.
kv_try secret list --vault-name "$KEYVAULT_NAME" --query "[].name" -o tsv > /dev/null \
  || { echo "cannot reach Key Vault $KEYVAULT_NAME; SQL passwords unchanged (behind SSL inspection? set REQUESTS_CA_BUNDLE)" >&2; exit 1; }

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

kv_try secret set --vault-name "$KEYVAULT_NAME" -n db-password --value "$APP_PW" -o none
azd env set REFEREE_SQL_PASSWORD "$REF_PW"
azd env set OPS_CLEANUP_SQL_PASSWORD "$CLEAN_PW"

# ---- control-plane secrets (G2). A new role assignment on the vault can take a few minutes to apply. ----
if [ -n "${CONTROL_KEYVAULT_NAME:-}" ]; then
  kv_try secret list --vault-name "$CONTROL_KEYVAULT_NAME" --query "[].name" -o tsv > /dev/null
  existing="$(az keyvault secret list --vault-name "$CONTROL_KEYVAULT_NAME" --query "[].name" -o tsv)"
  # random once; rotated only by hand. mcp-*-key: WS3's per-endpoint keys (ca-mcp reads them in key mode)
  for name in ops-runner-key ops-agent-key recovery-grant-key mcp-planner-key mcp-engineer-key mcp-recovery-key; do
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

  # GitHub App keys (WS3's Planner and Engineer, WS4's runner) for a new environment, stored once (ADR-025): copied
  # from another environment's control vault (SECRETS_SOURCE_VAULT, set by lab.sh new-env), or read from a private
  # folder outside this repo (GITHUB_APP_KEYS: planner.pem, engineer.pem, runner.pem). A key passes through a
  # private temporary file, never a command line or this log
  copy_key() {  # copy_key <name>: from SECRETS_SOURCE_VAULT, exactly as stored there
    local tmp rc=0
    tmp="$(umask 077 && mktemp)"
    if az keyvault secret show --vault-name "$SECRETS_SOURCE_VAULT" -n "$1" --query value -o json 2>/dev/null \
      | jq -j . > "$tmp" && [ -s "$tmp" ]; then
      kv_try secret set --vault-name "$CONTROL_KEYVAULT_NAME" -n "$1" --file "$tmp" -o none || rc=$?
    else
      rc=1
    fi
    rm -f "$tmp"
    return "$rc"
  }
  for pair in planner:gh-planner-private-key engineer:gh-engineer-private-key runner:gh-runner-private-key; do
    name="${pair#*:}" file="${GITHUB_APP_KEYS:-}/${pair%%:*}.pem"
    grep -qx "$name" <<<"$existing" && continue
    if [ -n "${SECRETS_SOURCE_VAULT:-}" ]; then
      if copy_key "$name"; then echo "copied $name from $SECRETS_SOURCE_VAULT"
      else echo "WARNING: $name is not in $SECRETS_SOURCE_VAULT (or can't be read); deploy.sh names what it holds back" >&2; fi
    elif [ -n "${GITHUB_APP_KEYS:-}" ] && [ -r "$file" ]; then
      kv_try secret set --vault-name "$CONTROL_KEYVAULT_NAME" -n "$name" --file "$file" -o none
      echo "stored $name from $file"
    fi
  done

  # WS5's Control Center reads two secrets at deploy time. A new passcode goes only to a private file for the
  # presenter, never this log; WS5 rotates it after each walkthrough (deploy-cc.sh rotate-passcode)
  if [ -n "${CONTROL_CENTER_SOURCE:-}${CONTROL_CENTER_IMAGE:-}" ]; then
    if ! grep -qx cc-session-secret <<<"$existing"; then
      kv_try secret set --vault-name "$CONTROL_KEYVAULT_NAME" -n cc-session-secret --value "$(openssl rand -base64 48)" -o none
      echo "created cc-session-secret"
    fi
    if [ "${CONTROL_CENTER_AUTH_MODE:-passcode}" = passcode ] && ! grep -qx cc-passcode-sha256 <<<"$existing"; then
      mkdir -p .local
      pass_file=".local/cc-passcode-${AZURE_ENV_NAME:-lab}.txt"
      (umask 077 && openssl rand -base64 18 | tr '+/' '-_' > "$pass_file")
      kv_try secret set --vault-name "$CONTROL_KEYVAULT_NAME" -n cc-passcode-sha256 \
        --value "$(tr -d '\n' < "$pass_file" | openssl dgst -sha256 -r | cut -d' ' -f1)" -o none
      echo "created cc-passcode-sha256; the passcode is in $pass_file (share it out of band)"
    fi
  fi
fi

# ---- WS3: the incident index the Planner searches, rebuilt on every provision ----
# The incidents are the agents' test material, so they live outside this public repo (ADR-004): INCIDENT_CORPUS is
# an azd env value pointing at the incidents folder of a private checkout. Hybrid (vector) once OPENAI_ENDPOINT and
# EMBEDDING_DEPLOYMENT are set. The deployer's Search roles can take a few minutes to apply on a new service.
# Not fatal: the order path doesn't need it; rerun the command shown.
if [ -n "${SEARCH_ENDPOINT:-}" ] && [ ! -d "${INCIDENT_CORPUS:-}" ]; then
  echo "WARNING: incident index not loaded: set INCIDENT_CORPUS (azd env set INCIDENT_CORPUS <folder>) and re-run" >&2
elif [ -n "${SEARCH_ENDPOINT:-}" ]; then
  load_cmd=(python3 scripts/load-incidents.py --endpoint "$SEARCH_ENDPOINT" --corpus "$INCIDENT_CORPUS")
  if ! python3 -c 'import azure.search.documents, azure.identity' 2>/dev/null; then
    echo "WARNING: incident index not loaded: pip install azure-search-documents azure-identity, then: ${load_cmd[*]}" >&2
  else
    loaded=""
    for _ in $(seq 18); do
      if "${load_cmd[@]}"; then loaded=1; break; fi
      sleep 10
    done
    [ -n "$loaded" ] || echo "WARNING: incident index not loaded; rerun: ${load_cmd[*]}" >&2
  fi
fi

az containerapp revision restart -g "$TWIN_RG" -n "$ORDER_APP_NAME" \
  --revision "$(az containerapp show -g "$TWIN_RG" -n "$ORDER_APP_NAME" --query properties.latestRevisionName -o tsv)"
DRILL_ID="$(./scripts/new-drill.sh)"; export DRILL_ID   # the baseline gets its own drill ID
./scripts/wait-for.sh ok
# The browser baseline runs on this machine (Playwright, Chromium, the ODBC driver). POSTPROVISION_BASELINE=off skips
# only it, for provisions that don't touch the twin (deploy.sh foundry and runner, ADR-026); a drill runs its own
# baseline through job-referee. Default on.
if [ "${POSTPROVISION_BASELINE:-on}" = off ]; then
  echo "baseline skipped (POSTPROVISION_BASELINE=off); the twin answered ok above"
  exit 0
fi
./scripts/referee.sh baseline                     # a failed baseline fails azd provision
