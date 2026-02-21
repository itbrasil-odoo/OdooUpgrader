"""Execution state persistence service for checkpoint/resume support."""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from odooupgrader.errors import UpgraderError


class StateService:
    """Persists and validates resumable execution state."""

    SCHEMA_VERSION = 1

    def __init__(self, state_file: str, logger):
        self.state_file = state_file
        self.logger = logger

    def load(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.state_file):
            return None

        try:
            with open(self.state_file, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except (OSError, json.JSONDecodeError) as exc:
            raise UpgraderError(f"Could not read state file '{self.state_file}': {exc}") from exc

        if not isinstance(data, dict):
            raise UpgraderError(f"State file '{self.state_file}' has invalid format.")

        return data

    def save(self, state: Dict[str, Any]):
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        state["schema_version"] = self.SCHEMA_VERSION
        state["updated_at"] = self._now()

        fd, temp_path = tempfile.mkstemp(prefix="run-state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                json.dump(state, file_obj, indent=2, sort_keys=True)
                file_obj.write("\n")
            os.replace(temp_path, self.state_file)
        except OSError as exc:
            raise UpgraderError(f"Could not write state file '{self.state_file}': {exc}") from exc
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def initialize(
        self,
        metadata: Dict[str, Any],
        run_context: Dict[str, Any],
        resume: bool,
    ) -> Tuple[Dict[str, Any], bool]:
        existing_state = self.load()

        if resume and existing_state:
            self._validate_resume_compatibility(existing_state, metadata)
            return existing_state, True

        state = {
            "schema_version": self.SCHEMA_VERSION,
            "created_at": self._now(),
            "updated_at": self._now(),
            "status": "running",
            "metadata": metadata,
            "run_context": run_context,
            "completed_steps": [],
            "current_step": None,
            "current_version": None,
            "data": {},
            "steps": [],
            "last_error": None,
        }
        self.save(state)
        return state, False

    def mark_step_started(self, state: Dict[str, Any], step_name: str):
        state["current_step"] = step_name
        state["steps"].append(
            {
                "name": step_name,
                "status": "running",
                "started_at": self._now(),
                "finished_at": None,
                "error": None,
            }
        )
        self.save(state)

    def mark_step_completed(self, state: Dict[str, Any], step_name: str):
        self._update_step_status(state, step_name, "success")
        if step_name not in state["completed_steps"]:
            state["completed_steps"].append(step_name)
        state["current_step"] = None
        self.save(state)

    def mark_step_failed(self, state: Dict[str, Any], step_name: str, error: str):
        self._update_step_status(state, step_name, "failed", error=error)
        state["status"] = "failed"
        state["last_error"] = error
        self.save(state)

    def mark_status(self, state: Dict[str, Any], status: str, error: Optional[str] = None):
        state["status"] = status
        if error:
            state["last_error"] = error
        self.save(state)

    def is_step_completed(self, state: Dict[str, Any], step_name: str) -> bool:
        return step_name in state.get("completed_steps", [])

    def set_current_version(self, state: Dict[str, Any], current_version: str):
        state["current_version"] = current_version
        self.save(state)

    def get_current_version(self, state: Dict[str, Any]) -> Optional[str]:
        return state.get("current_version")

    def set_value(self, state: Dict[str, Any], key: str, value: Any):
        state.setdefault("data", {})[key] = value
        self.save(state)

    def get_value(self, state: Dict[str, Any], key: str, default: Any = None) -> Any:
        return state.get("data", {}).get(key, default)

    def _validate_resume_compatibility(self, state: Dict[str, Any], metadata: Dict[str, Any]):
        existing_meta = state.get("metadata", {})
        keys_to_match = (
            "source",
            "target_version",
            "extra_addons",
            "source_sha256",
            "extra_addons_sha256",
        )
        mismatches = []
        for key in keys_to_match:
            if existing_meta.get(key) != metadata.get(key):
                mismatches.append(key)

        if mismatches:
            mismatch_list = ", ".join(mismatches)
            raise UpgraderError(
                "Cannot resume run with different inputs. " f"Mismatched fields: {mismatch_list}."
            )

    def _update_step_status(
        self,
        state: Dict[str, Any],
        step_name: str,
        status: str,
        error: Optional[str] = None,
    ):
        for step in reversed(state.get("steps", [])):
            if step.get("name") == step_name and step.get("status") == "running":
                step["status"] = status
                step["finished_at"] = self._now()
                step["error"] = error
                return

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
