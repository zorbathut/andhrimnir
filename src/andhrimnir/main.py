import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from andhrimnir.api.routes import router as api_router
from andhrimnir.api.websocket import router as ws_router
from andhrimnir.config import Settings
from andhrimnir.source.ble import BLETemperatureSource

settings = Settings.from_env()
source = BLETemperatureSource(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(source.start())
    yield
    await source.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
