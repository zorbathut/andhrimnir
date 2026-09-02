import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from andhrimnir.api.routes import router as api_router
from andhrimnir.api.websocket import router as ws_router
from andhrimnir.config import ConfigError, Settings
from andhrimnir.db import db_writer, init_db
from andhrimnir.source.base import TemperatureSource
from andhrimnir.source.ble import TemperatureSourceBLE
from andhrimnir.source.bleak_esp_proxy import ESPHomeProxyBackend

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)

settings = Settings.from_env()


def source_make(settings: Settings) -> TemperatureSource:
    """Build the temperature source for the configured backend.

    Both backends are the same BLE source; they differ only in which bleak transport reaches the thermometer — this host's own radio, or an ESPHome bluetooth_proxy.
    """
    if not settings.ble_address:
        raise ConfigError("ble.address is required (set it in config.toml or ANDHRIMNIR_BLE_ADDRESS)")

    if settings.source_kind == "esp":
        logger.info("Reading probes over the ESP proxy at %s:%d", settings.esp_host, settings.esp_port)
        kwargs = dict(
            backend=ESPHomeProxyBackend,
            esp_host=settings.esp_host,
            esp_port=settings.esp_port,
            esp_password=settings.esp_password,
            esp_noise_psk=settings.esp_noise_psk,
        )
    else:
        logger.info("Reading probes over the local BLE radio")
        kwargs = {}

    return TemperatureSourceBLE(settings, **kwargs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    source = source_make(settings)
    app.state.source = source
    conn = await init_db(settings.db_path)
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

app.include_router(api_router)
app.include_router(ws_router)

static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def cli() -> None:
    import uvicorn

    uvicorn.run(
        "andhrimnir.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
