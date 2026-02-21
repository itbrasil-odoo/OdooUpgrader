import json

from odooupgrader.services.manifest import ManifestService


class DummyLogger:
    def warning(self, *_args, **_kwargs):
        return None


def test_manifest_service_writes_run_metadata(tmp_path):
    manifest_file = tmp_path / "run-manifest.json"
    service = ManifestService(str(manifest_file), logger=DummyLogger())

    service.start_run("run-123", {"source": "db.dump", "target_version": "15.0"})
    service.set_versions("14.0", "15.0", "14.0")
    service.step_started("prepare")
    service.step_finished("prepare", "success")
    service.add_artifact("upgraded_zip", "output/upgraded.zip")
    service.finalize("success")

    data = json.loads(manifest_file.read_text(encoding="utf-8"))

    assert data["run_id"] == "run-123"
    assert data["status"] == "success"
    assert data["versions"]["source"] == "14.0"
    assert data["artifacts"]["upgraded_zip"] == "output/upgraded.zip"
    assert data["steps"][0]["name"] == "prepare"
    assert data["steps"][0]["status"] == "success"
