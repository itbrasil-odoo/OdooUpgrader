import subprocess
from pathlib import Path

import pytest

from odooupgrader.errors import UpgraderError
from odooupgrader.models import RunContext
from odooupgrader.services.database import DatabaseService


class DummyLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class DummyConsole:
    def print(self, *_args, **_kwargs):
        return None


class DummyFilesystem:
    def cleanup_dir(self, *_args, **_kwargs):
        return None

    def set_permissions(self, *_args, **_kwargs):
        return None

    def set_tree_permissions(self, *_args, **_kwargs):
        return None


def _context() -> RunContext:
    return RunContext(
        run_id="abc",
        db_container_name="db_container",
        upgrade_container_name="up_container",
        network_name="network_name",
        volume_name="volume_name",
        postgres_user="user",
        postgres_password="pass",
        postgres_bootstrap_db="odoo",
        target_database="database",
    )


def test_get_current_version_returns_first_non_empty_query_result():
    service = DatabaseService(
        logger=DummyLogger(),
        console=DummyConsole(),
        filesystem_service=DummyFilesystem(),
    )

    calls = {"count": 0}

    def fake_run_cmd(_cmd, check=False, capture_output=True):
        calls["count"] += 1
        if calls["count"] == 1:
            return subprocess.CompletedProcess(_cmd, 0, stdout="\n", stderr="")
        return subprocess.CompletedProcess(_cmd, 0, stdout="14.0\n", stderr="")

    version = service.get_current_version(_context(), fake_run_cmd)

    assert version == "14.0"


def test_restore_sql_dump_strips_unsupported_parameters_and_retries(tmp_path):
    service = DatabaseService(
        logger=DummyLogger(),
        console=DummyConsole(),
        filesystem_service=DummyFilesystem(),
    )
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    filestore_dir = tmp_path / "filestore"
    filestore_dir.mkdir()

    dump_file = source_dir / "dump.sql"
    dump_file.write_text(
        "-- header\n"
        "SET statement_timeout = 0;\n"
        "SET transaction_timeout = 0;\n"
        "CREATE TABLE foo (id integer);\n",
        encoding="utf-8",
    )

    cp_sources = []
    psql_calls = {"count": 0}

    def fake_run_cmd(cmd, check=False, capture_output=True, **kwargs):  # noqa: ARG001
        if cmd[:2] == ["docker", "cp"]:
            cp_sources.append(cmd[2])
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "psql" in cmd:
            psql_calls["count"] += 1
            if psql_calls["count"] == 1:
                return subprocess.CompletedProcess(
                    cmd,
                    3,
                    stdout="",
                    stderr='psql:/tmp/dump.sql:13: ERROR:  unrecognized configuration parameter "transaction_timeout"',  # noqa: E501
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    service.restore_database("ZIP", str(source_dir), str(filestore_dir), _context(), fake_run_cmd)

    assert psql_calls["count"] == 2
    assert len(cp_sources) == 2
    assert cp_sources[0].endswith("dump.sql")
    assert cp_sources[1].endswith(".compat.sql")
    compat_file = Path(cp_sources[1])
    assert compat_file.exists()
    compat_content = compat_file.read_text(encoding="utf-8")
    assert "SET transaction_timeout = 0;" not in compat_content
    assert "SET statement_timeout = 0;" in compat_content


def test_restore_binary_dump_raises_actionable_error_on_pg_restore_version_mismatch(tmp_path):
    service = DatabaseService(
        logger=DummyLogger(),
        console=DummyConsole(),
        filesystem_service=DummyFilesystem(),
    )
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    filestore_dir = tmp_path / "filestore"
    filestore_dir.mkdir()
    (source_dir / "database.dump").write_bytes(b"binary")

    def fake_run_cmd(cmd, check=False, capture_output=True, **kwargs):  # noqa: ARG001
        if "pg_restore" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="pg_restore: error: unsupported version (1.15) in file header",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(UpgraderError, match="--postgres-version"):
        service.restore_database("DUMP", str(source_dir), str(filestore_dir), _context(), fake_run_cmd)
