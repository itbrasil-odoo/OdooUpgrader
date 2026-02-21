import pytest

from odooupgrader.errors import UpgraderError
from odooupgrader.services.validation import ValidationService


class DummyLogger:
    def warning(self, *_args, **_kwargs):
        return None


class DummyConsole:
    def print(self, *_args, **_kwargs):
        return None


class FakeRequestsModule:
    class RequestException(Exception):
        pass

    def __init__(self):
        self.called = False

    def request(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("network should not be called")


def test_validation_service_blocks_insecure_http_before_network():
    fake_requests = FakeRequestsModule()
    service = ValidationService(allow_insecure_http=False, requests_module=fake_requests)

    with pytest.raises(UpgraderError, match="insecure HTTP"):
        service.validate_source_accessibility(
            source="http://example.com/database.dump",
            extra_addons=None,
            logger=DummyLogger(),
            console=DummyConsole(),
        )

    assert fake_requests.called is False


def test_validation_service_rejects_invalid_source_extension(tmp_path):
    source = tmp_path / "database.sql"
    source.write_text("SELECT 1;", encoding="utf-8")

    service = ValidationService()

    with pytest.raises(UpgraderError, match="Invalid source format"):
        service.validate_source_accessibility(
            source=str(source),
            extra_addons=None,
            logger=DummyLogger(),
            console=DummyConsole(),
        )


def test_validation_service_accepts_valid_local_addons_directory(tmp_path):
    source = tmp_path / "database.dump"
    source.write_text("dummy", encoding="utf-8")

    addons_root = tmp_path / "addons"
    module = addons_root / "my_module"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        "{'name': 'My Module', 'version': '14.0.1.0.0', 'depends': ['base']}",
        encoding="utf-8",
    )

    service = ValidationService()

    service.validate_source_accessibility(
        source=str(source),
        extra_addons=str(addons_root),
        logger=DummyLogger(),
        console=DummyConsole(),
    )


def test_validation_service_rejects_addons_manifest_with_invalid_depends(tmp_path):
    source = tmp_path / "database.dump"
    source.write_text("dummy", encoding="utf-8")

    addons_root = tmp_path / "addons"
    module = addons_root / "bad_module"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        "{'name': 'Bad Module', 'version': '14.0.1.0.0', 'depends': 'base'}",
        encoding="utf-8",
    )

    service = ValidationService()

    with pytest.raises(UpgraderError, match="invalid 'depends'"):
        service.validate_source_accessibility(
            source=str(source),
            extra_addons=str(addons_root),
            logger=DummyLogger(),
            console=DummyConsole(),
        )
