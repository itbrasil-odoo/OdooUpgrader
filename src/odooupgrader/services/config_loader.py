"""Configuration loader for OdooUpgrader."""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from odooupgrader.errors import UpgraderError


class ConfigLoader:
    """Loads YAML configuration files for CLI defaults."""

    SUPPORTED_KEYS = {
        "source",
        "version",
        "extra_addons",
        "verbose",
        "postgres_version",
        "log_file",
        "allow_insecure_http",
        "source_sha256",
        "extra_addons_sha256",
        "resume",
        "state_file",
        "download_timeout",
        "retry_count",
        "retry_backoff_seconds",
        "step_timeout_minutes",
        "dry_run",
    }

    def load(self, config_path: Optional[str]) -> Dict[str, Any]:
        if not config_path:
            return {}

        path = Path(config_path)
        if not path.exists():
            raise UpgraderError(f"Config file not found: {config_path}")

        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            raise UpgraderError(f"Invalid config file '{config_path}': {exc}") from exc

        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise UpgraderError("Config file must contain a YAML mapping at the root.")

        unknown = sorted(set(parsed.keys()) - self.SUPPORTED_KEYS)
        if unknown:
            unknown_list = ", ".join(unknown)
            raise UpgraderError(f"Unknown configuration keys: {unknown_list}")

        return parsed
