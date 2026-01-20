import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

client = MongoClient(MONGO_URI)

db = client[DB_NAME]

def get_db():
    return db

def get_auth_collection():
    return db["auth"]

# ✅ SINGLE source of truth
rooms_collection = db["rooms"]
