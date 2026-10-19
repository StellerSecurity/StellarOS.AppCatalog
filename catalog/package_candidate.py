"""Package an unsigned candidate and reviewed signing tools for offline transfer."""
import hashlib
from pathlib import Path
import zipfile


def main():
    output = Path('downloads')
    output.mkdir(exist_ok=True)
    archive = output / 'StellarOS-AppCatalog-signing-kit.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED) as z:
        files = [Path('README.md'), Path('requirements.txt'), Path('requirements.lock'),
                 Path('apps-policy.json'), Path('sources.json')]
        for folder in ('catalog', 'docs', 'trust', 'candidate'):
            files.extend(p for p in Path(folder).rglob('*') if p.is_file()
                         and '__pycache__' not in p.parts and p.suffix != '.pyc')
        for path in sorted(files):
            if path.is_symlink() or path.suffix in {'.pem', '.key', '.p12', '.jks'}:
                raise ValueError('Unexpected file in signing kit')
            z.write(path, 'StellarOS.AppCatalog/' + path.as_posix())
        z.write('incoming/download-receipt.json', 'StellarOS.AppCatalog/download-receipt.json')
    with archive.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    (output / 'SHA256SUMS').write_text(digest + '  ' + archive.name + '\n')
    (output / 'SIGNING.txt').write_text(
        'Extract StellarOS-AppCatalog-signing-kit.zip and open StellarOS.AppCatalog/docs/OFFLINE-RELEASE.md.\n'
        'The ZIP contains APKs, catalog, public root, Python signing tools and instructions.\n'
        'Prepare Python 3.12 and platform-native Android build-tools before disconnecting.\n'
        'Sign offline with your existing encrypted private key. No key is included in this download.\n'
        'This unsigned candidate is for review and offline signing, not deployment.\n')


if __name__ == '__main__': main()
