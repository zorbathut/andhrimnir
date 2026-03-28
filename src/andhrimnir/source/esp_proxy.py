import asyncio
import logging
import struct
import time
from collections.abc import Callable
from datetime import datetime, timezone

import aioesphomeapi.model as _ble_model
from aioesphomeapi import APIClient

from andhrimnir.config import Settings
from andhrimnir.models import ProbeReading
from andhrimnir.source.base import BaseTemperatureSource

# Patch aioesphomeapi's UUID parser to handle empty UUID lists instead of
# crashing with IndexError.  Some BLE devices send services with neither
# short_uuid nor a full 128-bit UUID array.
_orig_join_split_uuid = _ble_model._join_split_uuid


def _safe_join_split_uuid(value: list[int]) -> str:
    if len(value) < 2:
        return "00000000-0000-0000-0000-000000000000"
    return _orig_join_split_uuid(value)


_ble_model._join_split_uuid = _safe_join_split_uuid

logger = logging.getLogger(__name__)

PROBE_DISCONNECTED = 0xFFFF
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"


def _mac_to_int(mac: str) -> int:
    return int(mac.replace(":", "").replace("-", ""), 16)


class ESPProxyTemperatureSource(BaseTemperatureSource):
    """Read BBQ probes via BLE, proxied through an ESP32 bluetooth_proxy."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._esp_host = settings.esp_host
        self._esp_port = settings.esp_port
        self._esp_password = settings.esp_password
        self._noise_psk = settings.esp_noise_psk or None
        self._ble_address = settings.ble_address
        self._ble_char_uuid = settings.ble_char_uuid
        self._reconnect_delay = settings.esp_reconnect_delay
        self._ble_address_int = _mac_to_int(self._ble_address)

    def _make_client(self) -> APIClient:
        return APIClient(
            address=self._esp_host,
            port=self._esp_port,
            password=self._esp_password,
            noise_psk=self._noise_psk,
        )

    async def probe(self) -> bool:
        if not self._esp_host or not self._ble_address:
            return False
        client = self._make_client()
        try:
            async with asyncio.timeout(5.0):
                await client.connect(login=True)
                await client.disconnect()
                return True
        except Exception:
            return False

    async def _wait_for_advertisement(
        self, client: APIClient, timeout: float = 30.0
    ) -> tuple[int, Callable[[], None]]:
        """Subscribe to raw BLE advertisements and wait for our target device.

        Returns (address_type, unsub) — caller must call unsub when done.
        """
        found: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        def on_raw_advs(msg: object) -> None:
            for adv in msg.advertisements:  # type: ignore[attr-defined]
                if adv.address == self._ble_address_int and not found.done():
                    found.set_result(adv.address_type)

        unsub = client.subscribe_bluetooth_le_raw_advertisements(on_raw_advs)
        try:
            async with asyncio.timeout(timeout):
                address_type = await found
        except BaseException:
            unsub()
            raise
        return address_type, unsub

    async def start(self) -> None:
        while not self._stop_event.is_set():
            client = self._make_client()
            cancel_connection_state = None
            stop_notify = None
            unsub_advs = None
            ble_connected = False
            try:
                logger.info(
                    "Connecting to ESP proxy %s:%s ...",
                    self._esp_host,
                    self._esp_port,
                )
                await client.connect(login=True)
                connect_time = time.monotonic()

                device_info = await client.device_info()
                feature_flags = device_info.bluetooth_proxy_feature_flags_compat(
                    client.api_version
                )
                logger.info(
                    "ESP API connected (bt features=0x%x), waiting for BLE device %s ...",
                    feature_flags,
                    self._ble_address,
                )

                # Wait for the device to appear in scan results so we get
                # the correct address_type and know it's in range.
                address_type, unsub_advs = await self._wait_for_advertisement(client)
                logger.info(
                    "Found %s (address_type=%d), connecting ...",
                    self._ble_address,
                    address_type,
                )

                connected_future: asyncio.Future[bool] = (
                    asyncio.get_running_loop().create_future()
                )
                disconnected = asyncio.Event()

                def on_connection_state(
                    connected: bool, mtu: int, error: int
                ) -> None:
                    nonlocal ble_connected
                    if not connected_future.done():
                        if error:
                            connected_future.set_exception(
                                ConnectionError(
                                    f"BLE connect error code {error}"
                                )
                            )
                        elif connected:
                            ble_connected = True
                            logger.info("BLE connected (mtu=%d)", mtu)
                            connected_future.set_result(True)
                        # else: intermediate state, keep waiting
                    elif not connected:
                        ble_connected = False
                        uptime = time.monotonic() - connect_time
                        logger.warning(
                            "BLE device disconnected (error=%d, uptime=%.1fs)",
                            error,
                            uptime,
                        )
                        disconnected.set()

                cancel_connection_state = await client.bluetooth_device_connect(
                    self._ble_address_int,
                    on_connection_state,
                    timeout=30.0,
                    feature_flags=feature_flags,
                    address_type=address_type,
                )
                await connected_future

                # Discover services to find the characteristic and CCCD handles
                services = await client.bluetooth_gatt_get_services(
                    self._ble_address_int
                )
                target_handle = None
                cccd_handle = None
                for service in services.services:
                    for char in service.characteristics:
                        if char.uuid.lower() == self._ble_char_uuid.lower():
                            target_handle = char.handle
                            for desc in char.descriptors:
                                if desc.uuid.lower() == CCCD_UUID:
                                    cccd_handle = desc.handle

                if target_handle is None:
                    raise RuntimeError(
                        f"Characteristic {self._ble_char_uuid} not found"
                    )

                logger.info(
                    "Subscribing to notifications on handle %d", target_handle
                )
                stop_notify_coro, _notify_abort = (
                    await client.bluetooth_gatt_start_notify(
                        self._ble_address_int,
                        target_handle,
                        self._handle_notification,
                    )
                )
                stop_notify = stop_notify_coro

                # The proxy's start_notify registers the callback but doesn't
                # write the CCCD — we must enable notifications explicitly.
                if cccd_handle is None:
                    cccd_handle = target_handle + 1
                await client.bluetooth_gatt_write_descriptor(
                    self._ble_address_int,
                    cccd_handle,
                    b"\x01\x00",
                    timeout=10.0,
                )
                logger.info("Notifications enabled")

                # Wait until BLE disconnects or we're told to stop
                stop_wait = asyncio.create_task(self._stop_event.wait())
                disc_wait = asyncio.create_task(disconnected.wait())
                done, pending = await asyncio.wait(
                    [stop_wait, disc_wait],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

            except Exception as exc:
                logger.warning(
                    "ESP proxy BLE error: %s: %s", type(exc).__name__, exc
                )
            finally:
                if unsub_advs is not None:
                    try:
                        unsub_advs()
                    except Exception:
                        pass
                if stop_notify is not None:
                    try:
                        await stop_notify()
                    except Exception:
                        pass
                if ble_connected:
                    try:
                        await client.bluetooth_device_disconnect(
                            self._ble_address_int
                        )
                    except Exception:
                        pass
                if cancel_connection_state is not None:
                    cancel_connection_state()
                try:
                    await client.disconnect()
                except Exception:
                    pass

            if not self._stop_event.is_set():
                logger.info("Reconnecting in %ss ...", self._reconnect_delay)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._reconnect_delay,
                    )
                except asyncio.TimeoutError:
                    pass

    def _handle_notification(self, _handle: int, data: bytearray) -> None:
        if len(data) < 14:
            logger.warning("Short BLE packet: %d bytes", len(data))
            return

        probes: list[float | None] = []
        for i in range(6):
            offset = 2 + i * 2
            raw = struct.unpack_from(">H", data, offset)[0]
            probes.append(None if raw == PROBE_DISCONNECTED else raw / 10.0)

        reading = ProbeReading(
            timestamp=datetime.now(timezone.utc),
            probe1=probes[0],
            probe2=probes[1],
            probe3=probes[2],
            probe4=probes[3],
            probe5=probes[4],
            probe6=probes[5],
        )
        self._broadcast(reading)
