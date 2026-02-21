"""OpenUpgrade step execution service for OdooUpgrader."""

import os
import time
from collections import deque
from typing import Deque, Optional


class UpgradeStepService:
    """Builds/runs per-version OpenUpgrade container steps."""

    def __init__(self, logger, console):
        self.logger = logger
        self.console = console

    def build_upgrade_dockerfile(self, target_version: str, include_custom_addons: bool) -> str:
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

    def build_upgrade_compose(self, run_context, extra_addons_path_arg: str) -> str:
        return f"""
services:
  odoo-openupgrade:
    image: odoo-openupgrade
    build:
      context: .
      dockerfile: Dockerfile
    container_name: {run_context.upgrade_container_name}
    environment:
      - HOST={run_context.db_container_name}
      - POSTGRES_USER={run_context.postgres_user}
      - POSTGRES_PASSWORD={run_context.postgres_password}
    networks:
      - {run_context.network_name}
    volumes:
      - ./output/filestore:/var/lib/odoo/filestore/{run_context.target_database}
      - ./output:/var/log/odoo
    restart: "no"
    entrypoint: /entrypoint.sh
    command: >
      odoo -d {run_context.target_database}
      --upgrade-path=/mnt/extra-addons/openupgrade_scripts/scripts
      --addons-path=/mnt/extra-addons{extra_addons_path_arg}
      --update all
      --stop-after-init
      --load=base,web,openupgrade_framework
      --log-level=info
      --logfile=/var/log/odoo/odoo.log
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
    ) -> bool:
        self.logger.info("Preparing upgrade step to version %s", target_version)

        include_custom_addons = bool(extra_addons)
        extra_addons_path_arg = ",/mnt/custom-addons" if include_custom_addons else ""

        if include_custom_addons:
            timestamp_path = os.path.join(custom_addons_dir, ".build_timestamp")
            with open(timestamp_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(str(time.time()))

        dockerfile_content = self.build_upgrade_dockerfile(target_version, include_custom_addons)
        with open("Dockerfile", "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(dockerfile_content)

        compose_content = self.build_upgrade_compose(run_context, extra_addons_path_arg)
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

        last_lines: Deque[str] = deque(maxlen=40)

        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            progress.add_task(f"[bold magenta]Upgrading to {target_version}...", total=None)

            try:
                process = subprocess_module.Popen(
                    cmd_up,
                    stdout=subprocess_module.PIPE,
                    stderr=subprocess_module.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )
            except Exception as exc:
                from odooupgrader.errors import UpgraderError

                raise UpgraderError(f"Failed to start upgrade container: {exc}") from exc

            if not process.stdout:
                from odooupgrader.errors import UpgraderError

                raise UpgraderError("Upgrade process did not expose logs. Aborting.")

            for line in process.stdout:
                cleaned = line.rstrip()
                if not cleaned:
                    continue
                last_lines.append(cleaned)
                self.logger.debug(cleaned)
                if verbose:
                    self.console.print(f"[dim]{cleaned}[/dim]")

            process.wait()

            if process.returncode != 0:
                self.logger.error("Upgrade process returned non-zero exit code: %s", process.returncode)
                if last_lines:
                    self.logger.error("Recent upgrade logs:\n%s", "\n".join(last_lines))
                    self.console.print("[red]Recent upgrade logs:[/red]")
                    for line in last_lines:
                        self.console.print(f"[red]{line}[/red]")
                return False

        inspect_result = run_cmd(
            ["docker", "inspect", run_context.upgrade_container_name, "--format={{.State.ExitCode}}"],
            check=False,
            capture_output=True,
        )

        if inspect_result.returncode != 0:
            self.logger.error("Could not inspect upgrade container exit code.")
            return False

        try:
            exit_code = int(inspect_result.stdout.strip() or "1")
        except ValueError:
            self.logger.error("Invalid exit code from inspect: %s", inspect_result.stdout)
            return False

        if exit_code == 0:
            self.console.print(f"[green]Upgrade to {target_version} successful.[/green]")
            run_cmd(
                compose_cmd + ["-f", "odoo-upgrade-composer.yml", "down"],
                check=False,
                capture_output=True,
            )
            return True

        self.console.print(f"[bold red]Container exited with code {exit_code}[/bold red]")
        return False
