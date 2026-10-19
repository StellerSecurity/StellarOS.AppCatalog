import unittest
import test_release
from catalog.static_site import build

class StaticSiteTests(unittest.TestCase):
    setUp = test_release.ReleaseTests.setUp
    sign = test_release.ReleaseTests.sign

    def test_exports_signed_metadata_but_no_apks(self):
        output = self.base / 'site'
        build(self.rootpath, self.metadata, self.candidate, output)
        self.assertEqual((output / 'metadata/timestamp.json').read_bytes(),
                         (self.metadata / 'timestamp.json').read_bytes())
        self.assertEqual(len(list((output / 'targets').glob('*.catalog.json'))), 1)
        self.assertFalse(list(output.rglob('*.apk')))

    def test_corrupt_release_is_not_exported(self):
        self.apk.write_bytes(b'changed')
        output = self.base / 'site'
        with self.assertRaises(ValueError):
            build(self.rootpath, self.metadata, self.candidate, output)
        self.assertFalse(output.exists())
