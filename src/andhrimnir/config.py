import os
from dataclasses import dataclass


@dataclass
class Settings:
    ble_address: str = "02:CA:6A:21:A7:16"
    ble_service_uuid: str = "0000ffb0-0000-1000-8000-00805f9b34fb"
    ble_char_uuid: str = "0000ffb2-0000-1000-8000-00805f9b34fb"
    ble_reconnect_delay: float = 5.0
    esp_host: str = "192.168.42.60"
    esp_port: int = 6053
    esp_password: str = ""
    esp_noise_psk: str = ""
    esp_reconnect_delay: float = 5.0
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "andhrimnir.db"

    @classmethod
    def from_env(cls) -> "Settings":
        kwargs = {}
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
