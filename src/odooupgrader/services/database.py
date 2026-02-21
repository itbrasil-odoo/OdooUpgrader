"""Database restore/query/package services for OdooUpgrader."""

import os
import re
import zipfile
from pathlib import PurePosixPath
from typing import List, Set, cast

from odooupgrader.constants import DIR_MODE
from odooupgrader.errors import UpgraderError


class DatabaseService:
    """Handles PostgreSQL restore, version lookup and final packaging."""

    SQL_COMPAT_MAX_PASSES = 5
    SQL_COMPAT_FILE_SUFFIX = ".compat.sql"

    def __init__(self, logger, console, filesystem_service):
        self.logger = logger
        self.console = console
        self.filesystem_service = filesystem_service

    @staticmethod
    def _container_tmp_path(filename: str) -> str:
        return str(PurePosixPath("/", "tmp", filename))

    @staticmethod
    def _extract_unsupported_parameters(stderr_output: str) -> List[str]:
        params = re.findall(
            r'unrecognized configuration parameter\s+"([^"]+)"',
            stderr_output,
            flags=re.IGNORECASE,
        )
        unique: List[str] = []
        for param in params:
            if param not in unique:
                unique.append(param)
        return unique

    @staticmethod
    def _line_sets_parameter(line: str, parameter: str) -> bool:
        pattern = rf"^\s*SET\s+{re.escape(parameter)}\s*="
        return re.match(pattern, line, flags=re.IGNORECASE) is not None

    @staticmethod
    def _line_calls_set_config_parameter(line: str, parameter: str) -> bool:
        pattern = rf"^\s*SELECT\s+pg_catalog\.set_config\(\s*'{re.escape(parameter)}'\s*,"
        return re.match(pattern, line, flags=re.IGNORECASE) is not None

    def _create_sql_compat_dump(self, source_dump_path: str, unsupported_params: List[str]) -> str:
        params_set: Set[str] = {param.strip() for param in unsupported_params if param.strip()}
        if not params_set:
            raise UpgraderError("Could not build SQL compatibility dump: no unsupported params.")

        compat_dump_path = f"{source_dump_path}{self.SQL_COMPAT_FILE_SUFFIX}"
        removed_lines = 0

        with open(source_dump_path, "r", encoding="utf-8", errors="ignore") as src_file, open(
            compat_dump_path, "w", encoding="utf-8", newline="\n"
        ) as dst_file:
            for line in src_file:
                should_skip = any(
                    self._line_sets_parameter(line, param)
                    or self._line_calls_set_config_parameter(line, param)
                    for param in params_set
                )
                if should_skip:
                    removed_lines += 1
                    continue
                dst_file.write(line)

        if removed_lines == 0:
            raise UpgraderError(
                "Could not build SQL compatibility dump automatically because no matching "
                f"SET statements were found for: {', '.join(sorted(params_set))}."
            )

        self.logger.warning(
            "Created SQL compatibility dump at %s removing %s line(s) for params: %s",
            compat_dump_path,
            removed_lines,
            ", ".join(sorted(params_set)),
        )
        return compat_dump_path

    def _restore_sql_dump_with_compat(self, dump_path: str, run_context, run_cmd):
        attempted_params: Set[str] = set()
        current_dump_path = dump_path

        for pass_number in range(1, self.SQL_COMPAT_MAX_PASSES + 1):
            container_sql_dump = self._container_tmp_path("dump.sql")
            run_cmd(
                [
                    "docker",
                    "cp",
                    current_dump_path,
                    f"{run_context.db_container_name}:{container_sql_dump}",
                ],
                check=True,
                capture_output=True,
            )

            result = run_cmd(
                [
                    "docker",
                    "exec",
                    "-i",
                    run_context.db_container_name,
                    "psql",
                    "-U",
                    run_context.postgres_user,
                    "-d",
                    run_context.target_database,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-f",
                    container_sql_dump,
                ],
                check=False,
                capture_output=True,
                retry_count=0,
            )

            if result.returncode == 0:
                return

            stderr_output = (result.stderr or "").strip()
            unsupported = self._extract_unsupported_parameters(stderr_output)
            new_unsupported = [param for param in unsupported if param not in attempted_params]

            if new_unsupported and pass_number < self.SQL_COMPAT_MAX_PASSES:
                attempted_params.update(new_unsupported)
                self.logger.warning(
                    "SQL restore failed due to unsupported PostgreSQL parameter(s): %s. "
                    "Generating compatibility dump and retrying...",
                    ", ".join(new_unsupported),
                )
                current_dump_path = self._create_sql_compat_dump(current_dump_path, new_unsupported)
                continue

            command = (
                "docker exec -i "
                f"{run_context.db_container_name} psql -U {run_context.postgres_user} "
                f"-d {run_context.target_database} -v ON_ERROR_STOP=1 -f {container_sql_dump}"
            )
            message = f"Command failed ({result.returncode}): {command}"
            if stderr_output:
                message = f"{message}\n{stderr_output}"

            if unsupported:
                message = (
                    f"{message}\nDetected unsupported PostgreSQL settings in SQL dump: "
                    f"{', '.join(sorted(set(unsupported)))}. "
                    "Try using a newer --postgres-version or regenerate the dump with a "
                    "pg_dump version closer to your restore PostgreSQL version."
                )
            raise UpgraderError(message)

    def restore_database(
        self, file_type: str, source_dir: str, filestore_dir: str, run_context, run_cmd
    ):
        self.console.print("[blue]Restoring database...[/blue]")
        self.logger.info("Restoring database...")

        run_cmd(
            [
                "docker",
                "exec",
                run_context.db_container_name,
                "dropdb",
                "-U",
                run_context.postgres_user,
                "--if-exists",
                run_context.target_database,
            ],
            check=True,
            capture_output=True,
        )

        run_cmd(
            [
                "docker",
                "exec",
                run_context.db_container_name,
                "createdb",
                "-U",
                run_context.postgres_user,
                run_context.target_database,
            ],
            check=True,
            capture_output=True,
        )

        if file_type == "ZIP":
            dump_path = os.path.join(source_dir, "dump.sql")
            if not os.path.exists(dump_path):
                sql_files = [
                    file_name for file_name in os.listdir(source_dir) if file_name.endswith(".sql")
                ]
                if not sql_files:
                    raise UpgraderError(
                        "No SQL dump found inside ZIP. Ensure it contains `dump.sql` or another `.sql` file."
                    )
                dump_path = os.path.join(source_dir, sql_files[0])

            source_filestore = os.path.join(source_dir, "filestore")
            if os.path.exists(source_filestore):
                try:
                    self.filesystem_service.cleanup_dir(filestore_dir)
                    os.makedirs(filestore_dir, exist_ok=True)
                    self.filesystem_service.set_permissions(filestore_dir, DIR_MODE)
                    for item in os.listdir(source_filestore):
                        src_path = os.path.join(source_filestore, item)
                        dst_path = os.path.join(filestore_dir, item)
                        if os.path.isdir(src_path):
                            import shutil

                            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                        else:
                            import shutil

                            shutil.copy2(src_path, dst_path)
                    self.filesystem_service.set_tree_permissions(
                        filestore_dir,
                        dir_mode=0o755,
                        file_mode=0o644,
                        script_mode=0o755,
                    )
                except Exception as exc:
                    self.logger.warning("Failed to copy filestore: %s", exc)

            self._restore_sql_dump_with_compat(dump_path, run_context, run_cmd)
            return

        dump_path = os.path.join(source_dir, "database.dump")
        container_binary_dump = self._container_tmp_path("database.dump")
        run_cmd(
            ["docker", "cp", dump_path, f"{run_context.db_container_name}:{container_binary_dump}"],
            check=True,
            capture_output=True,
        )

        restore_result = run_cmd(
            [
                "docker",
                "exec",
                run_context.db_container_name,
                "pg_restore",
                "-U",
                run_context.postgres_user,
                "-d",
                run_context.target_database,
                "--no-owner",
                "--no-privileges",
                "--clean",
                "--if-exists",
                "--single-transaction",
                "--exit-on-error",
                container_binary_dump,
            ],
            check=False,
            capture_output=True,
            retry_count=0,
        )

        if restore_result.returncode == 0:
            return

        stderr_output = (restore_result.stderr or "").strip()
        base_message = (
            "pg_restore failed while restoring binary dump. "
            f"Return code: {restore_result.returncode}."
        )

        if "unsupported version" in stderr_output.lower():
            raise UpgraderError(
                f"{base_message}\n{stderr_output}\n"
                "This usually means the dump was created by a newer pg_dump version than "
                "the restore PostgreSQL image. Re-run with a newer --postgres-version."
            )

        if stderr_output:
            raise UpgraderError(f"{base_message}\n{stderr_output}")
        raise UpgraderError(base_message)

    def get_current_version(self, run_context, run_cmd) -> str:
        queries = [
            "SELECT latest_version FROM ir_module_module WHERE name = 'base' AND state = 'installed';",
            "SELECT value FROM ir_config_parameter WHERE key = 'database.latest_version';",
            "SELECT latest_version FROM ir_module_module WHERE name = 'base' ORDER BY id DESC LIMIT 1;",
        ]

        for query in queries:
            result = run_cmd(
                [
                    "docker",
                    "exec",
                    "-i",
                    run_context.db_container_name,
                    "psql",
                    "-U",
                    run_context.postgres_user,
                    "-d",
                    run_context.target_database,
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
                    return cast(str, cleaned)

        return ""

    def finalize_package(self, output_dir: str, filestore_dir: str, run_context, subprocess_module):
        self.console.print("[blue]Creating final package...[/blue]")
        self.logger.info("Creating final package...")

        dump_path = os.path.join(output_dir, "dump.sql")

        try:
            with open(dump_path, "w", encoding="utf-8") as file_obj:
                subprocess_module.run(
                    [
                        "docker",
                        "exec",
                        run_context.db_container_name,
                        "pg_dump",
                        "-U",
                        run_context.postgres_user,
                        run_context.target_database,
                    ],
                    stdout=file_obj,
                    check=True,
                    text=True,
                )
        except Exception as exc:
            raise UpgraderError(f"Failed to dump final database: {exc}") from exc

        zip_name = os.path.join(output_dir, "upgraded.zip")
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(dump_path, "dump.sql")

            if os.path.exists(filestore_dir):
                for root, _, files in os.walk(filestore_dir):
                    for file_name in files:
                        file_path = os.path.join(root, file_name)
                        archive_name = os.path.relpath(file_path, output_dir)
                        zip_file.write(file_path, archive_name)

        self.console.print(
            f"[bold green]Upgrade Complete! Package available at: {zip_name}[/bold green]"
        )
        self.logger.info("Upgrade complete. Package: %s", zip_name)

        try:
            os.remove(dump_path)
        except OSError:
            pass
