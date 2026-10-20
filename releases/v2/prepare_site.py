"""Validate the v2 signing kit and retain v1 immutable catalog objects."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

from catalog import release as r
from catalog.artifacts import require_frozen_urls
from catalog.static_site import build
from catalog.trust import ROOT_PATH, require_trusted_root

KIT_SHA256 = '7e2d60321274c418a0ec5f93116855f004bcc0321eac612a4a1804c87294897c'
CATALOG_SHA256 = '173b3a903b1bf1994191dab8d21c638046eb348f2bd2d70562e9f436e45a8304'


def prepare(stage):
    stage = Path(stage)
    release = Path(__file__).resolve().parent
    require_trusted_root()
    with (stage/'kit.zip').open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != KIT_SHA256:
            raise ValueError('Signing kit checksum mismatch')
    candidate = stage/'candidate'
    with zipfile.ZipFile(stage/'kit.zip') as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive entry')
        prefix = 'StellarOS.AppCatalog/candidate/'
        entries = [i for i in archive.infolist() if i.filename.startswith(prefix) and not i.is_dir()]
        if sum(i.file_size for i in entries) > 1024**3:
            raise ValueError('Oversized candidate')
        for entry in entries:
            relative = Path(entry.filename[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts or entry.file_size > 536870912:
                raise ValueError('Unsafe archive entry')
            dest = candidate/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, dest.open('xb') as target:
                shutil.copyfileobj(source, target)
    catalog = (candidate/'catalog.json').read_bytes()
    if hashlib.sha256(catalog).hexdigest() != CATALOG_SHA256 or catalog != (release/'catalog.json').read_bytes():
        raise ValueError('Catalog differs from the signed release')
    data = json.loads(catalog)
    require_frozen_urls(data)
    root, roles = r.validate_release(ROOT_PATH, release, candidate)
    for md in roles.values():
        if md.signed.version != 2 or md.signed.expires != root.signed.expires:
            raise ValueError('Unexpected release version or expiry')
    build(ROOT_PATH, release, candidate, stage/'site')

    # Keep prior objects so a client that already fetched timestamp v1 can finish.
    previous = release/'previous'
    old_catalog = (previous/'catalog.json').read_bytes()
    before = {a['packageName']: {k:v for k,v in a.items() if k != 'url'} for a in json.loads(old_catalog)['apps']}
    after = {a['packageName']: {k:v for k,v in a.items() if k != 'url'} for a in data['apps']}
    if before != after:
        raise ValueError('URL migration changed approved APK identities')
    (candidate/'catalog.json').write_bytes(old_catalog)
    _, old_roles = r.validate_release(ROOT_PATH, previous, candidate)
    if any(md.signed.version != 1 for md in old_roles.values()):
        raise ValueError('Unexpected previous version')
    for role in ('snapshot', 'targets'):
        shutil.copyfile(previous/f'{role}.json', stage/f'site/metadata/1.{role}.json')
    (stage/'site/targets'/f'{hashlib.sha256(old_catalog).hexdigest()}.catalog.json').write_bytes(old_catalog)
    print('Verified v2 signatures, all nine APK hashes and preserved v1 objects.')


if __name__ == '__main__':
    prepare(sys.argv[1])
