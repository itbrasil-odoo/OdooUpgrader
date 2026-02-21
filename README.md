# OdooUpgrader
[![GitHub Release](https://img.shields.io/github/v/release/itbrasil-odoo/OdooUpgrader)](https://github.com/itbrasil-odoo/OdooUpgrader/releases)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)

Professional command-line tool for automating Odoo database upgrades using [OCA OpenUpgrade](https://github.com/OCA/OpenUpgrade). It upgrades databases incrementally from Odoo 10.0 to 18.0 with isolated Docker environments.

## Features

- Automated incremental upgrades (major-by-major)
- Supports source database as local `.zip`/`.dump` or remote URL
- Supports custom addons from local folder, local `.zip`, or remote `.zip`
- Runtime-isolated Docker resources (unique network/container/volume per execution)
- Streamed download progress with optional SHA-256 verification
- Hardened ZIP extraction (path traversal and symlink protections)
- Optional module audit for installed modules + OCA target-version availability
- Rich CLI output and optional log file

## Requirements

- Python 3.9+
- Docker Engine
- Docker Compose v2 (`docker compose`) or v1 (`docker-compose`)
- Linux, macOS, or Windows (WSL2 recommended on Windows)

## Installation

### From PyPI

```bash
pip install odooupgrader
```

### From source

```bash
git clone https://github.com/itbrasil-odoo/OdooUpgrader.git
cd OdooUpgrader
pip install -e .
```

## Usage

### Basic usage

```bash
odooupgrader --source /path/to/database.zip --version 16.0
```

### Source from URL with checksum validation

```bash
odooupgrader \
  --source https://example.com/database.dump \
  --source-sha256 <sha256_hex> \
  --version 17.0
```

### Upgrade with custom addons

```bash
odooupgrader \
  --source /path/to/database.zip \
  --version 16.0 \
  --extra-addons /path/to/custom_addons
```

### Custom addons from remote ZIP with checksum

```bash
odooupgrader \
  --source /path/to/database.dump \
  --version 17.0 \
  --extra-addons https://example.com/custom_addons.zip \
  --extra-addons-sha256 <sha256_hex>
```

### Allow insecure HTTP explicitly (not recommended)

```bash
odooupgrader \
  --source http://example.com/database.dump \
  --allow-insecure-http \
  --version 15.0
```

### Verbose logs + file output

```bash
odooupgrader \
  --source /path/to/database.dump \
  --version 18.0 \
  --verbose \
  --log-file upgrade.log
```

### Dry-run execution planning

```bash
odooupgrader \
  --source ./sample_odoo14.dump \
  --version 15.0 \
  --dry-run
```

### Module audit before migration

```bash
odooupgrader \
  --source ./database.dump \
  --version 18.0 \
  --extra-addons ./extra_addons \
  --analyze-modules \
  --analyze-modules-only \
  --module-audit-file ./output/module-audit.json
```

### PostgreSQL dump compatibility

If your SQL or binary dump was produced by a newer PostgreSQL toolchain, run with a compatible
database image:

```bash
odooupgrader \
  --source ./database.dump \
  --version 18.0 \
  --postgres-version 17
```

For SQL dumps (`dump.sql`), OdooUpgrader also retries automatically by stripping unsupported
`SET` parameters when possible.

### Configuration file usage

```bash
odooupgrader --config .odooupgrader.yml --source ./override.dump
```

## Command-line options

| Option | Required | Description |
|--------|----------|-------------|
| `--source` | ✅ | Local `.zip`/`.dump` path or remote URL |
| `--version` | ✅ | Target Odoo version (`10.0` ... `18.0`) |
| `--extra-addons` | ❌ | Local folder, local `.zip`, or remote `.zip` URL |
| `--postgres-version` | ❌ | PostgreSQL image version (default: `13`) |
| `--verbose` | ❌ | Enable debug-level runtime logs |
| `--log-file` | ❌ | Save logs to a file |
| `--allow-insecure-http` | ❌ | Allow `http://` URLs (default blocks HTTP) |
| `--source-sha256` | ❌ | Expected SHA-256 of remote source download |
| `--extra-addons-sha256` | ❌ | Expected SHA-256 of remote addons download |
| `--resume` | ❌ | Resume interrupted runs using persisted state |
| `--state-file` | ❌ | Custom path for state file (`output/run-state.json`) |
| `--download-timeout` | ❌ | Download timeout in seconds |
| `--retry-count` | ❌ | Retries for transient download/runtime failures |
| `--retry-backoff-seconds` | ❌ | Backoff between retries |
| `--step-timeout-minutes` | ❌ | Timeout per OpenUpgrade step |
| `--config` | ❌ | YAML config file (`.odooupgrader.yml`) |
| `--dry-run` | ❌ | Validate inputs and print upgrade plan without running Docker |
| `--analyze-modules` | ❌ | Audit installed modules and check OCA module existence on target version |
| `--analyze-modules-only` | ❌ | Stop after module audit without running upgrade steps |
| `--strict-module-audit` | ❌ | Fail run when module audit finds missing OCA modules/check errors |
| `--module-audit-file` | ❌ | Output path for module audit JSON report |

## How it works

1. Validate Docker environment and input source(s)
2. Prepare working directories and PostgreSQL container
3. Download/copy source and custom addons (if provided)
4. Restore database and filestore
5. Detect current Odoo version
6. Upgrade step-by-step with OpenUpgrade containers
7. Package final `dump.sql` + `filestore` into `output/upgraded.zip`

## Architecture

Core orchestration now follows single-responsibility boundaries:

- `src/odooupgrader/core.py`: workflow orchestration and service wiring
- `src/odooupgrader/errors.py`: domain exceptions
- `src/odooupgrader/models.py`: runtime models
- `src/odooupgrader/constants.py`: shared constants/defaults
- `src/odooupgrader/services/`: side-effect services (`validation`, `archive`, `download`, `filesystem`, `command_runner`, `docker_runtime`, `database`, `upgrade_step`)

See `docs/architecture.md` for the full responsibility map and flow.

## Output structure

```text
output/
├── upgraded.zip
├── odoo.log
├── module-audit.json (when `--analyze-modules` is enabled)
├── run-manifest.json
└── run-state.json (when `--resume` is enabled)
```

## Security defaults

- HTTP is blocked by default (`https://` required)
- Optional SHA-256 checksum validation for remote downloads
- ZIP extraction rejects traversal/symlink entries
- Temporary Docker credentials are generated per execution
- Docker runtime names are generated per execution (collision-safe)
- Addon manifests are validated with safe parsing rules

## Supported versions

Odoo 10.0 through 18.0, aligned with OpenUpgrade availability.

## Operational notes

- If module audit reports OCA modules missing in the target branch, plan replacement/porting before migration.
- For dumps created with newer PostgreSQL client versions, use `--postgres-version` accordingly.
- SQL restore retries include compatibility stripping for unsupported PostgreSQL `SET` directives.
- Upgrade image build supports pip installs under externally-managed Python environments (PEP 668).

## Contributing

Contributions are welcome.

## License

MIT. See [LICENSE](LICENSE).

## Support

- Issues: [GitHub Issues](https://github.com/itbrasil-odoo/OdooUpgrader/issues)
- Scope matrix: [docs/support-matrix.md](docs/support-matrix.md)

## Changelog

### Version 0.6.0

- Added config-driven execution (`--config`) with precedence rules (CLI > config > defaults)
- Added dry-run planning mode (`--dry-run`)
- Added checkpoint/resume state handling (`--resume`, `--state-file`)
- Added execution manifest (`output/run-manifest.json`)
- Added runtime retry/timeout controls for reliability
- Added OpenUpgrade source cache by version
- Added security and quality automation (`ruff`, `mypy`, `bandit`, `pip-audit`, CodeQL)
- Added release automation (`release-please`) and support matrix documentation

### Version 0.5.0

- Added resumable state and execution manifest
- Added retry/timeout controls and deterministic integration fixtures
- Added OpenUpgrade source cache optimization

### Version 0.4.0

- Added quality/security baseline and hardened addon manifest validation

- Added secure ZIP extraction with traversal/symlink blocking
- Added HTTPS-by-default policy and `--allow-insecure-http`
- Added optional SHA-256 verification (`--source-sha256`, `--extra-addons-sha256`)
- Added per-run Docker isolation (dynamic container/network/volume names)
- Added per-run ephemeral PostgreSQL credentials
- Added upgrade progression guard to prevent silent loops
- Added deterministic CI (`pytest` + `compileall`) and new unit test suite
- Updated project metadata and repository links to `itbrasil-odoo`

### Version 0.2.0

- Added custom addons support via `--extra-addons`

### Version 0.1.0

- Initial release with core upgrade workflow
