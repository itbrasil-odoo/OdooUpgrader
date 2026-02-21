#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR="${1:-$(pwd)/.fixtures}"
PROFILE_INPUT="${2:-}"
FIXTURE_PROFILE="${FIXTURE_PROFILE:-minimal}"
PROFILE="${PROFILE_INPUT:-$FIXTURE_PROFILE}"

if [[ "$PROFILE" != "minimal" && "$PROFILE" != "base-db" ]]; then
  echo "Unsupported fixture profile: $PROFILE" >&2
  echo "Supported profiles: minimal, base-db" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

WORK_DIR="$(mktemp -d)"
PG_CONTAINER=""
ODOO_CONTAINER=""
BOOTSTRAP_NETWORK=""

cleanup() {
  if [[ -n "$ODOO_CONTAINER" ]]; then
    docker rm -f "$ODOO_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ -n "$PG_CONTAINER" ]]; then
    docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ -n "$BOOTSTRAP_NETWORK" ]]; then
    docker network rm "$BOOTSTRAP_NETWORK" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK_DIR"
}

trap cleanup EXIT

generate_minimal_sql_fixture() {
  # Deterministic SQL fixture with minimum legacy module graph schema used by OpenUpgrade.
  cat > "$WORK_DIR/dump.sql" <<'SQL'
CREATE TABLE IF NOT EXISTS ir_module_module (
    id integer PRIMARY KEY,
    name text NOT NULL UNIQUE,
    state text NOT NULL,
    latest_version text,
    demo boolean DEFAULT false
);

CREATE TABLE IF NOT EXISTS ir_module_module_dependency (
    id integer PRIMARY KEY,
    module_id integer NOT NULL,
    name text NOT NULL,
    auto_install_required boolean DEFAULT false
);

CREATE TABLE IF NOT EXISTS ir_module_module_exclusion (
    id integer PRIMARY KEY,
    module_id integer NOT NULL,
    name text NOT NULL
);

DELETE FROM ir_module_module_dependency;
DELETE FROM ir_module_module_exclusion;
DELETE FROM ir_module_module;

INSERT INTO ir_module_module(id, name, state, latest_version, demo)
VALUES (1, 'base', 'installed', '14.0', false);
SQL

  mkdir -p "$WORK_DIR/filestore/placeholder"
  echo "fixture" > "$WORK_DIR/filestore/placeholder/readme.txt"
}

wait_for_postgres() {
  local container_name="$1"
  local user_name="$2"
  local db_name="$3"
  local max_attempts=60
  local attempt=1

  while (( attempt <= max_attempts )); do
    if docker exec "$container_name" pg_isready -U "$user_name" -d "$db_name" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    ((attempt++))
  done

  echo "PostgreSQL container did not become ready in time." >&2
  return 1
}

run_postgres_sql() {
  local container_name="$1"
  local db_name="$2"
  local sql="$3"
  local max_attempts=60
  local attempt=1

  while (( attempt <= max_attempts )); do
    if docker exec "$container_name" psql -U odoo -d "$db_name" -v ON_ERROR_STOP=1 -c "$sql" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    ((attempt++))
  done

  echo "Could not execute SQL in PostgreSQL bootstrap container." >&2
  return 1
}

generate_base_db_fixture() {
  BOOTSTRAP_NETWORK="odooupgrader_fixture_net_$(date +%s)_$RANDOM"
  PG_CONTAINER="odooupgrader_fixture_pg_$(date +%s)_$RANDOM"
  ODOO_CONTAINER="odooupgrader_fixture_odoo_$(date +%s)_$RANDOM"

  docker network create "$BOOTSTRAP_NETWORK" >/dev/null

  docker run -d \
    --name "$PG_CONTAINER" \
    --network "$BOOTSTRAP_NETWORK" \
    -e POSTGRES_USER=odoo \
    -e POSTGRES_PASSWORD=odoo \
    -e POSTGRES_DB=postgres \
    postgres:13 >/dev/null

  wait_for_postgres "$PG_CONTAINER" "odoo" "postgres"
  run_postgres_sql "$PG_CONTAINER" "postgres" "DROP DATABASE IF EXISTS fixture;"
  run_postgres_sql "$PG_CONTAINER" "postgres" "CREATE DATABASE fixture;"

  docker run \
    --name "$ODOO_CONTAINER" \
    --network "$BOOTSTRAP_NETWORK" \
    -e HOST="$PG_CONTAINER" \
    -e USER=odoo \
    -e PASSWORD=odoo \
    odoo:14.0 \
    odoo -d fixture --init=base --without-demo=all --stop-after-init --log-level=warn >/dev/null

  docker exec "$PG_CONTAINER" pg_dump -U odoo --no-owner --no-privileges fixture > "$WORK_DIR/dump.sql"

  mkdir -p "$WORK_DIR/filestore"
  if ! docker cp "$ODOO_CONTAINER":/var/lib/odoo/filestore/fixture/. "$WORK_DIR/filestore/" >/dev/null 2>&1; then
    mkdir -p "$WORK_DIR/filestore/placeholder"
    echo "fixture" > "$WORK_DIR/filestore/placeholder/readme.txt"
  fi
}

if [[ "$PROFILE" == "base-db" ]]; then
  generate_base_db_fixture
else
  generate_minimal_sql_fixture
fi

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
echo "fixture_profile=$PROFILE"
echo "source_zip=$OUTPUT_DIR/sample_odoo14.zip"
echo "source_dump=$OUTPUT_DIR/sample_odoo14.dump"
echo "extra_addons_zip=$OUTPUT_DIR/extra_addons.zip"
