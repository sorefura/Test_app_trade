# src/adapters/offline_broker.py
from datetime import datetime, timezone
from typing import Any, List, Optional
import uuid
import logging
import math

from src.interfaces import BrokerClient
from src.models import MarketSnapshot, PositionSummary, AiAction

logger = logging.getLogger(__name__)

class OfflineBrokerClient(BrokerClient):
    
    def __init__(self, config: dict):
        self._mock_positions: list[PositionSummary] = []
        self._config = config
        self._balance = 1000000.0  # 口座残高保持

    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        # (変更なし) 以前のコードと同じ
        return MarketSnapshot(
            pair=pair,
            timestamp=datetime.now(timezone.utc),
            bid=150.00, ask=150.05,
            swap_long_per_day=0.15, swap_short_per_day=-0.20,
            realized_vol_24h=0.0035
        )
    
    def get_positions(self) -> list[PositionSummary]:
        return self._mock_positions

    def get_account_state(self) -> Any:
        # ポジションから証拠金使用率を簡易計算
        used_margin = sum([p.amount * p.current_price / 25.0 for p in self._mock_positions])
        maintenance_pct = (self._balance / used_margin) if used_margin > 0 else 9.99

        return {
            "balance": self._balance,
            "margin_used": used_margin,
            "leverage_max": 25.0,
            "margin_maintain_pct": maintenance_pct
        }

    def place_order(self, action: AiAction) -> Any:
        # ExecutionServiceで計算されたロットではなく、簡易的にここでレバレッジから再計算するモック
        snapshot = self.get_market_snapshot(action.target_pair)
        price = snapshot.ask if action.action == "BUY" else snapshot.bid
        
        # 簡易ロット計算 (Balance * Lev / Price)
        amount = int((self._balance * action.suggested_leverage) / price)
        amount = max(amount, 1000) # 最低1000

        if action.action == "BUY":
            new_pos = PositionSummary(
                pair=action.target_pair,
                side="LONG",
                amount=amount,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                leverage=action.suggested_leverage
            )
            self._mock_positions.append(new_pos)
            logger.info(f"Offline: BUY Executed. {amount} units @ {price}")
            return {"order_id": str(uuid.uuid4()), "status": "FILLED"}
        
        elif action.action == "SELL":
             # 両建て可の簡易実装
            new_pos = PositionSummary(
                pair=action.target_pair,
                side="SHORT",
                amount=amount,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                leverage=action.suggested_leverage
            )
            self._mock_positions.append(new_pos)
            logger.info(f"Offline: SELL Executed. {amount} units @ {price}")
            return {"order_id": str(uuid.uuid4()), "status": "FILLED"}

        return {"status": "REJECTED"}

    def close_position(self, position_id: str, amount: Optional[float] = None) -> Any:
        """
        position_id (ここではペア名) に一致するポジションを全て決済する
        """
        removed_positions = [p for p in self._mock_positions if p.pair == position_id]
        if not removed_positions:
            logger.warning(f"Offline: No positions found for {position_id} to close.")
            return {"status": "NOT_FOUND"}

        # 残高更新（簡易PL計算）
        for p in removed_positions:
            # 簡易的にスプレッド分の損失だけ引くなど、モック挙動
            pl = -100.0 
            self._balance += pl
            logger.info(f"Offline: Closed {p.side} {p.amount} units. PL: {pl}")

        # リストから削除
        self._mock_positions = [p for p in self._mock_positions if p.pair != position_id]
        return {"status": "CLOSED"}