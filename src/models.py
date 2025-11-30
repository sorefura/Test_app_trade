# src/models.py
from datetime import datetime
from typing import Literal, List, Optional
from pydantic import BaseModel, Field

# --- AI Input Models ---

class NewsItem(BaseModel):
    id          : str = Field(description="Unique ID for logging")
    source      : str = Field(description="Source name (e.g., Reuters)")
    published_at: datetime
    title       : str
    body        : str

class MarketSnapshot(BaseModel):
    pair              : str = Field(description="Currency Pair (e.g., 'USD_JPY')")
    timestamp         : datetime
    bid               : float
    ask               : float
    swap_long_per_day : float = Field(description="Daily swap points for Long")
    swap_short_per_day: float = Field(description="Daily swap points for Short")
    realized_vol_24h  : Optional[float] = Field(default=None, description="Realized volatility (24h)")

class RiskEnvironment(BaseModel):
    vix_index         : float = Field(description="Latest VIX index")
    risk_off_flag     : bool = Field(description="Pre-calculated risk-off status")

class PositionSummary(BaseModel):
    pair           : str
    side           : Literal["LONG", "SHORT"]
    amount         : float
    avg_entry_price: float
    current_price  : float
    unrealized_pnl : float
    leverage       : float

class AiInputPayload(BaseModel):
    """Payload sent to gpt-5.1"""
    request_id: str
    generated_at: datetime
    market: MarketSnapshot
    risk_env: RiskEnvironment
    positions: List[PositionSummary]
    news: List[NewsItem]
    future_extension: Optional[dict] = None

# --- AI Output Models ---

class AiAction(BaseModel):
    action: Literal["BUY", "SELL", "HOLD", "EXIT"] = Field(description="Recommended Action")
    units: Optional[float] = Field(default=None, description="Final calculated units for execution")
    target_pair: str
    suggested_leverage: float = Field(description="Max leverage suggestion")
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence 0-1")
    risk_level: int = Field(ge=1, le=10, description="Risk level 1-10")
    expected_holding_period_days: float
    rationale: str = Field(description="Reasoning for the decision")
    notes_for_human: Optional[str] = None
    technical_bias: Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]] = None
    macro_bias: Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]] = None

class AiOutputPayload(BaseModel):
    """Response received from gpt-5.1"""
    request_id: str
    generated_at: datetime
    decision: AiAction