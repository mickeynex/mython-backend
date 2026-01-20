from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from bson import ObjectId
from argon2 import PasswordHasher, exceptions
from datetime import datetime
from ..db import rooms_collection
from datetime import datetime, timedelta
import secrets

def validate_join(room, key: str | None):
    join = room.get("join")
    if not join:
        raise HTTPException(status_code=403, detail="Room is not joinable")

    if not key or key != join.get("key"):
        raise HTTPException(status_code=403, detail="Invalid or expired link")

    expires_at = join.get("expires_at")
    if expires_at and expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Room expired")

    if join.get("revoked"):
        raise HTTPException(status_code=403, detail="Room expired")

router = APIRouter(prefix="/rooms/guest")
ph = PasswordHasher()
GUEST_TOKEN_TTL_MINUTES = 15

class GuestSetup(BaseModel):
    room_id: str
    name: str
    pin: str
    key: str | None = None   # allow None temporarily (frontend not updated yet)

class GuestVerify(BaseModel):
    room_id: str
    name: str
    pin: str
    key: str | None = None

# --------------------
# First-time guest setup
# --------------------
@router.post("/setup")
def setup_guest(payload: GuestSetup):
    room = rooms_collection.find_one({"_id": ObjectId(payload.room_id)})
    validate_join(room, payload.key)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # allow setup only once
    if room.get("guest", {}).get("pin_hash"):
        raise HTTPException(status_code=403, detail="Guest already exists")

    pin_hash = ph.hash(payload.pin)

    rooms_collection.update_one(
        {"_id": ObjectId(payload.room_id)},
        {"$set": {
            "guest": {
                "name": payload.name,
                "pin_hash": pin_hash,
            }
        }}
    )

    return { "ok": True }

# --------------------
# Returning guest verify
# --------------------
@router.post("/verify")
def verify_guest(payload: GuestVerify):
    room = rooms_collection.find_one({"_id": ObjectId(payload.room_id)})
    validate_join(room, payload.key)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    guest = room.get("guest")
    if not guest or guest.get("name") != payload.name:
        raise HTTPException(status_code=404, detail="Guest not found")

    try:
        ph.verify(guest["pin_hash"], payload.pin)
    except exceptions.VerifyMismatchError:
        raise HTTPException(status_code=401, detail="Wrong PIN")
    return { "ok": True }
