"""Docker runtime services for OdooUpgrader."""

import subprocess
import time
from typing import Callable, List

from odooupgrader.errors import UpgraderError


class DockerRuntimeService:
    """Manages docker-compose detection and runtime lifecycle helpers."""

    def __init__(self, logger, console, subprocess_module=subprocess):
        self.logger = logger
        self.console = console
        self.subprocess = subprocess_module

    def get_docker_compose_cmd(self) -> List[str]:
        try:
            self.subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
            return ["docker", "compose"]
        except (self.subprocess.CalledProcessError, FileNotFoundError):
            try:
                self.subprocess.run(["docker-compose", "--version"], check=True, capture_output=True)
                return ["docker-compose"]
            except (self.subprocess.CalledProcessError, FileNotFoundError):
                raise UpgraderError(
                    "Docker Compose is not available. Install Docker Compose v2 (`docker compose`) "
                    "or v1 (`docker-compose`) and try again."
                )

    def validate_environment(self, compose_cmd: List[str], run_cmd: Callable):
        self.console.print("[blue]Validating Docker environment...[/blue]")
        run_cmd(["docker", "--version"], capture_output=True)
        run_cmd(compose_cmd + ["version"], capture_output=True)
        self.console.print("[green]Docker is available.[/green]")

    def create_db_compose_file(self, run_context, postgres_version: str):
        content = f"""
services:
  db:
    container_name: {run_context.db_container_name}
    image: postgres:{postgres_version}
    environment:
      - POSTGRES_DB={run_context.postgres_bootstrap_db}
      - POSTGRES_PASSWORD={run_context.postgres_password}
      - POSTGRES_USER={run_context.postgres_user}
    networks:
      - {run_context.network_name}
    volumes:
      - {run_context.volume_name}:/var/lib/postgresql/data
    restart: unless-stopped

networks:
  {run_context.network_name}:
    driver: bridge
    name: {run_context.network_name}

volumes:
  {run_context.volume_name}:
"""
        with open("db-composer.yml", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(content.strip())

    def wait_for_db(self, run_context, run_cmd: Callable, max_retries: int = 30):
        self.console.print("[yellow]Waiting for database to be ready...[/yellow]")

        cmd = [
            "docker",
            "exec",
            run_context.db_container_name,
            "pg_isready",
            "-U",
            run_context.postgres_user,
            "-d",
            run_context.postgres_bootstrap_db,
        ]

        for _ in range(max_retries):
            result = run_cmd(cmd, check=False, capture_output=True)
            if result.returncode == 0:
                self.console.print("[green]Database is ready.[/green]")
                return
            time.sleep(2)

        raise UpgraderError(
            "Database failed to become ready. Check Docker logs and available resources."
        )

    def cleanup_docker_environment(self, compose_cmd: List[str], run_cmd: Callable):
        self.console.print("[dim]Cleaning up Docker environment...[/dim]")
        self.logger.info("Cleaning up Docker environment...")

        run_cmd(
            compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
            check=False,
            capture_output=True,
        )
        run_cmd(
            compose_cmd + ["-f", "db-composer.yml", "down", "-v"],
            check=False,
            capture_output=True,
        )
