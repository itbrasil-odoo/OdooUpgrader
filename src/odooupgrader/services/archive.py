"""Archive extraction helpers for OdooUpgrader."""

import os
import shutil
import zipfile
from pathlib import Path

from odooupgrader.errors import UpgraderError


class ArchiveService:
    """Encapsulates safe archive extraction logic."""

    def is_within_dir(self, base_dir: Path, candidate: Path) -> bool:
        try:
            return os.path.commonpath([str(base_dir), str(candidate)]) == str(base_dir)
        except ValueError:
            return False

    def safe_extract_zip(self, zip_path: str, destination_dir: str):
        base = Path(destination_dir).resolve()

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                for member in zip_ref.infolist():
                    normalized_name = member.filename.replace("\\", "/")
                    target_path = (base / normalized_name).resolve()

                    if not self.is_within_dir(base, target_path):
                        raise UpgraderError(
                            f"Unsafe ZIP entry detected: `{member.filename}`. "
                            "Archive extraction aborted to prevent path traversal."
                        )

                    file_type = (member.external_attr >> 16) & 0o170000
                    if file_type == 0o120000:
                        raise UpgraderError(
                            f"Unsafe ZIP entry detected: `{member.filename}` is a symbolic link."
                        )

                for member in zip_ref.infolist():
                    normalized_name = member.filename.replace("\\", "/")
                    target_path = (base / normalized_name).resolve()

                    if member.is_dir() or normalized_name.endswith("/"):
                        target_path.mkdir(parents=True, exist_ok=True)
                        continue

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zip_ref.open(member, "r") as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as exc:
            raise UpgraderError(f"Invalid ZIP archive: {zip_path}") from exc
