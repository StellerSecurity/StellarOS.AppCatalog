from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root
from catalog import release as r


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.keys = [CryptoSigner.generate_ed25519() for _ in range(3)]
        public = []
        for i, key in enumerate(self.keys):
            path = self.base / f'{i}.json'
            path.write_text(json.dumps({'keyid': key.public_key.keyid, 'key': key.public_key.to_dict()}))
            public.append(path)
        self.root = r.initialize(public, r.now() + timedelta(days=365))
        self.sign(self.root)
        self.rootpath = self.base / 'root.json'
        r.write(self.root, self.rootpath)
        self.candidate = self.base / 'candidate'
        self.candidate.mkdir()
        data = b'test bytes, not a production APK'
        digest = hashlib.sha256(data).hexdigest()
        entry = {'packageName': 'test.stellar.app', 'versionCode': 1, 'length': len(data),
                 'sha256': digest, 'target': f'apks/test.stellar.app/1/{digest}.apk', 'signerSha256': ['a'*64]}
        path = self.candidate / entry['target']
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        self.apk = path
        (self.candidate / 'catalog.json').write_text(json.dumps({'schemaVersion': 1, 'apps': [entry]}))
        self.metadata = self.base / 'metadata'
        self.targets = r.prepare_targets(self.candidate, 1, r.now() + timedelta(days=30))
        self.sign(self.targets)
        r.write(self.targets, self.metadata / 'targets.json')
        self.snapshot = r.prepare_snapshot(self.rootpath, self.metadata / 'targets.json', 1, r.now() + timedelta(days=30))
        self.sign(self.snapshot)
        r.write(self.snapshot, self.metadata / 'snapshot.json')
        self.timestamp = r.prepare_timestamp(self.rootpath, self.metadata / 'snapshot.json', 1, r.now() + timedelta(days=7))
        self.sign(self.timestamp)
        r.write(self.timestamp, self.metadata / 'timestamp.json')

    def sign(self, md):
        for key in self.keys[:2]:
            md.sign(key, append=True)

    def verify(self):
        return r.validate_release(self.rootpath, self.metadata, self.candidate)

    def test_valid_chain_and_export(self):
        self.verify()
        output = self.base / 'export'
        r.export(self.rootpath, self.metadata, self.candidate, output)
        self.assertTrue((output / 'metadata/1.root.json').exists())
        self.assertTrue((output / 'metadata/1.targets.json').exists())
        self.assertEqual(len([p for p in (output / 'targets').rglob('*') if p.is_file()]), 2)

    def test_single_signature_rejected(self):
        self.targets.signatures.pop(self.keys[1].public_key.keyid)
        r.write(self.targets, self.metadata / 'targets.json')
        with self.assertRaises(Exception): self.verify()

    def test_unknown_signatures_rejected(self):
        self.targets.sign(CryptoSigner.generate_ed25519())
        r.write(self.targets, self.metadata / 'targets.json')
        with self.assertRaises(Exception): self.verify()

    def test_expired_timestamp_rejected(self):
        self.timestamp.signed.expires = r.now() - timedelta(seconds=1)
        self.sign(self.timestamp)
        r.write(self.timestamp, self.metadata / 'timestamp.json')
        with self.assertRaises(ValueError): self.verify()

    def test_tampered_apk_rejected(self):
        self.apk.write_bytes(b'attacker replacement')
        with self.assertRaises(ValueError): self.verify()

    def test_tampered_catalog_rejected(self):
        path = self.candidate / 'catalog.json'
        data = json.loads(path.read_text())
        data['apps'][0]['signerSha256'] = ['b'*64]
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.verify()

    def test_mixed_snapshot_rejected(self):
        self.snapshot.signed.version += 1
        self.sign(self.snapshot)
        r.write(self.snapshot, self.metadata / 'snapshot.json')
        with self.assertRaises(ValueError): self.verify()

    def test_path_traversal_rejected(self):
        path = self.candidate / 'catalog.json'
        data = json.loads(path.read_text())
        data['apps'][0]['target'] = '../secret'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.verify()

    def test_duplicate_package_rejected(self):
        path = self.candidate / 'catalog.json'
        data = json.loads(path.read_text())
        data['apps'].append(data['apps'][0])
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.verify()

    def test_ci_cannot_sign(self):
        with patch.dict('os.environ', {'CI': 'true'}):
            with self.assertRaises(ValueError): r.sign_file('missing', 'missing', b'no')


if __name__ == '__main__': unittest.main()
