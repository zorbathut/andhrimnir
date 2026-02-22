import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_temperatures(websocket: WebSocket):
    await websocket.accept()
    source = websocket.app.state.source

    current = source.get_current()
    await websocket.send_json(current.to_dict())

    queue = source.subscribe()
    try:
        while True:
            reading = await queue.get()
            await websocket.send_json(reading.to_dict())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket closed: %s", exc)
    finally:
        source.unsubscribe(queue)
