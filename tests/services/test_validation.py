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
