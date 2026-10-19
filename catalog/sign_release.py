"""Verify an APK candidate and sign its metadata offline with one encrypted key."""
import argparse
from datetime import timedelta
import getpass
import os
from pathlib import Path
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner
from catalog import release as r
from catalog.candidate import verify_candidate
from catalog.trust import ROOT_PATH, require_trusted_root


def sign(candidate, output, private, policy, apksigner, aapt2, version, password):
    if os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS'):
        raise ValueError('Signing is offline only')
    require_trusted_root()
    if version < 1: raise ValueError('Version must be positive')
    candidate, output = Path(candidate), Path(output)
    if output.exists(): raise ValueError('Output already exists; use a new release directory')
    verify_candidate(candidate, policy, apksigner, aapt2)
    for app in r.validate_catalog(json.loads((candidate / 'catalog.json').read_text()))['apps']:
        r.validate_url(app['url'])
    key = serialization.load_pem_private_key(Path(private).read_bytes(), password)
    if not isinstance(key, Ed25519PrivateKey): raise ValueError('Expected encrypted Ed25519 key')
    signer = CryptoSigner(key)
    root = r.load(ROOT_PATH)
    for role in r.ROLES:
        if signer.public_key.keyid not in root.signed.roles[role].keyids:
            raise ValueError('Private key does not match approved root')
    output.mkdir(parents=True)
    targets = r.prepare_targets(candidate, version, r.now() + timedelta(days=90))
    targets.sign(signer); r.write(targets, output / 'targets.json')
    snapshot = r.prepare_snapshot(ROOT_PATH, output / 'targets.json', version, r.now() + timedelta(days=90))
    snapshot.sign(signer); r.write(snapshot, output / 'snapshot.json')
    timestamp = r.prepare_timestamp(ROOT_PATH, output / 'snapshot.json', version, r.now() + timedelta(days=30))
    timestamp.sign(signer); r.write(timestamp, output / 'timestamp.json')
    r.validate_release(ROOT_PATH, output, candidate)
    print('Verified and signed targets, snapshot and timestamp. Timestamp expires in 30 days.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'output', 'private', 'apksigner', 'aapt2'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--policy', default='apps-policy.json')
    p.add_argument('--version', required=True, type=int)
    a = p.parse_args()
    password = getpass.getpass('Offline key password: ').encode()
    if not password: raise ValueError('Key password is required')
    sign(a.candidate, a.output, a.private, a.policy, a.apksigner, a.aapt2, a.version, password)


if __name__ == '__main__': main()
