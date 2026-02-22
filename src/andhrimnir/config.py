import os
from dataclasses import dataclass


@dataclass
class Settings:
    ble_address: str = "02:CA:6A:21:A7:16"
    ble_service_uuid: str = "0000ffb0-0000-1000-8000-00805f9b34fb"
    ble_char_uuid: str = "0000ffb2-0000-1000-8000-00805f9b34fb"
    ble_reconnect_delay: float = 5.0
    host: str = "0.0.0.0"
    port: int = 8000

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
        if v := os.environ.get("ANDHRIMNIR_HOST"):
            kwargs["host"] = v
        if v := os.environ.get("ANDHRIMNIR_PORT"):
            kwargs["port"] = int(v)
        return cls(**kwargs)
