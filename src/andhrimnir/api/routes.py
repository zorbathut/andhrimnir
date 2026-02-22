from fastapi import APIRouter, Request

from andhrimnir.db import get_history

router = APIRouter(prefix="/api")


@router.get("/temperatures")
async def get_temperatures(request: Request):
    source = request.app.state.source
    return source.get_current().to_dict()


@router.get("/temperatures/history")
async def get_temperature_history(
    request: Request, limit: int = 100, offset: int = 0
):
    rows = await get_history(request.app.state.db, limit=limit, offset=offset)
    return rows
