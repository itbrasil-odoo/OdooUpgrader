import pytest

from odooupgrader.errors import UpgraderError
from odooupgrader.services.config_loader import ConfigLoader


def test_config_loader_loads_yaml_mapping(tmp_path):
    config_file = tmp_path / ".odooupgrader.yml"
    config_file.write_text(
        "source: ./source.dump\nversion: '15.0'\nretry_count: 2\n",
        encoding="utf-8",
    )

    loader = ConfigLoader()
    loaded = loader.load(str(config_file))

    assert loaded["source"] == "./source.dump"
    assert loaded["version"] == "15.0"
    assert loaded["retry_count"] == 2


def test_config_loader_rejects_unknown_keys(tmp_path):
    config_file = tmp_path / ".odooupgrader.yml"
    config_file.write_text("unknown_key: true\n", encoding="utf-8")

    loader = ConfigLoader()

    with pytest.raises(UpgraderError, match="Unknown configuration keys"):
        loader.load(str(config_file))
