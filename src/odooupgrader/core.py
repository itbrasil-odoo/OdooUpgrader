import hashlib
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, List, Optional
from urllib.parse import urlparse

import requests
from packaging import version
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

console = Console()
logger = logging.getLogger("odooupgrader")

SOURCE_EXTENSIONS = {".zip", ".dump"}
ADDONS_ZIP_EXTENSION = ".zip"

DIR_MODE = 0o755
FILE_MODE = 0o644
SCRIPT_MODE = 0o755


class UpgraderError(RuntimeError):
    """Raised when the upgrade cannot continue safely."""


@dataclass(frozen=True)
class RunContext:
    """Runtime identifiers and credentials isolated per execution."""

    run_id: str
    db_container_name: str
    upgrade_container_name: str
    network_name: str
    volume_name: str
    postgres_user: str
    postgres_password: str
    postgres_bootstrap_db: str
    target_database: str


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

        self.cwd = os.getcwd()
        self.source_dir = os.path.join(self.cwd, "source")
        self.output_dir = os.path.join(self.cwd, "output")
        self.filestore_dir = os.path.join(self.output_dir, "filestore")
        self.custom_addons_dir = os.path.join(self.output_dir, "custom_addons")

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

    def _run_cmd(
        self,
        cmd: List[str],
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess:
        """Executes command with consistent logging and actionable failures."""
        cmd_str = " ".join(cmd)
        logger.debug("Executing: %s", cmd_str)

        try:
            result = subprocess.run(
                cmd,
                text=True,
                capture_output=capture_output,
            )
        except FileNotFoundError as exc:
            raise UpgraderError(
                f"Required command not found: {cmd[0]}. "
                "Please install it and try again."
            ) from exc
        except Exception as exc:
            raise UpgraderError(f"Failed to execute command: {cmd_str}. {exc}") from exc

        if capture_output and result.stdout:
            logger.debug("Command output: %s", result.stdout.strip())

        if result.returncode != 0:
            stderr = (result.stderr or "").strip() if capture_output else ""
            base_message = f"Command failed ({result.returncode}): {cmd_str}"
            if stderr:
                base_message = f"{base_message}\n{stderr}"

            if check:
                raise UpgraderError(base_message)

            logger.warning(base_message)

        return result

    def _get_docker_compose_cmd(self) -> List[str]:
        """Finds an available Docker Compose command."""
        try:
            subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                subprocess.run(["docker-compose", "--version"], check=True, capture_output=True)
                return ["docker-compose"]
            except (subprocess.CalledProcessError, FileNotFoundError):
                raise UpgraderError(
                    "Docker Compose is not available. Install Docker Compose v2 (`docker compose`) "
                    "or v1 (`docker-compose`) and try again."
                )

    def _is_url(self, location: str) -> bool:
        scheme = urlparse(location).scheme.lower()
        return scheme in {"http", "https"}

    def _get_location_extension(self, location: str) -> str:
        path = urlparse(location).path if self._is_url(location) else location
        return Path(path).suffix.lower()

    def _ensure_supported_source_extension(self, location: str):
        ext = self._get_location_extension(location)
        if ext not in SOURCE_EXTENSIONS:
            raise UpgraderError(
                "Invalid source format. Supported formats are `.zip` and `.dump`. "
                "Provide a source file/URL ending with one of these extensions."
            )

    def _ensure_supported_addons_extension(self, location: str):
        ext = self._get_location_extension(location)
        if ext != ADDONS_ZIP_EXTENSION:
            raise UpgraderError("Invalid addons format. Remote or file addons must be a `.zip` file.")

    def _enforce_https_policy(self, location: str, label: str):
        if not self._is_url(location):
            return

        scheme = urlparse(location).scheme.lower()
        if scheme == "http" and not self.allow_insecure_http:
            raise UpgraderError(
                f"{label} uses insecure HTTP. Use HTTPS instead, or pass "
                "`--allow-insecure-http` only when you explicitly trust the endpoint."
            )

        if scheme == "http" and self.allow_insecure_http:
            logger.warning("Insecure HTTP enabled for %s: %s", label, location)
            console.print(
                f"[yellow]Warning:[/yellow] Using insecure HTTP for {label}. "
                "Prefer HTTPS whenever possible."
            )

    def _probe_url(self, location: str, label: str):
        """Checks remote accessibility with HEAD, then GET fallback."""
        self._enforce_https_policy(location, label)

        last_error: Optional[Exception] = None
        for method in ("HEAD", "GET"):
            try:
                response = requests.request(
                    method,
                    location,
                    allow_redirects=True,
                    timeout=30,
                    stream=(method == "GET"),
                )
                response.raise_for_status()
                response.close()
                return
            except requests.RequestException as exc:
                last_error = exc

        raise UpgraderError(f"{label} is not accessible: {last_error}")

    def _is_within_dir(self, base_dir: Path, candidate: Path) -> bool:
        try:
            return os.path.commonpath([str(base_dir), str(candidate)]) == str(base_dir)
        except ValueError:
            return False

    def _safe_extract_zip(self, zip_path: str, destination_dir: str):
        """Extract zip safely to block path traversal and symlinks."""
        base = Path(destination_dir).resolve()

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                for member in zip_ref.infolist():
                    normalized_name = member.filename.replace("\\", "/")
                    target_path = (base / normalized_name).resolve()

                    if not self._is_within_dir(base, target_path):
                        raise UpgraderError(
                            f"Unsafe ZIP entry detected: `{member.filename}`. "
                            "Archive extraction aborted to prevent path traversal."
                        )

                    file_type = (member.external_attr >> 16) & 0o170000
                    if file_type == 0o120000:
                        raise UpgraderError(
                            f"Unsafe ZIP entry detected: `{member.filename}` is a symbolic link."
                        )

                for member in zip_ref.infolist():
                    normalized_name = member.filename.replace("\\", "/")
                    target_path = (base / normalized_name).resolve()

                    if member.is_dir() or normalized_name.endswith("/"):
                        target_path.mkdir(parents=True, exist_ok=True)
                        continue

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zip_ref.open(member, "r") as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as exc:
            raise UpgraderError(f"Invalid ZIP archive: {zip_path}") from exc

    def _set_permissions(self, path: str, mode: int):
        if sys.platform == "win32":
            return

        try:
            os.chmod(path, mode)
        except Exception as exc:
            logger.warning("Could not set permissions on %s: %s", path, exc)

    def _set_tree_permissions(
        self,
        root: str,
        dir_mode: int = DIR_MODE,
        file_mode: int = FILE_MODE,
    ):
        if sys.platform == "win32" or not os.path.exists(root):
            return

        for current_root, dirs, files in os.walk(root):
            for directory in dirs:
                self._set_permissions(os.path.join(current_root, directory), dir_mode)
            for file_name in files:
                mode = SCRIPT_MODE if file_name.endswith(".sh") else file_mode
                self._set_permissions(os.path.join(current_root, file_name), mode)

    def _cleanup_dir(self, path: str):
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                logger.debug("Removed directory: %s", path)
            except Exception as exc:
                message = f"Warning: Could not remove {path}: {exc}"
                console.print(f"[yellow]{message}[/yellow]")
                logger.warning(message)

    def validate_docker_environment(self):
        console.print("[blue]Validating Docker environment...[/blue]")
        self._run_cmd(["docker", "--version"], capture_output=True)
        self._run_cmd(self.compose_cmd + ["version"], capture_output=True)
        console.print("[green]Docker is available.[/green]")

    def validate_source_accessibility(self):
        """Checks source and addons inputs early with strict validation."""
        console.print("[blue]Validating source accessibility...[/blue]")
        logger.info("Validating source: %s", self.source)

        self._ensure_supported_source_extension(self.source)

        if self._is_url(self.source):
            self._probe_url(self.source, "source URL")
            console.print("[green]Source URL is accessible.[/green]")
        else:
            if not os.path.exists(self.source):
                raise UpgraderError(f"Source file not found: {self.source}")
            if not os.path.isfile(self.source):
                raise UpgraderError(f"Source path must be a file: {self.source}")
            console.print("[green]Source file exists.[/green]")

        if not self.extra_addons:
            return

        console.print("[blue]Validating extra addons...[/blue]")

        if self._is_url(self.extra_addons):
            self._ensure_supported_addons_extension(self.extra_addons)
            self._probe_url(self.extra_addons, "extra addons URL")
            return

        if not os.path.exists(self.extra_addons):
            raise UpgraderError(f"Extra addons path not found: {self.extra_addons}")

        if os.path.isdir(self.extra_addons):
            return

        if os.path.isfile(self.extra_addons):
            self._ensure_supported_addons_extension(self.extra_addons)
            return

        raise UpgraderError(
            "Invalid extra addons source. Provide a local directory, a local `.zip` file, "
            "or an HTTPS URL to a `.zip` file."
        )

    def prepare_environment(self):
        logger.info("Preparing environment directories...")
        self._cleanup_dir(self.source_dir)
        self._cleanup_dir(self.output_dir)

        os.makedirs(self.source_dir, exist_ok=True)
        os.makedirs(self.filestore_dir, exist_ok=True)
        os.makedirs(self.custom_addons_dir, exist_ok=True)

        self._set_permissions(self.source_dir, DIR_MODE)
        self._set_permissions(self.output_dir, DIR_MODE)
        self._set_permissions(self.filestore_dir, DIR_MODE)
        self._set_permissions(self.custom_addons_dir, DIR_MODE)

    def download_file(
        self,
        url: str,
        dest_path: str,
        description: str = "Downloading...",
        expected_sha256: Optional[str] = None,
    ):
        logger.info("Downloading %s to %s", url, dest_path)
        self._enforce_https_policy(url, description)

        hasher = hashlib.sha256() if expected_sha256 else None

        try:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", 0))

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    "•",
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(f"[cyan]{description}", total=total_size or None)
                    with open(dest_path, "wb") as file_obj:
                        for chunk in response.iter_content(chunk_size=8192):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            if hasher:
                                hasher.update(chunk)
                            progress.update(task, advance=len(chunk))

            if hasher:
                downloaded_sha = hasher.hexdigest()
                if downloaded_sha != expected_sha256:
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass
                    raise UpgraderError(
                        f"Checksum mismatch for {description}. Expected {expected_sha256}, "
                        f"but got {downloaded_sha}."
                    )

        except requests.RequestException as exc:
            raise UpgraderError(f"Download failed for {description}: {exc}") from exc

    def download_or_copy_source(self) -> str:
        if self._is_url(self.source):
            url_path = urlparse(self.source).path
            ext = Path(url_path).suffix.lower()
            filename = os.path.basename(url_path) or f"downloaded_db{ext or '.dump'}"
            target_path = os.path.join(self.source_dir, filename)
            self.download_file(
                self.source,
                target_path,
                "Downloading source DB...",
                expected_sha256=self.source_sha256,
            )
            return target_path

        return self.source

    def process_extra_addons(self):
        """Downloads/copies/extracts addons and normalizes structure."""
        if not self.extra_addons:
            return

        console.print("[blue]Processing custom addons...[/blue]")
        logger.info("Processing custom addons...")

        if self._is_url(self.extra_addons):
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

        requirements_path = os.path.join(self.custom_addons_dir, "requirements.txt")
        if not os.path.exists(requirements_path):
            with open(requirements_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("")
        elif os.path.getsize(requirements_path) == 0:
            logger.warning("Empty requirements.txt found in custom addons.")

        self._set_tree_permissions(self.custom_addons_dir)
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
        context = self.run_context
        content = f"""
services:
  db:
    container_name: {context.db_container_name}
    image: postgres:{self.postgres_version}
    environment:
      - POSTGRES_DB={context.postgres_bootstrap_db}
      - POSTGRES_PASSWORD={context.postgres_password}
      - POSTGRES_USER={context.postgres_user}
    networks:
      - {context.network_name}
    volumes:
      - {context.volume_name}:/var/lib/postgresql/data
    restart: unless-stopped

networks:
  {context.network_name}:
    driver: bridge
    name: {context.network_name}

volumes:
  {context.volume_name}:
"""
        with open("db-composer.yml", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(content.strip())

    def wait_for_db(self):
        console.print("[yellow]Waiting for database to be ready...[/yellow]")
        max_retries = 30
        context = self.run_context

        cmd = [
            "docker",
            "exec",
            context.db_container_name,
            "pg_isready",
            "-U",
            context.postgres_user,
            "-d",
            context.postgres_bootstrap_db,
        ]

        for _ in range(max_retries):
            result = self._run_cmd(cmd, check=False, capture_output=True)
            if result.returncode == 0:
                console.print("[green]Database is ready.[/green]")
                return
            time.sleep(2)

        raise UpgraderError(
            "Database failed to become ready. Check Docker logs and available resources."
        )

    def restore_database(self, file_type: str):
        console.print("[blue]Restoring database...[/blue]")
        logger.info("Restoring database...")

        context = self.run_context

        self._run_cmd(
            [
                "docker",
                "exec",
                context.db_container_name,
                "dropdb",
                "-U",
                context.postgres_user,
                "--if-exists",
                context.target_database,
            ],
            check=True,
            capture_output=True,
        )

        self._run_cmd(
            [
                "docker",
                "exec",
                context.db_container_name,
                "createdb",
                "-U",
                context.postgres_user,
                context.target_database,
            ],
            check=True,
            capture_output=True,
        )

        if file_type == "ZIP":
            dump_path = os.path.join(self.source_dir, "dump.sql")
            if not os.path.exists(dump_path):
                sql_files = [
                    file_name for file_name in os.listdir(self.source_dir) if file_name.endswith(".sql")
                ]
                if not sql_files:
                    raise UpgraderError(
                        "No SQL dump found inside ZIP. Ensure it contains `dump.sql` or another `.sql` file."
                    )
                dump_path = os.path.join(self.source_dir, sql_files[0])

            source_filestore = os.path.join(self.source_dir, "filestore")
            if os.path.exists(source_filestore):
                try:
                    shutil.copytree(source_filestore, self.filestore_dir, dirs_exist_ok=True)
                    self._set_permissions(self.filestore_dir, DIR_MODE)
                    self._set_tree_permissions(self.filestore_dir)
                except Exception as exc:
                    logger.warning("Failed to copy filestore: %s", exc)

            self._run_cmd(
                ["docker", "cp", dump_path, f"{context.db_container_name}:/tmp/dump.sql"],
                check=True,
                capture_output=True,
            )

            self._run_cmd(
                [
                    "docker",
                    "exec",
                    "-i",
                    context.db_container_name,
                    "psql",
                    "-U",
                    context.postgres_user,
                    "-d",
                    context.target_database,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-f",
                    "/tmp/dump.sql",
                ],
                check=True,
                capture_output=True,
            )
            return

        dump_path = os.path.join(self.source_dir, "database.dump")
        self._run_cmd(
            ["docker", "cp", dump_path, f"{context.db_container_name}:/tmp/database.dump"],
            check=True,
            capture_output=True,
        )

        self._run_cmd(
            [
                "docker",
                "exec",
                context.db_container_name,
                "pg_restore",
                "-U",
                context.postgres_user,
                "-d",
                context.target_database,
                "--no-owner",
                "--no-privileges",
                "--clean",
                "--if-exists",
                "--single-transaction",
                "--exit-on-error",
                "/tmp/database.dump",
            ],
            check=True,
            capture_output=True,
        )

    def get_current_version(self) -> str:
        context = self.run_context
        queries = [
            "SELECT latest_version FROM ir_module_module WHERE name = 'base' AND state = 'installed';",
            "SELECT value FROM ir_config_parameter WHERE key = 'database.latest_version';",
            "SELECT latest_version FROM ir_module_module WHERE name = 'base' ORDER BY id DESC LIMIT 1;",
        ]

        for query in queries:
            result = self._run_cmd(
                [
                    "docker",
                    "exec",
                    "-i",
                    context.db_container_name,
                    "psql",
                    "-U",
                    context.postgres_user,
                    "-d",
                    context.target_database,
                    "-t",
                    "-A",
                    "-c",
                    query,
                ],
                check=False,
                capture_output=True,
            )

            if result.returncode != 0:
                continue

            for line in result.stdout.splitlines():
                cleaned = line.strip()
                if cleaned:
                    return cleaned

        return ""

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
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/OCA/OpenUpgrade.git --depth 1 --branch {target_version} /mnt/extra-addons
RUN pip3 install --no-cache-dir -r /mnt/extra-addons/requirements.txt

{custom_addons_section}

USER odoo
""".strip()

    def _build_upgrade_compose(self, extra_addons_path_arg: str) -> str:
        context = self.run_context
        return f"""
services:
  odoo-openupgrade:
    image: odoo-openupgrade
    build:
      context: .
      dockerfile: Dockerfile
    container_name: {context.upgrade_container_name}
    environment:
      - HOST={context.db_container_name}
      - POSTGRES_USER={context.postgres_user}
      - POSTGRES_PASSWORD={context.postgres_password}
    networks:
      - {context.network_name}
    volumes:
      - ./output/filestore:/var/lib/odoo/filestore/{context.target_database}
      - ./output:/var/log/odoo
    restart: "no"
    entrypoint: /entrypoint.sh
    command: >
      odoo -d {context.target_database}
      --upgrade-path=/mnt/extra-addons/openupgrade_scripts/scripts
      --addons-path=/mnt/extra-addons{extra_addons_path_arg}
      --update all
      --stop-after-init
      --load=base,web,openupgrade_framework
      --log-level=info
      --logfile=/var/log/odoo/odoo.log
networks:
  {context.network_name}:
    external: true
    name: {context.network_name}
""".strip()

    def run_upgrade_step(self, target_version: str) -> bool:
        logger.info("Preparing upgrade step to version %s", target_version)

        include_custom_addons = bool(self.extra_addons)
        extra_addons_path_arg = ",/mnt/custom-addons" if include_custom_addons else ""

        if include_custom_addons:
            timestamp_path = os.path.join(self.custom_addons_dir, ".build_timestamp")
            with open(timestamp_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(str(time.time()))

        dockerfile_content = self._build_upgrade_dockerfile(target_version, include_custom_addons)
        with open("Dockerfile", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(dockerfile_content)

        compose_content = self._build_upgrade_compose(extra_addons_path_arg)
        with open("odoo-upgrade-composer.yml", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(compose_content)

        self._run_cmd(
            ["docker", "rm", "-f", self.run_context.upgrade_container_name],
            check=False,
            capture_output=True,
        )

        cmd_up = self.compose_cmd + [
            "-f",
            "odoo-upgrade-composer.yml",
            "up",
            "--build",
            "--abort-on-container-exit",
        ]

        last_lines: Deque[str] = deque(maxlen=40)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            progress.add_task(f"[bold magenta]Upgrading to {target_version}...", total=None)

            try:
                process = subprocess.Popen(
                    cmd_up,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )
            except Exception as exc:
                raise UpgraderError(f"Failed to start upgrade container: {exc}") from exc

            if not process.stdout:
                raise UpgraderError("Upgrade process did not expose logs. Aborting.")

            for line in process.stdout:
                cleaned = line.rstrip()
                if not cleaned:
                    continue
                last_lines.append(cleaned)
                logger.debug(cleaned)
                if self.verbose:
                    console.print(f"[dim]{cleaned}[/dim]")

            process.wait()

            if process.returncode != 0:
                logger.error("Upgrade process returned non-zero exit code: %s", process.returncode)
                if last_lines:
                    logger.error("Recent upgrade logs:\n%s", "\n".join(last_lines))
                    console.print("[red]Recent upgrade logs:[/red]")
                    for line in last_lines:
                        console.print(f"[red]{line}[/red]")
                return False

        inspect_result = self._run_cmd(
            [
                "docker",
                "inspect",
                self.run_context.upgrade_container_name,
                "--format={{.State.ExitCode}}",
            ],
            check=False,
            capture_output=True,
        )

        if inspect_result.returncode != 0:
            logger.error("Could not inspect upgrade container exit code.")
            return False

        try:
            exit_code = int(inspect_result.stdout.strip() or "1")
        except ValueError:
            logger.error("Invalid exit code from inspect: %s", inspect_result.stdout)
            return False

        if exit_code == 0:
            console.print(f"[green]Upgrade to {target_version} successful.[/green]")
            self._run_cmd(
                self.compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                check=False,
                capture_output=True,
            )
            return True

        console.print(f"[bold red]Container exited with code {exit_code}[/bold red]")
        return False

    def finalize_package(self):
        console.print("[blue]Creating final package...[/blue]")
        logger.info("Creating final package...")

        context = self.run_context
        dump_path = os.path.join(self.output_dir, "dump.sql")

        try:
            with open(dump_path, "w", encoding="utf-8") as file_obj:
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        context.db_container_name,
                        "pg_dump",
                        "-U",
                        context.postgres_user,
                        context.target_database,
                    ],
                    stdout=file_obj,
                    check=True,
                    text=True,
                )
        except Exception as exc:
            raise UpgraderError(f"Failed to dump final database: {exc}") from exc

        zip_name = os.path.join(self.output_dir, "upgraded.zip")
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(dump_path, "dump.sql")

            if os.path.exists(self.filestore_dir):
                for root, _, files in os.walk(self.filestore_dir):
                    for file_name in files:
                        file_path = os.path.join(root, file_name)
                        archive_name = os.path.relpath(file_path, self.output_dir)
                        zip_file.write(file_path, archive_name)

        console.print(f"[bold green]Upgrade Complete! Package available at: {zip_name}[/bold green]")
        logger.info("Upgrade complete. Package: %s", zip_name)

        try:
            os.remove(dump_path)
        except OSError:
            pass

    def cleanup_artifacts(self):
        logger.info("Cleaning up artifacts...")
        self._cleanup_dir(self.source_dir)
        self._cleanup_dir(self.filestore_dir)
        self._cleanup_dir(self.custom_addons_dir)

    def cleanup(self):
        console.print("[dim]Cleaning up Docker environment...[/dim]")
        logger.info("Cleaning up Docker environment...")

        if os.path.exists("odoo-upgrade-composer.yml"):
            self._run_cmd(
                self.compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                check=False,
                capture_output=True,
            )

        if os.path.exists("db-composer.yml"):
            self._run_cmd(
                self.compose_cmd + ["-f", "db-composer.yml", "down", "-v"],
                check=False,
                capture_output=True,
            )

        for file_name in ["Dockerfile", "odoo-upgrade-composer.yml", "db-composer.yml"]:
            if os.path.exists(file_name):
                try:
                    os.remove(file_name)
                except OSError as exc:
                    logger.warning("Could not remove %s: %s", file_name, exc)

    def run(self) -> int:
        try:
            logger.info("Starting OdooUpgrader...")

            if self.target_version not in self.VALID_VERSIONS:
                raise UpgraderError(f"Invalid version. Supported versions: {', '.join(self.VALID_VERSIONS)}")

            self.validate_docker_environment()
            self.validate_source_accessibility()
            self.prepare_environment()
            self.process_extra_addons()

            self.create_db_compose_file()
            self._run_cmd(self.compose_cmd + ["-f", "db-composer.yml", "up", "-d"], check=True)
            self.wait_for_db()

            local_source = self.download_or_copy_source()
            file_type = self.process_source_file(local_source)
            self.restore_database(file_type)

            current_ver_str = self.get_current_version()
            if not current_ver_str:
                raise UpgraderError(
                    "Could not determine database version after restore. "
                    "Check that the source dump is a valid Odoo database."
                )

            console.print(f"[bold blue]Current Database Version: {current_ver_str}[/bold blue]")
            logger.info("Current database version: %s", current_ver_str)

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
                    self.finalize_package()
                    self.cleanup_artifacts()
                    return 0

                if current_ver.major > target_ver.major:
                    console.print("[yellow]Current version is already higher than target.[/yellow]")
                    self.finalize_package()
                    self.cleanup_artifacts()
                    return 0

                next_ver_str = self.generate_next_version(current_ver_str)

                if next_ver_str not in self.VALID_VERSIONS:
                    raise UpgraderError(
                        f"No supported upgrade step found from {current_ver_str} to {self.target_version}."
                    )

                if not self.run_upgrade_step(next_ver_str):
                    raise UpgraderError(
                        f"Upgrade step to {next_ver_str} failed. "
                        "Review container logs in output/odoo.log and retry."
                    )

                new_ver_str = self.get_current_version()
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
                console.print(f"[blue]Database is now at version: {current_ver_str}[/blue]")

        except KeyboardInterrupt:
            console.print("[bold red]Operation cancelled by user.[/bold red]")
            logger.info("Operation cancelled by user")
            return 1
        except UpgraderError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            logger.error(str(exc))
            return 1
        except Exception as exc:
            console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
            logger.exception("Unexpected error")
            return 1
        finally:
            self.cleanup()
