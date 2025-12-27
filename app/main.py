from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from .db import get_db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "Mython Backend Running"}

@app.get("/test-db")
async def test_db():
    db = get_db()
    collections = db.list_collection_names()
    return {"collections": collections}

# store active WebSocket clients per room
rooms = {}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()

    if room_id not in rooms:
        rooms[room_id] = []
    rooms[room_id].append(websocket)

    await websocket.send_text(f"Connected to room: {room_id}")

    try:
        while True:
            data = await websocket.receive_text()

            # broadcast received message to everyone in room
            for conn in rooms[room_id]:
                await conn.send_text(data)

    except WebSocketDisconnect:
        rooms[room_id].remove(websocket)
