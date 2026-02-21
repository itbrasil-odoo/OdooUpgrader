import zipfile

import pytest

from odooupgrader.errors import UpgraderError
from odooupgrader.services.archive import ArchiveService


def test_archive_service_blocks_path_traversal(tmp_path):
    service = ArchiveService()

    zip_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.writestr("../escape.txt", "malicious")

    destination = tmp_path / "extract"
    destination.mkdir()

    with pytest.raises(UpgraderError):
        service.safe_extract_zip(str(zip_path), str(destination))


def test_archive_service_extracts_valid_zip(tmp_path):
    service = ArchiveService()

    zip_path = tmp_path / "valid.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.writestr("nested/dump.sql", "SELECT 1;")

    destination = tmp_path / "extract"
    destination.mkdir()

    service.safe_extract_zip(str(zip_path), str(destination))

    assert (destination / "nested" / "dump.sql").read_text(encoding="utf-8") == "SELECT 1;"
