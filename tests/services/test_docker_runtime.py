import subprocess

import pytest

import odooupgrader.services.docker_runtime as docker_runtime_module
from odooupgrader.errors import UpgraderError
from odooupgrader.models import RunContext
from odooupgrader.services.docker_runtime import DockerRuntimeService


class DummyLogger:
    def info(self, *_args, **_kwargs):
        return None


class DummyConsole:
    def print(self, *_args, **_kwargs):
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


def test_create_db_compose_file_contains_dynamic_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = DockerRuntimeService(logger=DummyLogger(), console=DummyConsole())

    service.create_db_compose_file(_context(), postgres_version="15")

    content = (tmp_path / "db-composer.yml").read_text(encoding="utf-8")
    assert "container_name: db_container" in content
    assert "image: postgres:15" in content
    assert "name: network_name" in content


def test_wait_for_db_raises_when_not_ready(monkeypatch):
    service = DockerRuntimeService(logger=DummyLogger(), console=DummyConsole())

    monkeypatch.setattr(docker_runtime_module.time, "sleep", lambda *_args, **_kwargs: None)

    def failing_run_cmd(*_args, **_kwargs):
        return subprocess.CompletedProcess(["docker"], 1, stdout="", stderr="")

    with pytest.raises(UpgraderError, match="failed to become ready"):
        service.wait_for_db(_context(), run_cmd=failing_run_cmd, max_retries=1)
