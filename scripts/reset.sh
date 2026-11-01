#!/usr/bin/env bash
# Returns the twin to baseline from any state: access back, app restarted, drill rows deleted, health green.
# Run it before every drill. For G1 it is also the kill switch.
source "$(dirname "$0")/lib.sh"
HERE="$(dirname "$0")"
ENTRIES="$("$HERE/fault.sh" status | grep -o '[0-9]*$')"
if [ "$ENTRIES" = "0" ]; then "$HERE/fault.sh" restore; fi
REV="$(az containerapp show -g "$TWIN_RG" -n "$ORDER_APP_NAME" --query properties.latestRevisionName -o tsv)"
az containerapp revision restart -g "$TWIN_RG" -n "$ORDER_APP_NAME" --revision "$REV" -o none
sqlcmd -S "$SQL_SERVER_FQDN" -d "$SQL_DB_NAME" -U lfadmin -P "$SQL_ADMIN_PASSWORD" -b -Q "
  DELETE pa FROM dbo.payment_authorizations pa JOIN dbo.orders o ON o.order_id = pa.order_id
    WHERE o.drill_id LIKE 'drill-%';
  DELETE FROM dbo.orders WHERE drill_id LIKE 'drill-%';"
"$HERE/wait-for.sh" ok
event reset ok
echo "reset done"
