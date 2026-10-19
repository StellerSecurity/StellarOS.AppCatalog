"""Offline TUF release assembly. This module performs no network operations.

Private keys are accepted only by explicit signing commands, never by CI.
All four metadata roles are offline-signed (including timestamp).
"""
import argparse
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner, SSlibKey
from tuf.api.metadata import Metadata, Root, Targets, Snapshot, Timestamp, MetaFile, TargetFile

ROLES = ('root', 'targets', 'snapshot', 'timestamp')


def now():
    return datetime.now(timezone.utc)


def load(path):
    return Metadata.from_file(str(path))


def write(metadata, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata.to_file(str(path))


def assert_fresh(md):
    if md.signed.is_expired(now()):
        raise ValueError('Expired metadata: ' + md.signed.type)


def verify_role(root, role, md):
    if md.signed.type != role:
        raise ValueError('Wrong metadata role')
    assert_fresh(md)
    root.signed.verify_delegate(role, md.signed_bytes, md.signatures)


def initialize(public_files, expires):
    """One offline Ed25519 key signs every metadata role."""
    keys = []
    for path in public_files:
        data = json.loads(Path(path).read_text())
        key = SSlibKey.from_dict(data['keyid'], data['key'])
        if key.keytype != 'ed25519':
            raise ValueError('Only Ed25519 keys supported by this release profile')
        keys.append(key)
    if len(keys) != 1:
        raise ValueError('Provide exactly one catalog signing public key')
    root = Root(version=1, expires=expires, consistent_snapshot=True)
    for role in ROLES:
        root.roles[role].threshold = 1
        for key in keys:
            root.add_key(key, role)
    return Metadata(root)


def sign_file(path, private_path, password):
    if os.environ.get('GITHUB_ACTIONS') or os.environ.get('CI'):
        raise ValueError('Signing is forbidden in CI; use an offline computer')
    key = serialization.load_pem_private_key(Path(private_path).read_bytes(), password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Expected an encrypted Ed25519 private key')
    md = load(path)
    md.sign(CryptoSigner(key), append=True)
    write(md, path)


def validate_url(url):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or any(ord(c) < 33 for c in url):
        raise ValueError('Invalid HTTPS APK URL')
    return url


def validate_catalog(data):
    if data.get('schemaVersion') != 1 or not isinstance(data.get('apps'), list) or not data['apps']:
        raise ValueError('Invalid or empty catalog')
    seen = set()
    for app in data['apps']:
        package = app['packageName']
        version = app['versionCode']
        digest = app['sha256']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', package):
            raise ValueError('Invalid package name')
        if package in seen:
            raise ValueError('Duplicate package')
        seen.add(package)
        if type(version) is not int or version < 1 or type(app['length']) is not int or app['length'] < 1:
            raise ValueError('Invalid version or size')
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid file digest')
        if app['target'] != f'apks/{package}/{version}/{digest}.apk':
            raise ValueError('APK path must be immutable and content-addressed')
        if 'url' in app:
            validate_url(app['url'])
        pins = app['signerSha256']
        if not pins or len(set(pins)) != len(pins) or any(not re.fullmatch(r'[0-9a-f]{64}', p) for p in pins):
            raise ValueError('Invalid signer fingerprints')
    return data


def prepare_targets(candidate, version, expires):
    candidate = Path(candidate)
    catalog_bytes = (candidate / 'catalog.json').read_bytes()
    catalog = validate_catalog(json.loads(catalog_bytes))
    targets = Targets(version=version, expires=expires)
    if version < 1:
        raise ValueError('Version must be positive')
    targets.targets['catalog.json'] = TargetFile.from_data('catalog.json', catalog_bytes)
    for app in catalog['apps']:
        path = app['target']
        with (candidate / path).open('rb') as f:
            target = TargetFile.from_data(path, f)
        if target.length != app['length'] or target.hashes.get('sha256') != app['sha256']:
            raise ValueError('APK does not match catalog: ' + app['packageName'])
        targets.targets[path] = target
    return Metadata(targets)


def prepare_snapshot(root_path, targets_path, version, expires):
    root, targets = load(root_path), load(targets_path)
    verify_role(root, 'root', root)
    verify_role(root, 'targets', targets)
    return Metadata(Snapshot(version=version, expires=expires, meta={
        'targets.json': MetaFile.from_data(targets.signed.version, Path(targets_path).read_bytes(), ['sha256'])
    }))


def prepare_timestamp(root_path, snapshot_path, version, expires):
    root, snapshot = load(root_path), load(snapshot_path)
    verify_role(root, 'root', root)
    verify_role(root, 'snapshot', snapshot)
    return Metadata(Timestamp(version=version, expires=expires,
        snapshot_meta=MetaFile.from_data(snapshot.signed.version, Path(snapshot_path).read_bytes(), ['sha256'])))


def validate_release(root_path, metadata_dir, candidate):
    """Publisher validation anchored to separately approved root, never release-supplied root."""
    root = load(root_path)
    verify_role(root, 'root', root)
    folder = Path(metadata_dir)
    roles = {role: load(folder / f'{role}.json') for role in ROLES[1:]}
    for role, md in roles.items():
        verify_role(root, role, md)
    snapshot, timestamp, targets = (roles[x] for x in ('snapshot', 'timestamp', 'targets'))
    smeta = timestamp.signed.snapshot_meta
    tmeta = snapshot.signed.meta['targets.json']
    if smeta.version != snapshot.signed.version or tmeta.version != targets.signed.version:
        raise ValueError('Mixed metadata versions')
    smeta.verify_length_and_hashes((folder / 'snapshot.json').read_bytes())
    tmeta.verify_length_and_hashes((folder / 'targets.json').read_bytes())
    expected = prepare_targets(candidate, targets.signed.version, targets.signed.expires)
    if expected.signed.targets != targets.signed.targets:
        # TUF model objects do not define structural equality consistently.
        actual = {p: t.to_dict() for p, t in targets.signed.targets.items()}
        wanted = {p: t.to_dict() for p, t in expected.signed.targets.items()}
        if actual != wanted:
            raise ValueError('Signed targets differ from release files')
    return root, roles


def export(root_path, metadata_dir, candidate, output):
    root, roles = validate_release(root_path, metadata_dir, candidate)
    output = Path(output)
    if output.exists():
        raise ValueError('Output must not exist')
    for role, md in {'root': root, **roles}.items():
        source = Path(root_path) if role == 'root' else Path(metadata_dir) / f'{role}.json'
        name = 'timestamp.json' if role == 'timestamp' else f'{md.signed.version}.{role}.json'
        dest = output / 'metadata' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    for path, info in roles['targets'].signed.targets.items():
        p = Path(path)
        dest = output / 'targets' / p.parent / (info.hashes['sha256'] + '.' + p.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((Path(candidate) / path).read_bytes())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    k = sub.add_parser('keygen')
    k.add_argument('--private', required=True)
    k.add_argument('--public', required=True)
    i = sub.add_parser('init-root')
    i.add_argument('--public', nargs=1, required=True)
    i.add_argument('--output', required=True)
    i.add_argument('--days', type=int, default=365)
    s = sub.add_parser('sign')
    s.add_argument('metadata')
    s.add_argument('--private', required=True)
    s.add_argument('--candidate')
    s.add_argument('--policy', default='apps-policy.json')
    s.add_argument('--apksigner')
    s.add_argument('--aapt2')
    for role in ('targets', 'snapshot', 'timestamp'):
        r = sub.add_parser('prepare-' + role)
        r.add_argument('--version', required=True, type=int)
        r.add_argument('--days', type=int, default=30 if role != 'timestamp' else 7)
        r.add_argument('--output', required=True)
        if role == 'targets':
            r.add_argument('--candidate', required=True)
        else:
            r.add_argument('--root', required=True)
            r.add_argument('--input', required=True)
    for name in ('verify', 'export'):
        r = sub.add_parser(name)
        r.add_argument('--root', required=True)
        r.add_argument('--metadata', required=True)
        r.add_argument('--candidate', required=True)
        if name == 'export':
            r.add_argument('--output', required=True)
    args = p.parse_args()
    if args.command == 'keygen':
        if os.environ.get('CI') or os.environ.get('GITHUB_ACTIONS'):
            p.error('Key generation is forbidden in CI')
        password = getpass.getpass('New offline key password: ').encode()
        if not password or getpass.getpass('Repeat password: ').encode() != password:
            p.error('Matching non-empty passwords are required')
        private = Ed25519PrivateKey.generate()
        pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.BestAvailableEncryption(password))
        with os.fdopen(os.open(args.private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            f.write(pem)
        public = SSlibKey.from_crypto(private.public_key())
        with open(args.public, 'x') as f:
            json.dump({'keyid': public.keyid, 'key': public.to_dict()}, f, indent=2)
    elif args.command == 'sign':
        if load(args.metadata).signed.type == 'targets':
            if not all([args.candidate, args.apksigner, args.aapt2]):
                p.error('Targets signing requires --candidate, --apksigner and --aapt2 for offline APK inspection')
            from catalog.candidate import verify_candidate
            verify_candidate(args.candidate, args.policy, args.apksigner, args.aapt2)
            expected = prepare_targets(args.candidate, load(args.metadata).signed.version, load(args.metadata).signed.expires)
            if expected.signed.to_dict() != load(args.metadata).signed.to_dict():
                p.error('Targets differ from inspected candidate')
        sign_file(args.metadata, args.private, getpass.getpass('Offline key password: ').encode())
    elif args.command == 'init-root':
        write(initialize(args.public, now() + timedelta(days=args.days)), args.output)
    elif args.command.startswith('prepare-'):
        if args.days < 1 or args.version < 1:
            p.error('Positive lifetime and version required')
        expiry = now() + timedelta(days=args.days)
        if args.command == 'prepare-targets':
            md = prepare_targets(args.candidate, args.version, expiry)
        elif args.command == 'prepare-snapshot':
            md = prepare_snapshot(args.root, args.input, args.version, expiry)
        else:
            md = prepare_timestamp(args.root, args.input, args.version, expiry)
        write(md, args.output)
    elif args.command == 'verify':
        validate_release(args.root, args.metadata, args.candidate)
        print('Verified: signature thresholds, expiry, metadata chain and all target bytes')
    else:
        export(args.root, args.metadata, args.candidate, args.output)


if __name__ == '__main__':
    main()
