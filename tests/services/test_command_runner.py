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
