import asyncio
import logging
import struct
from typing import Any

from bleak import BleakClient
from datetime import datetime, timezone

from andhrimnir.config import Settings
from andhrimnir.models import PROBE_COUNT, ProbeReading
from andhrimnir.source.base import BaseTemperatureSource

logger = logging.getLogger(__name__)

PROBE_DISCONNECTED = 0xFFFF


class BLETemperatureSource(BaseTemperatureSource):
    def __init__(self, settings: Settings, **bleak_kwargs: Any) -> None:
        super().__init__()
        self._address = settings.ble_address
        self._char_uuid = settings.ble_char_uuid
        self._reconnect_delay = settings.ble_reconnect_delay
        self._bleak_kwargs = bleak_kwargs

    async def probe(self) -> bool:
        try:
            async with asyncio.timeout(5.0):
                async with BleakClient(self._address, **self._bleak_kwargs) as client:
                    return client.is_connected
        except Exception:
            return False

    async def start(self) -> None:
        while not self._stop_event.is_set():
            try:
                logger.info("Connecting to BLE device %s ...", self._address)
                async with BleakClient(self._address, **self._bleak_kwargs) as client:
                    logger.info("Connected to %s", self._address)
                    await client.start_notify(self._char_uuid, self._handle_notification)
                    while client.is_connected and not self._stop_event.is_set():
                        await asyncio.sleep(1.0)
                    await client.stop_notify(self._char_uuid)
            except Exception as exc:
                logger.warning("BLE connection error: %s", exc)

            if not self._stop_event.is_set():
                logger.info("Reconnecting in %ss ...", self._reconnect_delay)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._reconnect_delay)
                except asyncio.TimeoutError:
                    pass

    def _handle_notification(self, _sender: int, data: bytearray) -> None:
        if len(data) < 14:
            logger.warning("Short BLE packet: %d bytes", len(data))
            return

        probes: list[float | None] = []
        for i in range(PROBE_COUNT):
            offset = 2 + i * 2
            raw = struct.unpack_from(">H", data, offset)[0]
            probes.append(None if raw == PROBE_DISCONNECTED else raw / 10.0)

        self._broadcast(ProbeReading(timestamp=datetime.now(timezone.utc), probes=tuple(probes)))
