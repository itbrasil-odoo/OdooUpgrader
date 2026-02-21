#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR="${1:-$(pwd)/.fixtures}"
mkdir -p "$OUTPUT_DIR"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

# Minimal deterministic SQL fixture with Odoo base version metadata.
cat > "$WORK_DIR/dump.sql" <<'SQL'
CREATE TABLE IF NOT EXISTS ir_module_module (name text, state text, latest_version text);
DELETE FROM ir_module_module;
INSERT INTO ir_module_module(name, state, latest_version) VALUES ('base', 'installed', '14.0');
SQL

mkdir -p "$WORK_DIR/filestore/placeholder"
echo "fixture" > "$WORK_DIR/filestore/placeholder/readme.txt"

(
  cd "$WORK_DIR"
  zip -rq "$OUTPUT_DIR/sample_odoo14.zip" dump.sql filestore
)

# Synthetic dump placeholder used for deterministic validation scenarios.
cat > "$OUTPUT_DIR/sample_odoo14.dump" <<'DUMP'
SYNTHETIC_DUMP_PLACEHOLDER
DUMP

# Deterministic extra addons fixture.
mkdir -p "$WORK_DIR/custom_addons/sample_custom_module"
cat > "$WORK_DIR/custom_addons/sample_custom_module/__init__.py" <<'PY'
# fixture module
PY
cat > "$WORK_DIR/custom_addons/sample_custom_module/__manifest__.py" <<'MANIFEST'
{
    'name': 'Sample Custom Module',
    'version': '14.0.1.0.0',
    'depends': ['base'],
}
MANIFEST
(
  cd "$WORK_DIR/custom_addons"
  zip -rq "$OUTPUT_DIR/extra_addons.zip" .
)

echo "fixture_dir=$OUTPUT_DIR"
echo "source_zip=$OUTPUT_DIR/sample_odoo14.zip"
echo "source_dump=$OUTPUT_DIR/sample_odoo14.dump"
echo "extra_addons_zip=$OUTPUT_DIR/extra_addons.zip"
