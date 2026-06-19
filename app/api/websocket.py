from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketDisconnect as StarletteDisconnect
from app.auth.utils import verify_jwt

router = APIRouter()

active_connections: list[WebSocket] = []


@router.websocket("/ws/compress")
async def compress_progress(ws: WebSocket, token: str = Query("")):
    payload = await verify_jwt(token)
    if not payload:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, StarletteDisconnect):
        pass
    except Exception:
        pass
    finally:
        try:
            active_connections.remove(ws)
        except ValueError:
            pass
