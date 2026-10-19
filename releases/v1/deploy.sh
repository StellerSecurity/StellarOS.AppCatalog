#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
test "$(az staticwebapp show --name stellaros-appcatalog --resource-group stellaros-appcatalog_group --query sku.name -o tsv)" = Free
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' --retry 3   'https://github.com/StellerSecurity/StellarOS.AppCatalog/releases/download/catalog-candidate-39232911551-1/StellarOS-AppCatalog-signing-kit.zip'   -o "$stage/kit.zip"
printf '%s  %s\n' '6f4c4ec6022cc88054f63b07cf3bb8b632b540fd43f9b0c382b346f2647e3450' "$stage/kit.zip" | sha256sum -c -
python3 -m venv "$stage/venv"
"$stage/venv/bin/pip" install --require-hashes -r requirements.lock
"$stage/venv/bin/python" - "$stage" <<'PY'
from pathlib import Path
import sys, zipfile, shutil
from catalog.static_site import build
from catalog.trust import ROOT_PATH, require_trusted_root
from catalog import release as r
stage = Path(sys.argv[1])
with zipfile.ZipFile(stage/'kit.zip') as z:
    for i in z.infolist():
        prefix = 'StellarOS.AppCatalog/candidate/'
        if not i.filename.startswith(prefix) or i.is_dir(): continue
        rel = Path(i.filename[len(prefix):])
        assert not rel.is_absolute() and '..' not in rel.parts and i.file_size <= 536870912
        out = stage/'candidate'/rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with z.open(i) as source, out.open('wb') as target: shutil.copyfileobj(source, target)
require_trusted_root()
for role in ('targets','snapshot','timestamp'):
    assert r.load(Path('releases/v1')/f'{role}.json').signed.expires == r.load(ROOT_PATH).signed.expires
build(ROOT_PATH, 'releases/v1', stage/'candidate', stage/'site')
print('Verified all signatures and candidate APK hashes before deployment')
PY
export SWA_CLI_DEPLOYMENT_TOKEN
SWA_CLI_DEPLOYMENT_TOKEN="$(az staticwebapp secrets list --name stellaros-appcatalog --resource-group stellaros-appcatalog_group --query properties.apiKey -o tsv)"
test -n "$SWA_CLI_DEPLOYMENT_TOKEN"
npx --yes @azure/static-web-apps-cli@2.0.10 deploy "$stage/site" --env production
unset SWA_CLI_DEPLOYMENT_TOKEN
"$stage/venv/bin/python" -m catalog.client_check --root trust/root.json --state "$stage/client" --base-url https://stellarosappcatalog.stellarsecurity.com
