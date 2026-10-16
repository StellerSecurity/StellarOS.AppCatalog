"""Reference verification using the official TUF updater, not an Android integration."""
import argparse
import json
from pathlib import Path
import shutil
from tuf.ngclient import Updater
from catalog.release import validate_catalog


def check(root, state, metadata_url, targets_url):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    trusted = state / 'root.json'
    if not trusted.exists():
        shutil.copyfile(root, trusted)
    # Persist this directory across runs for rollback protection.
    updater = Updater(str(state), metadata_url, target_base_url=targets_url)
    updater.refresh()
    target = updater.get_targetinfo('catalog.json')
    if target is None: raise ValueError('Missing signed catalog')
    path = updater.download_target(target, str(state / 'catalog.json'))
    data = validate_catalog(json.loads(Path(path).read_text()))
    for app in data['apps']:
        info = updater.get_targetinfo(app['target'])
        if info is None or info.length != app['length'] or info.hashes.get('sha256') != app['sha256']:
            raise ValueError('Catalog entry does not match signed APK target')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--state', required=True)
    p.add_argument('--base-url', required=True)
    a = p.parse_args()
    if not a.base_url.startswith('https://'): p.error('HTTPS required')
    data = check(a.root, a.state, a.base_url.rstrip('/') + '/metadata/', a.base_url.rstrip('/') + '/targets/')
    print(f"Verified {len(data['apps'])} catalog entries with the official TUF client")


if __name__ == '__main__': main()
