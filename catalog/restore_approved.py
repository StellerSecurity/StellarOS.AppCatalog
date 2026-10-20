"""Recover a previously signed APK set without following upstream latest links."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from catalog import release as r
from catalog.artifacts import digest, freeze
from catalog.candidate import verify_candidate
from catalog.discover import fetch
from catalog.trust import ROOT_PATH, require_trusted_root


def extract_candidate(archive, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    prefix = 'StellarOS.AppCatalog/candidate/'
    total, seen = 0, set()
    with zipfile.ZipFile(archive) as zipped:
        if len(zipped.infolist()) > 2000:
            raise ValueError('Too many archive entries')
        for entry in zipped.infolist():
            if not entry.filename.startswith(prefix) or entry.is_dir():
                continue
            rel = PurePosixPath(entry.filename[len(prefix):])
            if rel.is_absolute() or '..' in rel.parts or '\\' in str(rel) or not rel.parts:
                raise ValueError('Unsafe candidate path')
            if str(rel) in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Duplicate or symlink candidate entry')
            seen.add(str(rel))
            total += entry.file_size
            if entry.file_size > 536870912 or total > 2 * 1024**3:
                raise ValueError('Candidate archive exceeds bounds')
            target = output.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(entry) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest)


def restore(request_file, output, apksigner, aapt2):
    require_trusted_root()
    request = json.loads(Path(request_file).read_text())
    if request['mode'] != 'preserve-approved':
        raise ValueError('Not a preservation request')
    import re
    if not re.fullmatch(r'[0-9a-f]{64}', request['archiveSha256']):
        raise ValueError('Archive SHA-256 is required')
    metadata = Path(request['metadata'])
    if metadata.is_absolute() or '..' in metadata.parts or metadata.parts[:1] != ('releases',):
        raise ValueError('Metadata must be an existing repository release')
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        archive = temp / 'kit.zip'
        fetch(request['archiveUrl'], archive, 2 * 1024**3)
        if digest(archive) != request['archiveSha256']:
            raise ValueError('Archived signing kit checksum mismatch')
        original = temp / 'original'
        extract_candidate(archive, original)
        # Authenticate the complete old APK set before changing only download URLs.
        r.validate_release(ROOT_PATH, metadata, original)
        verify_candidate(original, 'apps-policy.json', apksigner, aapt2)
        freeze(original, output)
        receipt = [{'packageName': app['packageName'], 'sourceUrl': app.get('url'),
                    'preservedFromSignedRelease': metadata.as_posix()}
                   for app in json.loads((original / 'catalog.json').read_text())['apps']]
        Path('incoming').mkdir(exist_ok=False)
        Path('incoming/download-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('request', 'output', 'apksigner', 'aapt2'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    restore(args.request, args.output, args.apksigner, args.aapt2)


if __name__ == '__main__':
    main()
