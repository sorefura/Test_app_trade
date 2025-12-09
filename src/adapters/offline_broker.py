# src/adapters/offline_broker.py
from datetime import datetime, timezone
from typing import Any, List, Optional
import uuid
import logging

from src.interfaces import BrokerClient
from src.models import MarketSnapshot, PositionSummary, AiAction, BrokerResult

logger = logging.getLogger(__name__)

class OfflineBrokerClient(BrokerClient):
    """
    外部APIを使用せず、メモリ上で取引をシミュレーションするモックブローカー。
    """
    
    def __init__(self, config: dict):
        """
        モックブローカーを初期化する。

        Args:
            config (dict): 設定情報
        """
        self._mock_positions: list[PositionSummary] = []
        self._config = config
        self._balance = 1000000.0

    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        """固定の市場データを返す。"""
        return MarketSnapshot(
            pair=pair,
            timestamp=datetime.now(timezone.utc),
            bid=150.00, ask=150.05,
            swap_long_per_day=0.15, swap_short_per_day=-0.20,
            realized_vol_24h=0.0035
        )
    
    def get_positions(self) -> List[PositionSummary]:
        """現在のモックポジションを返す。"""
        return self._mock_positions

    def get_account_state(self) -> Any:
        """モック口座状態を計算して返す。"""
        used_margin = sum([p.amount * p.current_price / 25.0 for p in self._mock_positions])
        maintenance_pct = (self._balance / used_margin) if used_margin > 0 else 9.99

        return {
            "balance": self._balance,
            "margin_used": used_margin,
            "leverage_max": 25.0,
            "margin_maintain_pct": maintenance_pct
        }

    def place_order(self, action: AiAction) -> BrokerResult:
        """注文をシミュレーションし、即座に約定させる。"""
        snapshot = self.get_market_snapshot(action.target_pair)
        price = snapshot.ask if action.action == "BUY" else snapshot.bid
        
        amount = int((self._balance * action.suggested_leverage) / price)
        amount = max(amount, 1000)

        new_pos = PositionSummary(
            pair=action.target_pair,
            side="LONG" if action.action == "BUY" else "SHORT",
            amount=amount,
            avg_entry_price=price,
            current_price=price,
            unrealized_pnl=0.0,
            leverage=action.suggested_leverage
        )
        self._mock_positions.append(new_pos)
        
        order_id = str(uuid.uuid4())
        logger.info(f"Offline: {action.action} Executed. {amount} units @ {price}")
        
        return BrokerResult(
            status="EXECUTED",
            order_id=order_id,
            details={"mock_price": price, "amount": amount}
        )

    def close_position(self, pair: str, amount: Optional[float] = None) -> BrokerResult:
        """決済をシミュレーションする。"""
        target_positions = [p for p in self._mock_positions if p.pair == pair]
        
        if not target_positions:
            return BrokerResult(status="CLOSED_ALL", details={"msg": "No positions found."})
        
        self._mock_positions = [p for p in self._mock_positions if p.pair != pair]
        
        return BrokerResult(
            status="CLOSED_ALL", 
            details={"closed_count": len(target_positions)}
        )
