"""Run manifest generation service."""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class ManifestService:
    """Collects execution metadata and writes run manifest JSON."""

    def __init__(self, manifest_file: str, logger):
        self.manifest_file = manifest_file
        self.logger = logger
        self.manifest: Dict[str, Any] = {
            "run_id": None,
            "status": "running",
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "metadata": {},
            "versions": {
                "source": None,
                "target": None,
                "current": None,
            },
            "steps": [],
            "artifacts": {},
            "error": None,
        }

    def start_run(self, run_id: str, metadata: Dict[str, Any]):
        self.manifest["run_id"] = run_id
        self.manifest["status"] = "running"
        self.manifest["started_at"] = self._now()
        self.manifest["metadata"] = metadata
        self.write()

    def set_versions(self, source: Optional[str], target: Optional[str], current: Optional[str]):
        self.manifest["versions"]["source"] = source
        self.manifest["versions"]["target"] = target
        self.manifest["versions"]["current"] = current
        self.write()

    def step_started(self, step_name: str, details: Optional[Dict[str, Any]] = None):
        self.manifest["steps"].append(
            {
                "name": step_name,
                "status": "running",
                "started_at": self._now(),
                "finished_at": None,
                "duration_seconds": None,
                "details": details or {},
                "error": None,
            }
        )
        self.write()

    def step_finished(
        self,
        step_name: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        for step in reversed(self.manifest["steps"]):
            if step["name"] == step_name and step["status"] == "running":
                step["status"] = status
                step["finished_at"] = self._now()
                step["error"] = error
                if details:
                    step["details"].update(details)
                started_at = datetime.fromisoformat(step["started_at"])
                finished_at = datetime.fromisoformat(step["finished_at"])
                step["duration_seconds"] = (finished_at - started_at).total_seconds()
                break
        self.write()

    def add_artifact(self, key: str, value: str):
        self.manifest["artifacts"][key] = value
        self.write()

    def finalize(self, status: str, error: Optional[str] = None):
        self.manifest["status"] = status
        self.manifest["finished_at"] = self._now()
        if self.manifest.get("started_at"):
            started_at = datetime.fromisoformat(self.manifest["started_at"])
            finished_at = datetime.fromisoformat(self.manifest["finished_at"])
            self.manifest["duration_seconds"] = (finished_at - started_at).total_seconds()
        self.manifest["error"] = error
        self.write()

    def write(self):
        os.makedirs(os.path.dirname(self.manifest_file) or ".", exist_ok=True)

        fd, temp_path = tempfile.mkstemp(prefix="run-manifest-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                json.dump(self.manifest, file_obj, indent=2, sort_keys=True)
                file_obj.write("\n")
            os.replace(temp_path, self.manifest_file)
        except OSError as exc:
            self.logger.warning("Could not write manifest file '%s': %s", self.manifest_file, exc)
            try:
                os.remove(temp_path)
            except OSError:
                pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
