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
from andhrimnir.source.ble import BLETemperatureSource

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")

settings = Settings.from_env()
source = BLETemperatureSource(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.state.source = source

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
