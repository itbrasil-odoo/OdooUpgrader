# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0] - 2026-02-21

- Added recursive addon discovery for nested addon layouts (including OCA-style repository trees).
- Added module preflight audit (`--analyze-modules`, `--analyze-modules-only`) with OCA target-branch checks.
- Added strict audit mode and JSON report output controls (`--strict-module-audit`, `--module-audit-file`).
- Improved SQL restore resilience by retrying with compatibility-stripped unsupported PostgreSQL `SET` directives.
- Added actionable binary dump restore guidance for PostgreSQL version mismatch (`--postgres-version`).
- Added PEP 668-compatible dependency installation during OpenUpgrade image build.
- Added pre-upgrade filestore checklist preparation to avoid attachment GC path failures.
- Improved upgrade runtime path handling for host-mounted filestore/log output.
- Retry policy now avoids re-running non-transient migration failures to prevent state corruption.
- Added target-version validation for local addon manifest versions (fails fast on mismatched branches).
- Added deterministic fixture profile `base-db` for realistic OpenUpgrade integration scenarios.
- Added optional manual CI job for full `14.0 -> 15.0` upgrade validation using `base-db` fixtures.

## [0.6.0] - 2026-02-21

- Added configuration-file support (`--config`) with precedence rules.
- Added dry-run execution planning (`--dry-run`).
- Added actionable error catalog for operator-focused diagnostics.
- Added release governance automation with release-please.
- Added formal support matrix documentation for Community/Enterprise and OCA/custom scope.

## [0.5.0] - 2026-02-21

- Added checkpoint/resume runtime state (`--resume`, `--state-file`).
- Added run execution manifest (`output/run-manifest.json`).
- Added retry/timeout runtime controls for download and upgrade steps.
- Added OpenUpgrade source cache by version for faster repeated runs.
- Added deterministic integration fixtures and workflow coverage.

## [0.4.0] - 2026-02-21

- Added quality baseline with `ruff`, `mypy`, and `pre-commit`.
- Added security workflow with `pip-audit`, `bandit`, and CodeQL.
- Hardened addon validation with manifest structure and safe parsing checks.

## [0.3.0] - 2026-02-21

- Security hardening for ZIP extraction and HTTPS policy.
- Runtime isolation with dynamic Docker resources and credentials.
- Refactor to SRP-based services and expanded unit test coverage.
