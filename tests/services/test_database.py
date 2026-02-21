import subprocess

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
