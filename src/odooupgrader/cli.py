import logging

import click
from rich.logging import RichHandler

from .core import OdooUpgrader, UpgraderError


logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_level=False, show_path=False)],
)


@click.command()
@click.option("--source", required=True, help="Path to local .zip/.dump file or URL")
@click.option(
    "--version",
    required=True,
    type=click.Choice(OdooUpgrader.VALID_VERSIONS),
    help="Target Odoo version",
)
@click.option(
    "--extra-addons",
    required=False,
    help="Custom addons location: local folder, local .zip file, or URL to a .zip file.",
)
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
@click.option(
    "--postgres-version",
    default="13",
    help="PostgreSQL version for the database container (default: 13)",
)
@click.option("--log-file", type=click.Path(), help="Path to log file")
@click.option(
    "--allow-insecure-http",
    is_flag=True,
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
def main(
    source,
    version,
    extra_addons,
    verbose,
    postgres_version,
    log_file,
    allow_insecure_http,
    source_sha256,
    extra_addons_sha256,
):
    """Automate incremental Odoo database upgrades using OpenUpgrade."""
    logger = logging.getLogger("odooupgrader")

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
        )
    except UpgraderError as exc:
        raise click.ClickException(str(exc)) from exc

    raise SystemExit(upgrader.run())


if __name__ == "__main__":
    main()
