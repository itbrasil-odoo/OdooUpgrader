# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0](https://github.com/itbrasil-odoo/OdooUpgrader/compare/v0.6.0...v0.7.0) (2026-02-21)


### Features

* Add custom addons support via --extra-addons option ([6d965ab](https://github.com/itbrasil-odoo/OdooUpgrader/commit/6d965ab54dbe7f00a32fbc182ab7a88d9b0cc36f))
* **cli:** add dry-run planning mode ([50fb79f](https://github.com/itbrasil-odoo/OdooUpgrader/commit/50fb79f7368b2a96c711dfa4e86e5d9f2bd9cf0f))
* **config:** add yaml config loader and precedence rules ([39a53d6](https://github.com/itbrasil-odoo/OdooUpgrader/commit/39a53d68c9102e0d37ed92ad47474a55e0bc7db6))
* **manifest:** emit run execution manifest json ([114f28c](https://github.com/itbrasil-odoo/OdooUpgrader/commit/114f28c2a8d5d73de53c7683403b53aa34575085))
* **runtime:** add retry and timeout controls ([3490e07](https://github.com/itbrasil-odoo/OdooUpgrader/commit/3490e07347eeabd5e1d987afd58cdd4692514718))
* **state:** add checkpoint resume execution state ([7959908](https://github.com/itbrasil-odoo/OdooUpgrader/commit/7959908a602de87af9ebf65d0bc8d0882f0635b8))
* **upgrader:** harden upgrade runtime and input security ([92034bf](https://github.com/itbrasil-odoo/OdooUpgrader/commit/92034bf857299c438b501c787412e90890e6f116))
* **validation:** validate Odoo addon manifest structure ([7bd3608](https://github.com/itbrasil-odoo/OdooUpgrader/commit/7bd36083d817809468801a95ddd3005287948f3c))


### Bug Fixes

* **ci:** resolve formatting and bandit security failures ([e81d526](https://github.com/itbrasil-odoo/OdooUpgrader/commit/e81d52657e419a345ec671f4c152fcf398bb6227))
* **security:** avoid clear-text postgres password in compose files ([4831a81](https://github.com/itbrasil-odoo/OdooUpgrader/commit/4831a811345f023d6db8e60551a0f6a073dc4763))


### Performance Improvements

* **upgrade:** cache openupgrade sources by version ([91ae6d4](https://github.com/itbrasil-odoo/OdooUpgrader/commit/91ae6d44d72662691f2eb6d20610cfaec5e9cbc4))


### Documentation

* **architecture:** document module boundaries and developer guide ([ff407f2](https://github.com/itbrasil-odoo/OdooUpgrader/commit/ff407f25fe13ae9269f09e2949c82d674460b390))
* **support:** add official support matrix and ops guidance ([f033637](https://github.com/itbrasil-odoo/OdooUpgrader/commit/f03363756f095d5c9af911f9780d5e31a9643832))
* update README and add v0.2 baseline snapshot ([5483b68](https://github.com/itbrasil-odoo/OdooUpgrader/commit/5483b68ec551b3bea3f12731ae4a7666c38370ba))

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
