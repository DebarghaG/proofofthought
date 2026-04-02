# Nightly Release Policy

## Stability

Nightly releases are intentionally unstable. They are suitable for evaluation, integration testing, and early feedback, not for a long-term compatibility guarantee.

## Versioning

Nightly builds use PyPI prerelease versions in the form:

```text
BASE.devYYYYMMDDHHMM
```

The timestamp is generated in UTC during the GitHub Actions workflow.

## Validation Before Upload

The nightly workflow blocks publication unless all of the following succeed:

1. The unit test suite passes.
2. The wheel and source distribution build successfully.
3. `twine check` passes.
4. The built artifacts do not contain obvious secret-bearing files or token patterns.
5. The built wheel installs into a fresh virtual environment.

## Authentication

PyPI uploads are authenticated with the repository secret `PYPI_API_TOKEN`.
