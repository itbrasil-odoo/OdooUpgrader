import subprocess
from types import SimpleNamespace

from odooupgrader.services.module_audit import ModuleAuditService


class DummyLogger:
    def debug(self, *_args, **_kwargs):
        return None


class DummyConsole:
    def print(self, *_args, **_kwargs):
        return None


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeRequests:
    def get(self, url, headers=None, params=None, timeout=20):  # noqa: ARG002
        if "module_ok" in url:
            return FakeResponse(200, payload={"type": "dir"})
        if "module_missing" in url:
            return FakeResponse(404, payload={"message": "Not Found"})
        return FakeResponse(500, payload={"message": "Server error"})


def test_discover_local_modules_handles_recursive_and_direct_addons(tmp_path):
    addons_root = tmp_path / "addons"
    oca_repo = addons_root / "OCA" / "server-tools"
    oca_repo.mkdir(parents=True)
    (oca_repo / "module_oca").mkdir()
    (oca_repo / "module_oca" / "__manifest__.py").write_text(
        "{'name': 'module_oca', 'depends': ['base']}",
        encoding="utf-8",
    )

    custom_root = addons_root / "custom" / "my_module"
    custom_root.mkdir(parents=True)
    (custom_root / "__manifest__.py").write_text(
        "{'name': 'my_module', 'depends': ['base']}",
        encoding="utf-8",
    )

    direct_module = tmp_path / "direct_module"
    direct_module.mkdir()
    (direct_module / "__manifest__.py").write_text(
        "{'name': 'direct_module', 'depends': ['base']}",
        encoding="utf-8",
    )

    service = ModuleAuditService(logger=DummyLogger(), console=DummyConsole(), requests_module=FakeRequests())
    discovered = service.discover_local_modules(
        [str(addons_root), str(direct_module)],
        recursive=True,
    )

    assert "module_oca" in discovered
    assert "my_module" in discovered
    assert "direct_module" in discovered
    assert discovered["module_oca"]["is_oca"] is True
    assert "server-tools" in discovered["module_oca"]["oca_repositories"]


def test_run_audit_reports_missing_oca_modules(tmp_path):
    addons_root = tmp_path / "addons"
    repo_root = addons_root / "OCA" / "server-tools"
    (repo_root / "module_ok").mkdir(parents=True)
    (repo_root / "module_ok" / "__manifest__.py").write_text(
        "{'name': 'module_ok', 'depends': ['base']}",
        encoding="utf-8",
    )
    (repo_root / "module_missing").mkdir(parents=True)
    (repo_root / "module_missing" / "__manifest__.py").write_text(
        "{'name': 'module_missing', 'depends': ['base']}",
        encoding="utf-8",
    )

    run_context = SimpleNamespace(
        db_container_name="db",
        postgres_user="odoo",
        target_database="database",
    )

    def fake_run_cmd(cmd, check=False, capture_output=False):  # noqa: ARG001
        stdout = (
            "base|17.0|installed\n"
            "module_ok|17.0|installed\n"
            "module_missing|17.0|installed\n"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    service = ModuleAuditService(logger=DummyLogger(), console=DummyConsole(), requests_module=FakeRequests())
    report_file = tmp_path / "report.json"
    report = service.run_audit(
        run_context=run_context,
        run_cmd=fake_run_cmd,
        target_version="18.0",
        addons_locations=[str(addons_root)],
        recursive=True,
        output_file=str(report_file),
    )

    assert report["installed_modules_count"] == 3
    assert report["oca"]["checked_modules_count"] == 2
    assert report["oca"]["missing_in_target_count"] == 1
    assert report["oca"]["missing_in_target"][0]["module"] == "module_missing"
    assert report_file.exists()
