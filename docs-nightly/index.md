# ProofOfThought Nightly

This site documents the nightly prerelease channel for ProofOfThought.

Nightly builds are published from the current `main` branch and can include breaking changes, incomplete features, and behavior changes that have not yet been stabilized.

## Install Nightly

```bash
pip install --pre proofofthought
```

To lock a reproducible environment, pin the exact prerelease version that you tested:

```bash
pip install "proofofthought==2.0.0.dev202604011230"
```

## What To Expect

- Public Python imports remain `z3adapter`
- Nightly artifacts are validated with unit tests, package checks, and an artifact secret scan before upload
- Nightly does not promise stable compatibility between prerelease versions

## Current Nightly Line

Nightlies for the staged-major line use prerelease versions in the form `2.0.0.devYYYYMMDDHHMM`.

See [Release Notes](release-notes.md) for the staged-major changes carried by this nightly line.

For the main documentation site, use <https://debarghaG.github.io/proofofthought/>.
