import json

import pytest

from odooupgrader.errors import UpgraderError
from odooupgrader.services.state import StateService


class DummyLogger:
    def info(self, *_args, **_kwargs):
        return None


def _metadata(source: str = "db.dump"):
    return {
        "source": source,
        "target_version": "15.0",
        "extra_addons": None,
        "source_sha256": None,
        "extra_addons_sha256": None,
    }


def _run_context():
    return {
        "run_id": "abc123",
        "db_container_name": "db",
        "upgrade_container_name": "upgrade",
        "network_name": "net",
        "volume_name": "vol",
        "postgres_user": "user",
        "postgres_password": "pass",
        "postgres_bootstrap_db": "odoo",
        "target_database": "database",
    }


def test_state_service_creates_and_updates_state(tmp_path):
    state_file = tmp_path / "run-state.json"
    service = StateService(str(state_file), logger=DummyLogger())

    state, resumed = service.initialize(_metadata(), _run_context(), resume=True)

    assert resumed is False
    assert state_file.exists()

    service.mark_step_started(state, "prepare")
    service.mark_step_completed(state, "prepare")
    service.set_current_version(state, "14.0")
    service.set_value(state, "database_restored", True)

    loaded = json.loads(state_file.read_text(encoding="utf-8"))
    assert loaded["current_version"] == "14.0"
    assert loaded["data"]["database_restored"] is True
    assert "prepare" in loaded["completed_steps"]


def test_state_service_resumes_with_same_metadata(tmp_path):
    state_file = tmp_path / "run-state.json"
    service = StateService(str(state_file), logger=DummyLogger())

    state, _ = service.initialize(_metadata(), _run_context(), resume=True)
    service.mark_step_started(state, "prepare")
    service.mark_step_completed(state, "prepare")

    resumed_state, resumed = service.initialize(_metadata(), _run_context(), resume=True)

    assert resumed is True
    assert service.is_step_completed(resumed_state, "prepare")


def test_state_service_rejects_resume_with_different_metadata(tmp_path):
    state_file = tmp_path / "run-state.json"
    service = StateService(str(state_file), logger=DummyLogger())

    service.initialize(_metadata(source="first.dump"), _run_context(), resume=True)

    with pytest.raises(UpgraderError, match="Cannot resume run with different inputs"):
        service.initialize(_metadata(source="second.dump"), _run_context(), resume=True)
