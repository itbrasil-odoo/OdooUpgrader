import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import odooupgrader.core as core_module
from odooupgrader.core import OdooUpgrader, UpgraderError


@pytest.fixture
def patch_compose_detection(monkeypatch):
    monkeypatch.setattr(OdooUpgrader, "_get_docker_compose_cmd", lambda self: ["docker", "compose"])


@pytest.fixture
def local_source_file(tmp_path):
    source = tmp_path / "database.dump"
    source.write_text("dummy dump", encoding="utf-8")
    return source


def build_upgrader(tmp_path, source, **kwargs):
    return OdooUpgrader(source=str(source), target_version="15.0", **kwargs)


def test_safe_extract_zip_blocks_path_traversal(tmp_path, patch_compose_detection, local_source_file):
    upgrader = build_upgrader(tmp_path, local_source_file)

    malicious_zip = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_zip, "w") as zip_file:
        zip_file.writestr("../escape.txt", "malicious")

    destination = tmp_path / "extract"
    destination.mkdir()

    with pytest.raises(UpgraderError):
        upgrader._safe_extract_zip(str(malicious_zip), str(destination))

    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_zip_allows_valid_archive(tmp_path, patch_compose_detection, local_source_file):
    upgrader = build_upgrader(tmp_path, local_source_file)

    valid_zip = tmp_path / "valid.zip"
    with zipfile.ZipFile(valid_zip, "w") as zip_file:
        zip_file.writestr("nested/dump.sql", "SELECT 1;")

    destination = tmp_path / "extract"
    destination.mkdir()

    upgrader._safe_extract_zip(str(valid_zip), str(destination))

    assert (destination / "nested" / "dump.sql").read_text(encoding="utf-8") == "SELECT 1;"


def test_http_source_is_blocked_by_default(
    tmp_path,
    monkeypatch,
    patch_compose_detection,
):
    called = {"value": False}

    def fake_request(*args, **kwargs):
        called["value"] = True
        raise AssertionError("network should not be called when HTTP is blocked")

    monkeypatch.setattr(core_module.requests, "request", fake_request)

    upgrader = OdooUpgrader(source="http://example.com/database.dump", target_version="15.0")

    with pytest.raises(UpgraderError, match="insecure HTTP"):
        upgrader.validate_source_accessibility()

    assert called["value"] is False


def test_http_source_can_be_allowed_with_explicit_flag(
    monkeypatch,
    patch_compose_detection,
):
    class FakeProbeResponse:
        def raise_for_status(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(core_module.requests, "request", lambda *args, **kwargs: FakeProbeResponse())

    upgrader = OdooUpgrader(
        source="http://example.com/database.dump",
        target_version="15.0",
        allow_insecure_http=True,
    )

    upgrader.validate_source_accessibility()


class FakeDownloadResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_download_file_rejects_checksum_mismatch(
    tmp_path,
    monkeypatch,
    patch_compose_detection,
    local_source_file,
):
    monkeypatch.setattr(
        core_module.requests,
        "get",
        lambda *args, **kwargs: FakeDownloadResponse(b"hello"),
    )

    upgrader = build_upgrader(tmp_path, local_source_file)
    destination = tmp_path / "download.dump"

    with pytest.raises(UpgraderError, match="Checksum mismatch"):
        upgrader.download_file(
            "https://example.com/database.dump",
            str(destination),
            description="Downloading source DB...",
            expected_sha256="0" * 64,
        )

    assert not destination.exists()


def test_download_file_accepts_matching_checksum(
    tmp_path,
    monkeypatch,
    patch_compose_detection,
    local_source_file,
):
    payload = b"checksum-ok"
    expected = "accb7eefbc70421e3f4fdbe387e92dfc15f82902c3e66320d393368e468b79b3"

    monkeypatch.setattr(
        core_module.requests,
        "get",
        lambda *args, **kwargs: FakeDownloadResponse(payload),
    )

    upgrader = build_upgrader(tmp_path, local_source_file)
    destination = tmp_path / "download.dump"

    upgrader.download_file(
        "https://example.com/database.dump",
        str(destination),
        description="Downloading source DB...",
        expected_sha256=expected,
    )

    assert destination.read_bytes() == payload


def test_invalid_extra_addons_file_is_rejected(tmp_path, patch_compose_detection, local_source_file):
    invalid_addons = tmp_path / "addons.txt"
    invalid_addons.write_text("not a zip", encoding="utf-8")

    upgrader = OdooUpgrader(
        source=str(local_source_file),
        target_version="15.0",
        extra_addons=str(invalid_addons),
    )

    with pytest.raises(UpgraderError, match="Invalid addons format"):
        upgrader.validate_source_accessibility()


def test_run_context_is_unique_per_execution(tmp_path, patch_compose_detection, local_source_file):
    first = OdooUpgrader(source=str(local_source_file), target_version="15.0")
    second = OdooUpgrader(source=str(local_source_file), target_version="15.0")

    assert first.run_context.db_container_name != second.run_context.db_container_name
    assert first.run_context.network_name != second.run_context.network_name


def test_run_upgrade_step_uses_custom_addons_on_intermediate_steps(
    tmp_path,
    monkeypatch,
    patch_compose_detection,
    local_source_file,
):
    monkeypatch.chdir(tmp_path)

    addons_dir = tmp_path / "addons"
    addons_dir.mkdir()

    upgrader = OdooUpgrader(
        source=str(local_source_file),
        target_version="16.0",
        extra_addons=str(addons_dir),
    )

    Path(upgrader.custom_addons_dir).mkdir(parents=True, exist_ok=True)
    Path(upgrader.custom_addons_dir, "requirements.txt").write_text("", encoding="utf-8")

    def fake_run_cmd(cmd, check=True, capture_output=False):
        if "inspect" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO("upgrade logs\n")
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(upgrader, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(core_module.subprocess, "Popen", FakePopen)

    assert upgrader.run_upgrade_step("15.0") is True

    compose_content = Path("odoo-upgrade-composer.yml").read_text(encoding="utf-8")
    assert "--addons-path=/mnt/extra-addons,/mnt/custom-addons" in compose_content
    assert "--load=base,web,openupgrade_framework" in compose_content


def test_run_fails_when_upgrade_does_not_progress(
    tmp_path,
    monkeypatch,
    patch_compose_detection,
    local_source_file,
):
    upgrader = OdooUpgrader(source=str(local_source_file), target_version="15.0")

    monkeypatch.setattr(upgrader, "validate_docker_environment", lambda: None)
    monkeypatch.setattr(upgrader, "validate_source_accessibility", lambda: None)
    monkeypatch.setattr(upgrader, "prepare_environment", lambda: None)
    monkeypatch.setattr(upgrader, "process_extra_addons", lambda: None)
    monkeypatch.setattr(upgrader, "create_db_compose_file", lambda: None)
    monkeypatch.setattr(
        upgrader,
        "_run_cmd",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(upgrader, "wait_for_db", lambda: None)
    monkeypatch.setattr(upgrader, "download_or_copy_source", lambda: str(local_source_file))
    monkeypatch.setattr(upgrader, "process_source_file", lambda *_: "DUMP")
    monkeypatch.setattr(upgrader, "restore_database", lambda *_: None)
    monkeypatch.setattr(upgrader, "run_upgrade_step", lambda *_: True)
    monkeypatch.setattr(upgrader, "cleanup", lambda: None)

    versions = iter(["14.0", "14.0"])
    monkeypatch.setattr(upgrader, "get_current_version", lambda: next(versions))

    assert upgrader.run() == 1


def test_run_cmd_bubbles_stderr_in_error_message(tmp_path, patch_compose_detection, local_source_file):
    upgrader = build_upgrader(tmp_path, local_source_file)

    with pytest.raises(UpgraderError) as error:
        upgrader._run_cmd(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('boom'); sys.exit(1)",
            ],
            check=True,
            capture_output=True,
        )

    assert "boom" in str(error.value)


def test_rejects_unsupported_source_extension(tmp_path, patch_compose_detection):
    source = tmp_path / "database.sql"
    source.write_text("SELECT 1;", encoding="utf-8")

    upgrader = OdooUpgrader(source=str(source), target_version="15.0")

    with pytest.raises(UpgraderError, match="Invalid source format"):
        upgrader.validate_source_accessibility()


def test_dry_run_builds_plan_without_docker_runtime(tmp_path, monkeypatch, patch_compose_detection):
    source = tmp_path / "sample_odoo14.dump"
    source.write_text("synthetic", encoding="utf-8")

    upgrader = OdooUpgrader(
        source=str(source),
        target_version="16.0",
        dry_run=True,
    )

    docker_called = {"value": False}
    cleanup_called = {"value": False}

    def fail_if_called():
        docker_called["value"] = True
        raise AssertionError("Docker validation should not run during --dry-run")

    monkeypatch.setattr(upgrader, "validate_docker_environment", fail_if_called)
    monkeypatch.setattr(upgrader, "cleanup", lambda: cleanup_called.__setitem__("value", True))

    assert upgrader.run() == 0
    assert docker_called["value"] is False
    assert cleanup_called["value"] is False
