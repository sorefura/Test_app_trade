# src/market_data.py
import logging
from typing import Any, List
from src.interfaces import MarketDataProvider, BrokerClient, VixProvider, SwapProvider
from src.models import MarketSnapshot, PositionSummary
from src.adapters.vix_provider import FixedVixProvider, YahooVixProvider
from src.adapters.swap_provider import AggregatedSwapProvider

logger = logging.getLogger(__name__)

class MarketDataFetcher(MarketDataProvider):
    """
    BrokerClient, VixProvider, SwapProvider からデータを集約し、
    StrategyEngineへ統一された市場データを提供するクラス。
    """
    
    def __init__(self, broker_client: BrokerClient, config: dict):
        """
        MarketDataFetcherを初期化する。

        Args:
            broker_client (BrokerClient): データソースとなるブローカークライアント
            config (dict): アプリケーション設定
        """
        self._broker_client = broker_client
        
        # VIXプロバイダーの初期化 (P1)
        if config.get('use_web_vix', False):
            logger.info("Using YahooVixProvider for VIX data.")
            self._vix_provider: VixProvider = YahooVixProvider()
        else:
            fixed_vix = config.get('fixed_vix_value', 25.0)
            logger.info(f"Using FixedVixProvider with value: {fixed_vix}")
            self._vix_provider: VixProvider = FixedVixProvider(fixed_vix)

        # スワッププロバイダー: 設定ファイルと外部ソースを集約するプロバイダーを使用
        self._swap_provider: SwapProvider = AggregatedSwapProvider(config)

    def fetch_market_snapshot(self, pair: str) -> MarketSnapshot:
        """
        最新の市場スナップショットを取得する。
        ブローカーからの価格情報と、SwapProviderからのスワップ情報を統合する。

        Args:
            pair (str): 対象通貨ペア (例: "USD_JPY")

        Returns:
            MarketSnapshot: 統合された市場データ

        Raises:
            Exception: データ取得に失敗した場合
        """
        try:
            # 1. Brokerから価格情報を取得
            snapshot = self._broker_client.get_market_snapshot(pair)
            
            # 2. SwapProviderからスワップ情報を補完 (Broker取得値が0の場合など)
            # GMO APIはTickerにスワップを含まないため、基本はこちらで上書き
            swaps = self._swap_provider.get_swap_points(pair)
            if swaps:
                snapshot.swap_long_per_day = swaps.get("long", 0.0)
                snapshot.swap_short_per_day = swaps.get("short", 0.0)
            
            # スワップ情報が取れない場合は警告 (StrategyでHOLD要因になる)
            if snapshot.swap_long_per_day == 0 and snapshot.swap_short_per_day == 0:
                logger.warning(f"Swap points for {pair} are ZERO. Check providers.")

            return snapshot
        except Exception as e:
            logger.error(f"Error fetching market snapshot: {e}")
            raise

    def fetch_vix(self) -> float:
        """
        市場の恐怖指数（VIX）を取得する。
        取得失敗時は、強制的にリスクオフ（Risk Off）とするために高い値を返す。

        Returns:
            float: VIX指数。取得失敗時は 99.9 を返す。
        """
        try:
            val = self._vix_provider.fetch_vix()
            if val is None:
                logger.warning("VIX fetch returned None. Returning safe fallback (99.9).")
                return 99.9 # 確実にRisk Offにする値
            return val
        except Exception as e:
            logger.error(f"VIX fetch failed with exception: {e}. Returning safe fallback (99.9).")
            return 99.9 # 確実にRisk Offにする値

    def fetch_positions(self) -> List[PositionSummary]:
        """
        現在の保有ポジション一覧を取得する。

        Returns:
            List[PositionSummary]: ポジションリスト
        """
        return self._broker_client.get_positions()
    
    def fetch_account_state(self) -> Any:
        """
        口座状態（残高、証拠金維持率など）を取得する。

        Returns:
            Any: 口座情報オブジェクト
        """
        return self._broker_client.get_account_state()