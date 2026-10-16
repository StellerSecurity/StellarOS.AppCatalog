# StellarOS.AppCatalog

Offline-signed application catalog for StellarOS Lupin. GitHub prepares candidates;
Azure Blob Storage serves approved files. Neither service holds signing keys.

**Status: release tooling and reference-client tests. Not activated in Lupin.**
Production root keys, Azure destination and Android TUF client integration are still
required. There is deliberately no bundled production root or unsigned fallback.

## Trust model

- Standard TUF root, targets, snapshot and timestamp metadata, using python-tuf.
- Three independently held offline Ed25519 keys; two signatures required for every
  role in this initial small-team profile. Losing one key is insufficient to sign.
- All roles are offline-signed, including timestamp. Default lifetimes: root 365 days,
  targets/snapshot 30 days, timestamp 7 days. Renew before expiry; no online signer.
- The signed catalog identifies package name, actual APK version, length, complete
  APK SHA-256, signer fingerprints and immutable content-addressed target path.
- Each offline targets signer re-inspects APK signatures with Android apksigner and
  package/version with aapt2 before signing. Review tools and policy independently.
- Android must keep its own certificate pins: catalog metadata cannot replace them.
- GitHub Actions only tests and prepares unsigned candidates. It cannot sign.

Read [the offline release procedure](docs/OFFLINE-RELEASE.md) and
[Azure publishing and Android activation](docs/DEPLOYMENT.md).

## Development

Python 3.12, Linux x86-64:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.lock
python -m unittest discover -s tests -v
```

The lock file pins the Linux/Python 3.12 wheels used for CI and the offline signing
kit. Re-lock deliberately for another platform. Test keys exist only in temporary
memory/directories and are not production keys.

Nine configured channels: WhatsApp, Signal, Molly, Session, SimpleX, F-Droid Basic,
Aurora, Threema Libre and Briar. Source discovery is untrusted; certificate/package
checks follow. Pins were imported from the current Lupin allowlist and still need
an independent release review. Android signature validity is not a malware audit.

APK artifacts are not committed to Git. Confirm redistribution permission before
mirroring an app to Azure. Mutable upstream `latest` URLs are only used for discovery;
phones must fetch the immutable bytes approved in the signed release.

## Limitations before production

- No production key ceremony has taken place.
- No cloud resources have been provisioned or published.
- Lupin's current device build is not yet a TUF client.
- Root rotation is supported by TUF but the release CLI currently initializes only
  root version 1. A reviewed rotation command and recovery rehearsal are required
  before production activation.
- Offline signing does not prove a candidate is benign. Two independent custodians
  must check upstream provenance, signer pins, versions and changes.
- A newly reset phone needs a trusted build-time metadata baseline and sufficiently
  trustworthy time to limit replay/freeze attacks. Persisted client state protects
  subsequent updates; it is not preserved by a factory reset.
