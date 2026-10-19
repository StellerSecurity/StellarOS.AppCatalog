#!/usr/bin/env bash
# Explicit operator test: temporarily denies catalog refreshes in production.
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
test "$(az staticwebapp show --name stellaros-appcatalog --resource-group stellaros-appcatalog_group --query sku.name -o tsv)" = Free
backup="$(mktemp -d "$HOME/stellar-catalog-rollback.XXXXXX")"
python3 -m venv "$backup/venv"
"$backup/venv/bin/pip" -q install --require-hashes -r requirements.lock
"$backup/venv/bin/python" -m catalog.client_check --root trust/root.json --state "$backup/client" --base-url https://stellarosappcatalog.stellarsecurity.com
"$backup/venv/bin/python" - "$backup" <<'PY'
from pathlib import Path
import sys,json,hashlib,urllib.request,shutil
from catalog.trust import require_trusted_root,ROOT_PATH
from catalog import release as r
b=Path(sys.argv[1]);good=b/'good';(good/'metadata').mkdir(parents=True);(good/'targets').mkdir()
require_trusted_root()
def get(path):
 with urllib.request.urlopen('https://stellarosappcatalog.stellarsecurity.com/'+path,timeout=30) as f: return f.read()
for role in ('timestamp','snapshot','targets'):
 md=r.load(Path('releases/v1')/(role+'.json'))
 name=(str(md.signed.version)+'.' if role!='timestamp' else '')+role+'.json'
 data=get('metadata/'+name)
 assert data==(Path('releases/v1')/(role+'.json')).read_bytes(),'Live release changed; abort'
 (good/'metadata'/name).write_bytes(data)
root=get('metadata/1.root.json');assert root==ROOT_PATH.read_bytes()
(good/'metadata/1.root.json').write_bytes(root)
data=(b/'client/catalog.json').read_bytes();name=hashlib.sha256(data).hexdigest()+'.catalog.json'
assert get('targets/'+name)==data
(good/'targets'/name).write_bytes(data)
(good/'index.html').write_bytes(get(''))
(good/'staticwebapp.config.json').write_text(json.dumps({'globalHeaders':{'X-Content-Type-Options':'nosniff','Cache-Control':'no-cache, max-age=0, must-revalidate'},'mimeTypes':{'.json':'application/json'},'routes':[{'route':'/metadata/timestamp.json','headers':{'Cache-Control':'no-store, max-age=0'}}]},indent=2)+'\n')
shutil.copytree(good,b/'bad')
p=b/'bad/metadata/timestamp.json';md=json.loads(p.read_text());sig=md['signatures'][0]['sig'];md['signatures'][0]['sig']=('0' if sig[0]!='0' else '1')+sig[1:];p.write_text(json.dumps(md,separators=(',',':')))
try:r.load(ROOT_PATH).verify_delegate('timestamp',r.load(p))
except Exception: pass
else: raise AssertionError('Test signature unexpectedly valid')
(b/'backup-sha256.json').write_text(json.dumps({str(p.relative_to(good)):hashlib.sha256(p.read_bytes()).hexdigest() for p in good.rglob('*') if p.is_file()},indent=2))
print('Verified rollback backup:',b)
PY
export SWA_CLI_DEPLOYMENT_TOKEN
SWA_CLI_DEPLOYMENT_TOKEN="$(az staticwebapp secrets list --name stellaros-appcatalog --resource-group stellaros-appcatalog_group --query properties.apiKey -o tsv)"
test -n "$SWA_CLI_DEPLOYMENT_TOKEN"
restore() {
 trap - EXIT INT TERM HUP
 for attempt in 1 2 3; do
  if npx --yes @azure/static-web-apps-cli@2.0.10 deploy "$backup/good" --env production; then
   if "$backup/venv/bin/python" -m catalog.client_check --root trust/root.json --state "$backup/restored-client" --base-url https://stellarosappcatalog.stellarsecurity.com; then
    echo "RESTORED AND VERIFIED; backup retained: $backup"
    unset SWA_CLI_DEPLOYMENT_TOKEN
    return 0
   fi
  fi
 done
 echo "RESTORE FAILED: retained verified backup at $backup" >&2
 return 1
}
trap restore EXIT
trap 'exit 130' INT TERM HUP
npx --yes @azure/static-web-apps-cli@2.0.10 deploy "$backup/bad" --env production
echo 'INVALID SIGNATURE LIVE: automatic restore in 90 seconds'
sleep 90
