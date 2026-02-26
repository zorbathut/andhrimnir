import asyncio
import logging
import re
import time
from dataclasses import replace
from datetime import datetime, timezone

from aioesphomeapi import APIClient, SensorInfo, SensorState

from andhrimnir.config import Settings
from andhrimnir.models import ProbeReading
from andhrimnir.source.base import BaseTemperatureSource

logger = logging.getLogger(__name__)

PROBE_NAME_RE = re.compile(r"BBQ Probe (\d+)", re.IGNORECASE)
DEBOUNCE_SECONDS = 0.1


class ESPTemperatureSource(BaseTemperatureSource):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._host = settings.esp_host
        self._port = settings.esp_port
        self._password = settings.esp_password
        self._noise_psk = settings.esp_noise_psk or None
        self._reconnect_delay = settings.esp_reconnect_delay
        self._key_to_probe: dict[int, int] = {}
        self._pending: dict[int, float | None] = {}
        self._flush_handle: asyncio.TimerHandle | None = None
        self._connected = asyncio.Event()

    def _make_client(self) -> APIClient:
        return APIClient(
            address=self._host,
            port=self._port,
            password=self._password,
            noise_psk=self._noise_psk,
        )

    async def probe(self) -> bool:
        client = self._make_client()
        try:
            async with asyncio.timeout(3.0):
                await client.connect(login=True)
                await client.disconnect()
                return True
        except Exception:
            return False

    async def start(self) -> None:
        while not self._stop_event.is_set():
            client = self._make_client()
            try:
                logger.info("Connecting to ESP gateway %s:%s ...", self._host, self._port)
                await client.connect(on_stop=self._on_disconnect, login=True)
                self._connected.set()
                self._connect_time = time.monotonic()
                logger.info("Connected to ESP gateway")

                entities, _ = await client.list_entities_services()
                self._key_to_probe.clear()
                for entity in entities:
                    if isinstance(entity, SensorInfo):
                        m = PROBE_NAME_RE.search(entity.name)
                        if m:
                            probe_num = int(m.group(1))
                            self._key_to_probe[entity.key] = probe_num
                            logger.info(
                                "Mapped entity %r (key=%d) -> probe %d",
                                entity.name, entity.key, probe_num,
                            )

                if not self._key_to_probe:
                    logger.warning("No BBQ Probe entities found on ESP device")

                client.subscribe_states(self._on_state)

                while self._connected.is_set() and not self._stop_event.is_set():
                    await asyncio.sleep(1.0)

            except Exception as exc:
                uptime = time.monotonic() - getattr(self, '_connect_time', time.monotonic())
                logger.warning("ESP connection error after %.1fs: %s: %s", uptime, type(exc).__name__, exc)
            finally:
                self._connected.clear()
                if self._flush_handle is not None:
                    self._flush_handle.cancel()
                    self._flush_handle = None
                self._pending.clear()
                try:
                    await client.disconnect()
                except Exception:
                    pass

            if not self._stop_event.is_set():
                logger.info("Reconnecting in %ss ...", self._reconnect_delay)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._reconnect_delay
                    )
                except asyncio.TimeoutError:
                    pass

    async def _on_disconnect(self, expected: bool) -> None:
        uptime = time.monotonic() - getattr(self, '_connect_time', time.monotonic())
        logger.warning("ESP gateway disconnected (expected=%s, uptime=%.1fs)", expected, uptime)
        self._connected.clear()

    def _on_state(self, state: SensorState) -> None:
        if not isinstance(state, SensorState):
            return
        probe_num = self._key_to_probe.get(state.key)
        if probe_num is None:
            return

        if state.missing_state:
            self._pending[probe_num] = None
        else:
            self._pending[probe_num] = state.state

        if self._flush_handle is None:
            loop = asyncio.get_event_loop()
            self._flush_handle = loop.call_later(DEBOUNCE_SECONDS, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        if not self._pending:
            return

        current = self._current
        fields: dict[str, float | None] = {}
        for probe_num, value in self._pending.items():
            fields[f"probe{probe_num}"] = value
        self._pending.clear()

        reading = replace(
            current,
            timestamp=datetime.now(timezone.utc),
            **fields,
        )
        self._broadcast(reading)
