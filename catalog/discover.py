"""Fetch untrusted upstream candidates. APK verification happens in candidate.py."""
import argparse
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

MAX_APK = 1024 * 1024 * 1024
MAX_METADATA = 32 * 1024 * 1024


def https(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('Only credential-free HTTPS URLs are allowed')
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, https(newurl))


def fetch(url, destination=None, limit=MAX_METADATA):
    opener = urllib.request.build_opener(Redirects())
    req = urllib.request.Request(https(url), headers={'User-Agent': 'App Installer 0.1'})
    with opener.open(req, timeout=60) as response:
        https(response.url)
        size = 0
        chunks = []
        file = None if destination is None else Path(destination).open('xb')
        try:
            while data := response.read(1024 * 1024):
                size += len(data)
                if size > limit:
                    raise ValueError('Upstream response exceeds size limit')
                if file is None: chunks.append(data)
                else: file.write(data)
        finally:
            if file is not None: file.close()
        return b''.join(chunks), response.url


def resolve(source):
    kind = source['type']
    if kind == 'direct': return https(source['url'])
    if kind == 'signal': return https(json.loads(fetch('https://updates.signal.org/android/latest.json')[0])['url'])
    if kind == 'github':
        data = json.loads(fetch(f"https://api.github.com/repos/{source['repo']}/releases/latest")[0])
        if data['draft'] or data['prerelease']: raise ValueError('Unstable release')
        assets = [a['browser_download_url'] for a in data['assets'] if re.fullmatch(source['assetRegex'], a['name'])]
        if len(assets) != 1: raise ValueError('Expected exactly one release asset')
        return https(assets[0])
    if kind == 'fdroid':
        pkg = source['packageName']
        data = fetch(f'https://f-droid.org/en/packages/{pkg}/')[0].decode()
        matches = re.findall(re.escape(pkg) + r'_\d+\.apk', data)
        if not matches: raise ValueError('No APK in F-Droid listing')
        # Follow the channel listing, like Lupin; signed package/version checks follow.
        return 'https://f-droid.org/repo/' + matches[0]
    if kind == 'izzy':
        data = json.loads(fetch('https://apt.izzysoft.de/fdroid/repo/index-v1.json')[0])
        item = max(data['packages'][source['packageName']], key=lambda x: x['versionCode'])
        name = item['apkName']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.apk', name): raise ValueError('Invalid APK filename')
        return 'https://apt.izzysoft.de/fdroid/repo/' + name
    raise ValueError('Unknown source')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', default='sources.json')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = []
    for app in json.loads(Path(args.sources).read_text())['apps']:
        pkg = app['packageName']
        if not re.fullmatch(r'[A-Za-z0-9_.]+', pkg): raise ValueError('Invalid package')
        url = resolve(app['source'])
        _, resolved = fetch(url, output / (pkg + '.apk'), MAX_APK)
        receipt.append({'packageName': pkg, 'sourceUrl': url, 'resolvedUrl': resolved})
    (output / 'download-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__': main()
