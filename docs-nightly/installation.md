# Nightly Installation

## Channel Semantics

The nightly channel is for testing the newest packaged state of `main`. It is appropriate when you want to validate unreleased work or share current progress without waiting for a stable cut.

Nightly builds may:

- change APIs without warning
- include breaking behavior changes
- be superseded quickly by a newer prerelease

## Install

```bash
pip install --pre proofofthought
```

The project name on PyPI is `proofofthought`, while Python imports continue to use `z3adapter`.

## Pinning

If you need reproducibility, pin an explicit nightly version:

```bash
pip install "proofofthought==2.0.0.dev202604011230"
```

## From Source

```bash
git clone https://github.com/debarghaG/proofofthought.git
cd proofofthought
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```
