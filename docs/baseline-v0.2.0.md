# Baseline Snapshot (v0.2.0)

This baseline captures pre-hardening behavior before implementing `hardening/v0.3.0`.

## Technical snapshot

- Branch at baseline: `main`
- CLI smoke check:
  - `PYTHONPATH=src python -m odooupgrader --help` succeeded
- Project state:
  - Core logic concentrated in `src/odooupgrader/core.py`
  - No unit test suite in repository
  - Ubuntu integration workflow depended on external sample URLs and executed on PR/push

## Baseline CLI options

- `--source`
- `--version`
- `--extra-addons`
- `--verbose`
- `--postgres-version`
- `--log-file`

## Baseline known gaps addressed in v0.3.0 plan

- No SHA-256 verification for remote downloads
- HTTP accepted by default
- Static Docker runtime names and credentials
- ZIP extraction used non-hardened extraction path
- No deterministic unit-test workflow for PR
