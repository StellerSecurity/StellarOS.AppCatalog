# Publishing and client integration

## Catalog hosting

The catalog endpoint is
[stellarosappcatalog.stellarsecurity.com](https://stellarosappcatalog.stellarsecurity.com).
It uses Azure Static Web Apps Free with a custom HTTPS domain. Hosting is provisioned;
a signed production catalog and automated publication are not deployed yet.

The planned static site contains signed metadata and the catalog. APK artifacts need
a separate configured HTTPS origin, with immutable paths matching the signed target
hashes. The split-origin deployment and client behavior still require integration
testing. Confirm redistribution rights before mirroring third-party APKs.

No private signing keys belong in Azure or GitHub. Deployment credentials must only
permit publishing approved public files. Independently pin the trusted root, verify
all signatures and artifact hashes before deployment, and preserve previous immutable
objects for clients already downloading a release. Publish the timestamp only after
its referenced metadata and artifacts are available.

## Available Blob publisher

`catalog.publish` publishes a complete signed repository to an existing Azure Blob
container. It is an alternative publisher, **not a Static Web Apps deployment tool**.
Use it only after configuring and testing the intended destination. It does not
create infrastructure or sign releases.

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

## Android activation requirements

These tools do not enable TUF verification in Lupin. Before activation:

1. Integrate and test an Android-compatible TUF client.
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
It neither installs APKs nor replaces the Android implementation.
