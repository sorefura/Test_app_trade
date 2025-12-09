# src/market_data.py (修正版)
import logging
from typing import Any, List
from src.interfaces import MarketDataProvider, BrokerClient
from src.models import MarketSnapshot, PositionSummary  # <--- Added PositionSummary

logger = logging.getLogger(__name__)

class MarketDataFetcher(MarketDataProvider):
    """
    MarketDataFetcher クラス。
    BrokerClient インターフェースを利用し、ブローカー依存の詳細を隠蔽する。
    """
    
    def __init__(self, broker_client: BrokerClient):
        # 依存性の注入 (Dependency Injection)
        self._broker_client = broker_client

    def fetch_market_snapshot(self, pair: str) -> MarketSnapshot:
        """
        ブローカークライアントから市場データスナップショットを取得する。
        """
        try:
            return self._broker_client.get_market_snapshot(pair)
        except Exception as e:
            logger.error(f"Error fetching market snapshot via broker: {e}")
            raise

    # VIX指数など、ブローカーに依存しない外部データの取得メソッドを追加予定
    def fetch_vix(self) -> float:
        """外部APIからVIX指数を取得する（仮値）"""
        # ここに実装が入る（例：Stooq, Quandlなどの外部API）
        # V1では仮値としておく
        return 15.0  # 現在は安定した相場を仮定

    def fetch_positions(self) -> list[PositionSummary]:
        """現在ポジションを取得する。"""
        return self._broker_client.get_positions()
    
    def fetch_account_state(self) -> Any:
        """口座状態を取得する。"""
        return self._broker_client.get_account_state()