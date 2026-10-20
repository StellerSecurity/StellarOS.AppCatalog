import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from catalog import artifacts as a
from catalog.restore_approved import extract_candidate


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'original'
        self.data = b'approved fixture APK bytes'
        sha = hashlib.sha256(self.data).hexdigest()
        self.app = dict(packageName='org.example.app', versionCode=7, length=len(self.data),
                        sha256=sha, signerSha256=['a'*64], target=f'apks/org.example.app/7/{sha}.apk',
                        url='https://upstream.example/current.apk')
        self.catalog = dict(schemaVersion=1, apps=[self.app])
        self.apk = self.source / self.app['target']
        self.apk.parent.mkdir(parents=True)
        self.apk.write_bytes(self.data)
        (self.source / 'catalog.json').write_text(json.dumps(self.catalog))

    def frozen(self):
        result = self.base / 'frozen'
        a.freeze(self.source, result)
        return result

    def staged(self):
        result = self.base / 'staged'
        a.stage(self.frozen(), result)
        return result

    def test_freeze_preserves_all_identity_fields_and_original(self):
        result = self.frozen()
        changed = json.loads((result / 'catalog.json').read_text())['apps'][0]
        self.assertEqual({k:v for k,v in changed.items() if k != 'url'},
                         {k:v for k,v in self.app.items() if k != 'url'})
        self.assertEqual((result / self.app['target']).read_bytes(), self.data)
        self.assertEqual(json.loads((self.source / 'catalog.json').read_text()), self.catalog)
        self.assertNotIn('current', changed['url'])
        a.require_frozen_urls(dict(schemaVersion=1, apps=[changed]))

    def test_upstream_new_version_cannot_change_frozen_bytes(self):
        frozen = self.frozen()
        url = json.loads((frozen / 'catalog.json').read_text())['apps'][0]['url']
        self.apk.write_bytes(b'new upstream version')
        staged = self.base / 'staged'
        a.stage(frozen, staged)
        self.assertEqual((staged / a.asset_name(self.app)).read_bytes(), self.data)
        self.assertEqual(json.loads((staged / 'catalog.json').read_text())['apps'][0]['url'], url)

    def test_reject_changed_bytes_before_creating_destination(self):
        self.apk.write_bytes(b'x' * len(self.data))
        output = self.base / 'bad'
        with self.assertRaises(ValueError): a.freeze(self.source, output)
        self.assertFalse(output.exists())

    def test_never_overwrite_frozen_candidate(self):
        frozen = self.frozen()
        with self.assertRaises(FileExistsError): a.freeze(self.source, frozen)

    def test_signing_requires_hash_named_url_but_allows_future_host_change(self):
        with self.assertRaises(ValueError): a.require_frozen_urls(self.catalog)
        c = a.assign_urls(copy.deepcopy(self.catalog))
        c['apps'][0]['url'] = 'https://another.example/archive/' + a.asset_name(self.app)
        a.require_frozen_urls(c)
        with self.assertRaises(ValueError): a.require_github_urls(c)
        c['apps'][0]['url'] += '?latest=true'
        with self.assertRaises(ValueError): a.require_frozen_urls(c)

    def test_collection_tag_changes_with_version_not_source_url_or_order(self):
        c = copy.deepcopy(self.catalog)
        tag = a.release_tag(c)
        c['apps'][0]['url'] = 'https://changed.example/new'
        self.assertEqual(a.release_tag(c), tag)
        c['apps'][0]['versionCode'] += 1
        self.assertNotEqual(a.release_tag(c), tag)

    def test_symlink_outside_candidate_rejected(self):
        external = self.base / 'outside.apk'
        external.write_bytes(self.data)
        self.apk.unlink()
        self.apk.symlink_to(external)
        with self.assertRaises(ValueError): a.freeze(self.source, self.base / 'bad')

    def run_publish(self, staged, release, corrupt_download=False):
        calls = []
        def fake(*args):
            calls.append(args)
            if args[0] == 'api':
                if release is None:
                    raise subprocess.CalledProcessError(1, ['gh'], stderr='gh: Not Found (HTTP 404)')
                return json.dumps(release)
            if args[:2] == ('release', 'download'):
                directory = Path(args[args.index('--dir') + 1])
                (directory / a.asset_name(self.app)).write_bytes(b'tampered' if corrupt_download else self.data)
            return ''
        with patch('catalog.artifacts.gh', side_effect=fake):
            a.publish(staged, 'a'*40)
        return calls

    def test_new_release_downloads_and_verifies_before_publication(self):
        calls = self.run_publish(self.staged(), None)
        commands = [c[:2] for c in calls]
        self.assertLess(commands.index(('release', 'download')), commands.index(('release', 'edit')))
        self.assertFalse(any('--clobber' in c for c in calls))

    def test_existing_release_is_only_read_and_verified(self):
        calls = self.run_publish(self.staged(), {'draft':False, 'assets':[{'name':a.asset_name(self.app)}]})
        self.assertFalse(any(c[:2] in [('release','edit'), ('release','upload'), ('release','create')] for c in calls))

    def test_published_missing_asset_is_not_modified(self):
        with self.assertRaises(ValueError): self.run_publish(self.staged(), {'draft':False,'assets':[]})

    def test_corrupted_remote_asset_cannot_be_published(self):
        with self.assertRaises(ValueError): self.run_publish(self.staged(), None, corrupt_download=True)

    def test_zip_traversal_rejected(self):
        for number, name in enumerate(['../escape.apk', '/absolute.apk', 'a\\b.apk']):
            archive = self.base / f'bad{number}.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('StellarOS.AppCatalog/candidate/' + name, b'bad')
            with self.assertRaises(ValueError): extract_candidate(archive, self.base / f'out{number}')

    def test_zip_duplicate_entries_rejected(self):
        import warnings
        archive = self.base / 'duplicate.zip'
        with zipfile.ZipFile(archive, 'w') as z, warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            for _ in range(2):
                z.writestr('StellarOS.AppCatalog/candidate/catalog.json', b'{}')
        with self.assertRaises(ValueError): extract_candidate(archive, self.base / 'duplicate-output')

    def test_zip_ignores_executable_tools_and_extracts_only_candidate(self):
        archive = self.base / 'kit.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('StellarOS.AppCatalog/catalog/untrusted.py', b'not executed')
            z.writestr('StellarOS.AppCatalog/candidate/catalog.json', b'{}')
        output = self.base / 'restored'
        extract_candidate(archive, output)
        self.assertEqual([p.name for p in output.iterdir()], ['catalog.json'])
