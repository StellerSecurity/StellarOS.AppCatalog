import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from catalog import release


class KeygenTests(unittest.TestCase):
    def run_keygen(self, directory, answers):
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', [
            'release', 'keygen', '--private', str(directory / 'key.pem'),
            '--public', str(directory / 'public.json'),
        ]), patch('getpass.getpass', side_effect=answers):
            release.main()

    def test_short_password_still_encrypts_private_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.run_keygen(directory, ['abc', 'abc'])
            pem = (directory / 'key.pem').read_bytes()
            serialization.load_pem_private_key(pem, b'abc')
            with self.assertRaises((ValueError, TypeError)):
                serialization.load_pem_private_key(pem, None)
            with self.assertRaises(FileExistsError):
                self.run_keygen(directory, ['abc', 'abc'])
            self.assertEqual(pem, (directory / 'key.pem').read_bytes())

    def test_empty_and_mismatched_passwords_create_no_files(self):
        for answers in [[''], ['abc', 'different']]:
            with self.subTest(answers=answers), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    self.run_keygen(directory, answers)
                self.assertEqual(list(directory.iterdir()), [])
