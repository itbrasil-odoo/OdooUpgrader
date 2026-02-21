"""Database restore/query/package services for OdooUpgrader."""

import os
import zipfile
from pathlib import PurePosixPath
from typing import cast

from odooupgrader.constants import DIR_MODE
from odooupgrader.errors import UpgraderError


class DatabaseService:
    """Handles PostgreSQL restore, version lookup and final packaging."""

    def __init__(self, logger, console, filesystem_service):
        self.logger = logger
        self.console = console
        self.filesystem_service = filesystem_service

    @staticmethod
    def _container_tmp_path(filename: str) -> str:
        return str(PurePosixPath("/", "tmp", filename))

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

            container_sql_dump = self._container_tmp_path("dump.sql")
            run_cmd(
                [
                    "docker",
                    "cp",
                    dump_path,
                    f"{run_context.db_container_name}:{container_sql_dump}",
                ],
                check=True,
                capture_output=True,
            )

            run_cmd(
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
                check=True,
                capture_output=True,
            )
            return

        dump_path = os.path.join(source_dir, "database.dump")
        container_binary_dump = self._container_tmp_path("database.dump")
        run_cmd(
            ["docker", "cp", dump_path, f"{run_context.db_container_name}:{container_binary_dump}"],
            check=True,
            capture_output=True,
        )

        run_cmd(
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
            check=True,
            capture_output=True,
        )

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
