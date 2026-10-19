"""Export only verified catalog metadata to Azure Static Web Apps Free.

APKs remain at the separately configured HTTPS artifact origin. This command does
not upload files, sign metadata, or select an untrusted root.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from catalog.release import export


def build(root, metadata, candidate, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Output must not exist')
    with tempfile.TemporaryDirectory() as temporary:
        full = Path(temporary) / 'verified'
        export(root, metadata, candidate, full)
        output.mkdir(parents=True)
        shutil.copytree(full / 'metadata', output / 'metadata')
        (output / 'targets').mkdir()
        for path in (full / 'targets').glob('*.catalog.json'):
            shutil.copyfile(path, output / 'targets' / path.name)
    (output / 'index.html').write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<title>StellarOS App Catalog</title><h1>StellarOS App Catalog</h1>'
        '<p>Offline-signed application release metadata.</p></html>\n')
    (output / 'staticwebapp.config.json').write_text(json.dumps({
        'globalHeaders': {'X-Content-Type-Options': 'nosniff',
                          'Cache-Control': 'no-cache, max-age=0, must-revalidate'},
        'mimeTypes': {'.json': 'application/json'},
        'routes': [{'route': '/metadata/timestamp.json', 'headers': {
            'Cache-Control': 'no-store, max-age=0'}}]
    }, indent=2) + '\n')
    size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    if size > 100 * 1024 * 1024:
        raise ValueError('Metadata site exceeds conservative 100 MiB budget')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'metadata', 'candidate', 'output'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    from catalog.trust import require_trusted_root
    require_trusted_root(a.root)
    build(a.root, a.metadata, a.candidate, a.output)


if __name__ == '__main__': main()
