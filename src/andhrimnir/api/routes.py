from fastapi import APIRouter, Request

router = APIRouter(prefix="/api")


@router.get("/temperatures")
async def get_temperatures(request: Request):
    source = request.app.state.source
    return source.get_current().to_dict()
