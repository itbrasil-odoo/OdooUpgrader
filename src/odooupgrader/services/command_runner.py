"""Subprocess execution service for OdooUpgrader."""

import subprocess
from typing import List

from odooupgrader.errors import UpgraderError


class CommandRunner:
    """Runs external commands with consistent error handling."""

    def __init__(self, logger):
        self.logger = logger

    def run(self, cmd: List[str], check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess:
        cmd_str = " ".join(cmd)
        self.logger.debug("Executing: %s", cmd_str)

        try:
            result = subprocess.run(
                cmd,
                text=True,
                capture_output=capture_output,
            )
        except FileNotFoundError as exc:
            raise UpgraderError(
                f"Required command not found: {cmd[0]}. Please install it and try again."
            ) from exc
        except Exception as exc:
            raise UpgraderError(f"Failed to execute command: {cmd_str}. {exc}") from exc

        if capture_output and result.stdout:
            self.logger.debug("Command output: %s", result.stdout.strip())

        if result.returncode != 0:
            stderr = (result.stderr or "").strip() if capture_output else ""
            message = f"Command failed ({result.returncode}): {cmd_str}"
            if stderr:
                message = f"{message}\n{stderr}"

            if check:
                raise UpgraderError(message)

            self.logger.warning(message)

        return result
