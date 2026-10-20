# Publishing and client integration

## Catalog hosting

The catalog endpoint is
[stellarosappcatalog.stellarsecurity.com](https://stellarosappcatalog.stellarsecurity.com).
The hosting configuration uses Azure Static Web Apps Free with a custom HTTPS domain.

Serve signed metadata and the catalog from the static site. APKs are preserved as
GitHub release assets in this repository, separate from the Azure Free metadata site.
Each collection has a tag derived from its package versions, lengths and hashes;
every asset name includes the package, version and complete SHA-256. Upstream
`current` or `latest` URLs are used only to discover new candidates.

The candidate workflow uploads the preserved APKs, downloads and verifies them,
then publishes the signing kit. It never replaces assets in a published collection.
Keep referenced collections for as long as signed catalogs use them. Enable
[GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
to also prevent asset changes at the hosting layer. Client SHA-256, package and
certificate checks remain mandatory regardless of hosting settings.

Download links can be changed in a newly offline-signed catalog without an OS update.
Alternative HTTPS hosts can be used with the same hash-named APK files. Publish and
verify those exact files before deploying metadata that points to them.

## Preserve an existing approved catalog

Set `releases/build-request.json` to `mode: preserve-approved`, specifying the archived
signing kit URL and SHA-256 and the existing signed metadata directory. The workflow
verifies the archived kit, the previous catalog signature chain, all APK hashes and
their signing certificates. It changes only download addresses, preserving approved
package versions and bytes. Sign the resulting kit with the next catalog version.

For later app updates, run the candidate workflow manually with `mode: latest`.
Review and sign only the releases you want to publish. There is no scheduled
upstream-update requirement and no change to the live catalog before offline signing.

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
.venv/bin/python -m catalog.publish \
  --root trust/root.json --metadata metadata --candidate candidate \
  --account ACCOUNT --container CONTAINER
```

Replace the account and container placeholders. The approved bootstrap root is pinned in catalog/trust.py; ROOT_SHA256, if supplied, must match that pin. Grant the publisher only the
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

1. Validate the Android catalog client against the supported metadata profile and on-device tests.
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

## Bootstrap root

The approved public bootstrap root is stored in `trust/root.json` and expires on
2031-10-19. Its exact-byte SHA-256 is
`5b03c1dcb252c0df6a4d85675986ba9903ea16a7fbd5df66a0d400337b479b95`.
The publication and reference-client commands verify this pin before use.
Root rotation requires sequential, authenticated TUF root updates; do not replace
the bootstrap file with a newly generated root of the same version.
