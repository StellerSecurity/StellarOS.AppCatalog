# Offline release procedure

Use a disconnected signing machine and reviewed tools. This repository's CLI never
uses the network for key generation, signing or release assembly. That does not
make an internet-connected host offline: disconnect it physically. Do not generate
production keys on CI or the online build machine.

## Prepare the signing kit

On an online machine, download the pinned wheels:

```sh
pip download --require-hashes -r requirements.lock -d wheels
```

Transfer reviewed source, requirements.lock, wheels, a pinned Android build-tools
installation and the unsigned candidate via removable media. Install dependencies
with `pip install --no-index --find-links wheels --require-hashes -r requirements.lock`.
Only carry public keys, signatures and approved release files back online.

## Initial root ceremony

Each of three custodians independently runs on their own offline machine:

```sh
python -m catalog.release keygen --private /offline-storage/custodian.pem --public custodian-public.json
```

The CLI requires an encryption password and creates private files with mode 0600.
Each custodian keeps their own private key and backup outside the repository.
Exchange only the three public JSON files; confirm their fingerprints out of band.

```sh
python -m catalog.release init-root --public alice.json bob.json carol.json --output root.json
```

At least two custodians review all keys, roles, thresholds, version and expiry and
sign the **same** root file sequentially (the second signature is appended):

```sh
python -m catalog.release sign root.json --private /offline-storage/custodian.pem
```

Publish only the completed root to `trust/root.json`. Record its file SHA-256 in the
protected Azure publishing environment and embed the public root in the OS through
an independently reviewed build. Do not bootstrap trust from the serving endpoint.

## Prepare and approve a release

The manual GitHub workflow prepares all nine candidate APKs. Its output is untrusted.
Review against the last accepted release; never lower versions or accept changed APK
bytes at the same version. To repeat inspection locally, use `catalog.candidate`
with `--previous` pointing to the previously verified catalog.

1. Assemble targets metadata:

```sh
python -m catalog.release prepare-targets --candidate candidate --version 1 --output metadata/targets.json
```

2. Each of two offline custodians inspects and signs targets. The command independently
   parses the actual APKs and validates their signatures against local policy:

```sh
python -m catalog.release sign metadata/targets.json --private /offline-storage/custodian.pem \
  --candidate candidate --policy apps-policy.json --apksigner /tools/apksigner --aapt2 /tools/aapt2
```

3. After both targets signatures, prepare snapshot, then obtain two signatures:

```sh
python -m catalog.release prepare-snapshot --root root.json --input metadata/targets.json --version 1 --output metadata/snapshot.json
python -m catalog.release sign metadata/snapshot.json --private /offline-storage/custodian.pem
```

4. After both snapshot signatures, prepare timestamp, then obtain two signatures:

```sh
python -m catalog.release prepare-timestamp --root root.json --input metadata/snapshot.json --version 1 --output metadata/timestamp.json
python -m catalog.release sign metadata/timestamp.json --private /offline-storage/custodian.pem
```

5. Verify the complete release:

```sh
python -m catalog.release verify --root root.json --metadata metadata --candidate candidate
```

Use increasing versions on every renewal, including releases with unchanged APKs.
Never edit metadata after signing: downstream metadata hashes cover the signed files.
No server-side expiry extension is possible without the offline signatures.
