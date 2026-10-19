import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import timedelta
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root
from catalog import release as r
from catalog.sign_release import sign

class SignReleaseTests(unittest.TestCase):
    def test_one_password_signs_all_roles_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); key = Ed25519PrivateKey.generate(); signer = CryptoSigner(key)
            private = base/'key.pem'
            private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b'test')))
            root = Root(expires=r.now()+timedelta(days=365), consistent_snapshot=True)
            for role in r.ROLES: root.add_key(signer.public_key, role)
            md = Metadata(root); md.sign(signer); rootpath = base/'root.json'; r.write(md, rootpath)
            candidate = base/'candidate'; candidate.mkdir()
            import hashlib
            digest = hashlib.sha256(b'apk').hexdigest()
            app = dict(packageName='org.example.app', versionCode=1, length=3, sha256=digest, target=f'apks/org.example.app/1/{digest}.apk', signerSha256=['a'*64], url='https://example.org/app.apk')
            apk = candidate/app['target']; apk.parent.mkdir(parents=True); apk.write_bytes(b'apk')
            (candidate/'catalog.json').write_text(json.dumps(dict(schemaVersion=1, apps=[app])))
            with patch('catalog.sign_release.ROOT_PATH', rootpath), patch('catalog.sign_release.require_trusted_root'), patch('catalog.sign_release.verify_candidate') as inspect, patch.dict('os.environ', {}, clear=True):
                sign(candidate, base/'signed', private, 'policy', 'apksigner', 'aapt2', 1, b'test')
                inspect.assert_called_once()
                r.validate_release(rootpath, base/'signed', candidate)
                with self.assertRaises(ValueError): sign(candidate, base/'signed', private, 'policy', 'apksigner', 'aapt2', 1, b'test')

    def test_url_checks(self):
        for url in ['http://example.org/a.apk','https://user@example.org/a.apk','https://example.org/a.apk#x','https://example.org/\na.apk']:
            with self.subTest(url=url), self.assertRaises(ValueError): r.validate_url(url)
        self.assertEqual(r.validate_url('https://example.org/a.apk'), 'https://example.org/a.apk')
