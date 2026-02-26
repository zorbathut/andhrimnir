import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    ble_address: str = ""
    ble_service_uuid: str = "0000ffb0-0000-1000-8000-00805f9b34fb"
    ble_char_uuid: str = "0000ffb2-0000-1000-8000-00805f9b34fb"
    ble_reconnect_delay: float = 5.0
    esp_host: str = ""
    esp_port: int = 6053
    esp_password: str = ""
    esp_noise_psk: str = ""
    esp_reconnect_delay: float = 5.0
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "andhrimnir.db"

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
        if v := os.environ.get("ANDHRIMNIR_BLE_SERVICE_UUID"):
            kwargs["ble_service_uuid"] = v
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
        if v := os.environ.get("ANDHRIMNIR_ESP_RECONNECT_DELAY"):
            kwargs["esp_reconnect_delay"] = float(v)
        if v := os.environ.get("ANDHRIMNIR_HOST"):
            kwargs["host"] = v
        if v := os.environ.get("ANDHRIMNIR_PORT"):
            kwargs["port"] = int(v)
        if v := os.environ.get("ANDHRIMNIR_DB_PATH"):
            kwargs["db_path"] = v
        return cls(**kwargs)


_TOML_BLE = {
    "address": "ble_address",
    "service_uuid": "ble_service_uuid",
    "char_uuid": "ble_char_uuid",
    "reconnect_delay": "ble_reconnect_delay",
}

_TOML_ESP = {
    "host": "esp_host",
    "port": "esp_port",
    "password": "esp_password",
    "noise_psk": "esp_noise_psk",
    "reconnect_delay": "esp_reconnect_delay",
}

_TOML_SERVER = {
    "host": "host",
    "port": "port",
    "db_path": "db_path",
}
