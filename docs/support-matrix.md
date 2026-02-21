# Support Matrix

## Official Scope

| Topic | Status | Notes |
|---|---|---|
| Odoo versions | Supported | Incremental migrations from 10.0 to 18.0 |
| Edition: Community | Supported | Primary tested scope |
| Edition: Enterprise | Supported with constraints | Enterprise databases can be migrated when Enterprise code and dependencies are provided in custom addons path |
| OCA modules | Supported with constraints | Module availability and migration scripts depend on each OCA repository/version |
| Custom modules | Supported with constraints | Must include valid manifests and migration compatibility for each target major |
| Source formats | Supported | `.zip` (with `dump.sql`) and `.dump` |

## Enterprise, OCA and Custom Addons Guidance

1. Enterprise migrations require Enterprise source code matching each target Odoo major.
2. OCA/custom modules are mounted via `--extra-addons` for all upgrade steps.
3. Compatibility of module APIs and data model changes is the responsibility of each module maintainer.
4. Use checksums for remote sources and keep a rollback snapshot before any migration.

## Operational Guidance

1. Use `--dry-run` first to verify input validity and planned version path.
2. Use `--resume` for long-running migrations and interruption recovery.
3. Keep `output/run-manifest.json` for audit, duration and step diagnostics.
4. Run integration workflows with deterministic fixtures before production cutover.
