"""Shared domain models for OdooUpgrader."""

from dataclasses import dataclass


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
