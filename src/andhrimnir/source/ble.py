import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import Any

from bleak import BleakClient

from andhrimnir.config import Settings
from andhrimnir.models import PROBE_COUNT, ProbeReading

logger = logging.getLogger(__name__)

PROBE_DISCONNECTED = 0xFFFF


class TemperatureSourceBLE:
    """Streams probe readings off a BLE thermometer, reconnecting for as long as it runs."""

    def __init__(self, settings: Settings, **bleak_kwargs: Any) -> None:
        self._address = settings.ble_address
        self._char_uuid = settings.ble_char_uuid
        self._reconnect_delay = settings.ble_reconnect_delay
        self._bleak_kwargs = bleak_kwargs
        self._current = ProbeReading(timestamp=datetime.now(timezone.utc))
        self._subscribers: list[asyncio.Queue[ProbeReading]] = []
        self._stop_event = asyncio.Event()

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

    async def stop(self) -> None:
        self._stop_event.set()

    def get_current(self) -> ProbeReading:
        return self._current

    def subscribe(self) -> asyncio.Queue[ProbeReading]:
        q: asyncio.Queue[ProbeReading] = asyncio.Queue(maxsize=16)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[ProbeReading]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def _handle_notification(self, _sender: int, data: bytearray) -> None:
        if len(data) < 14:
            logger.warning("Short BLE packet: %d bytes", len(data))
            return

        probes: list[float | None] = []
        for i in range(PROBE_COUNT):
            raw = struct.unpack_from(">H", data, 2 + i * 2)[0]
            probes.append(None if raw == PROBE_DISCONNECTED else raw / 10.0)

        self._broadcast(ProbeReading(timestamp=datetime.now(timezone.utc), probes=tuple(probes)))

    def _broadcast(self, reading: ProbeReading) -> None:
        self._current = reading
        for q in self._subscribers:
            try:
                q.put_nowait(reading)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(reading)
                except asyncio.QueueFull:
                    pass
