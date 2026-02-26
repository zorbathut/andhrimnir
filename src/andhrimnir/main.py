import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from andhrimnir.api.routes import router as api_router
from andhrimnir.api.websocket import router as ws_router
from andhrimnir.config import Settings
from andhrimnir.db import db_writer, init_db
from andhrimnir.source.base import TemperatureSource
from andhrimnir.source.ble import BLETemperatureSource
from andhrimnir.source.esp import ESPTemperatureSource

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)

settings = Settings.from_env()


async def _detect_source(settings: Settings) -> TemperatureSource:
    """Try ESP and BLE in parallel, return whichever connects first."""
    esp = ESPTemperatureSource(settings)
    ble = BLETemperatureSource(settings)

    esp_task = asyncio.create_task(esp.probe())
    ble_task = asyncio.create_task(ble.probe())

    done, pending = await asyncio.wait(
        [esp_task, ble_task], return_when=asyncio.FIRST_COMPLETED
    )

    # Check if the first to finish succeeded
    for task in done:
        if task.exception() is None and task.result():
            for p in pending:
                p.cancel()
            if task is esp_task:
                logger.info("ESP gateway detected, using ESP source")
                return esp
            else:
                logger.info("BLE device detected, using BLE source")
                return ble

    # First to finish failed — wait for the other
    if pending:
        done2, _ = await asyncio.wait(pending)
        for task in done2:
            if task.exception() is None and task.result():
                if task is esp_task:
                    logger.info("ESP gateway detected, using ESP source")
                    return esp
                else:
                    logger.info("BLE device detected, using BLE source")
                    return ble

    # Both failed, default to BLE (it has its own reconnect loop)
    logger.warning("Neither source detected, defaulting to BLE")
    return ble


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
