# Releasing ProofOfThought

## Nightly PyPI releases

Nightly releases are published manually from GitHub Actions through the `Nightly PyPI Release` workflow.

Before using the workflow:

1. Add the PyPI API token as the repository secret `PYPI_API_TOKEN`.
2. Confirm the checkout does not contain real credentials in tracked files.
3. Make sure the current `main` branch state is the code you want to ship as a nightly prerelease.

The workflow will:

1. Compute a version in the form `BASE.devYYYYMMDDHHMM`.
2. Run the unit test suite.
3. Rewrite `z3adapter/VERSION` inside the CI checkout to that explicit prerelease version.
4. Remove stale `build/`, `dist/`, and `*.egg-info` directories so deleted modules cannot leak into the release artifacts.
5. Build the wheel and source distribution without build isolation, using the already-installed release dependencies.
6. Run `twine check`.
7. Scan the built artifacts for obvious secret-bearing files, token patterns, and removed runtime modules.
8. Smoke-install the built wheel in a fresh virtual environment.
9. Upload the artifacts to PyPI when the `publish` input is left enabled.

Use the workflow's `publish=false` input for a validation-only dry run.

## Documentation

The normal documentation workflow builds both:

- the primary site at `https://debarghaG.github.io/proofofthought/`
- the nightly site at `https://debarghaG.github.io/proofofthought/nightly/`

The nightly docs are intended for the current development branch and should clearly communicate that the channel is unstable and potentially breaking.
