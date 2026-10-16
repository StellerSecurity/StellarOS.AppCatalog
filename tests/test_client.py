from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
import test_release
from catalog import release as r
from catalog.client_check import check


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


class ClientTests(unittest.TestCase):
    setUp = test_release.ReleaseTests.setUp
    sign = test_release.ReleaseTests.sign
    def test_official_client_accepts_release_then_rejects_rollback(self):
        # Real TUF client against a local HTTP server; production CLI requires HTTPS.
        self.targets.signed.version = 2
        self.sign(self.targets)
        r.write(self.targets, self.metadata / 'targets.json')
        self.snapshot = r.prepare_snapshot(self.rootpath, self.metadata / 'targets.json', 2, self.snapshot.signed.expires)
        self.sign(self.snapshot)
        r.write(self.snapshot, self.metadata / 'snapshot.json')
        self.timestamp = r.prepare_timestamp(self.rootpath, self.metadata / 'snapshot.json', 2, self.timestamp.signed.expires)
        self.sign(self.timestamp)
        r.write(self.timestamp, self.metadata / 'timestamp.json')
        output = self.base / 'export'
        r.export(self.rootpath, self.metadata, self.candidate, output)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(output)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}/'
        data = check(self.rootpath, self.base / 'client', base+'metadata/', base+'targets/')
        self.assertEqual(data['apps'][0]['packageName'], 'test.stellar.app')
        self.timestamp.signed.version = 1
        self.sign(self.timestamp)
        r.write(self.timestamp, output / 'metadata/timestamp.json')
        with self.assertRaises(Exception):
            check(self.rootpath, self.base / 'client', base+'metadata/', base+'targets/')
