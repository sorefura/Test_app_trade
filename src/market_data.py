# src/market_data.py
import logging
from typing import Any, List
from src.interfaces import MarketDataProvider, BrokerClient
from src.models import MarketSnapshot, PositionSummary

logger = logging.getLogger(__name__)

class MarketDataFetcher(MarketDataProvider):
    """
    BrokerClientから市場データを取得し、StrategyEngineへ提供するアダプタークラス。
    """
    
    def __init__(self, broker_client: BrokerClient):
        """
        MarketDataFetcherを初期化する。

        Args:
            broker_client (BrokerClient): データソースとなるブローカー
        """
        self._broker_client = broker_client

    def fetch_market_snapshot(self, pair: str) -> MarketSnapshot:
        """
        最新の市場スナップショットを取得する。

        Args:
            pair (str): 通貨ペア

        Returns:
            MarketSnapshot: 市場データ
        """
        try:
            return self._broker_client.get_market_snapshot(pair)
        except Exception as e:
            logger.error(f"Error fetching market snapshot via broker: {e}")
            raise

    def fetch_vix(self) -> float:
        """
        VIX指数を取得する（現在は固定値を返却）。
        将来的に外部APIと連携予定。

        Returns:
            float: VIX指数
        """
        return 15.0 

    def fetch_positions(self) -> List[PositionSummary]:
        """
        保有ポジション一覧を取得する。

        Returns:
            List[PositionSummary]: ポジションリスト
        """
        return self._broker_client.get_positions()
    
    def fetch_account_state(self) -> Any:
        """
        口座状態を取得する。

        Returns:
            Any: 口座情報
        """
        return self._broker_client.get_account_state()
