from datetime import datetime, timedelta
from jose import jwt

# TODO: MOVED TO .env LATER
import os
SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"
EXPIRY_MINUTES = 60 * 24 * 30  # token valid for 30 days

def create_token():
    expire = datetime.utcnow() + timedelta(minutes=EXPIRY_MINUTES)
    return jwt.encode({"exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return True
    except Exception:
        return False

