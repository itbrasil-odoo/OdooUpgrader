import sys

import pytest

from odooupgrader.errors import UpgraderError
from odooupgrader.services.command_runner import CommandRunner


class DummyLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


def test_command_runner_raises_with_stderr():
    runner = CommandRunner(logger=DummyLogger())

    with pytest.raises(UpgraderError, match="boom"):
        runner.run(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"],
            check=True,
            capture_output=True,
        )


def test_command_runner_returns_when_check_disabled():
    runner = CommandRunner(logger=DummyLogger())

    result = runner.run(
        [sys.executable, "-c", "import sys; sys.exit(1)"],
        check=False,
        capture_output=True,
    )

    assert result.returncode == 1


def test_command_runner_retries_before_success(tmp_path, monkeypatch):
    runner = CommandRunner(logger=DummyLogger())
    monkeypatch.chdir(tmp_path)

    command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path;"
            "p=Path('retry-counter.txt');"
            "n=int(p.read_text()) if p.exists() else 0;"
            "p.write_text(str(n+1));"
            "import sys; sys.exit(1 if n == 0 else 0)"
        ),
    ]

    result = runner.run(
        command,
        check=True,
        capture_output=True,
        retry_count=1,
        retry_backoff_seconds=0.0,
    )

    assert result.returncode == 0


def test_command_runner_timeout_raises_error():
    runner = CommandRunner(logger=DummyLogger())

    with pytest.raises(UpgraderError, match="timed out"):
        runner.run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            check=True,
            capture_output=True,
            timeout=0.1,
        )
