"""Preserve exact candidate APKs as versioned GitHub release assets.

This does not sign or deploy catalog metadata. Existing assets are never replaced.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from catalog.release import validate_catalog

REPOSITORY = 'StellerSecurity/StellarOS.AppCatalog'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def asset_name(app):
    return f"{app['packageName']}-{app['versionCode']}-{app['sha256']}.apk"


def release_tag(catalog):
    # URL changes do not change the identity of the APK collection.
    identity = [{k: app[k] for k in ('packageName', 'versionCode', 'sha256', 'length')}
                for app in sorted(catalog['apps'], key=lambda app: app['packageName'])]
    payload = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
    return 'catalog-apks-' + hashlib.sha256(payload).hexdigest()


def assign_urls(catalog):
    validate_catalog(catalog)
    tag = release_tag(catalog)
    for app in catalog['apps']:
        app['url'] = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{asset_name(app)}'
    return catalog


def require_frozen_urls(catalog):
    from urllib.parse import urlsplit
    from catalog.release import validate_url
    validate_catalog(catalog)
    for app in catalog['apps']:
        url = urlsplit(validate_url(app.get('url', '')))
        if url.query or not url.path.endswith('/' + asset_name(app)):
            raise ValueError('APK must use its preserved release URL: ' + app['packageName'])


def require_github_urls(catalog):
    require_frozen_urls(catalog)
    tag = release_tag(catalog)
    for app in catalog['apps']:
        expected = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{asset_name(app)}'
        if app['url'] != expected:
            raise ValueError('GitHub publisher does not match catalog destination')


def checked_files(candidate, catalog):
    """Validate the complete set before copying or publishing anything."""
    candidate = Path(candidate).resolve()
    validate_catalog(catalog)
    files = []
    for app in catalog['apps']:
        path = candidate / app['target']
        if not path.resolve().is_relative_to(candidate) or path.is_symlink():
            raise ValueError('APK must be a regular file inside candidate')
        if not path.is_file() or path.stat().st_size != app['length'] or digest(path) != app['sha256']:
            raise ValueError('Preserved APK differs from catalog: ' + app['packageName'])
        files.append((app, path))
    return files


def freeze(candidate, output):
    candidate, output = Path(candidate), Path(output)
    catalog = json.loads((candidate / 'catalog.json').read_text())
    files = checked_files(candidate, catalog)
    assign_urls(catalog)
    output.mkdir(parents=True, exist_ok=False)
    for app, source in files:
        dest = output / app['target']
        dest.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as inp, dest.open('xb') as out:
            shutil.copyfileobj(inp, out)
    (output / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')


def stage(candidate, output):
    candidate, output = Path(candidate), Path(output)
    catalog = json.loads((candidate / 'catalog.json').read_text())
    require_github_urls(catalog)
    files = checked_files(candidate, catalog)
    output.mkdir(parents=True, exist_ok=False)
    for app, source in files:
        with source.open('rb') as inp, (output / asset_name(app)).open('xb') as out:
            shutil.copyfileobj(inp, out)
    (output / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')


def gh(*args):
    return subprocess.run(['gh', *args], capture_output=True, text=True,
                          check=True, timeout=900).stdout


def check_downloads(folder, catalog):
    for app in catalog['apps']:
        path = Path(folder) / asset_name(app)
        if path.stat().st_size != app['length'] or digest(path) != app['sha256']:
            raise ValueError('Published asset differs: ' + app['packageName'])


def publish(staged, commit):
    import re
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('An exact source commit is required')
    staged = Path(staged)
    catalog = json.loads((staged / 'catalog.json').read_text())
    require_github_urls(catalog)
    check_downloads(staged, catalog)
    tag = release_tag(catalog)
    try:
        existing = json.loads(gh('api', f'repos/{REPOSITORY}/releases/tags/{tag}'))
    except subprocess.CalledProcessError as error:
        if '(HTTP 404)' not in error.stderr:
            raise
        existing = None
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        if existing is None:
            notes = temp / 'notes.txt'
            notes.write_text('Preserved APK bytes for offline catalog review. Publishing these assets does not approve an OS catalog release. Clients require the separately offline-signed catalog and APK certificate checks.\n')
            gh('release', 'create', tag, '--repo', REPOSITORY, '--target', commit,
               '--draft', '--prerelease', '--title', 'Preserved app catalog APKs', '--notes-file', str(notes))
            existing = {'draft': True, 'assets': []}
        expected = {asset_name(app) for app in catalog['apps']}
        present = {asset['name'] for asset in existing['assets']}
        if not present.issubset(expected):
            raise ValueError('Unexpected assets in preserved release')
        missing = expected - present
        if missing:
            if not existing['draft']:
                raise ValueError('Published release is incomplete; refusing to change it')
            # Deliberately no --clobber. A retry may add missing draft assets only.
            gh('release', 'upload', tag, '--repo', REPOSITORY,
               *[str(staged / name) for name in sorted(missing)])
        downloaded = temp / 'downloaded'
        downloaded.mkdir()
        gh('release', 'download', tag, '--repo', REPOSITORY, '--dir', str(downloaded), '--pattern', '*.apk')
        check_downloads(downloaded, catalog)
        if existing['draft']:
            gh('release', 'edit', tag, '--repo', REPOSITORY, '--draft=false', '--prerelease', '--latest=false')
    print('Preserved and verified APK release:', tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('freeze', 'stage'):
        sub = commands.add_parser(name)
        sub.add_argument('--candidate', required=True)
        sub.add_argument('--output', required=True)
    sub = commands.add_parser('publish')
    sub.add_argument('--staged', required=True)
    sub.add_argument('--commit', required=True)
    args = parser.parse_args()
    if args.command == 'publish':
        publish(args.staged, args.commit)
    else:
        {'freeze': freeze, 'stage': stage}[args.command](args.candidate, args.output)


if __name__ == '__main__':
    main()
