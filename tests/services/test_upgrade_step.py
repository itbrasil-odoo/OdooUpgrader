from odooupgrader.models import RunContext
from odooupgrader.services.upgrade_step import UpgradeStepService


class DummyLogger:
    def info(self, *_args, **_kwargs):
        return None

    def debug(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


class DummyConsole:
    def print(self, *_args, **_kwargs):
        return None


def _build_context() -> RunContext:
    return RunContext(
        run_id="abc123",
        db_container_name="db_name",
        upgrade_container_name="upgrade_name",
        network_name="net_name",
        volume_name="vol_name",
        postgres_user="pg_user",
        postgres_password="pg_pass",
        postgres_bootstrap_db="odoo",
        target_database="database",
    )


def test_build_upgrade_dockerfile_includes_custom_addons_section():
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())

    dockerfile = service.build_upgrade_dockerfile("16.0", include_custom_addons=True)

    assert "FROM odoo:16.0" in dockerfile
    assert "COPY --chown=odoo:odoo ./output/custom_addons/ /mnt/custom-addons/" in dockerfile


def test_build_upgrade_compose_uses_dynamic_runtime_names():
    service = UpgradeStepService(logger=DummyLogger(), console=DummyConsole())

    compose = service.build_upgrade_compose(_build_context(), extra_addons_path_arg=",/mnt/custom-addons")

    assert "container_name: upgrade_name" in compose
    assert "- HOST=db_name" in compose
    assert "--addons-path=/mnt/extra-addons,/mnt/custom-addons" in compose
    assert "name: net_name" in compose
