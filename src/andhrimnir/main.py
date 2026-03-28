import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aioesphomeapi import APIClient
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from andhrimnir.api.routes import router as api_router
from andhrimnir.api.websocket import router as ws_router
from andhrimnir.config import Settings
from andhrimnir.db import db_writer, init_db
from andhrimnir.source.base import TemperatureSource
from andhrimnir.source.ble import BLETemperatureSource
from andhrimnir.source.bleak_esp_proxy import ESPHomeProxyBackend

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)

settings = Settings.from_env()


def _esp_bleak_kwargs(settings: Settings) -> dict:
    return dict(
        backend=ESPHomeProxyBackend,
        esp_host=settings.esp_host,
        esp_port=settings.esp_port,
        esp_password=settings.esp_password,
        esp_noise_psk=settings.esp_noise_psk,
    )


async def _esp_reachable(settings: Settings) -> bool:
    """Quick check: can we connect to the ESPHome API?"""
    client = APIClient(
        address=settings.esp_host,
        port=settings.esp_port,
        password=settings.esp_password,
        noise_psk=settings.esp_noise_psk or None,
    )
    try:
        async with asyncio.timeout(5.0):
            await client.connect(login=True)
            await client.disconnect()
            return True
    except Exception:
        return False


async def _detect_source(settings: Settings) -> TemperatureSource:
    """Pick the best available temperature source."""
    if settings.esp_host and settings.ble_address:
        if await _esp_reachable(settings):
            logger.info("ESP proxy detected, using ESP proxy source")
            return BLETemperatureSource(settings, **_esp_bleak_kwargs(settings))

    if settings.ble_address:
        source = BLETemperatureSource(settings)
        if await source.probe():
            logger.info("BLE device detected, using direct BLE source")
            return source

    # Nothing responded — default to ESP proxy if configured, else direct BLE.
    if settings.esp_host and settings.ble_address:
        logger.warning("No source detected, defaulting to ESP proxy")
        return BLETemperatureSource(settings, **_esp_bleak_kwargs(settings))

    logger.warning("No source detected, defaulting to direct BLE")
    return BLETemperatureSource(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    source = await _detect_source(settings)
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
