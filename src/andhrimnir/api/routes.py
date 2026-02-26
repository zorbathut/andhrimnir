from fastapi import APIRouter, Request
from pydantic import BaseModel

from andhrimnir.db import get_alert_thresholds, get_history, get_probe_names, set_alert_threshold, set_probe_name

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


@router.get("/probes/names")
async def get_names(request: Request):
    return await get_probe_names(request.app.state.db)


class ProbeNameBody(BaseModel):
    name: str


@router.put("/probes/names/{probe_num}")
async def put_name(request: Request, probe_num: int, body: ProbeNameBody):
    await set_probe_name(request.app.state.db, probe_num, body.name)
    return await get_probe_names(request.app.state.db)


@router.get("/probes/thresholds")
async def get_thresholds(request: Request):
    return await get_alert_thresholds(request.app.state.db)


class ThresholdBody(BaseModel):
    low: float | None = None
    high: float | None = None


@router.put("/probes/thresholds/{probe_num}")
async def put_threshold(request: Request, probe_num: int, body: ThresholdBody):
    await set_alert_threshold(request.app.state.db, probe_num, body.low, body.high)
    return await get_alert_thresholds(request.app.state.db)
