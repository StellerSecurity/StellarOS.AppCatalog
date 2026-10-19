# Signing a release

This guide describes the **two-of-three Ed25519 signing profile**.
Three independent custodians hold one key each; any two approve each metadata role.
Keep each custodian’s key under separate custody.

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

## 3. Create one key per custodian

Each custodian independently sets a directory on their own offline storage:

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
  --public custodian-public.json
```

The command prompts twice for a non-empty password and refuses to
overwrite existing key files. Keep the private key and its secure backup outside
Git, cloud storage and CI. Store the password separately. Exchange only public JSON
files, named `alice.json`, `bob.json` and `carol.json`, and independently confirm
which key belongs to each custodian.

### Encrypted drives and hardware tokens

An encrypted USB drive can protect the key file while locked. During signing, this
CLI reads and decrypts the file in the computer's memory. Unlocking such a drive on
a compromised computer can expose the key. Lock and disconnect it after use.
The commands in this guide use encrypted Ed25519 key files. Review the content being
signed independently of how the key is stored.

## 4. Establish the trusted root

On an offline machine, assemble the three reviewed public keys:

```bash
.venv/bin/python -m catalog.release init-root \
  --public alice.json bob.json carol.json --output root.json
```

Two custodians review the keys, role thresholds, version and expiry. Each runs the
following on their own machine, passing the **same root file sequentially** between
them. The second signature is appended; do not create separate root files.

```bash
.venv/bin/python -m catalog.release sign root.json \
  --private "$SIGNING_DIR/catalog-key.pem"
```

After both signatures:

```bash
sha256sum root.json
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
`root.json`, `apps-policy.json`, and the reviewed Android tools. Each signer sets:

```bash
APKSIGNER='/opt/android-build-tools/apksigner'
AAPT2='/opt/android-build-tools/aapt2'
```

## 6. Sign the metadata in order

These are **first-release** commands. Use higher version numbers for subsequent
releases and renewals. Prepare each role once, then obtain both signatures before
preparing the next role. Re-running preparation replaces that role's signatures.

Prepare targets:

```bash
.venv/bin/python -m catalog.release prepare-targets \
  --candidate candidate --version 1 --output metadata/targets.json
```

Each of two custodians runs this on the same targets file, sequentially. The command
re-inspects the actual APKs against the local policy before signing:

```bash
.venv/bin/python -m catalog.release sign metadata/targets.json \
  --private "$SIGNING_DIR/catalog-key.pem" --candidate candidate \
  --policy apps-policy.json --apksigner "$APKSIGNER" --aapt2 "$AAPT2"
```

After both targets signatures, prepare snapshot:

```bash
.venv/bin/python -m catalog.release prepare-snapshot \
  --root root.json --input metadata/targets.json \
  --version 1 --output metadata/snapshot.json
```

Each of two custodians signs the same snapshot sequentially:

```bash
.venv/bin/python -m catalog.release sign metadata/snapshot.json \
  --private "$SIGNING_DIR/catalog-key.pem"
```

After both snapshot signatures, prepare timestamp:

```bash
.venv/bin/python -m catalog.release prepare-timestamp \
  --root root.json --input metadata/snapshot.json \
  --version 1 --output metadata/timestamp.json
```

Each of two custodians signs the same timestamp sequentially:

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
