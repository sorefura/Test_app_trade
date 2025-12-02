# src/interfaces.py
from typing import Protocol, List, Any, Optional
from src.models import (
    MarketSnapshot, PositionSummary, NewsItem, 
    AiAction
)

# ----------------------------------------------------
# A. ブローカー接続用 (BrokerClient)
#    GMO, IG, Offlineなどの「外部API」との通信規約
# ----------------------------------------------------

class BrokerClient(Protocol):
    """
    ブローカーAPIとの通信を抽象化するインターフェース。
    GMOコイン、IG、Offlineなどの実装がこの仕様に準拠する。
    """
    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        """指定通貨ペアの最新レート、スワップ、ボラティリティ情報を取得する。"""
        ...
    
    def get_positions(self) -> list[PositionSummary]:
        """現在保有している全ポジションのサマリを取得する。"""
        ...

    def get_account_state(self) -> Any:
        """口座全体の状態（証拠金、残高、レバレッジなど）を取得する。"""
        ...

    def place_order(self, action: AiAction) -> Any:
        """売買注文を実行する。"""
        ...

    def close_position(self, pair: str, amount: Optional[float] = None) -> Any:
        """指定された通貨ペアのポジションを決済する"""
        ...


# ----------------------------------------------------
# B. アプリ内部データ提供用 (MarketDataProvider)
#    StrategyEngineが利用するデータ取得の窓口
# ----------------------------------------------------

class MarketDataProvider(Protocol):
    """
    StrategyEngine がデータを要求する際のインターフェース。
    MarketDataFetcher クラスがこれを実装する。
    """
    def fetch_market_snapshot(self, pair: str) -> MarketSnapshot:
        """市場のスナップショット（価格・スワップ）を取得"""
        ...

    def fetch_positions(self) -> list[PositionSummary]:
        """現在のポジション一覧を取得"""
        ...

    def fetch_account_state(self) -> Any:
        """口座情報を取得"""
        ...

    def fetch_vix(self) -> float:
        """
        VIX指数などの市場リスク指標を取得。
        BrokerAPIから取れない場合は、外部ソースや計算値を使用する。
        """
        ...


# ----------------------------------------------------
# C. ニュースデータ系 (NewsClient)
# ----------------------------------------------------

class NewsClient(Protocol):
    """
    ニュース取得の抽象インターフェース。RSS、有料APIなどの実装が準拠する。
    """
    def fetch_recent_news(self, pair: str, limit: int = 20) -> list[NewsItem]:
        """指定通貨ペアに関連する直近のニュースを取得する。"""
        ...