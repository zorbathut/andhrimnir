import asyncio
from datetime import datetime, timezone
from typing import Callable

from andhrimnir.models import PROBE_COUNT, ProbeReading


async def until(condition: Callable[[], bool], what: str, timeout: float = 1.0) -> None:
    """Wait for a background task to reach some state, failing with what was awaited rather than a timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for: {what}")
        await asyncio.sleep(0.001)


def reading_make(*probes: float | None, timestamp: datetime | None = None) -> ProbeReading:
    """A reading with the probes given and the rest disconnected."""
    filled = tuple(probes) + (None,) * (PROBE_COUNT - len(probes))
    return ProbeReading(timestamp=timestamp or datetime.now(timezone.utc), probes=filled)


class TemperatureSourceFake:
    """Satisfies the TemperatureSource Protocol without touching a radio."""

    def __init__(self, current: ProbeReading | None = None) -> None:
        self.current = current or reading_make()
        self.subscribers: list[asyncio.Queue[ProbeReading]] = []
        self.started = False
        self.stopped = False
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self.started = True
        await self._stop_event.wait()

    async def stop(self) -> None:
        self.stopped = True
        self._stop_event.set()

    def get_current(self) -> ProbeReading:
        return self.current

    def subscribe(self) -> asyncio.Queue[ProbeReading]:
        q: asyncio.Queue[ProbeReading] = asyncio.Queue(maxsize=16)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[ProbeReading]) -> None:
        self.subscribers.remove(queue)

    def publish(self, reading: ProbeReading) -> None:
        self.current = reading
        for q in self.subscribers:
            q.put_nowait(reading)


class BleakClientFake:
    """Stands in for a BleakClient: scripted connect behaviour, and a hook to push notifications.

    `connect_errors` is consumed one entry per connection attempt; a non-None entry is
    raised instead of connecting, which is how the reconnect loop gets exercised.
    """

    def __init__(self, connect_errors: list[Exception | None] | None = None, connect_hangs: bool = False) -> None:
        self.connect_errors = list(connect_errors or [])
        self.connect_hangs = connect_hangs
        self.attempts = 0
        self.notify_callback = None
        self.notifying = False
        self.is_connected = False
        self.stop_notify_calls = 0

    async def __aenter__(self) -> "BleakClientFake":
        self.attempts += 1
        if self.connect_hangs:
            await asyncio.Event().wait()
        error = self.connect_errors.pop(0) if self.connect_errors else None
        if error is not None:
            raise error
        self.is_connected = True
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.is_connected = False

    async def start_notify(self, _char_uuid: str, callback) -> None:
        self.notify_callback = callback
        self.notifying = True

    async def stop_notify(self, _char_uuid: str) -> None:
        self.notifying = False
        self.stop_notify_calls += 1

    def notify(self, data: bytes) -> None:
        self.notify_callback(object(), bytearray(data))


def packet_make(*raws: int) -> bytes:
    """A notification packet: two header bytes then six big-endian deci-Celsius probes."""
    filled = tuple(raws) + (0xFFFF,) * (PROBE_COUNT - len(raws))
    return b"\xaa\xbb" + b"".join(r.to_bytes(2, "big") for r in filled)
