import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


async def _disconnect_wait(websocket: WebSocket) -> None:
    """Resolve once the client goes away.

    The dashboard never sends anything, so a receive completes only on disconnect.
    """
    while True:
        if (await websocket.receive())["type"] == "websocket.disconnect":
            return


@router.websocket("/ws")
async def websocket_temperatures(websocket: WebSocket):
    await websocket.accept()
    source = websocket.app.state.source

    await websocket.send_json(source.get_current().to_dict())

    queue = source.subscribe()
    disconnect = asyncio.create_task(_disconnect_wait(websocket))
    try:
        while True:
            reading = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({reading, disconnect}, return_when=asyncio.FIRST_COMPLETED)
            if reading not in done:
                # Waiting only on the queue would leave this handler parked until the next
                # reading arrives — forever if the thermometer is off — holding a subscription
                # and stalling shutdown behind a client that has already gone.
                reading.cancel()
                return
            await websocket.send_json(reading.result().to_dict())
    except WebSocketDisconnect:
        pass
    finally:
        disconnect.cancel()
        source.unsubscribe(queue)
