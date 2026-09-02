import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable

import aiosqlite
from bleak import BleakClient
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from andhrimnir.api.routes import router as api_router
from andhrimnir.api.websocket import router as ws_router
from andhrimnir.config import ConfigError, Settings
from andhrimnir.db import db_writer, init_db
from andhrimnir.source.base import TemperatureSource
from andhrimnir.source.ble import TemperatureSourceBLE
from andhrimnir.source.bleak_client_esphome import BleakClientESPHome

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.toml").resolve()
SHUTDOWN_TIMEOUT = 5.0

DbOpen = Callable[[], Awaitable[aiosqlite.Connection]]


def source_make(settings: Settings) -> TemperatureSource:
    """Build the temperature source for the configured backend.

    Both backends are the same BLE source; they differ only in which bleak transport reaches the thermometer — this host's own radio, or an ESPHome bluetooth_proxy.
    """
    if not settings.ble_address:
        raise ConfigError("ble.address is required (set it in config.toml or ANDHRIMNIR_BLE_ADDRESS)")

    if settings.source_kind == "esp":
        logger.info("Reading probes over the ESP proxy at %s:%d", settings.esp_host, settings.esp_port)
        kwargs = dict(
            backend=BleakClientESPHome,
            esp_host=settings.esp_host,
            esp_port=settings.esp_port,
            esp_password=settings.esp_password,
            esp_noise_psk=settings.esp_noise_psk,
        )
    else:
        logger.info("Reading probes over the local BLE radio")
        kwargs = {}

    return TemperatureSourceBLE(
        char_uuid=settings.ble_char_uuid,
        reconnect_delay=settings.ble_reconnect_delay,
        client_make=lambda: BleakClient(settings.ble_address, **kwargs),
    )


async def _task_stop(task: asyncio.Task) -> None:
    """Cancel a task and wait for it to finish, tolerating one that already died."""
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("%s had already failed before shutdown: %s", task.get_name(), exc)


def app_create(settings: Settings, source: TemperatureSource, db_open: DbOpen) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = await db_open()
        app.state.db = conn
        writer_task = asyncio.create_task(db_writer(source, conn))
        source_task = asyncio.create_task(source.start())
        try:
            yield
        finally:
            # Let the source close its BLE connection itself; cancelling straight away tears the client down inside an already-cancelled task, so its teardown raises at the first await and the proxy keeps an abandoned connection until its next keepalive sweep.
            await source.stop()
            _, pending = await asyncio.wait([source_task], timeout=SHUTDOWN_TIMEOUT)
            if pending:
                logger.warning("Source did not stop within %ss; cancelling", SHUTDOWN_TIMEOUT)
                await _task_stop(source_task)
            await _task_stop(writer_task)
            await conn.close()

    app = FastAPI(title="Andhrimnir", lifespan=lifespan)
    app.state.source = source

    app.include_router(api_router)
    app.include_router(ws_router)
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app


def app_factory() -> FastAPI:
    settings = Settings.load(CONFIG_PATH)
    return app_create(settings, source_make(settings), lambda: init_db(settings.db_path))


def cli() -> None:
    import uvicorn

    settings = Settings.load(CONFIG_PATH)
    uvicorn.run(
        "andhrimnir.main:app_factory",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
