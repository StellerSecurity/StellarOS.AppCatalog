import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from catalog.package_candidate import main

class PackageTests(unittest.TestCase):
    def test_kit_contains_candidate_and_tools_not_private_key(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                for name in ['README.md','requirements.txt','requirements.lock','apps-policy.json','sources.json','catalog/sign_release.py','docs/OFFLINE-RELEASE.md','trust/root.json','candidate/catalog.json','candidate/apks/test.apk','incoming/download-receipt.json']:
                    p=Path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('test')
                Path('private.pem').write_text('must not be packaged')
                main()
                path=Path('downloads/StellarOS-AppCatalog-signing-kit.zip')
                with zipfile.ZipFile(path) as z:
                    self.assertIn('StellarOS.AppCatalog/candidate/apks/test.apk',z.namelist())
                    self.assertIn('StellarOS.AppCatalog/catalog/sign_release.py',z.namelist())
                    self.assertFalse(any(n.endswith('.pem') for n in z.namelist()))
                self.assertEqual(Path('downloads/SHA256SUMS').read_text().split()[0], hashlib.sha256(path.read_bytes()).hexdigest())
            finally: os.chdir(previous)
