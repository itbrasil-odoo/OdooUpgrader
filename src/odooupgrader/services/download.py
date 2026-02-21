"""Download service with progress reporting and checksum validation."""

import hashlib
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from odooupgrader.errors import UpgraderError


class DownloadService:
    """Handles remote download logic and source retrieval."""

    def __init__(self, validation_service, logger, console, requests_module):
        self.validation_service = validation_service
        self.logger = logger
        self.console = console
        self.requests = requests_module

    def download_file(
        self,
        url: str,
        dest_path: str,
        description: str = "Downloading...",
        expected_sha256: Optional[str] = None,
    ):
        self.logger.info("Downloading %s to %s", url, dest_path)
        self.validation_service.enforce_https_policy(url, description, self.logger, self.console)

        hasher = hashlib.sha256() if expected_sha256 else None

        try:
            with self.requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", 0))

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    "•",
                    TimeElapsedColumn(),
                    console=self.console,
                ) as progress:
                    task = progress.add_task(f"[cyan]{description}", total=total_size or None)
                    with open(dest_path, "wb") as file_obj:
                        for chunk in response.iter_content(chunk_size=8192):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            if hasher:
                                hasher.update(chunk)
                            progress.update(task, advance=len(chunk))

            if hasher:
                downloaded_sha = hasher.hexdigest()
                if downloaded_sha != expected_sha256:
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                    raise UpgraderError(
                        f"Checksum mismatch for {description}. Expected {expected_sha256}, "
                        f"but got {downloaded_sha}."
                    )

        except self.requests.RequestException as exc:
            raise UpgraderError(f"Download failed for {description}: {exc}") from exc

    def download_or_copy_source(self, source: str, source_dir: str, source_sha256: Optional[str]) -> str:
        if self.validation_service.is_url(source):
            url_path = urlparse(source).path
            ext = Path(url_path).suffix.lower()
            filename = os.path.basename(url_path) or f"downloaded_db{ext or '.dump'}"
            target_path = os.path.join(source_dir, filename)
            self.download_file(
                source,
                target_path,
                "Downloading source DB...",
                expected_sha256=source_sha256,
            )
            return target_path

        return source
