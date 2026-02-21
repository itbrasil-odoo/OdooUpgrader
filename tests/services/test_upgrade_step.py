import io
import subprocess

from rich.console import Console

from odooupgrader.models import RunContext
from odooupgrader.services.upgrade_step import UpgradeStepService


class DummyLogger:
    def info(self, *_args, **_kwargs):
        return None

    def debug(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class DummyConsole:
    def print(self, *_args, **_kwargs):
        return None


def _build_context() -> RunContext:
    return RunContext(
        run_id="abc123",
        db_container_name="db_name",
        upgrade_container_name="upgrade_name",
        network_name="net_name",
        volume_name="vol_name",
        postgres_user="pg_user",
        postgres_password="pg_pass",
        postgres_bootstrap_db="odoo",
        target_database="database",
    )


def test_build_upgrade_dockerfile_includes_custom_addons_section():
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())

    dockerfile = service.build_upgrade_dockerfile("16.0", include_custom_addons=True)

    assert "FROM odoo:16.0" in dockerfile
    assert "ENV PIP_BREAK_SYSTEM_PACKAGES=1" in dockerfile
    assert "COPY --chown=odoo:odoo ./output/custom_addons/ /mnt/custom-addons/" in dockerfile


def test_build_upgrade_compose_uses_dynamic_runtime_names():
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())

    compose = service.build_upgrade_compose(
        _build_context(), extra_addons_path_arg=",/mnt/custom-addons"
    )

    assert "container_name: upgrade_name" in compose
    assert "- HOST=db_name" in compose
    assert "--addons-path=/mnt/extra-addons,/mnt/custom-addons" in compose
    assert "name: net_name" in compose


def test_build_upgrade_compose_includes_runtime_user_when_provided():
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())

    compose = service.build_upgrade_compose(
        _build_context(),
        extra_addons_path_arg="",
        runtime_uid=1000,
        runtime_gid=1000,
    )

    assert 'user: "1000:1000"' in compose


def test_discover_custom_addons_paths_handles_recursive_layout(tmp_path):
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())
    root = tmp_path / "custom_addons"

    (root / "OCA" / "server-tools" / "module_a").mkdir(parents=True)
    (root / "OCA" / "server-tools" / "module_a" / "__manifest__.py").write_text(
        "{'name': 'module_a', 'depends': ['base']}",
        encoding="utf-8",
    )

    (root / "itbrasil" / "manufacture" / "module_b").mkdir(parents=True)
    (root / "itbrasil" / "manufacture" / "module_b" / "__manifest__.py").write_text(
        "{'name': 'module_b', 'depends': ['base']}",
        encoding="utf-8",
    )

    (root / "root_module").mkdir(parents=True)
    (root / "root_module" / "__manifest__.py").write_text(
        "{'name': 'root_module', 'depends': ['base']}",
        encoding="utf-8",
    )

    discovered = service.discover_custom_addons_paths(str(root))

    assert discovered == sorted(
        [
            "/mnt/custom-addons",
            "/mnt/custom-addons/OCA/server-tools",
            "/mnt/custom-addons/itbrasil/manufacture",
        ]
    )


def test_run_upgrade_step_does_not_retry_non_transient_failures(monkeypatch, tmp_path):
    service = UpgradeStepService(logger=DummyLogger(), console=Console(record=True))
    context = _build_context()
    monkeypatch.chdir(tmp_path)

    cache_root = tmp_path / ".cache" / "openupgrade"
    version_cache = cache_root / "15.0"
    version_cache.mkdir(parents=True)
    (version_cache / "requirements.txt").write_text("openupgradelib\n", encoding="utf-8")

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)

    popen_calls = {"count": 0}

    class FakePopen:
        def __init__(self, *_args, **_kwargs):
            popen_calls["count"] += 1
            with open(output_dir / "odoo.log", "a", encoding="utf-8") as log_file:
                log_file.write("ValueError: Module purchase_request: invalid manifest\n")
            self.stdout = io.StringIO("container exited with code 255\n")
            self.returncode = 1

        def wait(self, timeout=None):  # noqa: ARG002
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def kill(self):
            self.returncode = 1

    class FakeSubprocessModule:
        PIPE = object()
        STDOUT = object()
        Popen = FakePopen

    def fake_run_cmd(cmd, **_kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = service.run_upgrade_step(
        target_version="15.0",
        run_context=context,
        compose_cmd=["docker", "compose"],
        extra_addons=None,
        custom_addons_dir=str(tmp_path / "custom_addons"),
        run_cmd=fake_run_cmd,
        verbose=False,
        subprocess_module=FakeSubprocessModule,
        cache_root=str(cache_root),
        retry_count=1,
        retry_backoff_seconds=0.0,
        step_timeout_seconds=None,
    )

    assert result is False
    assert popen_calls["count"] == 1


def test_run_upgrade_step_retries_transient_failures(monkeypatch, tmp_path):
    service = UpgradeStepService(logger=DummyLogger(), console=Console(record=True))
    context = _build_context()
    monkeypatch.chdir(tmp_path)

    cache_root = tmp_path / ".cache" / "openupgrade"
    version_cache = cache_root / "15.0"
    version_cache.mkdir(parents=True)
    (version_cache / "requirements.txt").write_text("openupgradelib\n", encoding="utf-8")

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)

    popen_calls = {"count": 0}

    class FakePopen:
        def __init__(self, *_args, **_kwargs):
            popen_calls["count"] += 1
            with open(output_dir / "odoo.log", "a", encoding="utf-8") as log_file:
                log_file.write("Connection reset by peer while downloading dependency\n")
            self.stdout = io.StringIO("network timeout\n")
            self.returncode = 1

        def wait(self, timeout=None):  # noqa: ARG002
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def kill(self):
            self.returncode = 1

    class FakeSubprocessModule:
        PIPE = object()
        STDOUT = object()
        Popen = FakePopen

    run_cmd_calls = []

    def fake_run_cmd(cmd, **_kwargs):
        run_cmd_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = service.run_upgrade_step(
        target_version="15.0",
        run_context=context,
        compose_cmd=["docker", "compose"],
        extra_addons=None,
        custom_addons_dir=str(tmp_path / "custom_addons"),
        run_cmd=fake_run_cmd,
        verbose=False,
        subprocess_module=FakeSubprocessModule,
        cache_root=str(cache_root),
        retry_count=1,
        retry_backoff_seconds=0.0,
        step_timeout_seconds=None,
    )

    assert result is False
    assert popen_calls["count"] == 2
    assert any(call[-1] == "down" for call in run_cmd_calls if call)


def test_run_upgrade_step_respects_timeout(monkeypatch, tmp_path):
    service = UpgradeStepService(logger=DummyLogger(), console=Console(record=True))
    context = _build_context()
    monkeypatch.chdir(tmp_path)

    def fake_run_cmd(_cmd, **_kwargs):
        return subprocess.CompletedProcess(_cmd, 0, stdout="0\n", stderr="")

    class FakePopen:
        def __init__(self, *_args, **_kwargs):
            self.stdout = io.StringIO("line1\nline2\n")
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.returncode = 1

        def kill(self):
            self.returncode = 1

    class FakeSubprocessModule:
        PIPE = object()
        STDOUT = object()
        Popen = FakePopen

    monotonic_values = iter([0.0, 999.0, 999.0])
    monkeypatch.setattr(
        "odooupgrader.services.upgrade_step.time.monotonic", lambda: next(monotonic_values)
    )

    result = service.run_upgrade_step(
        target_version="15.0",
        run_context=context,
        compose_cmd=["docker", "compose"],
        extra_addons=None,
        custom_addons_dir=str(tmp_path / "custom_addons"),
        run_cmd=fake_run_cmd,
        verbose=False,
        subprocess_module=FakeSubprocessModule,
        cache_root=str(tmp_path / ".cache" / "openupgrade"),
        retry_count=0,
        retry_backoff_seconds=0.0,
        step_timeout_seconds=0.1,
    )

    assert result is False


def test_ensure_openupgrade_cache_reuses_existing_version(tmp_path):
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())
    cache_root = tmp_path / ".cache" / "openupgrade"
    version_cache = cache_root / "15.0"
    version_cache.mkdir(parents=True)
    (version_cache / "requirements.txt").write_text("psycopg2\n", encoding="utf-8")

    calls = []

    def fake_run_cmd(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = service.ensure_openupgrade_cache(
        target_version="15.0",
        cache_root=str(cache_root),
        run_cmd=fake_run_cmd,
    )

    assert result == str(version_cache)
    assert calls == []


def test_ensure_openupgrade_cache_clones_when_missing(tmp_path):
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())
    cache_root = tmp_path / ".cache" / "openupgrade"

    calls = []

    def fake_run_cmd(cmd, **_kwargs):
        calls.append(cmd)
        version_cache = cache_root / "16.0"
        version_cache.mkdir(parents=True, exist_ok=True)
        (version_cache / "requirements.txt").write_text("openupgradelib\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = service.ensure_openupgrade_cache(
        target_version="16.0",
        cache_root=str(cache_root),
        run_cmd=fake_run_cmd,
    )

    assert result.endswith("16.0")
    assert calls
