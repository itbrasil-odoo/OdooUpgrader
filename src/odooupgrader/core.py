import logging
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from packaging import version
from rich.console import Console

from .constants import DIR_MODE, FILE_MODE, SCRIPT_MODE
from .errors import UpgraderError
from .models import RunContext
from .services.archive import ArchiveService
from .services.command_runner import CommandRunner
from .services.database import DatabaseService
from .services.download import DownloadService
from .services.docker_runtime import DockerRuntimeService
from .services.filesystem import FileSystemService
from .services.manifest import ManifestService
from .services.state import StateService
from .services.upgrade_step import UpgradeStepService
from .services.validation import ValidationService

console = Console()
logger = logging.getLogger("odooupgrader")


class OdooUpgrader:
    VALID_VERSIONS = ["10.0", "11.0", "12.0", "13.0", "14.0", "15.0", "16.0", "17.0", "18.0"]

    def __init__(
        self,
        source: str,
        target_version: str,
        extra_addons: Optional[str] = None,
        verbose: bool = False,
        postgres_version: str = "13",
        allow_insecure_http: bool = False,
        source_sha256: Optional[str] = None,
        extra_addons_sha256: Optional[str] = None,
        resume: bool = False,
        state_file: Optional[str] = None,
    ):
        self.source = source
        self.target_version = target_version
        self.extra_addons = extra_addons
        self.verbose = verbose
        self.postgres_version = postgres_version
        self.allow_insecure_http = allow_insecure_http
        self.source_sha256 = self._normalize_sha256(source_sha256, "--source-sha256")
        self.extra_addons_sha256 = self._normalize_sha256(
            extra_addons_sha256,
            "--extra-addons-sha256",
        )
        self.resume = resume

        self.cwd = os.getcwd()
        self.source_dir = os.path.join(self.cwd, "source")
        self.output_dir = os.path.join(self.cwd, "output")
        self.filestore_dir = os.path.join(self.output_dir, "filestore")
        self.custom_addons_dir = os.path.join(self.output_dir, "custom_addons")
        self.state_file = state_file or os.path.join(self.output_dir, "run-state.json")
        self.manifest_file = os.path.join(self.output_dir, "run-manifest.json")
        self.state_service = StateService(state_file=self.state_file, logger=logger)
        self.manifest_service = ManifestService(manifest_file=self.manifest_file, logger=logger)
        self.state: Optional[Dict[str, Any]] = None
        self.current_step_name: Optional[str] = None

        self.filesystem_service = FileSystemService(logger=logger, console=console)
        self.archive_service = ArchiveService()
        self.validation_service = ValidationService(
            allow_insecure_http=self.allow_insecure_http,
            requests_module=requests,
        )
        self.command_runner = CommandRunner(logger=logger)
        self.download_service = DownloadService(
            validation_service=self.validation_service,
            logger=logger,
            console=console,
            requests_module=requests,
        )
        self.docker_runtime_service = DockerRuntimeService(
            logger=logger,
            console=console,
            subprocess_module=subprocess,
        )
        self.database_service = DatabaseService(
            logger=logger,
            console=console,
            filesystem_service=self.filesystem_service,
        )
        self.upgrade_step_service = UpgradeStepService(logger=logger, console=console)

        self.compose_cmd = self._get_docker_compose_cmd()
        self.run_context = self._build_run_context()

    def _normalize_sha256(self, value: Optional[str], option_name: str) -> Optional[str]:
        if value is None:
            return None

        clean_value = value.strip().lower()
        if len(clean_value) != 64 or any(c not in "0123456789abcdef" for c in clean_value):
            raise UpgraderError(
                f"{option_name} must be a valid SHA-256 hash (64 hexadecimal characters)."
            )
        return clean_value

    def _build_run_context(self) -> RunContext:
        run_id = uuid.uuid4().hex[:10]
        prefix = f"odooupgrader_{run_id}"
        return RunContext(
            run_id=run_id,
            db_container_name=f"{prefix}_db",
            upgrade_container_name=f"{prefix}_upgrade",
            network_name=f"{prefix}_net",
            volume_name=f"{prefix}_pgdata",
            postgres_user=f"odoo_{run_id[:8]}",
            postgres_password=secrets.token_hex(16),
            postgres_bootstrap_db="odoo",
            target_database="database",
        )

    def _build_resume_metadata(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target_version": self.target_version,
            "extra_addons": self.extra_addons,
            "source_sha256": self.source_sha256,
            "extra_addons_sha256": self.extra_addons_sha256,
        }

    def _build_manifest_metadata(self) -> Dict[str, Any]:
        metadata = self._build_resume_metadata()
        metadata.update(
            {
                "resume_enabled": self.resume,
                "state_file": self.state_file if self.resume else None,
            }
        )
        return metadata

    def _initialize_state(self) -> bool:
        if not self.resume:
            return False

        os.makedirs(self.output_dir, exist_ok=True)
        metadata = self._build_resume_metadata()
        state, resumed = self.state_service.initialize(
            metadata=metadata,
            run_context=asdict(self.run_context),
            resume=True,
        )
        self.state = state

        if resumed:
            context_data = state.get("run_context")
            if not isinstance(context_data, dict):
                raise UpgraderError("State file is missing run context. Start a fresh run without --resume.")
            self.run_context = RunContext(**context_data)
            logger.info(
                "Resuming previous run '%s' at step '%s'.",
                self.run_context.run_id,
                state.get("current_step") or "<none>",
            )
            if state.get("status") == "success":
                raise UpgraderError(
                    "The state file already belongs to a successful run. Remove it or choose another --state-file."
                )
            state["status"] = "running"
            self.state_service.save(state)
        else:
            logger.info("Resume state initialized at %s", self.state_file)

        return resumed

    def _run_step(
        self,
        name: str,
        callback,
        *args,
        skip_when_completed: bool = True,
        **kwargs,
    ):
        if (
            self.resume
            and self.state
            and skip_when_completed
            and self.state_service.is_step_completed(self.state, name)
        ):
            logger.info("Skipping completed step from state: %s", name)
            self.manifest_service.step_started(name, details={"resumed": True})
            self.manifest_service.step_finished(name, "skipped", details={"resumed": True})
            return None, True

        if self.state:
            self.state_service.mark_step_started(self.state, name)
        self.manifest_service.step_started(name)
        self.current_step_name = name

        try:
            result = callback(*args, **kwargs)
        except Exception as exc:
            if self.state:
                self.state_service.mark_step_failed(self.state, name, str(exc))
            self.manifest_service.step_finished(name, "failed", error=str(exc))
            raise

        if self.state:
            self.state_service.mark_step_completed(self.state, name)
        self.manifest_service.step_finished(name, "success")
        self.current_step_name = None
        return result, False

    def _run_cmd(
        self,
        cmd: List[str],
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess:
        return self.command_runner.run(cmd, check=check, capture_output=capture_output)

    def _get_docker_compose_cmd(self) -> List[str]:
        return self.docker_runtime_service.get_docker_compose_cmd()

    def _safe_extract_zip(self, zip_path: str, destination_dir: str):
        self.archive_service.safe_extract_zip(zip_path, destination_dir)

    def validate_docker_environment(self):
        self.docker_runtime_service.validate_environment(self.compose_cmd, self._run_cmd)

    def validate_source_accessibility(self):
        """Checks source and addons inputs early with strict validation."""
        console.print("[blue]Validating source accessibility...[/blue]")
        logger.info("Validating source: %s", self.source)
        if self.extra_addons:
            console.print("[blue]Validating extra addons...[/blue]")

        self.validation_service.validate_source_accessibility(
            source=self.source,
            extra_addons=self.extra_addons,
            logger=logger,
            console=console,
        )

        if self.validation_service.is_url(self.source):
            console.print("[green]Source URL is accessible.[/green]")
        else:
            console.print("[green]Source file exists.[/green]")

    def prepare_environment(self):
        logger.info("Preparing environment directories...")
        self.filesystem_service.cleanup_dir(self.source_dir)
        self.filesystem_service.cleanup_dir(self.output_dir)

        os.makedirs(self.source_dir, exist_ok=True)
        os.makedirs(self.filestore_dir, exist_ok=True)
        os.makedirs(self.custom_addons_dir, exist_ok=True)

        self.filesystem_service.set_permissions(self.source_dir, DIR_MODE)
        self.filesystem_service.set_permissions(self.output_dir, DIR_MODE)
        self.filesystem_service.set_permissions(self.filestore_dir, DIR_MODE)
        self.filesystem_service.set_permissions(self.custom_addons_dir, DIR_MODE)

    def download_file(
        self,
        url: str,
        dest_path: str,
        description: str = "Downloading...",
        expected_sha256: Optional[str] = None,
    ):
        self.download_service.download_file(
            url=url,
            dest_path=dest_path,
            description=description,
            expected_sha256=expected_sha256,
        )

    def download_or_copy_source(self) -> str:
        return self.download_service.download_or_copy_source(
            source=self.source,
            source_dir=self.source_dir,
            source_sha256=self.source_sha256,
        )

    def process_extra_addons(self):
        """Downloads/copies/extracts addons and normalizes structure."""
        if not self.extra_addons:
            return

        console.print("[blue]Processing custom addons...[/blue]")
        logger.info("Processing custom addons...")

        if self.validation_service.is_url(self.extra_addons):
            zip_path = os.path.join(self.source_dir, "addons.zip")
            self.download_file(
                self.extra_addons,
                zip_path,
                "Downloading extra addons...",
                expected_sha256=self.extra_addons_sha256,
            )
            self._safe_extract_zip(zip_path, self.custom_addons_dir)
            os.remove(zip_path)

        elif os.path.isfile(self.extra_addons):
            self._safe_extract_zip(self.extra_addons, self.custom_addons_dir)

        elif os.path.isdir(self.extra_addons):
            try:
                shutil.copytree(self.extra_addons, self.custom_addons_dir, dirs_exist_ok=True)
            except Exception as exc:
                raise UpgraderError(f"Failed to copy local addons: {exc}") from exc

        else:
            raise UpgraderError(
                "Invalid extra addons source. Provide a local directory, local `.zip`, "
                "or HTTPS `.zip` URL."
            )

        items = [item for item in os.listdir(self.custom_addons_dir) if not item.startswith(".")]
        if len(items) == 1:
            single_item_path = os.path.join(self.custom_addons_dir, items[0])
            if os.path.isdir(single_item_path):
                sub_items = os.listdir(single_item_path)
                is_module = any(
                    item in sub_items for item in ["__manifest__.py", "__openerp__.py"]
                )

                if not is_module:
                    logger.info("Detected wrapper directory '%s'. Flattening structure...", items[0])
                    for sub_item in sub_items:
                        src_path = os.path.join(single_item_path, sub_item)
                        dst_path = os.path.join(self.custom_addons_dir, sub_item)
                        if not os.path.exists(dst_path):
                            shutil.move(src_path, dst_path)
                    try:
                        os.rmdir(single_item_path)
                    except OSError:
                        pass

        root_items = os.listdir(self.custom_addons_dir)
        has_manifest = any(item in root_items for item in ["__manifest__.py", "__openerp__.py"])

        if has_manifest:
            logger.info("Detected flat addon structure. Reorganizing...")
            module_dir = os.path.join(self.custom_addons_dir, "downloaded_module")
            os.makedirs(module_dir, exist_ok=True)

            for item in root_items:
                if item == "requirements.txt":
                    continue

                src_path = os.path.join(self.custom_addons_dir, item)
                dst_path = os.path.join(module_dir, item)

                if src_path != module_dir:
                    shutil.move(src_path, dst_path)

        self.validation_service.validate_addons_structure(Path(self.custom_addons_dir))

        requirements_path = os.path.join(self.custom_addons_dir, "requirements.txt")
        if not os.path.exists(requirements_path):
            with open(requirements_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("")
        elif os.path.getsize(requirements_path) == 0:
            logger.warning("Empty requirements.txt found in custom addons.")

        self.filesystem_service.set_tree_permissions(
            self.custom_addons_dir,
            dir_mode=DIR_MODE,
            file_mode=FILE_MODE,
            script_mode=SCRIPT_MODE,
        )
        console.print("[green]Custom addons prepared.[/green]")

    def process_source_file(self, filepath: str) -> str:
        ext = Path(filepath).suffix.lower()

        if ext == ".zip":
            console.print("[blue]Extracting ZIP file...[/blue]")
            logger.info("Extracting ZIP file...")
            self._safe_extract_zip(filepath, self.source_dir)
            return "ZIP"

        if ext == ".dump":
            console.print("[blue]Processing DUMP file...[/blue]")
            logger.info("Processing DUMP file...")
            shutil.copy2(filepath, os.path.join(self.source_dir, "database.dump"))
            return "DUMP"

        raise UpgraderError("Unsupported source file format. Use `.zip` or `.dump`.")

    def create_db_compose_file(self):
        self.docker_runtime_service.create_db_compose_file(
            run_context=self.run_context,
            postgres_version=self.postgres_version,
        )

    def wait_for_db(self):
        self.docker_runtime_service.wait_for_db(self.run_context, self._run_cmd)

    def restore_database(self, file_type: str):
        self.database_service.restore_database(
            file_type=file_type,
            source_dir=self.source_dir,
            filestore_dir=self.filestore_dir,
            run_context=self.run_context,
            run_cmd=self._run_cmd,
        )

    def get_current_version(self) -> str:
        return self.database_service.get_current_version(self.run_context, self._run_cmd)

    def get_version_info(self, ver_str: str) -> version.Version:
        try:
            return version.parse(ver_str.strip())
        except Exception:
            return version.parse("0.0")

    def generate_next_version(self, current: str) -> str:
        try:
            major = int(current.split(".")[0])
            return f"{major + 1}.0"
        except Exception:
            parsed = version.parse(current)
            return f"{parsed.major + 1}.0"

    def _build_upgrade_dockerfile(self, target_version: str, include_custom_addons: bool) -> str:
        openupgrade_cache_relpath = os.path.join(
            "output", ".cache", "openupgrade", target_version
        ).replace(os.sep, "/")
        return self.upgrade_step_service.build_upgrade_dockerfile(
            target_version=target_version,
            include_custom_addons=include_custom_addons,
            openupgrade_cache_relpath=openupgrade_cache_relpath,
        )

    def _build_upgrade_compose(self, extra_addons_path_arg: str) -> str:
        return self.upgrade_step_service.build_upgrade_compose(
            run_context=self.run_context,
            extra_addons_path_arg=extra_addons_path_arg,
        )

    def run_upgrade_step(self, target_version: str) -> bool:
        return self.upgrade_step_service.run_upgrade_step(
            target_version=target_version,
            run_context=self.run_context,
            compose_cmd=self.compose_cmd,
            extra_addons=self.extra_addons,
            custom_addons_dir=self.custom_addons_dir,
            run_cmd=self._run_cmd,
            verbose=self.verbose,
            subprocess_module=subprocess,
            cache_root=os.path.join(self.output_dir, ".cache", "openupgrade"),
        )

    def finalize_package(self):
        self.database_service.finalize_package(
            output_dir=self.output_dir,
            filestore_dir=self.filestore_dir,
            run_context=self.run_context,
            subprocess_module=subprocess,
        )

    def cleanup_artifacts(self):
        logger.info("Cleaning up artifacts...")
        self.filesystem_service.cleanup_dir(self.source_dir)
        self.filesystem_service.cleanup_dir(self.filestore_dir)
        self.filesystem_service.cleanup_dir(self.custom_addons_dir)

    def cleanup(self):
        self.docker_runtime_service.cleanup_docker_environment(self.compose_cmd, self._run_cmd)

        for file_name in ["Dockerfile", "odoo-upgrade-composer.yml", "db-composer.yml"]:
            if os.path.exists(file_name):
                try:
                    os.remove(file_name)
                except OSError as exc:
                    logger.warning("Could not remove %s: %s", file_name, exc)

    def run(self) -> int:
        exit_code = 1
        preserve_runtime_for_resume = False
        manifest_status = "failed"
        manifest_error: Optional[str] = None

        try:
            logger.info("Starting OdooUpgrader...")

            if self.target_version not in self.VALID_VERSIONS:
                raise UpgraderError(f"Invalid version. Supported versions: {', '.join(self.VALID_VERSIONS)}")

            resumed = self._initialize_state()
            self.manifest_service.start_run(
                run_id=self.run_context.run_id,
                metadata=self._build_manifest_metadata(),
            )
            self.manifest_service.set_versions(source=None, target=self.target_version, current=None)

            self._run_step("validate_docker_environment", self.validate_docker_environment)
            self._run_step("validate_source_accessibility", self.validate_source_accessibility)

            database_restored = False
            current_ver_str = ""

            if self.resume and self.state:
                database_restored = bool(self.state_service.get_value(self.state, "database_restored", False))
                current_ver_str = self.state_service.get_current_version(self.state) or ""

            if not (resumed and database_restored):
                self._run_step("prepare_environment", self.prepare_environment)
                self._run_step("process_extra_addons", self.process_extra_addons)
            else:
                logger.info("Skipping environment preparation due to resume state.")

            self._run_step("create_db_compose_file", self.create_db_compose_file, skip_when_completed=False)
            self._run_step(
                "start_db_container",
                self._run_cmd,
                self.compose_cmd + ["-f", "db-composer.yml", "up", "-d"],
                check=True,
                skip_when_completed=False,
            )
            self._run_step("wait_for_db", self.wait_for_db, skip_when_completed=False)

            if not (resumed and database_restored):
                local_source, _ = self._run_step("download_source", self.download_or_copy_source)
                if self.state and local_source:
                    self.state_service.set_value(self.state, "local_source_path", local_source)

                file_type, _ = self._run_step("process_source", self.process_source_file, local_source)
                if self.state and file_type:
                    self.state_service.set_value(self.state, "source_file_type", file_type)

                self._run_step("restore_database", self.restore_database, file_type)
                if self.state:
                    self.state_service.set_value(self.state, "database_restored", True)

                current_ver_str, _ = self._run_step("detect_current_version", self.get_current_version)
                if self.state and current_ver_str:
                    self.state_service.set_current_version(self.state, current_ver_str)
            else:
                logger.info("Resuming from restored database state at version: %s", current_ver_str or "<unknown>")
                if not current_ver_str:
                    current_ver_str, _ = self._run_step("detect_current_version", self.get_current_version)
                    if self.state and current_ver_str:
                        self.state_service.set_current_version(self.state, current_ver_str)

            if not current_ver_str:
                raise UpgraderError(
                    "Could not determine database version after restore. "
                    "Check that the source dump is a valid Odoo database."
                )

            console.print(f"[bold blue]Current Database Version: {current_ver_str}[/bold blue]")
            logger.info("Current database version: %s", current_ver_str)
            self.manifest_service.set_versions(
                source=current_ver_str,
                target=self.target_version,
                current=current_ver_str,
            )

            current_ver = self.get_version_info(current_ver_str)
            target_ver = self.get_version_info(self.target_version)
            min_ver = self.get_version_info("10.0")

            if current_ver < min_ver:
                raise UpgraderError("Source database version is below 10.0 and is not supported.")

            seen_majors = set()

            while True:
                current_ver = self.get_version_info(current_ver_str)
                current_major_marker = current_ver.major

                if current_major_marker in seen_majors:
                    raise UpgraderError(
                        f"Upgrade loop detected at version {current_ver_str}. "
                        "The database version is not progressing."
                    )
                seen_majors.add(current_major_marker)

                if current_ver.major == target_ver.major:
                    console.print("[green]Target version reached![/green]")
                    break

                if current_ver.major > target_ver.major:
                    console.print("[yellow]Current version is already higher than target.[/yellow]")
                    break

                next_ver_str = self.generate_next_version(current_ver_str)

                if next_ver_str not in self.VALID_VERSIONS:
                    raise UpgraderError(
                        f"No supported upgrade step found from {current_ver_str} to {self.target_version}."
                    )

                step_name = f"upgrade_to_{next_ver_str}"
                upgrade_result, _ = self._run_step(step_name, self.run_upgrade_step, next_ver_str)
                if not upgrade_result:
                    raise UpgraderError(
                        f"Upgrade step to {next_ver_str} failed. "
                        "Review container logs in output/odoo.log and retry."
                    )

                new_ver_str, _ = self._run_step(
                    f"detect_current_version_{next_ver_str}",
                    self.get_current_version,
                )
                if not new_ver_str:
                    raise UpgraderError(
                        "Could not determine database version after upgrade step. "
                        "Inspect logs to identify migration failures."
                    )

                new_ver = self.get_version_info(new_ver_str)
                if new_ver.major <= current_ver.major:
                    raise UpgraderError(
                        f"Upgrade did not progress: stayed at {new_ver_str} after targeting {next_ver_str}."
                    )

                current_ver_str = new_ver_str
                if self.state:
                    self.state_service.set_current_version(self.state, current_ver_str)
                console.print(f"[blue]Database is now at version: {current_ver_str}[/blue]")
                self.manifest_service.set_versions(
                    source=None,
                    target=self.target_version,
                    current=current_ver_str,
                )

            self._run_step("finalize_package", self.finalize_package)
            self._run_step("cleanup_artifacts", self.cleanup_artifacts)
            if self.state:
                self.state_service.mark_status(self.state, "success")
            upgraded_zip = os.path.join(self.output_dir, "upgraded.zip")
            if os.path.exists(upgraded_zip):
                self.manifest_service.add_artifact("upgraded_zip", upgraded_zip)
            self.manifest_service.add_artifact("odoo_log", os.path.join(self.output_dir, "odoo.log"))
            manifest_status = "success"
            manifest_error = None
            exit_code = 0
            return exit_code

        except KeyboardInterrupt:
            console.print("[bold red]Operation cancelled by user.[/bold red]")
            logger.info("Operation cancelled by user")
            if self.state:
                self.state_service.mark_status(self.state, "aborted", "Operation cancelled by user.")
            manifest_status = "aborted"
            manifest_error = "Operation cancelled by user."
            exit_code = 1
            return exit_code
        except UpgraderError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            logger.error(str(exc))
            if self.state:
                failed_step = self.current_step_name or "run"
                self.state_service.mark_step_failed(self.state, failed_step, str(exc))
                self.state_service.mark_status(self.state, "failed", str(exc))
            preserve_runtime_for_resume = self.resume
            manifest_status = "failed"
            manifest_error = str(exc)
            exit_code = 1
            return exit_code
        except Exception as exc:
            console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
            logger.exception("Unexpected error")
            if self.state:
                failed_step = self.current_step_name or "run"
                self.state_service.mark_step_failed(self.state, failed_step, str(exc))
                self.state_service.mark_status(self.state, "failed", str(exc))
            preserve_runtime_for_resume = self.resume
            manifest_status = "failed"
            manifest_error = str(exc)
            exit_code = 1
            return exit_code
        finally:
            self.manifest_service.finalize(manifest_status, error=manifest_error)
            if preserve_runtime_for_resume:
                logger.warning(
                    "Preserving runtime artifacts and containers for resume mode. "
                    "Run again with --resume to continue from the last completed step."
                )
            else:
                self.cleanup()
