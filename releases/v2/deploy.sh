#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
test "$(az staticwebapp show --name stellaros-appcatalog --resource-group stellaros-appcatalog_group --query sku.name -o tsv)" = Free
stage="$(mktemp -d)"
trap 'unset SWA_CLI_DEPLOYMENT_TOKEN; rm -rf "$stage"' EXIT
python3 -m venv "$stage/venv"
"$stage/venv/bin/pip" install --require-hashes -r requirements.lock
base='https://stellarosappcatalog.stellarsecurity.com'
"$stage/venv/bin/python" -m catalog.client_check --root trust/root.json --state "$stage/before" --base-url "$base"
if cmp -s "$stage/before/timestamp.json" releases/v2/timestamp.json; then
  echo 'Catalog v2 is already live and verified.'
  exit 0
fi
cmp "$stage/before/timestamp.json" releases/v2/previous/timestamp.json
curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
  'https://github.com/StellerSecurity/StellarOS.AppCatalog/releases/download/catalog-candidate-39512752155-1/StellarOS-AppCatalog-signing-kit.zip' \
  -o "$stage/kit.zip"
"$stage/venv/bin/python" releases/v2/prepare_site.py "$stage"
# Recheck production immediately before changing it; never replace a newer release.
curl --fail --proto '=https' --max-time 30 "$base/metadata/timestamp.json" -o "$stage/current.json"
cmp "$stage/current.json" releases/v2/previous/timestamp.json
export SWA_CLI_DEPLOYMENT_TOKEN
SWA_CLI_DEPLOYMENT_TOKEN="$(az staticwebapp secrets list --name stellaros-appcatalog --resource-group stellaros-appcatalog_group --query properties.apiKey -o tsv)"
test -n "$SWA_CLI_DEPLOYMENT_TOKEN"
npx --yes @azure/static-web-apps-cli@2.0.10 deploy "$stage/site" --env production
unset SWA_CLI_DEPLOYMENT_TOKEN
for attempt in $(seq 1 30); do
  if "$stage/venv/bin/python" -m catalog.client_check --root trust/root.json --state "$stage/before" --base-url "$base" &&
      cmp -s "$stage/before/timestamp.json" releases/v2/timestamp.json &&
      cmp -s "$stage/before/catalog.json" releases/v2/catalog.json; then
    echo 'SUCCESS: Catalog v2 is live, with all nine entries verified.'
    exit 0
  fi
  sleep 5
done
echo 'Deployment returned, but live v2 verification has not completed.' >&2
exit 1
