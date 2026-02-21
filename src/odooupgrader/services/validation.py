"""Input and URL validation helpers for OdooUpgrader."""

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from odooupgrader.constants import ADDONS_ZIP_EXTENSION, SOURCE_EXTENSIONS
from odooupgrader.errors import UpgraderError


class ValidationService:
    """Validates local/remote sources and protocol policy."""

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
            raise UpgraderError(
                "Invalid source format. Supported formats are `.zip` and `.dump`. "
                "Provide a source file/URL ending with one of these extensions."
            )

    def ensure_supported_addons_extension(self, location: str):
        ext = self.get_location_extension(location)
        if ext != ADDONS_ZIP_EXTENSION:
            raise UpgraderError("Invalid addons format. Remote or file addons must be a `.zip` file.")

    def enforce_https_policy(self, location: str, label: str, logger, console):
        if not self.is_url(location):
            return

        scheme = urlparse(location).scheme.lower()
        if scheme == "http" and not self.allow_insecure_http:
            raise UpgraderError(
                f"{label} uses insecure HTTP. Use HTTPS instead, or pass "
                "`--allow-insecure-http` only when you explicitly trust the endpoint."
            )

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
                raise UpgraderError(f"Source file not found: {source}")
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
            raise UpgraderError(f"Extra addons path not found: {extra_addons}")

        if addons_path.is_dir():
            return

        if addons_path.is_file():
            self.ensure_supported_addons_extension(extra_addons)
            return

        raise UpgraderError(
            "Invalid extra addons source. Provide a local directory, a local `.zip` file, "
            "or an HTTPS URL to a `.zip` file."
        )
