"""Publish an already offline-signed release to an existing Azure Blob container.

Requires `az login` (OIDC in CI), Storage Blob Data Contributor, a protected
ROOT_SHA256 environment variable, and a root file approved outside this workflow.
Does not provision Azure resources or perform signing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from catalog import release as r


def az(*args):
    result = subprocess.run(['az', *args, '--only-show-errors', '-o', 'json'],
                            capture_output=True, text=True, check=True, timeout=600)
    return json.loads(result.stdout) if result.stdout.strip() else None


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def publish(root_path, metadata, candidate, account, container):
    expected_root = os.environ.get('ROOT_SHA256', '')
    if len(expected_root) != 64 or digest(root_path) != expected_root:
        raise ValueError('Root does not match independently pinned ROOT_SHA256')
    root, roles = r.validate_release(root_path, metadata, candidate)
    common = ['--account-name', account, '--container-name', container, '--auth-mode', 'login']
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        output = temp / 'export'
        r.export(root_path, metadata, candidate, output)

        def exists(name):
            return az('storage', 'blob', 'exists', *common, '--name', name)['exists']

        def download(name, path):
            az('storage', 'blob', 'download', *common, '--name', name, '--file', str(path))

        timestamp_name = 'metadata/timestamp.json'
        etag = None
        if exists(timestamp_name):
            properties = az('storage', 'blob', 'show', *common, '--name', timestamp_name)
            etag = properties['properties']['etag']
            previous = temp / 'previous-timestamp.json'
            download(timestamp_name, previous)
            old = r.load(previous)
            # An expired *previous* release may be replaced: preserve its authenticated
            # version floor. Only the NEW release must be fresh.
            root.signed.verify_delegate('timestamp', old.signed_bytes, old.signatures)
            if roles['timestamp'].signed.version <= old.signed.version:
                raise ValueError('Timestamp version must increase')
            previous_snapshot = temp / 'previous-snapshot.json'
            download(f'metadata/{old.signed.snapshot_meta.version}.snapshot.json', previous_snapshot)
            old.signed.snapshot_meta.verify_length_and_hashes(previous_snapshot.read_bytes())
            old_snapshot = r.load(previous_snapshot)
            root.signed.verify_delegate('snapshot', old_snapshot.signed_bytes, old_snapshot.signatures)
            if roles['snapshot'].signed.version <= old_snapshot.signed.version:
                raise ValueError('Snapshot version must increase')
            if roles['targets'].signed.version <= old_snapshot.signed.meta['targets.json'].version:
                raise ValueError('Targets version must increase')

        # Never overwrite immutable metadata or artifacts. Verify existing bytes on retries.
        for path in sorted(p for p in output.rglob('*') if p.is_file()):
            name = path.relative_to(output).as_posix()
            if name == timestamp_name: continue
            if exists(name):
                existing = temp / 'existing'
                if existing.exists(): existing.unlink()
                download(name, existing)
                if digest(existing) != digest(path):
                    raise ValueError('Immutable Azure object differs: ' + name)
            else:
                az('storage', 'blob', 'upload', *common, '--name', name, '--file', str(path),
                   '--overwrite', 'false', '--if-none-match', '*',
                   '--content-cache-control', 'public,max-age=31536000,immutable')
        # Commit point: prevent a concurrent publisher from replacing a newer release.
        condition = ['--if-match', etag] if etag else ['--if-none-match', '*']
        az('storage', 'blob', 'upload', *common, '--name', timestamp_name,
           '--file', str(output / timestamp_name), '--overwrite', 'true', *condition,
           '--content-cache-control', 'no-cache,max-age=0,must-revalidate')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'metadata', 'candidate', 'account', 'container'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    publish(a.root, a.metadata, a.candidate, a.account, a.container)


if __name__ == '__main__': main()
