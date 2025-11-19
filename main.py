import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents

app = FastAPI(title="YehagerBet Betting API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------
# Pydantic Models (Requests)
# -------------------------------
class RegisterRequest(BaseModel):
    name: str
    phone: str


class LoginRequest(BaseModel):
    phone: str


class TopupRequest(BaseModel):
    user_id: str
    amount: float = Field(..., gt=0)


class BetSelection(BaseModel):
    match_id: str
    market: str
    odds: float
    description: str


class PlaceBetRequest(BaseModel):
    user_id: str
    stake: float = Field(..., gt=0)
    selections: List[BetSelection]


# -------------------------------
# Utility
# -------------------------------

def now_utc():
    return datetime.now(timezone.utc)


def ensure_indexes():
    if db is None:
        return
    db["user"].create_index("phone", unique=True)
    db["match"].create_index([("start_time", 1)])
    db["bet"].create_index([("user_id", 1), ("created_at", -1)])
    db["wallettransaction"].create_index([("user_id", 1), ("created_at", -1)])


# -------------------------------
# Seed sample matches (if empty)
# -------------------------------

def seed_matches():
    if db is None:
        return
    if db["match"].count_documents({}) > 0:
        return
    samples = [
        {
            "sport": "football",
            "league": "Ethiopian Premier League",
            "home_team": "Saint George",
            "away_team": "Buna",
            "start_time": now_utc().replace(microsecond=0),
            "status": "scheduled",
            "odds": {"home_win": 1.85, "draw": 3.2, "away_win": 3.9},
        },
        {
            "sport": "football",
            "league": "Ethiopian Premier League",
            "home_team": "Fasil Kenema",
            "away_team": "Wolaita Dicha",
            "start_time": now_utc().replace(microsecond=0),
            "status": "scheduled",
            "odds": {"home_win": 2.1, "draw": 3.0, "away_win": 3.4},
        },
        {
            "sport": "basketball",
            "league": "Ethiopia Cup",
            "home_team": "Addis Lions",
            "away_team": "Hawassa Hawks",
            "start_time": now_utc().replace(microsecond=0),
            "status": "scheduled",
            "odds": {"home_win": 1.7, "draw": 0.0, "away_win": 2.2},
        },
    ]
    for m in samples:
        m["created_at"] = now_utc()
        m["updated_at"] = now_utc()
        db["match"].insert_one(m)


@app.on_event("startup")
async def on_startup():
    ensure_indexes()
    seed_matches()


# -------------------------------
# Health & Test
# -------------------------------
@app.get("/")
def read_root():
    return {"message": "YehagerBet Betting API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available" if db is None else "✅ Connected & Working",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "collections": []
    }
    try:
        if db is not None:
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"⚠️ Error: {str(e)[:80]}"
    return response


# -------------------------------
# Users
# -------------------------------
@app.post("/api/users/register")
def register_user(payload: RegisterRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    exists = db["user"].find_one({"phone": payload.phone})
    if exists:
        raise HTTPException(status_code=400, detail="Phone already registered")
    user = {
        "name": payload.name,
        "phone": payload.phone,
        "balance": 0.0,
        "is_active": True,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    res = db["user"].insert_one(user)
    user["_id"] = str(res.inserted_id)
    return {"user_id": user["_id"], "name": user["name"], "phone": user["phone"], "balance": user["balance"]}


@app.post("/api/users/login")
def login_user(payload: LoginRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user = db["user"].find_one({"phone": payload.phone})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user["_id"]), "name": user.get("name", ""), "phone": user["phone"], "balance": user.get("balance", 0.0)}


@app.get("/api/users/{user_id}")
def get_user(user_id: str):
    from bson import ObjectId
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        user = db["user"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id")
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user["_id"]), "name": user.get("name", ""), "phone": user["phone"], "balance": user.get("balance", 0.0)}


# -------------------------------
# Wallet
# -------------------------------
@app.post("/api/wallet/topup")
def topup_wallet(payload: TopupRequest):
    from bson import ObjectId
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        oid = ObjectId(payload.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id")

    user = db["user"].find_one({"_id": oid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_balance = float(user.get("balance", 0.0)) + float(payload.amount)
    db["user"].update_one({"_id": oid}, {"$set": {"balance": new_balance, "updated_at": now_utc()}})

    tx = {
        "user_id": payload.user_id,
        "type": "topup",
        "amount": float(payload.amount),
        "balance_after": new_balance,
        "reference": None,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    db["wallettransaction"].insert_one(tx)

    return {"balance": new_balance}


@app.get("/api/wallet/transactions")
def list_transactions(user_id: str, limit: int = 20):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    cursor = db["wallettransaction"].find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    items = []
    for t in cursor:
        t["_id"] = str(t["_id"])
        items.append(t)
    return {"items": items}


# -------------------------------
# Matches
# -------------------------------
@app.get("/api/matches")
def list_matches():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    cursor = db["match"].find({}).sort("start_time", 1)
    items = []
    for m in cursor:
        items.append({
            "id": str(m["_id"]),
            "sport": m.get("sport"),
            "league": m.get("league"),
            "home_team": m.get("home_team"),
            "away_team": m.get("away_team"),
            "start_time": m.get("start_time").isoformat() if m.get("start_time") else None,
            "status": m.get("status"),
            "odds": m.get("odds", {}),
        })
    return {"items": items}


# -------------------------------
# Bets
# -------------------------------
@app.get("/api/bets")
def list_bets(user_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    cursor = db["bet"].find({"user_id": user_id}).sort("created_at", -1)
    items = []
    for b in cursor:
        b["_id"] = str(b["_id"])
        items.append(b)
    return {"items": items}


@app.post("/api/bets")
def place_bet(payload: PlaceBetRequest):
    from bson import ObjectId
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # Validate user
    try:
        oid = ObjectId(payload.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id")

    user = db["user"].find_one({"_id": oid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not payload.selections:
        raise HTTPException(status_code=400, detail="No selections provided")

    # Compute potential return
    total_odds = 1.0
    for s in payload.selections:
        if s.odds <= 1.0:
            raise HTTPException(status_code=400, detail="Invalid odds in selection")
        total_odds *= float(s.odds)
    potential_return = round(float(payload.stake) * total_odds, 2)

    # Check balance
    balance = float(user.get("balance", 0.0))
    if balance < payload.stake:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # Deduct balance
    new_balance = round(balance - float(payload.stake), 2)
    db["user"].update_one({"_id": oid}, {"$set": {"balance": new_balance, "updated_at": now_utc()}})

    # Create bet
    bet_doc = {
        "user_id": payload.user_id,
        "stake": float(payload.stake),
        "selections": [s.model_dump() for s in payload.selections],
        "potential_return": potential_return,
        "status": "pending",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    bet_id = db["bet"].insert_one(bet_doc).inserted_id

    # Wallet transaction
    tx = {
        "user_id": payload.user_id,
        "type": "bet_place",
        "amount": -float(payload.stake),
        "balance_after": new_balance,
        "reference": str(bet_id),
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    db["wallettransaction"].insert_one(tx)

    return {"bet_id": str(bet_id), "potential_return": potential_return, "balance": new_balance}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
