"""OpenUpgrade step execution service for OdooUpgrader."""

import os
import time
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Deque, List, Optional

from odooupgrader.errors import UpgraderError


class UpgradeStepService:
    """Builds/runs per-version OpenUpgrade container steps."""

    MANIFEST_FILES = ("__manifest__.py", "__openerp__.py")
    CONTAINER_DATA_DIR = "/tmp/odooupgrader-data"
    CONTAINER_LOG_DIR = "/tmp/odooupgrader-output"
    LOG_PATH = os.path.join("output", "odoo.log")
    TRANSIENT_FAILURE_PATTERNS = (
        "connection reset",
        "temporary failure",
        "name resolution",
        "timed out",
        "timeout",
        "network is unreachable",
        "no route to host",
        "service unavailable",
        "context deadline exceeded",
        "i/o timeout",
        "unexpected eof",
        "tls handshake timeout",
        "too many requests",
        "429",
    )
    NON_RETRYABLE_FAILURE_PATTERNS = (
        "invalid manifest",
        "invalid version",
        "odoo.tools.convert.parseerror",
        "psycopg2.errors.",
        "duplicate table",
        "already exists",
    )

    def __init__(self, logger, console):
        self.logger = logger
        self.console = console

    def build_upgrade_dockerfile(
        self,
        target_version: str,
        include_custom_addons: bool,
        openupgrade_cache_relpath: str = "output/.cache/openupgrade/current",
        runtime_uid: Optional[int] = None,
        runtime_gid: Optional[int] = None,
    ) -> str:
        runtime_user_mapping_section = ""
        if runtime_uid is not None and runtime_gid is not None:
            runtime_user_mapping_section = f"""
RUN if ! getent group {runtime_gid} > /dev/null; then groupadd -g {runtime_gid} odooupgraderhost; fi \
 && if ! getent passwd {runtime_uid} > /dev/null; then useradd -u {runtime_uid} -g {runtime_gid} -M -s /usr/sbin/nologin odooupgraderhost; fi
"""

        custom_addons_section = ""
        if include_custom_addons:
            custom_addons_section = """
RUN mkdir -p /mnt/custom-addons
COPY --chown=odoo:odoo ./output/custom_addons/requirements.txt /mnt/custom-addons/requirements.txt
RUN pip3 install --no-cache-dir -r /mnt/custom-addons/requirements.txt
COPY --chown=odoo:odoo ./output/custom_addons/ /mnt/custom-addons/
"""

        return f"""
FROM odoo:{target_version}
USER root
ENV PIP_BREAK_SYSTEM_PACKAGES=1
COPY --chown=odoo:odoo ./{openupgrade_cache_relpath}/ /mnt/extra-addons/
RUN pip3 install --no-cache-dir -r /mnt/extra-addons/requirements.txt

{runtime_user_mapping_section}

{custom_addons_section}

USER odoo
""".strip()

    def discover_custom_addons_paths(self, custom_addons_dir: str) -> List[str]:
        root = Path(custom_addons_dir)
        if not root.exists() or not root.is_dir():
            return []

        container_root = PurePosixPath("/mnt/custom-addons")
        discovered: set[str] = set()

        for manifest_name in self.MANIFEST_FILES:
            for manifest_path in root.rglob(manifest_name):
                if not manifest_path.is_file():
                    continue
                if self._is_hidden_or_cache_path(manifest_path):
                    continue

                module_dir = manifest_path.parent
                try:
                    relative_parent = module_dir.relative_to(root).parent
                except ValueError:
                    continue

                if str(relative_parent) == ".":
                    discovered.add(str(container_root))
                    continue

                discovered.add(str(container_root.joinpath(*relative_parent.parts)))

        return sorted(discovered)

    @staticmethod
    def _is_hidden_or_cache_path(path: Path) -> bool:
        return any(part.startswith(".") or part == "__pycache__" for part in path.parts)

    @staticmethod
    def _read_log_delta(log_path: str, offset: int) -> str:
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as file_obj:
                file_obj.seek(max(0, offset))
                return file_obj.read()
        except OSError:
            return ""

    def _is_transient_failure(self, evidence: str) -> bool:
        text = evidence.lower()
        if not text.strip():
            return False

        if any(pattern in text for pattern in self.NON_RETRYABLE_FAILURE_PATTERNS):
            return False

        return any(pattern in text for pattern in self.TRANSIENT_FAILURE_PATTERNS)

    def build_upgrade_compose(
        self,
        run_context,
        extra_addons_path_arg: str,
        runtime_uid: Optional[int] = None,
        runtime_gid: Optional[int] = None,
    ) -> str:
        runtime_user_block = ""
        if runtime_uid is not None and runtime_gid is not None:
            runtime_user_block = f'\n    user: "{runtime_uid}:{runtime_gid}"'

        return f"""
services:
  odoo-openupgrade:
    image: odoo-openupgrade
    build:
      context: .
      dockerfile: Dockerfile
    container_name: {run_context.upgrade_container_name}
{runtime_user_block}
    environment:
      - HOST={run_context.db_container_name}
      - POSTGRES_USER={run_context.postgres_user}
      - POSTGRES_PASSWORD=${{ODOOUPGRADER_POSTGRES_PASSWORD}}
    networks:
      - {run_context.network_name}
    volumes:
      - ./output/filestore:{self.CONTAINER_DATA_DIR}/filestore/{run_context.target_database}
      - ./output:{self.CONTAINER_LOG_DIR}
    restart: "no"
    entrypoint: /entrypoint.sh
    command: >
      odoo -d {run_context.target_database}
      --data-dir={self.CONTAINER_DATA_DIR}
      --upgrade-path=/mnt/extra-addons/openupgrade_scripts/scripts
      --addons-path=/mnt/extra-addons{extra_addons_path_arg}
      --update all
      --stop-after-init
      --load=base,web,openupgrade_framework
      --log-level=info
      --logfile={self.CONTAINER_LOG_DIR}/odoo.log
networks:
  {run_context.network_name}:
    external: true
    name: {run_context.network_name}
""".strip()

    def run_upgrade_step(
        self,
        target_version: str,
        run_context,
        compose_cmd,
        extra_addons: Optional[str],
        custom_addons_dir: str,
        run_cmd,
        verbose: bool,
        subprocess_module,
        cache_root: str,
        retry_count: int = 0,
        retry_backoff_seconds: float = 0.0,
        step_timeout_seconds: Optional[float] = None,
        runtime_env: Optional[dict] = None,
        runtime_uid: Optional[int] = None,
        runtime_gid: Optional[int] = None,
    ) -> bool:
        self.logger.info("Preparing upgrade step to version %s", target_version)

        cache_dir = self.ensure_openupgrade_cache(
            target_version=target_version,
            cache_root=cache_root,
            run_cmd=run_cmd,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff_seconds,
        )

        include_custom_addons = bool(extra_addons)
        extra_addons_path_arg = ""
        if include_custom_addons:
            custom_addons_paths = self.discover_custom_addons_paths(custom_addons_dir)
            if not custom_addons_paths:
                raise UpgraderError(
                    "No valid custom addons directories were discovered for --addons-path. "
                    "Check extracted addons structure and manifest files."
                )
            extra_addons_path_arg = "," + ",".join(custom_addons_paths)

        if include_custom_addons:
            timestamp_path = os.path.join(custom_addons_dir, ".build_timestamp")
            with open(timestamp_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(str(time.time()))

        openupgrade_cache_relpath = os.path.relpath(cache_dir, os.getcwd()).replace(os.sep, "/")
        dockerfile_content = self.build_upgrade_dockerfile(
            target_version=target_version,
            include_custom_addons=include_custom_addons,
            openupgrade_cache_relpath=openupgrade_cache_relpath,
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
        )
        with open("Dockerfile", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(dockerfile_content)

        compose_content = self.build_upgrade_compose(
            run_context=run_context,
            extra_addons_path_arg=extra_addons_path_arg,
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
        )
        with open("odoo-upgrade-composer.yml", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(compose_content)

        run_cmd(
            ["docker", "rm", "-f", run_context.upgrade_container_name],
            check=False,
            capture_output=True,
        )

        cmd_up = compose_cmd + [
            "-f",
            "odoo-upgrade-composer.yml",
            "up",
            "--build",
            "--abort-on-container-exit",
        ]

        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        max_attempts = max(1, retry_count + 1)

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self.logger.warning(
                    "Retrying upgrade step to %s (%s/%s) after %.1fs",
                    target_version,
                    attempt,
                    max_attempts,
                    retry_backoff_seconds,
                )
                time.sleep(retry_backoff_seconds)

            last_lines: Deque[str] = deque(maxlen=40)
            timed_out = False

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=self.console,
            ) as progress:
                progress.add_task(
                    f"[bold magenta]Upgrading to {target_version} (attempt {attempt}/{max_attempts})...",
                    total=None,
                )

                log_offset = 0
                if os.path.exists(self.LOG_PATH):
                    try:
                        log_offset = os.path.getsize(self.LOG_PATH)
                    except OSError:
                        log_offset = 0

                try:
                    process = subprocess_module.Popen(
                        cmd_up,
                        stdout=subprocess_module.PIPE,
                        stderr=subprocess_module.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                        env=runtime_env,
                    )
                except Exception as exc:
                    raise UpgraderError(f"Failed to start upgrade container: {exc}") from exc

                if not process.stdout:
                    raise UpgraderError("Upgrade process did not expose logs. Aborting.")

                start = time.monotonic()
                for line in process.stdout:
                    if step_timeout_seconds and (time.monotonic() - start) > step_timeout_seconds:
                        timed_out = True
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except Exception:
                            process.kill()
                        self.logger.error(
                            "Upgrade step to %s exceeded timeout of %.1f seconds.",
                            target_version,
                            step_timeout_seconds,
                        )
                        break

                    cleaned = line.rstrip()
                    if not cleaned:
                        continue
                    last_lines.append(cleaned)
                    self.logger.debug(cleaned)
                    if verbose:
                        self.console.print(f"[dim]{cleaned}[/dim]")

                process.wait()

                if timed_out:
                    self.console.print(
                        f"[bold red]Upgrade step timed out after {step_timeout_seconds} seconds.[/bold red]"
                    )
                    run_cmd(
                        compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                        check=False,
                        capture_output=True,
                    )
                    if attempt == max_attempts:
                        return False
                    continue

                if process.returncode != 0:
                    self.logger.error(
                        "Upgrade process returned non-zero exit code: %s", process.returncode
                    )
                    attempt_log_delta = self._read_log_delta(self.LOG_PATH, log_offset)

                    if last_lines:
                        self.logger.error("Recent upgrade logs:\n%s", "\n".join(last_lines))
                        self.console.print("[red]Recent upgrade logs:[/red]")
                        for line in last_lines:
                            self.console.print(f"[red]{line}[/red]")

                    if attempt_log_delta:
                        delta_lines = [line for line in attempt_log_delta.splitlines() if line.strip()]
                        delta_excerpt = delta_lines[-40:]
                        if delta_excerpt:
                            self.logger.error("Recent odoo.log lines:\n%s", "\n".join(delta_excerpt))
                            self.console.print("[red]Recent odoo.log lines:[/red]")
                            for line in delta_excerpt:
                                self.console.print(f"[red]{line}[/red]")

                    evidence = "\n".join(last_lines)
                    if attempt_log_delta:
                        evidence = f"{evidence}\n{attempt_log_delta}" if evidence else attempt_log_delta

                    should_retry = attempt < max_attempts and self._is_transient_failure(evidence)
                    if not should_retry:
                        if attempt < max_attempts:
                            self.logger.error(
                                "Non-transient upgrade failure detected. "
                                "Skipping retry to avoid inconsistent migration state."
                            )
                        return False

                    run_cmd(
                        compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                        check=False,
                        capture_output=True,
                    )
                    continue

            inspect_result = run_cmd(
                [
                    "docker",
                    "inspect",
                    run_context.upgrade_container_name,
                    "--format={{.State.ExitCode}}",
                ],
                check=False,
                capture_output=True,
            )

            if inspect_result.returncode != 0:
                self.logger.error("Could not inspect upgrade container exit code.")
                if attempt == max_attempts:
                    return False
                continue

            try:
                exit_code = int(inspect_result.stdout.strip() or "1")
            except ValueError:
                self.logger.error("Invalid exit code from inspect: %s", inspect_result.stdout)
                if attempt == max_attempts:
                    return False
                continue

            if exit_code == 0:
                self.console.print(f"[green]Upgrade to {target_version} successful.[/green]")
                run_cmd(
                    compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                    check=False,
                    capture_output=True,
                )
                return True

            self.console.print(f"[bold red]Container exited with code {exit_code}[/bold red]")
            run_cmd(
                compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                check=False,
                capture_output=True,
            )

        return False

    def ensure_openupgrade_cache(
        self,
        target_version: str,
        cache_root: str,
        run_cmd,
        retry_count: int = 0,
        retry_backoff_seconds: float = 0.0,
    ) -> str:
        version_cache_path = os.path.join(cache_root, target_version)
        if self._is_cache_ready(version_cache_path):
            self.logger.debug(
                "Using cached OpenUpgrade source for %s at %s", target_version, version_cache_path
            )
            return version_cache_path

        os.makedirs(cache_root, exist_ok=True)
        if os.path.exists(version_cache_path):
            import shutil

            shutil.rmtree(version_cache_path, ignore_errors=True)

        self.logger.info(
            "Caching OpenUpgrade source for %s at %s", target_version, version_cache_path
        )
        clone_cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            target_version,
            "https://github.com/OCA/OpenUpgrade.git",
            version_cache_path,
        ]
        try:
            run_cmd(
                clone_cmd,
                check=True,
                capture_output=True,
                retry_count=retry_count,
                retry_backoff_seconds=retry_backoff_seconds,
            )
        except TypeError:
            run_cmd(clone_cmd, check=True, capture_output=True)

        os.makedirs(version_cache_path, exist_ok=True)
        requirements_file = os.path.join(version_cache_path, "requirements.txt")
        if os.path.isdir(version_cache_path) and not os.path.exists(requirements_file):
            self.logger.warning(
                "OpenUpgrade cache at %s has no requirements.txt. Creating empty placeholder.",
                version_cache_path,
            )
            with open(requirements_file, "w", encoding="utf-8") as file_obj:
                file_obj.write("")

        if not self._is_cache_ready(version_cache_path):
            raise UpgraderError(
                f"OpenUpgrade cache for {target_version} was not prepared correctly at {version_cache_path}."
            )
        return version_cache_path

    @staticmethod
    def _is_cache_ready(version_cache_path: str) -> bool:
        return os.path.isdir(version_cache_path) and os.path.isfile(
            os.path.join(version_cache_path, "requirements.txt")
        )
