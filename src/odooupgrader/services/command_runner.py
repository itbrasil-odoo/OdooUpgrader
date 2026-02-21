"""Subprocess execution service for OdooUpgrader."""

import subprocess
import time
from typing import Iterable, List, Optional

from odooupgrader.errors import UpgraderError


class CommandRunner:
    """Runs external commands with consistent error handling."""

    def __init__(self, logger, default_timeout: Optional[float] = None):
        self.logger = logger
        self.default_timeout = default_timeout

    def run(
        self,
        cmd: List[str],
        check: bool = True,
        capture_output: bool = False,
        timeout: Optional[float] = None,
        retry_count: int = 0,
        retry_backoff_seconds: float = 0.0,
        retry_on_returncodes: Optional[Iterable[int]] = None,
    ) -> subprocess.CompletedProcess:
        cmd_str = " ".join(cmd)
        self.logger.debug("Executing: %s", cmd_str)

        effective_timeout = timeout if timeout is not None else self.default_timeout
        max_attempts = max(1, retry_count + 1)
        retry_codes = set(retry_on_returncodes or [])

        for attempt in range(1, max_attempts + 1):
            try:
                result = subprocess.run(
                    cmd,
                    text=True,
                    capture_output=capture_output,
                    timeout=effective_timeout,
                )
            except FileNotFoundError as exc:
                raise UpgraderError(
                    f"Required command not found: {cmd[0]}. Please install it and try again."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                if attempt < max_attempts:
                    self.logger.warning(
                        "Command timed out on attempt %s/%s. Retrying in %.1fs: %s",
                        attempt,
                        max_attempts,
                        retry_backoff_seconds,
                        cmd_str,
                    )
                    time.sleep(retry_backoff_seconds)
                    continue
                raise UpgraderError(
                    f"Command timed out after {effective_timeout}s: {cmd_str}"
                ) from exc
            except Exception as exc:
                raise UpgraderError(f"Failed to execute command: {cmd_str}. {exc}") from exc

            if capture_output and result.stdout:
                self.logger.debug("Command output: %s", result.stdout.strip())

            if result.returncode == 0:
                return result

            stderr = (result.stderr or "").strip() if capture_output else ""
            message = f"Command failed ({result.returncode}): {cmd_str}"
            if stderr:
                message = f"{message}\n{stderr}"

            can_retry = attempt < max_attempts and (
                not retry_codes or result.returncode in retry_codes
            )
            if can_retry:
                self.logger.warning(
                    "Command failed on attempt %s/%s and will be retried in %.1fs.\n%s",
                    attempt,
                    max_attempts,
                    retry_backoff_seconds,
                    message,
                )
                time.sleep(retry_backoff_seconds)
                continue

            if check:
                raise UpgraderError(message)

            self.logger.warning(message)
            return result

        raise UpgraderError(f"Command failed after retries: {cmd_str}")
