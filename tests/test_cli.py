from click.testing import CliRunner

import odooupgrader.cli as cli_module


def test_cli_uses_config_and_allows_cli_override(tmp_path, monkeypatch):
    config_file = tmp_path / ".odooupgrader.yml"
    config_file.write_text(
        "source: config.dump\n" "version: '15.0'\n" "retry_count: 3\n" "download_timeout: 45\n",
        encoding="utf-8",
    )

    captured = {}

    class FakeUpgrader:
        VALID_VERSIONS = cli_module.OdooUpgrader.VALID_VERSIONS

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return 0

    monkeypatch.setattr(cli_module, "OdooUpgrader", FakeUpgrader)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.main,
        [
            "--config",
            str(config_file),
            "--source",
            "cli.dump",
            "--retry-count",
            "5",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert captured["source"] == "cli.dump"
    assert captured["target_version"] == "15.0"
    assert captured["retry_count"] == 5
    assert captured["download_timeout"] == 45.0
    assert captured["dry_run"] is True


def test_cli_uses_default_config_file_when_present(tmp_path, monkeypatch):
    default_config = tmp_path / ".odooupgrader.yml"
    default_config.write_text(
        "source: default.dump\n" "version: '16.0'\n",
        encoding="utf-8",
    )

    captured = {}

    class FakeUpgrader:
        VALID_VERSIONS = cli_module.OdooUpgrader.VALID_VERSIONS

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return 0

    monkeypatch.setattr(cli_module, "OdooUpgrader", FakeUpgrader)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli_module.main, [])

    assert result.exit_code == 0
    assert captured["source"] == "default.dump"
    assert captured["target_version"] == "16.0"
