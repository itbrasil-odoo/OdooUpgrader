from rich.console import Console

from odooupgrader.services.download import DownloadService


class DummyLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class FakeValidationService:
    def is_url(self, location: str) -> bool:
        return location.startswith("https://")

    def enforce_https_policy(self, *_args, **_kwargs):
        return None


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeRequestsModule:
    class RequestException(Exception):
        pass

    def __init__(self, payload: bytes):
        self.payload = payload

    def get(self, *_args, **_kwargs):
        return FakeResponse(self.payload)


class FlakyRequestsModule:
    class RequestException(Exception):
        pass

    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise self.RequestException("temporary download error")
        return FakeResponse(self.payload)


def test_download_or_copy_source_downloads_remote_file(tmp_path):
    requests_module = FakeRequestsModule(payload=b"dump-bytes")
    service = DownloadService(
        validation_service=FakeValidationService(),
        logger=DummyLogger(),
        console=Console(record=True),
        requests_module=requests_module,
    )

    source = "https://example.com/database.dump"
    downloaded_path = service.download_or_copy_source(source, str(tmp_path), None)

    assert downloaded_path.endswith("database.dump")
    assert (tmp_path / "database.dump").read_bytes() == b"dump-bytes"


def test_download_or_copy_source_returns_local_path(tmp_path):
    requests_module = FakeRequestsModule(payload=b"unused")
    service = DownloadService(
        validation_service=FakeValidationService(),
        logger=DummyLogger(),
        console=Console(record=True),
        requests_module=requests_module,
    )

    local = tmp_path / "database.dump"
    local.write_text("local", encoding="utf-8")

    resolved = service.download_or_copy_source(str(local), str(tmp_path), None)

    assert resolved == str(local)


def test_download_service_retries_transient_request_errors(tmp_path):
    requests_module = FlakyRequestsModule(payload=b"retried")
    service = DownloadService(
        validation_service=FakeValidationService(),
        logger=DummyLogger(),
        console=Console(record=True),
        requests_module=requests_module,
        retry_count=1,
        retry_backoff_seconds=0.0,
    )

    dest = tmp_path / "database.dump"
    service.download_file(
        "https://example.com/database.dump",
        str(dest),
        description="source",
    )

    assert requests_module.calls == 2
    assert dest.read_bytes() == b"retried"
