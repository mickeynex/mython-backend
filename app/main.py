from fastapi import FastAPI
from fastapi.websockets import WebSocket
from .db import get_db

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "Mython Backend Running"}

@app.get("/test-db")
async def test_db():
    db = get_db()
    collections = db.list_collection_names()
    return {"collections": collections}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    await websocket.send_text(f"Connected to room: {room_id}")
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Echo: {data}")