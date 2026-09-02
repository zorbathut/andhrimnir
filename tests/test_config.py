import pytest

from andhrimnir.config import ConfigError, Settings

TOML = """\
[ble]
address = "AA:BB:CC:DD:EE:FF"
reconnect_delay = 2.5

[esp]
host = "192.168.1.50"
port = 6054

[server]
port = 9000
db_path = "from-toml.db"
"""


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    for field in ("BLE_ADDRESS", "ESP_HOST", "ESP_PORT", "PORT", "DB_PATH", "SOURCE", "BLE_RECONNECT_DELAY"):
        monkeypatch.delenv(f"ANDHRIMNIR_{field}", raising=False)
    path = tmp_path / "config.toml"
    path.write_text(TOML)
    return path


def test_defaults_apply_when_no_config_exists(tmp_path):
    settings = Settings.load(tmp_path / "absent.toml")
    assert settings.port == 8000
    assert settings.ble_address == ""


def test_toml_is_loaded_and_typed(config_path):
    settings = Settings.load(config_path)
    assert settings.ble_address == "AA:BB:CC:DD:EE:FF"
    assert settings.ble_reconnect_delay == 2.5
    assert settings.esp_port == 6054
    assert settings.port == 9000


def test_env_overrides_toml(config_path, monkeypatch):
    monkeypatch.setenv("ANDHRIMNIR_PORT", "7000")
    monkeypatch.setenv("ANDHRIMNIR_BLE_ADDRESS", "11:22:33:44:55:66")
    settings = Settings.load(config_path)
    assert settings.port == 7000
    assert settings.ble_address == "11:22:33:44:55:66"


def test_env_values_are_coerced_to_the_field_type(config_path, monkeypatch):
    monkeypatch.setenv("ANDHRIMNIR_ESP_PORT", "1234")
    monkeypatch.setenv("ANDHRIMNIR_BLE_RECONNECT_DELAY", "0.5")
    settings = Settings.load(config_path)
    assert settings.esp_port == 1234
    assert settings.ble_reconnect_delay == 0.5


def test_an_empty_env_var_does_not_clear_a_toml_value(config_path, monkeypatch):
    """Documented behaviour, not an endorsement: an env var can override a setting but not blank it."""
    monkeypatch.setenv("ANDHRIMNIR_ESP_HOST", "")
    assert Settings.load(config_path).esp_host == "192.168.1.50"


def test_db_path_is_resolved_absolute(config_path):
    assert Settings.load(config_path).db_path.startswith("/")


def test_source_defaults_to_the_proxy_when_one_is_configured():
    assert Settings(esp_host="192.168.1.50").source_kind == "esp"
    assert Settings(esp_host="").source_kind == "ble"


def test_an_explicit_source_wins_over_the_default():
    assert Settings(esp_host="192.168.1.50", source="ble").source_kind == "ble"


def test_an_unknown_source_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ANDHRIMNIR_SOURCE", "carrier-pigeon")
    with pytest.raises(ConfigError, match="carrier-pigeon"):
        Settings.load(tmp_path / "absent.toml")
