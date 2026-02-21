"""Input and URL validation helpers for OdooUpgrader."""

import ast
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from odooupgrader.constants import ADDONS_ZIP_EXTENSION, SOURCE_EXTENSIONS
from odooupgrader.errors_catalog import actionable_error
from odooupgrader.errors import UpgraderError


class ValidationService:
    """Validates local/remote sources and protocol policy."""

    MANIFEST_FILES = ("__manifest__.py", "__openerp__.py")

    def __init__(self, allow_insecure_http: bool = False, requests_module=requests):
        self.allow_insecure_http = allow_insecure_http
        self.requests = requests_module

    def is_url(self, location: str) -> bool:
        scheme = urlparse(location).scheme.lower()
        return scheme in {"http", "https"}

    def get_location_extension(self, location: str) -> str:
        path = urlparse(location).path if self.is_url(location) else location
        return Path(path).suffix.lower()

    def ensure_supported_source_extension(self, location: str):
        ext = self.get_location_extension(location)
        if ext not in SOURCE_EXTENSIONS:
            raise UpgraderError(actionable_error("invalid_source_format"))

    def ensure_supported_addons_extension(self, location: str):
        ext = self.get_location_extension(location)
        if ext != ADDONS_ZIP_EXTENSION:
            raise UpgraderError(actionable_error("invalid_addons_format"))

    def enforce_https_policy(self, location: str, label: str, logger, console):
        if not self.is_url(location):
            return

        scheme = urlparse(location).scheme.lower()
        if scheme == "http" and not self.allow_insecure_http:
            raise UpgraderError(actionable_error("insecure_http", label=label))

        if scheme == "http" and self.allow_insecure_http:
            logger.warning("Insecure HTTP enabled for %s: %s", label, location)
            console.print(
                f"[yellow]Warning:[/yellow] Using insecure HTTP for {label}. "
                "Prefer HTTPS whenever possible."
            )

    def probe_url(self, location: str, label: str, logger, console):
        self.enforce_https_policy(location, label, logger, console)

        last_error: Optional[Exception] = None
        for method in ("HEAD", "GET"):
            try:
                response = self.requests.request(
                    method,
                    location,
                    allow_redirects=True,
                    timeout=30,
                    stream=(method == "GET"),
                )
                response.raise_for_status()
                response.close()
                return
            except self.requests.RequestException as exc:
                last_error = exc

        raise UpgraderError(f"{label} is not accessible: {last_error}")

    def validate_source_accessibility(self, source: str, extra_addons: Optional[str], logger, console):
        self.ensure_supported_source_extension(source)

        if self.is_url(source):
            self.probe_url(source, "source URL", logger, console)
        else:
            if not Path(source).exists():
                raise UpgraderError(actionable_error("source_not_found", path=source))
            if not Path(source).is_file():
                raise UpgraderError(f"Source path must be a file: {source}")

        if not extra_addons:
            return

        if self.is_url(extra_addons):
            self.ensure_supported_addons_extension(extra_addons)
            self.probe_url(extra_addons, "extra addons URL", logger, console)
            return

        addons_path = Path(extra_addons)
        if not addons_path.exists():
            raise UpgraderError(actionable_error("extra_addons_not_found", path=extra_addons))

        if addons_path.is_dir():
            self.validate_addons_structure(addons_path)
            return

        if addons_path.is_file():
            self.ensure_supported_addons_extension(extra_addons)
            return

        raise UpgraderError(
            "Invalid extra addons source. Provide a local directory, a local `.zip` file, "
            "or an HTTPS URL to a `.zip` file."
        )

    def validate_addons_structure(self, addons_path: Path):
        if not addons_path.exists() or not addons_path.is_dir():
            raise UpgraderError(f"Extra addons directory not found: {addons_path}")

        if self._is_odoo_module(addons_path):
            self._validate_manifest(addons_path)
            return

        module_dirs = [
            item
            for item in addons_path.iterdir()
            if item.is_dir() and not item.name.startswith(".") and item.name != "__pycache__"
        ]

        if not module_dirs:
            raise UpgraderError(
                f"No addon modules found in '{addons_path}'. "
                "Provide a directory containing at least one valid Odoo module."
            )

        valid_modules = 0
        for module_dir in module_dirs:
            if self._is_odoo_module(module_dir):
                self._validate_manifest(module_dir)
                valid_modules += 1

        if valid_modules == 0:
            raise UpgraderError(
                f"No valid Odoo module manifests found in '{addons_path}'. "
                "Each module must include `__manifest__.py` or `__openerp__.py`."
            )

    def _is_odoo_module(self, path: Path) -> bool:
        return any((path / manifest_name).is_file() for manifest_name in self.MANIFEST_FILES)

    def _validate_manifest(self, module_path: Path):
        manifest_file = None
        for file_name in self.MANIFEST_FILES:
            candidate = module_path / file_name
            if candidate.is_file():
                manifest_file = candidate
                break

        if manifest_file is None:
            raise UpgraderError(f"Missing manifest file in addon module '{module_path.name}'.")

        try:
            manifest_data = ast.literal_eval(manifest_file.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError) as exc:
            raise UpgraderError(
                f"Invalid manifest syntax in '{manifest_file}'. "
                "The manifest must be a valid Python dictionary literal."
            ) from exc
        except OSError as exc:
            raise UpgraderError(f"Could not read manifest file '{manifest_file}': {exc}") from exc

        if not isinstance(manifest_data, dict):
            raise UpgraderError(f"Manifest '{manifest_file}' must define a dictionary.")

        name = manifest_data.get("name")
        depends = manifest_data.get("depends")
        if not isinstance(name, str) or not name.strip():
            raise UpgraderError(f"Manifest '{manifest_file}' must define a non-empty 'name'.")

        if depends is None:
            raise UpgraderError(f"Manifest '{manifest_file}' must define 'depends'.")

        if not isinstance(depends, (list, tuple)) or not all(
            isinstance(dep, str) and dep.strip() for dep in depends
        ):
            raise UpgraderError(
                f"Manifest '{manifest_file}' has invalid 'depends'. It must be a list of module names."
            )
