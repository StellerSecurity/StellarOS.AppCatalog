# Azure and Android deployment

## Azure

Use an existing HTTPS Azure Blob Storage endpoint/container. A public read endpoint
serves metadata and APKs; upload access is separate. No web-service code or online
signing service is needed. Confirm the Azure account/container and APK redistribution
rights before provisioning or upload.

Configure GitHub-to-Azure OIDC constrained to this repository's protected production
environment. Grant only blob publication permissions scoped to the container, not
subscription owner or signing permissions. Require approval for that environment.
Protect workflow/source changes and the independently reviewed `ROOT_SHA256` variable.

Publication is intentionally not wired to Actions yet: destination and offline root
have not been supplied. From a trusted publisher with Azure CLI authenticated:

```sh
export ROOT_SHA256='<independently verified SHA-256 of trust/root.json>'
python -m catalog.publish --root trust/root.json --metadata release/metadata \
  --candidate release/candidate --account ACCOUNT --container CONTAINER
```

Publisher verifies the root pin, signature thresholds, expiry, metadata chain and
all artifact hashes. It checks increasing metadata versions against an existing
release, refuses immutable object replacement, uploads targets/versioned metadata
first and publishes timestamp last with an ETag condition. A failed/interrupted upload
before timestamp does not advertise the incomplete release. Retain old immutable
objects for clients midway through updates.

An expired previous timestamp can be replaced only by a fresh, correctly signed release
with increasing versions; the old signatures still anchor the version floor. Azure
deployment and concurrency behavior need an integration test against the chosen staging
container before production.

## Android activation gate

The phone is not switched to this catalog by these tools. Before activating Lupin:

1. Integrate a maintained TUF client compatible with Android/AOSP, or separately review
   and test a minimal client implementation against TUF conformance fixtures.
2. Ship the approved public root and minimum metadata versions in the OS, never test keys.
3. Persist trusted metadata atomically in app-private storage; enforce expiration,
   rollback protection, sequential root rotation and bounded downloads.
4. Verify catalog target, then the selected APK's exact hash/length, then independent
   OS-pinned APK signer/package identity and installed/minimum version before install.
5. Invalid/expired/unreachable metadata must not fall back to unsigned live discovery.
   Show a retryable installation error. Existing apps remain usable.
6. Qualify clock handling, factory-reset baseline, interrupted updates, bad signatures,
   key rotation, downgrade, cache replay and cross-profile installation on a real phone.

The `catalog.client_check` reference uses the official Python TUF client. It verifies
catalog and target metadata and preserves trust state, but does not install APKs and
is not the Android implementation.
