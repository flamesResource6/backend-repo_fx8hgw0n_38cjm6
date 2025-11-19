"""
Database Schemas for YehagerBet Betting

Each Pydantic model represents a MongoDB collection.
Collection name is the lowercase of the class name.

- User -> "user"
- Match -> "match"
- Bet -> "bet"
- WalletTransaction -> "wallettransaction"
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime


class User(BaseModel):
    name: str = Field(..., description="Full name")
    phone: str = Field(..., description="Phone number (used as login identifier)")
    balance: float = Field(0.0, ge=0, description="Wallet balance")
    is_active: bool = Field(True, description="Whether user is active")


class MatchSelection(BaseModel):
    market: Literal["home_win", "draw", "away_win"]
    odds: float = Field(..., gt=1.0)


class Match(BaseModel):
    sport: Literal["football", "basketball", "tennis"]
    league: str
    home_team: str
    away_team: str
    start_time: datetime
    status: Literal["scheduled", "live", "finished"] = "scheduled"
    odds: dict = Field(..., description="Odds dictionary, e.g., {home_win: 1.9, draw: 3.1, away_win: 3.5}")


class BetSelection(BaseModel):
    match_id: str
    market: Literal["home_win", "draw", "away_win"]
    odds: float
    description: str


class Bet(BaseModel):
    user_id: str
    stake: float = Field(..., gt=0)
    selections: List[BetSelection]
    potential_return: float = Field(..., gt=0)
    status: Literal["pending", "won", "lost", "void"] = "pending"


class WalletTransaction(BaseModel):
    user_id: str
    type: Literal["topup", "withdrawal", "bet_place", "bet_payout"]
    amount: float
    balance_after: float
    reference: Optional[str] = None
