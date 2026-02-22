from fastapi import APIRouter, Request

from andhrimnir.db import get_history

router = APIRouter(prefix="/api")


@router.get("/temperatures")
async def get_temperatures(request: Request):
    source = request.app.state.source
    return source.get_current().to_dict()


@router.get("/temperatures/history")
async def get_temperature_history(
    request: Request, limit: int = 5000, since: str | None = None
):
    rows = await get_history(request.app.state.db, limit=limit, since=since)
    return rows
