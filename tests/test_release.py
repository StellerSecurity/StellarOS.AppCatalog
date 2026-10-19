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
        self.keys = [CryptoSigner.generate_ed25519() for _ in range(1)]
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
        for key in self.keys:
            md.sign(key, append=True)

    def verify(self):
        return r.validate_release(self.rootpath, self.metadata, self.candidate)

    def test_single_key_required_for_each_role(self):
        for role in r.ROLES:
            self.assertEqual(self.root.signed.roles[role].threshold, 1)
            self.assertEqual(self.root.signed.roles[role].keyids, [self.keys[0].public_key.keyid])
        with self.assertRaises(ValueError):
            r.initialize([], r.now() + timedelta(days=365))
        with self.assertRaises(ValueError):
            r.initialize([self.base / '0.json'] * 2, r.now() + timedelta(days=365))

    def test_single_key_cli_init_and_sign(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from securesystemslib.signer import SSlibKey
        private = Ed25519PrivateKey.generate()
        key = SSlibKey.from_crypto(private.public_key())
        public_path = self.base / 'cli-public.json'
        private_path = self.base / 'cli-private.pem'
        output = self.base / 'cli-root.json'
        public_path.write_text(json.dumps({'keyid': key.keyid, 'key': key.to_dict()}))
        private_path.write_bytes(private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b'test-password')))
        with patch('sys.argv', ['release', 'init-root', '--public', str(public_path), '--output', str(output)]):
            r.main()
        with patch.dict('os.environ', {}, clear=True), patch('getpass.getpass', return_value='test-password'), patch(
                'sys.argv', ['release', 'sign', str(output), '--private', str(private_path)]):
            r.main()
        root = r.load(output)
        root.signed.verify_delegate('root', root.signed_bytes, root.signatures)
        self.assertEqual(len(root.signatures), 1)
        self.assertEqual(root.signed.roles['root'].threshold, 1)

    def test_valid_chain_and_export(self):
        self.verify()
        output = self.base / 'export'
        r.export(self.rootpath, self.metadata, self.candidate, output)
        self.assertTrue((output / 'metadata/1.root.json').exists())
        self.assertTrue((output / 'metadata/1.targets.json').exists())
        self.assertEqual(len([p for p in (output / 'targets').rglob('*') if p.is_file()]), 2)

    def test_unsigned_metadata_rejected(self):
        self.targets.signatures.clear()
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
