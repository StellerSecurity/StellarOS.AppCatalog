import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess
import tempfile
from catalog.candidate import inspect_apk, applicable_signers
from catalog.discover import https


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.apk = Path(self.tmp.name) / 'input.apk'
        self.apk.write_bytes(b'test fixture')
        self.policy = {'packageName': 'com.example.app', 'minimumVersionCode': 10, 'signerSha256': ['a'*64]}

    def inspect(self, signer='a'*64, package='com.example.app', version=10):
        with patch('subprocess.run', side_effect=[
            subprocess.CompletedProcess([], 0, f'Number of signers: 1\nSigner #1 certificate SHA-256 digest: {signer}\n'),
            subprocess.CompletedProcess([], 0, f"package: name='{package}' versionCode='{version}'\n")]):
            return inspect_apk(self.apk, self.policy, 'apksigner', 'aapt2')

    def test_valid(self): self.assertEqual(self.inspect()['versionCode'], 10)
    def test_wrong_signer(self):
        with self.assertRaises(ValueError): self.inspect(signer='b'*64)
    def test_wrong_package(self):
        with self.assertRaises(ValueError): self.inspect(package='com.evil.app')
    def test_old_version(self):
        with self.assertRaises(ValueError): self.inspect(version=9)
    def test_bad_signature_tool_failure(self):
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'apksigner')):
            with self.assertRaises(subprocess.CalledProcessError): inspect_apk(self.apk, self.policy, 'apksigner', 'aapt2')
    def test_url_policy(self):
        for url in ['http://example.com/a', 'https://user:pass@example.com/a', 'file:///etc/passwd', 'https:///bad']:
            with self.assertRaises(ValueError): https(url)
        self.assertEqual(https('https://example.com/app.apk'), 'https://example.com/app.apk')

class RotationTests(unittest.TestCase):
    def output(self, lo=33, hi=2147483647, current='a', old='b'):
        return ('Number of signers: 1\n'
                f'Signer (minSdkVersion={lo}, maxSdkVersion={hi}) certificate SHA-256 digest: {current*64}\n'
                f'Signer (minSdkVersion=24, maxSdkVersion=32) certificate SHA-256 digest: {old*64}\n')

    def test_current_signer(self):
        self.assertEqual(applicable_signers(self.output(), ['a'*64]), ['a'*64])

    def test_old_trusted_signer_cannot_authorize_current(self):
        with self.assertRaises(ValueError): applicable_signers(self.output(current='b', old='a'), ['a'*64])

    def test_gaps_and_missing_count(self):
        for output in [self.output(lo=34), self.output(hi=35), self.output().replace('Number of signers: 1', '')]:
            with self.assertRaises(ValueError): applicable_signers(output, ['a'*64])

    def test_multiple_or_ambiguous_signers(self):
        for output in [self.output().replace('Number of signers: 1', 'Number of signers: 2'),
                       self.output() + 'Signer #1 certificate SHA-256 digest: ' + 'a'*64 + '\n']:
            with self.assertRaises(ValueError): applicable_signers(output, ['a'*64])
