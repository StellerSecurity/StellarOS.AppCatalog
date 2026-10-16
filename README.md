# StellarOS App Catalog

Release tooling for the application catalog used by StellarOS's Lupin installer.
It prepares APK candidates, records their hashes and identities, and produces
metadata signed by offline release maintainers using The Update Framework (TUF).

**Development status:** signing and verification tooling is available. Production
signing keys and the Android TUF integration are not configured, and no signed
production catalog has been published. The HTTPS catalog host is provisioned at
[stellarosappcatalog.stellarsecurity.com](https://stellarosappcatalog.stellarsecurity.com).

## Documentation

- [Signing a release](docs/OFFLINE-RELEASE.md): prerequisites, key creation, signatures and renewal.
- [Publishing and client integration](docs/DEPLOYMENT.md): hosting layout and activation requirements.

## How it works

1. Fetch unsigned candidates from the configured upstream release channels.
2. Inspect each APK's package, version and signing certificate; calculate its exact SHA-256 and length.
3. Have two independent maintainers review and sign the release offline.
4. Publish approved metadata and immutable artifacts. Clients must verify the metadata,
   APK bytes and independently pinned APK signing certificates before installation.

The current signing profile uses three Ed25519 keys and requires two signatures
for each TUF role. GitHub Actions prepares candidates and runs tests; it does not
hold signing keys or approve releases. A valid signature authenticates a release,
not whether an application is free of malicious behavior.

## Configured applications

WhatsApp, Signal, Molly, Session, SimpleX, F-Droid Basic, Aurora Store, Threema Libre
and Briar. Release sources are defined in `sources.json`; package identities,
minimum versions and allowed APK signing certificates are in `apps-policy.json`.
These policies require independent review before production use. Upstream updates
become candidates, not automatically approved releases.

## Development

The dependency lock targets Python 3.12 on Linux x86-64. On Ubuntu 24.04, install
the prerequisites before creating the environment:

```bash
sudo apt update && sudo apt install python3.12-venv git
git clone https://github.com/StellerSecurity/StellarOS.AppCatalog.git
cd StellarOS.AppCatalog
python3.12 -m venv .venv &&
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary test keys. Never use those keys for production, commit private
keys or APK binaries, or put signing passwords in scripts or GitHub secrets.

## Current boundaries

- The CLI supports encrypted Ed25519 key files; hardware-token signing is not implemented.
- Root initialization supports version 1. A reviewed rotation/recovery procedure is
  required before production activation.
- All metadata roles are signed offline. The default timestamp expires after seven
  days, so releases require regular renewal even when no apps change.
- Android verification and deployment integration must be qualified before enabling
  this catalog in Lupin. See the deployment guide for the acceptance criteria.
