from datetime import datetime, timezone

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel

from andhrimnir.db import (
    get_alert_thresholds,
    get_history,
    get_probe_names,
    set_alert_threshold,
    set_probe_name,
)
from andhrimnir.models import PROBE_COUNT

router = APIRouter(prefix="/api")

ProbeNum = Annotated[int, Path(ge=1, le=PROBE_COUNT)]


def _since_normalize(since: str | None) -> str | None:
    """Readings are stored as UTC ISO-8601 and compared as text, so an offset-bearing or `Z`-suffixed timestamp has to be converted before it will compare correctly."""
    if since is None:
        return None
    try:
        parsed = datetime.fromisoformat(since)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"since: not an ISO-8601 timestamp ({exc})") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


@router.get("/temperatures")
async def get_temperatures(request: Request):
    return request.app.state.source.get_current().to_dict()


@router.get("/temperatures/history")
async def get_temperature_history(
    request: Request,
    limit: int = Query(default=5000, ge=1, le=100000),
    since: str | None = None,
):
    return await get_history(request.app.state.db, limit=limit, since=_since_normalize(since))


@router.get("/probes/names")
async def get_names(request: Request):
    return await get_probe_names(request.app.state.db)


class ProbeNameBody(BaseModel):
    name: str


@router.put("/probes/names/{probe_num}")
async def put_name(request: Request, probe_num: ProbeNum, body: ProbeNameBody):
    await set_probe_name(request.app.state.db, probe_num, body.name)
    return await get_probe_names(request.app.state.db)


@router.get("/probes/thresholds")
async def get_thresholds(request: Request):
    return await get_alert_thresholds(request.app.state.db)


class ThresholdBody(BaseModel):
    low: float | None = None
    high: float | None = None


@router.put("/probes/thresholds/{probe_num}")
async def put_threshold(request: Request, probe_num: ProbeNum, body: ThresholdBody):
    await set_alert_threshold(request.app.state.db, probe_num, body.low, body.high)
    return await get_alert_thresholds(request.app.state.db)
