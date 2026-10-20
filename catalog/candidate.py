"""Build an unsigned candidate from APKs; no signing keys or network access.

Input is a directory of <packageName>.apk files obtained by the discovery job.
APK tools must be installed and reviewed on both the online and offline machines.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def applicable_signers(output, allowed):
    """Require exactly one pinned signer throughout the verified SDK range."""
    count = re.findall(r'^Number of signers: (\d+)$', output, re.M)
    if count != ['1']:
        raise ValueError('Expected exactly one APK signer')
    plain = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$', output, re.M)
    ranged = re.findall(
        r'^Signer \(minSdkVersion=(\d+), maxSdkVersion=(\d+)\) certificate SHA-256 digest: ([0-9a-fA-F]{64})$',
        output, re.M)
    if plain and ranged:
        raise ValueError('Ambiguous APK signer output')
    selected = set()
    for sdk in range(33, 38):
        matches = plain if plain else [digest for lo, hi, digest in ranged if int(lo) <= sdk <= int(hi)]
        if len(matches) != 1 or matches[0].lower() not in allowed:
            raise ValueError('Unexpected APK signer for SDK ' + str(sdk))
        selected.add(matches[0].lower())
    # Android installer policy currently permits a single current certificate.
    if len(selected) != 1:
        raise ValueError('Signer differs across supported SDK versions')
    return sorted(selected)


def inspect_apk(apk, policy, apksigner, aapt2):
    result = subprocess.run([apksigner, 'verify', '--verbose', '--print-certs',
                             '--min-sdk-version', '33', '--max-sdk-version', '37', str(apk)],
                            capture_output=True, text=True, check=True, timeout=120)
    signers = applicable_signers(result.stdout, policy['signerSha256'])
    result = subprocess.run([aapt2, 'dump', 'badging', str(apk)], capture_output=True,
                            text=True, check=True, timeout=120)
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)'", result.stdout, re.M)
    if not match or match[1] != policy['packageName'] or int(match[2]) < policy['minimumVersionCode']:
        raise ValueError('Unexpected package or obsolete version')
    with apk.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'packageName': match[1], 'versionCode': int(match[2]), 'length': apk.stat().st_size,
            'sha256': digest, 'signerSha256': signers,
            'target': f'apks/{match[1]}/{int(match[2])}/{digest}.apk'}


def build(policy_file, apks, output, apksigner, aapt2, previous=None):
    policy = json.loads(Path(policy_file).read_text())['apps']
    if len({a['packageName'] for a in policy}) != len(policy):
        raise ValueError('Duplicate policy package')
    old = {} if previous is None else {a['packageName']: a for a in json.loads(Path(previous).read_text())['apps']}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for app in policy:
        apk = Path(apks) / (app['packageName'] + '.apk')
        entry = inspect_apk(apk, app, apksigner, aapt2)
        prev = old.get(app['packageName'])
        if prev and (entry['versionCode'] < prev['versionCode'] or
                     entry['versionCode'] == prev['versionCode'] and entry['sha256'] != prev['sha256']):
            raise ValueError('Rollback or changed bytes at the same version')
        target = output / entry['target']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(apk, target)
        entries.append(entry)
    from catalog.artifacts import assign_urls
    catalog = assign_urls({'schemaVersion': 1, 'apps': entries})
    (output / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy', default='apps-policy.json')
    p.add_argument('--apks', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--apksigner', required=True)
    p.add_argument('--aapt2', required=True)
    p.add_argument('--previous')
    a = p.parse_args()
    build(a.policy, a.apks, a.output, a.apksigner, a.aapt2, a.previous)


if __name__ == '__main__':
    main()


def verify_candidate(candidate, policy_file, apksigner, aapt2):
    from catalog.release import validate_catalog
    candidate = Path(candidate)
    data = validate_catalog(json.loads((candidate / 'catalog.json').read_text()))
    policies = {a['packageName']: a for a in json.loads(Path(policy_file).read_text())['apps']}
    if set(policies) != {a['packageName'] for a in data['apps']}:
        raise ValueError('Catalog must contain exactly the approved packages')
    for app in data['apps']:
        actual = inspect_apk(candidate / app['target'], policies[app['packageName']], apksigner, aapt2)
        if actual != {k: v for k, v in app.items() if k != "url"}:
            raise ValueError('APK inspection differs from candidate metadata')
