import logging
import os

import click
from rich.logging import RichHandler

from .core import OdooUpgrader, UpgraderError
from .services.config_loader import ConfigLoader


def _resolve_option(cli_value, config, key, default=None):
    if cli_value is not None:
        return cli_value
    if key in config:
        return config[key]
    return default


logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_level=False, show_path=False)],
)


@click.command()
@click.option("--source", required=False, help="Path to local .zip/.dump file or URL")
@click.option(
    "--version",
    required=False,
    type=click.Choice(OdooUpgrader.VALID_VERSIONS),
    help="Target Odoo version",
)
@click.option(
    "--config",
    required=False,
    type=click.Path(),
    help="Path to a YAML configuration file. Defaults to .odooupgrader.yml if present.",
)
@click.option(
    "--extra-addons",
    required=False,
    help="Custom addons location: local folder, local .zip file, or URL to a .zip file.",
)
@click.option("--verbose", is_flag=True, default=None, help="Enable verbose logging")
@click.option(
    "--postgres-version",
    required=False,
    default=None,
    help="PostgreSQL version for the database container (default: 13)",
)
@click.option("--log-file", type=click.Path(), help="Path to log file")
@click.option(
    "--allow-insecure-http",
    is_flag=True,
    default=None,
    help="Allow HTTP URLs (insecure). By default only HTTPS URLs are accepted.",
)
@click.option(
    "--source-sha256",
    required=False,
    help="Expected SHA-256 checksum for the source download (remote source only).",
)
@click.option(
    "--extra-addons-sha256",
    required=False,
    help="Expected SHA-256 checksum for the extra addons download (remote addons only).",
)
@click.option(
    "--resume",
    is_flag=True,
    default=None,
    help="Resume a previously interrupted run using the execution state file.",
)
@click.option(
    "--state-file",
    required=False,
    type=click.Path(),
    help="Path to the run state file (default: output/run-state.json).",
)
@click.option(
    "--download-timeout",
    required=False,
    type=float,
    default=None,
    help="HTTP download timeout in seconds.",
)
@click.option(
    "--retry-count",
    required=False,
    type=int,
    default=None,
    help="Number of retries for transient runtime/download failures.",
)
@click.option(
    "--retry-backoff-seconds",
    required=False,
    type=float,
    default=None,
    help="Backoff time in seconds between retries.",
)
@click.option(
    "--step-timeout-minutes",
    required=False,
    type=int,
    default=None,
    help="Timeout for each OpenUpgrade step in minutes.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=None,
    help="Validate inputs and print upgrade plan without running Docker or changing state.",
)
@click.option(
    "--analyze-modules",
    is_flag=True,
    default=None,
    help="Audit installed modules and check OCA modules against the target version.",
)
@click.option(
    "--analyze-modules-only",
    is_flag=True,
    default=None,
    help="Run module audit and stop before upgrade steps.",
)
@click.option(
    "--strict-module-audit",
    is_flag=True,
    default=None,
    help="Fail execution when module audit detects missing OCA modules or check errors.",
)
@click.option(
    "--module-audit-file",
    required=False,
    type=click.Path(),
    help="Path for module audit JSON report (default: output/module-audit.json).",
)
def main(
    source,
    version,
    config,
    extra_addons,
    verbose,
    postgres_version,
    log_file,
    allow_insecure_http,
    source_sha256,
    extra_addons_sha256,
    resume,
    state_file,
    download_timeout,
    retry_count,
    retry_backoff_seconds,
    step_timeout_minutes,
    dry_run,
    analyze_modules,
    analyze_modules_only,
    strict_module_audit,
    module_audit_file,
):
    """Automate incremental Odoo database upgrades using OpenUpgrade."""
    logger = logging.getLogger("odooupgrader")

    try:
        config_loader = ConfigLoader()
        resolved_config = config
        if resolved_config is None:
            default_config_path = os.path.join(os.getcwd(), ".odooupgrader.yml")
            if os.path.exists(default_config_path):
                resolved_config = default_config_path

        config_values = config_loader.load(resolved_config)
    except UpgraderError as exc:
        raise click.ClickException(str(exc)) from exc

    source = _resolve_option(source, config_values, "source")
    version = _resolve_option(version, config_values, "version")
    extra_addons = _resolve_option(extra_addons, config_values, "extra_addons")
    verbose = bool(_resolve_option(verbose, config_values, "verbose", default=False))
    postgres_version = str(
        _resolve_option(postgres_version, config_values, "postgres_version", default="13")
    )
    log_file = _resolve_option(log_file, config_values, "log_file")
    allow_insecure_http = bool(
        _resolve_option(allow_insecure_http, config_values, "allow_insecure_http", default=False)
    )
    source_sha256 = _resolve_option(source_sha256, config_values, "source_sha256")
    extra_addons_sha256 = _resolve_option(extra_addons_sha256, config_values, "extra_addons_sha256")
    resume = bool(_resolve_option(resume, config_values, "resume", default=False))
    state_file = _resolve_option(state_file, config_values, "state_file")
    download_timeout = float(
        _resolve_option(download_timeout, config_values, "download_timeout", default=60.0)
    )
    retry_count = int(_resolve_option(retry_count, config_values, "retry_count", default=1))
    retry_backoff_seconds = float(
        _resolve_option(
            retry_backoff_seconds,
            config_values,
            "retry_backoff_seconds",
            default=2.0,
        )
    )
    step_timeout_minutes = int(
        _resolve_option(step_timeout_minutes, config_values, "step_timeout_minutes", default=120)
    )
    dry_run = bool(_resolve_option(dry_run, config_values, "dry_run", default=False))
    analyze_modules = bool(
        _resolve_option(analyze_modules, config_values, "analyze_modules", default=False)
    )
    analyze_modules_only = bool(
        _resolve_option(
            analyze_modules_only,
            config_values,
            "analyze_modules_only",
            default=False,
        )
    )
    strict_module_audit = bool(
        _resolve_option(strict_module_audit, config_values, "strict_module_audit", default=False)
    )
    module_audit_file = _resolve_option(module_audit_file, config_values, "module_audit_file")

    if not source:
        raise click.ClickException("Missing required option '--source' (or provide it in config).")
    if not version:
        raise click.ClickException("Missing required option '--version' (or provide it in config).")

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(file_handler)

    try:
        upgrader = OdooUpgrader(
            source=source,
            target_version=version,
            extra_addons=extra_addons,
            verbose=verbose,
            postgres_version=postgres_version,
            allow_insecure_http=allow_insecure_http,
            source_sha256=source_sha256,
            extra_addons_sha256=extra_addons_sha256,
            resume=resume,
            state_file=state_file,
            download_timeout=download_timeout,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff_seconds,
            step_timeout_minutes=step_timeout_minutes,
            dry_run=dry_run,
            analyze_modules=analyze_modules,
            analyze_modules_only=analyze_modules_only,
            strict_module_audit=strict_module_audit,
            module_audit_file=module_audit_file,
        )
    except UpgraderError as exc:
        raise click.ClickException(str(exc)) from exc

    raise SystemExit(upgrader.run())


if __name__ == "__main__":
    main()
