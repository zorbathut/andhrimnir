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

# How often the loop rechecks a live connection.  Shutdown interrupts this wait rather than sitting it out; see _stop_wait.
CONNECTION_POLL_INTERVAL = 1.0

# A stalled subscriber drops a reading every cycle, so report only every Nth.
DROP_LOG_INTERVAL = 100


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
        self._connected = False
        self._dropped = 0

    async def start(self) -> None:
        stop_wait = asyncio.create_task(self._stop_event.wait())
        session: asyncio.Task | None = None
        try:
            while not self._stop_event.is_set():
                session = asyncio.create_task(self._session_run())
                done, _ = await asyncio.wait({session, stop_wait}, return_when=asyncio.FIRST_COMPLETED)

                if session not in done:
                    await self._session_close(session)
                    return

                self._session_report(session)
                if not self._stop_event.is_set():
                    logger.info("Reconnecting in %ss ...", self._reconnect_delay)
                    await self._stop_wait(self._reconnect_delay)
        finally:
            stop_wait.cancel()
            # asyncio.wait leaves what it was waiting on running, so a cancellation of
            # start() itself would otherwise strand the session with the BLE client open.
            if session is not None and not session.done():
                session.cancel()
                await asyncio.gather(session, return_exceptions=True)

    async def _session_close(self, session: asyncio.Task) -> None:
        """Wind up a session that is still running because a stop was requested."""
        # A live connection closes itself through the same stop event, so let it; an in-flight
        # connect has nothing to tear down and would hold shutdown open until the radio times out.
        if not self._connected:
            session.cancel()
        outcome = (await asyncio.gather(session, return_exceptions=True))[0]
        if isinstance(outcome, Exception):
            logger.warning("BLE teardown error: %s", outcome)

    def _session_report(self, session: asyncio.Task) -> None:
        """Say why a session ended on its own."""
        # Some bleak transports raise CancelledError from inside without anyone cancelling
        # them, which marks the task cancelled and makes .exception() re-raise.
        if session.cancelled():
            logger.warning("BLE session ended in cancellation")
            return
        exc = session.exception()
        if exc is not None:
            logger.warning("BLE connection error: %s", exc)

    async def _session_run(self) -> None:
        """One connection: hold it open, streaming notifications, until it drops or we stop."""
        async with self._client_make() as client:
            self._connected = True
            try:
                logger.info("Connected to BLE device")
                await client.start_notify(self._char_uuid, self._handle_notification)
                while client.is_connected and not await self._stop_wait(CONNECTION_POLL_INTERVAL):
                    pass
                await client.stop_notify(self._char_uuid)
            finally:
                self._connected = False

    async def _stop_wait(self, timeout: float) -> bool:
        """Sleep up to `timeout`, cutting it short if a stop is requested. True if stopping.

        Every wait in this loop goes through the event rather than a bare sleep, so shutdown is noticed at once instead of at the end of the current interval.
        """
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        self._stop_event.set()

    def get_current(self) -> ProbeReading:
        return self._current

    def subscribe(self) -> asyncio.Queue[ProbeReading]:
        q: asyncio.Queue[ProbeReading] = asyncio.Queue(maxsize=16)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[ProbeReading]) -> None:
        self._subscribers.remove(queue)

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
                # Drop the oldest so live consumers always see the newest reading.
                q.get_nowait()
                q.put_nowait(reading)
                if self._dropped % DROP_LOG_INTERVAL == 0:
                    logger.warning("Subscriber queue full; dropped a reading (%d so far)", self._dropped + 1)
                self._dropped += 1
