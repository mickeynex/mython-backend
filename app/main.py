from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from argon2 import PasswordHasher
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import secrets
import os

# ---- internal imports (CONSISTENT) ----
from .routes import guest
from .db import get_db, get_auth_collection, rooms_collection
from .auth import create_token, verify_token
from .websocket import attach_ws, ws_rooms

# ---- app ----
app = FastAPI()

# ✅ REGISTER WEBSOCKET ROUTES (THIS WAS THE MISSING PIECE)
attach_ws(app)

# ---- CORS ----
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- routers ----
app.include_router(guest.router)

# ---- auth ----
ph = PasswordHasher()
RECOVERY_SECRET = os.getenv("OWNER_RECOVERY_SECRET")
recovery_unlocked = False

# -------------------- BASIC ROUTES --------------------

@app.get("/")
async def root():
    return {"status": "Mython Backend Running"}

# -------------------- MASTER PIN AUTH --------------------

@app.post("/auth/setup")
async def setup_master_pin(pin: str):
    auth = get_auth_collection()
    if auth.find_one({}):
        raise HTTPException(status_code=400, detail="Master PIN already set")

    auth.insert_one({"pin_hash": ph.hash(pin)})
    return {"created": True}

@app.post("/auth/login")
async def login_master(pin: str):
    auth = get_auth_collection()
    record = auth.find_one({})
    if not record:
        raise HTTPException(status_code=404, detail="Master PIN not set")

    try:
        ph.verify(record["pin_hash"], pin)
    except:
        raise HTTPException(status_code=403, detail="Invalid PIN")

    return {"token": create_token()}

#change pin logic
from pydantic import BaseModel
from fastapi import HTTPException

class ChangePinPayload(BaseModel):
    currentPin: str
    newPin: str
class RecoveryVerifyPayload(BaseModel):
    code: str

class RecoveryResetPayload(BaseModel):
    newPin: str
@app.post("/auth/recovery/verify")
async def verify_recovery(payload: RecoveryVerifyPayload):
    if not RECOVERY_SECRET:
        raise HTTPException(status_code=500, detail="Recovery not configured")

    try:
        ph.verify(ph.hash(RECOVERY_SECRET), payload.code)
    except:
        raise HTTPException(status_code=403, detail="Invalid recovery code")

    global recovery_unlocked
    recovery_unlocked = True
    return {"ok": True}

@app.post("/auth/recovery/reset")
async def reset_pin_recovery(payload: RecoveryResetPayload):
    global recovery_unlocked
    if not recovery_unlocked:
        raise HTTPException(status_code=403, detail="Recovery not verified")

    auth = get_auth_collection()
    record = auth.find_one({})

    if not record:
        raise HTTPException(status_code=400, detail="No PIN set")

    auth.update_one(
        {"_id": record["_id"]},
        {"$set": {"pin_hash": ph.hash(payload.newPin)}}
    )

    recovery_unlocked = False
    return {"status": "ok"}

@app.get("/auth/check")
async def check_auth(token: str):
    return {"valid": verify_token(token)}

@app.post("/auth/change-pin")
async def change_pin(payload: ChangePinPayload):
    auth = get_auth_collection()
    record = auth.find_one({})

    if not record:
        raise HTTPException(status_code=400, detail="No PIN set")

    try:
        ph.verify(record["pin_hash"], payload.currentPin)
    except:
        raise HTTPException(status_code=403, detail="Invalid current PIN")

    auth.update_one(
        {"_id": record["_id"]},
        {"$set": {"pin_hash": ph.hash(payload.newPin)}}
    )

    return {"status": "ok"}

# -------------------- ROOMS --------------------

@app.post("/rooms/create")
async def create_room():
    join_key = secrets.token_urlsafe(24)
    expires_at = datetime.utcnow() + timedelta(hours=24)

    room = {
        "created_at": datetime.utcnow(),
        "guest": {"name": None, "pin_hash": None},
        "join": {
            "key": join_key,
            "expires_at": expires_at,
            "revoked": False,
        },
    }

    result = rooms_collection.insert_one(room)

    return {
        "room_id": str(result.inserted_id),
        "join_key": join_key,
        "expires_at": expires_at,
    }

@app.get("/rooms/list")
async def list_rooms():
    out = []
    for room in rooms_collection.find():
        guest = room.get("guest") or {}
        out.append({
            "id": str(room["_id"]),
            "created_at": room.get("created_at"),
            "guestName": guest.get("name"),
            "joinKey": room.get("join", {}).get("key"),
            "expiresAt": room.get("join", {}).get("expires_at"),
        })
    return {"rooms": out}

@app.get("/rooms/{room_id}")
async def get_room(room_id: str):
    room = rooms_collection.find_one({"_id": ObjectId(room_id)})
    if not room:
        return {"exists": False}

    guest = room.get("guest") or {}
    return {
        "exists": True,
        "guestSetup": bool(guest.get("pin_hash")),
        "guestName": guest.get("name"),
    }

@app.delete("/rooms/{room_id}")
async def delete_room(room_id: str):
    # close active websockets
    if room_id in ws_rooms:
        for ws in ws_rooms[room_id].values():
            try:
                if ws:
                    await ws.close()
            except:
                pass
        del ws_rooms[room_id]

    rooms_collection.delete_one({"_id": ObjectId(room_id)})
    return {"status": "deleted"}

@app.post("/rooms/{room_id}/expire-now")
async def expire_room_now(room_id: str):
    new_key = secrets.token_urlsafe(24)
    new_expiry = datetime.utcnow() + timedelta(hours=24)

    result = rooms_collection.update_one(
        {"_id": ObjectId(room_id)},
        {"$set": {
            "join.key": new_key,
            "join.expires_at": new_expiry,
            "join.revoked": False,
        }},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Invalid room")
    # kick active guests if connected
    if room_id in ws_rooms:
        room_ws = ws_rooms[room_id]

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

    return {"join_key": new_key, "expires_at": new_expiry}

@app.post("/rooms/{room_id}/set-expiry")
async def set_room_expiry(room_id: str, hours: float):
    if hours <= 0:
        raise HTTPException(status_code=400, detail="Invalid expiry")

    new_expiry = datetime.utcnow() + timedelta(hours=hours)

    result = rooms_collection.update_one(
        {"_id": ObjectId(room_id)},
        {"$set": {"join.expires_at": new_expiry, "join.revoked": False}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Invalid room")

    # 🔥 FORCE EXPIRE IF TIME IS NOW OR PAST
    if new_expiry <= datetime.utcnow():
        from .websocket import force_expire_room
        await force_expire_room(room_id)

    return {"expires_at": new_expiry}


def rotate_join(room_id):
    new_key = secrets.token_urlsafe(24)
    new_expiry = datetime.utcnow() + timedelta(hours=24)

    rooms_collection.update_one(
        {"_id": ObjectId(room_id)},
        {"$set": {
            "join.key": new_key,
            "join.expires_at": new_expiry,
            "join.revoked": False,
        }}
    )