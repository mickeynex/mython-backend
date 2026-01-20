from fastapi import WebSocket, FastAPI
from bson import ObjectId
from .db import rooms_collection
from datetime import datetime

ws_rooms = {}
async def broadcast_presence(room_id: str):
    room = ws_rooms.get(room_id)
    if not room:
        return

    payload = {
        "type": "presence",
        "owner": room.get("owner") is not None,
        "guest": room.get("guest") is not None,
    }

    for ws in room.values():
        if ws:
            try:
                await ws.send_json(payload)
            except:
                pass

async def force_expire_room(room_id: str):
    from .main import rotate_join
    room_ws = ws_rooms.get(room_id)
    if not room_ws:
        rotate_join(room_id)
        return

    guest = room_ws.get("guest")
    if guest:
        try:
            await guest.send_json({
                "type": "system",
                "reason": "ROOM_EXPIRED"
            })
            await guest.close()
        except:
            pass
        room_ws["guest"] = None

    rotate_join(room_id)

def attach_ws(app: FastAPI):
    app.add_api_websocket_route(
        "/ws/{room_id}",
        websocket_handler
    )

async def websocket_handler(websocket: WebSocket, room_id: str):
    await websocket.accept()
    # ensure room slot exists
    if room_id not in ws_rooms:
        ws_rooms[room_id] = {
            "owner": None,
            "guest": None,
        }

    try:
        # ---- AUTH PHASE (FIRST MESSAGE ONLY) ----
        auth = await websocket.receive_json()
        role = auth.get("role")

        if role == "owner":
            ws_rooms[room_id]["owner"] = websocket
            await broadcast_presence(room_id)

        elif role == "guest":
            if ws_rooms[room_id]["guest"] is not None:
                await websocket.close()
                return

            ws_rooms[room_id]["guest"] = websocket
            await broadcast_presence(room_id)

        else:
            await websocket.close()
            return

        # ---- MESSAGE RELAY LOOP ----
        while True:
            # ---- expiry check (authoritative) ----
            room = rooms_collection.find_one({"_id": ObjectId(room_id)})
            join = room.get("join") if room else None

            if not join or join.get("expires_at") <= datetime.utcnow():
                await force_expire_room(room_id)
                break

            import asyncio
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=1)
            except asyncio.TimeoutError:
                continue

            if role == "owner":
                guest = ws_rooms[room_id]["guest"]
                if guest:
                    await guest.send_json(msg)

            else:  # guest → owner
                owner = ws_rooms[room_id]["owner"]
                if owner:
                    await owner.send_json(msg)

    except Exception as e:
        print("WS ERROR:")

    finally:
        # ---- CLEANUP ON DISCONNECT ----
        try:
            if ws_rooms[room_id].get("owner") is websocket:
                ws_rooms[room_id]["owner"] = None

            if ws_rooms[room_id].get("guest") is websocket:
                ws_rooms[room_id]["guest"] = None

            await broadcast_presence(room_id)

        except:
            pass

        try:
            await websocket.close()
        except:
            pass


