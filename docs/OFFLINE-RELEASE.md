# Signing a release

This guide uses **one offline Ed25519 signing key**.
The same key signs root, targets, snapshot and timestamp metadata.
Keep the private key and a secure backup outside the repository.

Commands run from the repository root on Linux x86-64 with Python 3.12. Paths such
as `/media/USER/SIGNING` and `/opt/android-build-tools` are examples: replace them
with verified locations. Stop on any command failure.

## 1. Prepare dependencies while online

On Ubuntu 24.04:

```bash
sudo apt update && sudo apt install python3.12-venv git
```

From a reviewed checkout:

```bash
python3.12 -m venv .venv &&
.venv/bin/python -m pip download --require-hashes -r requirements.lock -d wheels
```

If Python reports `No module named pip` or `ensurepip is not available`, install
`python3.12-venv` and recreate `.venv` before continuing. Use `.venv/bin/python -m pip`,
not the system Python's pip.

Prepare each signing machine with Python 3.12 and venv support before disconnecting
it. Transfer reviewed source, `requirements.lock`, `wheels/`, Android build-tools
(`apksigner`, `aapt2` and their Java/runtime dependencies), and the release candidate
using removable media. The wheel lock is platform-specific; other platforms require
a separately reviewed lock.

## 2. Install on the offline signing machine

Disconnect the signing machine from all networks. From the transferred checkout:

```bash
python3.12 -m venv .venv &&
.venv/bin/python -m pip install --no-index --find-links wheels \
  --require-hashes -r requirements.lock
```

The signing CLI performs no network requests, but that alone does not make its host
offline. A temporarily disconnected everyday computer is not equivalent to a
machine reserved for offline signing.

## 3. Create the catalog signing key

Set a directory on your offline signing storage:

```bash
umask 077
SIGNING_DIR='/media/USER/SIGNING/catalog-keys'
```

Verify that the intended encrypted drive is actually mounted and unlocked before
creating the directory. Do not use an example path unchanged or allow it to resolve
to the computer's internal drive.

```bash
mkdir -p "$SIGNING_DIR" &&
.venv/bin/python -m catalog.release keygen \
  --private "$SIGNING_DIR/catalog-key.pem" \
  --public catalog-public.json
```

The command prompts twice for a non-empty password and refuses to
overwrite existing key files. Keep the private key and its secure backup outside
Git, cloud storage and CI. Store the password separately. Share only `catalog-public.json`; never share the private PEM or its password.

### Encrypted drives and hardware tokens

An encrypted USB drive can protect the key file while locked. During signing, this
CLI reads and decrypts the file in the computer's memory. Unlocking such a drive on
a compromised computer can expose the key. Lock and disconnect it after use.
The commands in this guide use encrypted Ed25519 key files. Review the content being
signed independently of how the key is stored.

## 4. Establish the trusted root

On an offline machine, initialize the root with your reviewed public key:

```bash
.venv/bin/python -m catalog.release init-root \
  --public catalog-public.json --output root.json
```

Review the public key, version and expiry, then sign the root once:

```bash
.venv/bin/python -m catalog.release sign root.json \
  --private "$SIGNING_DIR/catalog-key.pem"
```

After signing:

```bash
shasum -a 256 root.json
```

Record that exact file hash through an independent trusted channel. Only the public,
signed root goes into `trust/root.json` and the reviewed OS build. A hash obtained
from the same untrusted download as the root is not an independent trust anchor.

## 5. Review the unsigned candidate

The manual GitHub Actions candidate workflow produces untrusted APKs and metadata.
Review their upstream provenance, package identities, signer pins and versions.
On releases after the first, compare against the last accepted catalog using
`catalog.candidate --previous`; do not accept lower versions or changed bytes at the
same version. Do not change signer policy merely to make a failed check pass.

The following steps expect `candidate/catalog.json` and its APK target files,
`root.json`, `apps-policy.json`, and the reviewed Android tools. Set:

```bash
APKSIGNER='/opt/android-build-tools/apksigner'
AAPT2='/opt/android-build-tools/aapt2'
```

## 6. Sign the metadata in order

These are **first-release** commands. Use higher version numbers for subsequent
releases and renewals. Prepare each role once, then sign it once before
preparing the next role. Re-running preparation replaces that role's signatures.

Prepare targets:

```bash
.venv/bin/python -m catalog.release prepare-targets \
  --candidate candidate --version 1 --output metadata/targets.json
```

Sign targets once. The command re-inspects the actual APKs against the local policy before signing:

```bash
.venv/bin/python -m catalog.release sign metadata/targets.json \
  --private "$SIGNING_DIR/catalog-key.pem" --candidate candidate \
  --policy apps-policy.json --apksigner "$APKSIGNER" --aapt2 "$AAPT2"
```

After signing targets, prepare snapshot:

```bash
.venv/bin/python -m catalog.release prepare-snapshot \
  --root root.json --input metadata/targets.json \
  --version 1 --output metadata/snapshot.json
```

Sign snapshot:

```bash
.venv/bin/python -m catalog.release sign metadata/snapshot.json \
  --private "$SIGNING_DIR/catalog-key.pem"
```

After signing snapshot, prepare timestamp:

```bash
.venv/bin/python -m catalog.release prepare-timestamp \
  --root root.json --input metadata/snapshot.json \
  --version 1 --output metadata/timestamp.json
```

Sign timestamp:

```bash
.venv/bin/python -m catalog.release sign metadata/timestamp.json \
  --private "$SIGNING_DIR/catalog-key.pem"
```

## 7. Verify and export

```bash
.venv/bin/python -m catalog.release verify \
  --root root.json --metadata metadata --candidate candidate &&
.venv/bin/python -m catalog.release export \
  --root root.json --metadata metadata --candidate candidate --output dist/release-1
```

The output directory must not already exist. Verification checks signature thresholds,
expiry, metadata links and all target bytes. Copy only approved public release files
back online for [publication](DEPLOYMENT.md). Never transfer private keys with them.

## Renewal and recovery

Default lifetimes are 365 days for root, 30 days for targets/snapshot, and seven days
for timestamp. Renew before the earliest expiry, repeating steps 6–7 with increasing
versions for targets, snapshot and timestamp even if APKs are unchanged. Never edit
signed files: later roles authenticate their exact bytes. Expired metadata must cause
a client error, not an unsigned fallback.

Use `init-root` only to establish the initial version-1 root. For an established
catalog, follow a separately reviewed TUF root-rotation and recovery procedure;
never replace the existing trust anchor with a newly initialized root.
