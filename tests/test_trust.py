import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from catalog.trust import require_trusted_root, ROOT_PATH
from catalog.publish import publish

class TrustTests(unittest.TestCase):
    def test_approved_root(self):
        self.assertEqual(require_trusted_root(), ROOT_PATH.read_bytes())

    def test_substitution_rejected_before_network(self):
        original = ROOT_PATH.read_bytes()
        for bad in (b"", original[:-1], original + b"\n", original.replace(b"2031", b"2032")):
            with self.subTest(size=len(bad)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "root.json"
                root.write_bytes(bad)
                with patch("catalog.publish.az") as network:
                    with self.assertRaises(ValueError):
                        publish(root, "unused", "unused", "unused", "unused")
                    network.assert_not_called()
