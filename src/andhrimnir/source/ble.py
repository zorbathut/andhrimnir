import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import Callable

from bleak import BleakClient

from andhrimnir.models import PROBE_COUNT, ProbeReading

logger = logging.getLogger(__name__)

PROBE_DISCONNECTED = 0xFFFF
PACKET_LENGTH = 2 + PROBE_COUNT * 2


def reading_parse(data: bytes | bytearray) -> ProbeReading:
    """Decode one notification packet: a 2-byte header then six big-endian deci-Celsius probes."""
    if len(data) < PACKET_LENGTH:
        raise ValueError(f"expected at least {PACKET_LENGTH} bytes, got {len(data)}")

    probes = []
    for i in range(PROBE_COUNT):
        raw = struct.unpack_from(">H", data, 2 + i * 2)[0]
        probes.append(None if raw == PROBE_DISCONNECTED else raw / 10.0)

    return ProbeReading(timestamp=datetime.now(timezone.utc), probes=tuple(probes))


class TemperatureSourceBLE:
    """Streams probe readings off a BLE thermometer, reconnecting for as long as it runs."""

    def __init__(self, char_uuid: str, reconnect_delay: float, client_make: Callable[[], BleakClient]) -> None:
        self._char_uuid = char_uuid
        self._reconnect_delay = reconnect_delay
        self._client_make = client_make
        self._current = ProbeReading(timestamp=datetime.now(timezone.utc))
        self._subscribers: list[asyncio.Queue[ProbeReading]] = []
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        while not self._stop_event.is_set():
            try:
                async with self._client_make() as client:
                    logger.info("Connected to BLE device")
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

    def _handle_notification(self, _sender: object, data: bytearray) -> None:
        try:
            reading = reading_parse(data)
        except ValueError as exc:
            logger.warning("Malformed BLE packet: %s", exc)
            return
        self._broadcast(reading)

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
