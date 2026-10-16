# Publishing and client integration

## Catalog hosting

The catalog endpoint is
[stellarosappcatalog.stellarsecurity.com](https://stellarosappcatalog.stellarsecurity.com).
The hosting configuration uses Azure Static Web Apps Free with a custom HTTPS domain.

Serve signed metadata and the catalog from the static site. Configure a separate
HTTPS origin for APK artifacts, using immutable paths matching the signed target
hashes. Verify the complete download flow and redistribution rights before mirroring
third-party APKs.

No private signing keys belong in Azure or GitHub. Deployment credentials must only
permit publishing approved public files. Independently pin the trusted root, verify
all signatures and artifact hashes before deployment, and preserve previous immutable
objects for clients already downloading a release. Publish the timestamp only after
its referenced metadata and artifacts are available.

## Azure Blob publication

`catalog.publish` publishes a complete signed repository to an existing Azure Blob
container. Configure and test the destination first, and provide an already signed
release. This command targets Azure Blob Storage.

With Azure CLI authenticated and the reviewed root stored at `trust/root.json`:

```bash
export ROOT_SHA256='<independently verified SHA-256 of trust/root.json>'
.venv/bin/python -m catalog.publish \
  --root trust/root.json --metadata metadata --candidate candidate \
  --account ACCOUNT --container CONTAINER
```

Replace the hash, account and container placeholders. Grant the publisher only the
necessary container-scoped permissions. For CI, use repository/environment-scoped
OIDC, protected workflow changes and production approval rather than stored account
keys. Signing remains offline.

The publisher validates the root pin, signature thresholds, expiry and target bytes.
It rejects non-increasing release versions and changes to existing immutable objects,
then commits the timestamp last using an ETag condition. An expired previous timestamp
can be superseded by a fresh signed release, but its authenticated version floor is
still enforced. Cloud deployment and concurrency behavior require a staging test.

## Client verification

Configure clients to enforce the following rules:

1. Use a tested Android-compatible TUF client.
2. Embed the independently approved public root and minimum metadata versions in the OS.
3. Persist trusted metadata atomically; enforce expiration, rollback protection,
   sequential root rotation and bounded downloads.
4. Verify the catalog, APK SHA-256 and length, then independently pinned APK signer,
   package identity and installed/minimum version before installation.
5. Fail closed on invalid, expired or unreachable metadata with a retryable error.
   Never fall back to unsigned discovery; existing installed apps remain usable.
6. Test clock handling, factory-reset trust baselines, interrupted downloads,
   signature failures, rotation, replay, downgrade and cross-profile installation.

`catalog.client_check` is a Python reference verifier using the official TUF client.
It preserves trust state and checks catalog entries against signed target metadata.
Use it to validate metadata independently of the Android installer.
