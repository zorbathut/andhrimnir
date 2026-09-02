import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE_KINDS = ("ble", "esp")


class ConfigError(Exception):
    """A setting was supplied but could not be used."""


@dataclass
class Settings:
    ble_address: str = ""
    ble_char_uuid: str = "0000ffb2-0000-1000-8000-00805f9b34fb"
    ble_reconnect_delay: float = 5.0
    esp_host: str = ""
    esp_port: int = 6053
    esp_password: str = ""
    esp_noise_psk: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "andhrimnir.db"
    source: str = ""

    @property
    def source_kind(self) -> str:
        """Which backend to read probes through; defaults to the proxy when one is configured."""
        if self.source:
            return self.source
        return "esp" if self.esp_host else "ble"

    @classmethod
    def from_env(cls) -> "Settings":
        kwargs: dict = {}

        # Load config.toml if present
        cfg = Path("config.toml")
        if cfg.exists():
            with open(cfg, "rb") as f:
                toml = tomllib.load(f)
            ble = toml.get("ble", {})
            esp = toml.get("esp", {})
            server = toml.get("server", {})
            for toml_key, field in _TOML_BLE.items():
                if toml_key in ble:
                    kwargs[field] = ble[toml_key]
            for toml_key, field in _TOML_ESP.items():
                if toml_key in esp:
                    kwargs[field] = esp[toml_key]
            for toml_key, field in _TOML_SERVER.items():
                if toml_key in server:
                    kwargs[field] = server[toml_key]

        # Env vars override config file
        if v := os.environ.get("ANDHRIMNIR_BLE_ADDRESS"):
            kwargs["ble_address"] = v
        if v := os.environ.get("ANDHRIMNIR_BLE_CHAR_UUID"):
            kwargs["ble_char_uuid"] = v
        if v := os.environ.get("ANDHRIMNIR_BLE_RECONNECT_DELAY"):
            kwargs["ble_reconnect_delay"] = float(v)
        if v := os.environ.get("ANDHRIMNIR_ESP_HOST"):
            kwargs["esp_host"] = v
        if v := os.environ.get("ANDHRIMNIR_ESP_PORT"):
            kwargs["esp_port"] = int(v)
        if v := os.environ.get("ANDHRIMNIR_ESP_PASSWORD"):
            kwargs["esp_password"] = v
        if v := os.environ.get("ANDHRIMNIR_ESP_NOISE_PSK"):
            kwargs["esp_noise_psk"] = v
        if v := os.environ.get("ANDHRIMNIR_HOST"):
            kwargs["host"] = v
        if v := os.environ.get("ANDHRIMNIR_PORT"):
            kwargs["port"] = int(v)
        if v := os.environ.get("ANDHRIMNIR_DB_PATH"):
            kwargs["db_path"] = v
        if v := os.environ.get("ANDHRIMNIR_SOURCE"):
            kwargs["source"] = v

        settings = cls(**kwargs)
        if settings.source and settings.source not in SOURCE_KINDS:
            raise ConfigError(f"source: expected one of {', '.join(SOURCE_KINDS)}, got {settings.source!r}")
        return settings


_TOML_BLE = {
    "address": "ble_address",
    "char_uuid": "ble_char_uuid",
    "reconnect_delay": "ble_reconnect_delay",
}

_TOML_ESP = {
    "host": "esp_host",
    "port": "esp_port",
    "password": "esp_password",
    "noise_psk": "esp_noise_psk",
}

_TOML_SERVER = {
    "host": "host",
    "port": "port",
    "db_path": "db_path",
    "source": "source",
}
