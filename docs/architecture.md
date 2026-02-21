# OdooUpgrader Architecture

This document describes the internal module boundaries after the SRP refactor.

## Goals

- Keep CLI/public API stable
- Isolate side effects into dedicated services
- Make each domain behavior testable in isolation

## Public surface

- `odooupgrader.cli:main`
- `odooupgrader.OdooUpgrader`
- `odooupgrader.UpgraderError`

## Package layout

```text
src/odooupgrader/
├── cli.py
├── core.py
├── errors.py
├── models.py
├── constants.py
└── services/
    ├── command_runner.py
    ├── validation.py
    ├── archive.py
    ├── download.py
    ├── filesystem.py
    ├── docker_runtime.py
    ├── database.py
    └── upgrade_step.py
```

## Responsibility map

- `core.py`
  - Workflow orchestration (`run()`)
  - Service wiring and execution order
  - Compatibility wrappers kept for external/internal callers
- `errors.py`
  - Domain exception types
- `models.py`
  - Runtime data contracts (`RunContext`)
- `constants.py`
  - Shared constants and defaults
- `services/validation.py`
  - URL/local path validation and protocol policy
- `services/archive.py`
  - Safe ZIP extraction
- `services/download.py`
  - Download + checksum logic
- `services/filesystem.py`
  - Permissions and cleanup operations
- `services/command_runner.py`
  - Subprocess execution and stderr propagation
- `services/docker_runtime.py`
  - Docker runtime lifecycle and db compose setup
- `services/database.py`
  - Restore/version lookup/final package dump
- `services/upgrade_step.py`
  - OpenUpgrade image/compose generation and step execution

## Flow overview

1. Validate Docker and inputs
2. Prepare local workspace folders
3. Download/copy source and addons
4. Boot DB runtime and restore source
5. Loop major upgrades until target version
6. Build final package and cleanup runtime/artifacts

## Testing strategy

- `tests/test_core.py`: regression and orchestration-level behavior
- `tests/services/`: focused unit tests per service boundary
