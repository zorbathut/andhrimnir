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


def app_create(settings: Settings, source: TemperatureSource, db_open: DbOpen) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = await db_open()
        app.state.db = conn
        writer_task = asyncio.create_task(db_writer(source, conn))
        source_task = asyncio.create_task(source.start())
        yield
        await source.stop()
        writer_task.cancel()
        source_task.cancel()
        try:
            await writer_task
        except asyncio.CancelledError:
            pass
        try:
            await source_task
        except asyncio.CancelledError:
            pass
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
