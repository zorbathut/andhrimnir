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
from andhrimnir.source.esp_proxy import ESPProxyTemperatureSource

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)

settings = Settings.from_env()


async def _detect_source(settings: Settings) -> TemperatureSource:
    """Try ESP proxy, ESP gateway, and direct BLE — return whichever connects first."""
    sources: list[tuple[str, TemperatureSource]] = []

    if settings.esp_host and settings.ble_address:
        sources.append(("ESP proxy", ESPProxyTemperatureSource(settings)))
    if settings.ble_address:
        sources.append(("BLE direct", BLETemperatureSource(settings)))

    if not sources:
        logger.warning("No source configured, defaulting to BLE")
        return BLETemperatureSource(settings)

    tasks = {
        asyncio.create_task(source.probe()): (name, source)
        for name, source in sources
    }
    remaining = set(tasks)

    while remaining:
        done, remaining = await asyncio.wait(
            remaining, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            name, source = tasks[task]
            if task.exception() is None and task.result():
                for p in remaining:
                    p.cancel()
                logger.info("%s detected, using %s source", name, name)
                return source

    # All failed, default to first configured source (it has its own reconnect loop)
    fallback_name, fallback = sources[0]
    logger.warning("No source detected, defaulting to %s", fallback_name)
    return fallback


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
