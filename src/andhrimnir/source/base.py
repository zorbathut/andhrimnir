import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from andhrimnir.models import ProbeReading


@runtime_checkable
class TemperatureSource(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def get_current(self) -> ProbeReading: ...
    def subscribe(self) -> asyncio.Queue[ProbeReading]: ...
    def unsubscribe(self, queue: asyncio.Queue[ProbeReading]) -> None: ...


class BaseTemperatureSource(ABC):
    def __init__(self) -> None:
        self._current = ProbeReading(timestamp=datetime.now(timezone.utc))
        self._subscribers: list[asyncio.Queue[ProbeReading]] = []
        self._stop_event = asyncio.Event()

    @abstractmethod
    async def start(self) -> None: ...

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
