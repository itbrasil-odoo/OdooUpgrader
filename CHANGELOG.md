# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0](https://github.com/itbrasil-odoo/OdooUpgrader/compare/v0.6.0...v0.7.0) (2026-02-21)


### Features

* Add custom addons support via --extra-addons option ([6d965ab](https://github.com/itbrasil-odoo/OdooUpgrader/commit/6d965ab54dbe7f00a32fbc182ab7a88d9b0cc36f))
* **audit:** add installed module and OCA target preflight ([657a6bb](https://github.com/itbrasil-odoo/OdooUpgrader/commit/657a6bb9ca317a81d3992f43e0742567620b37e2))
* **cli:** add dry-run planning mode ([50fb79f](https://github.com/itbrasil-odoo/OdooUpgrader/commit/50fb79f7368b2a96c711dfa4e86e5d9f2bd9cf0f))
* **config:** add yaml config loader and precedence rules ([39a53d6](https://github.com/itbrasil-odoo/OdooUpgrader/commit/39a53d68c9102e0d37ed92ad47474a55e0bc7db6))
* **database:** add restore compatibility for newer postgres dumps ([6406ea6](https://github.com/itbrasil-odoo/OdooUpgrader/commit/6406ea63b5d5c8d9afd4d35a8a965c92ef6e96d6))
* **fixtures:** add base-db profile for realistic upgrade fixtures ([589bbe3](https://github.com/itbrasil-odoo/OdooUpgrader/commit/589bbe35a602ea7d27d65ac9b6cf04f5107a39b9))
* **manifest:** emit run execution manifest json ([114f28c](https://github.com/itbrasil-odoo/OdooUpgrader/commit/114f28c2a8d5d73de53c7683403b53aa34575085))
* **release:** v0.7.0 module preflight and runtime hardening ([0530d83](https://github.com/itbrasil-odoo/OdooUpgrader/commit/0530d835e81ecb6f381ab5260737264b642c106e))
* **runtime:** add retry and timeout controls ([3490e07](https://github.com/itbrasil-odoo/OdooUpgrader/commit/3490e07347eeabd5e1d987afd58cdd4692514718))
* **state:** add checkpoint resume execution state ([7959908](https://github.com/itbrasil-odoo/OdooUpgrader/commit/7959908a602de87af9ebf65d0bc8d0882f0635b8))
* **upgrader:** harden upgrade runtime and input security ([92034bf](https://github.com/itbrasil-odoo/OdooUpgrader/commit/92034bf857299c438b501c787412e90890e6f116))
* **validation:** fail fast on target-incompatible addon manifest versions ([b4fcfb1](https://github.com/itbrasil-odoo/OdooUpgrader/commit/b4fcfb160ddfe58ff471b1b58ea83067220e57a5))
* **validation:** support recursive addon discovery ([cabbbbe](https://github.com/itbrasil-odoo/OdooUpgrader/commit/cabbbbe88c5f7999b72bd27e45c3c247c55fb2cf))
* **validation:** validate Odoo addon manifest structure ([7bd3608](https://github.com/itbrasil-odoo/OdooUpgrader/commit/7bd36083d817809468801a95ddd3005287948f3c))


### Bug Fixes

* **ci:** resolve black and bandit failures ([5e963d5](https://github.com/itbrasil-odoo/OdooUpgrader/commit/5e963d5fb82c9054f9d80a2f2dfb5b4cc911fada))
* **ci:** resolve formatting and bandit security failures ([e81d526](https://github.com/itbrasil-odoo/OdooUpgrader/commit/e81d52657e419a345ec671f4c152fcf398bb6227))
* **runtime:** map host uid to passwd entry for older odoo images ([fd284c9](https://github.com/itbrasil-odoo/OdooUpgrader/commit/fd284c970e744ac8da15aa9d608cdc8a9ce2111a))
* **security:** avoid clear-text postgres password in compose files ([4831a81](https://github.com/itbrasil-odoo/OdooUpgrader/commit/4831a811345f023d6db8e60551a0f6a073dc4763))
* **upgrade:** harden runtime flow for real migration failures ([5ff6590](https://github.com/itbrasil-odoo/OdooUpgrader/commit/5ff65902007609c2e70a3991729aff753804ffff))


### Performance Improvements

* **upgrade:** cache openupgrade sources by version ([91ae6d4](https://github.com/itbrasil-odoo/OdooUpgrader/commit/91ae6d44d72662691f2eb6d20610cfaec5e9cbc4))


### Documentation

* **architecture:** document module boundaries and developer guide ([ff407f2](https://github.com/itbrasil-odoo/OdooUpgrader/commit/ff407f25fe13ae9269f09e2949c82d674460b390))
* **changelog:** record runtime and addon compatibility safeguards ([7ecd8e5](https://github.com/itbrasil-odoo/OdooUpgrader/commit/7ecd8e5551393edee030e5a91e385a04266e51f9))
* **fixtures:** document base-db profile and ci coverage ([08d9017](https://github.com/itbrasil-odoo/OdooUpgrader/commit/08d9017d5cc2eb5b9f4ba245f9fc3e2680857967))
* **operations:** document module preflight and postgres restore guidance ([bf1407e](https://github.com/itbrasil-odoo/OdooUpgrader/commit/bf1407ea90fce44d26125217224a6f691b763825))
* **readme:** document module audit workflow and flags ([62f4b14](https://github.com/itbrasil-odoo/OdooUpgrader/commit/62f4b14387b0c5ddeb4e9e1a042c1d22d97236b7))
* **readme:** note pep668-compatible build behavior ([ce829a8](https://github.com/itbrasil-odoo/OdooUpgrader/commit/ce829a8ee0b9801f00805e55b613523913177b9c))
* **support:** add official support matrix and ops guidance ([f033637](https://github.com/itbrasil-odoo/OdooUpgrader/commit/f03363756f095d5c9af911f9780d5e31a9643832))
* update README and add v0.2 baseline snapshot ([5483b68](https://github.com/itbrasil-odoo/OdooUpgrader/commit/5483b68ec551b3bea3f12731ae4a7666c38370ba))

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
