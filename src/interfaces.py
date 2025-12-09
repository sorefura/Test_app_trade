# src/interfaces.py
from typing import Protocol, List, Any, Optional, Dict
from src.models import (
    MarketSnapshot, PositionSummary, NewsItem, 
    AiAction, BrokerResult
)

# ----------------------------------------------------
# A. Broker Client Protocol
# ----------------------------------------------------

class BrokerClient(Protocol):
    """
    ブローカーAPI（GMOコイン、Offline等）との通信を抽象化するインターフェース。
    全ての実装クラスはこのプロトコルに準拠する必要がある。
    """
    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        """
        指定通貨ペアの最新市場データ（レート、スワップ等）を取得する。

        Args:
            pair (str): 通貨ペア (例: "USD_JPY")

        Returns:
            MarketSnapshot: 最新の市場スナップショット
        """
        ...
    
    def get_positions(self) -> List[PositionSummary]:
        """
        現在保有している全ポジションのサマリーを取得する。

        Returns:
            List[PositionSummary]: ポジション一覧
        """
        ...

    def get_account_state(self) -> Any:
        """
        口座全体の状態（証拠金、残高、レバレッジ等）を取得する。

        Returns:
            Any: 口座情報を含む辞書オブジェクト
        """
        ...

    def place_order(self, action: AiAction) -> BrokerResult:
        """
        AIの判断に基づき、売買注文を実行する。

        Args:
            action (AiAction): 実行するアクションの詳細

        Returns:
            BrokerResult: 実行結果（ステータス、注文ID等）
        """
        ...

    def close_position(self, pair: str, amount: Optional[float] = None) -> BrokerResult:
        """
        指定された通貨ペアのポジションを決済する。

        Args:
            pair (str): 対象通貨ペア
            amount (Optional[float]): 決済数量（Noneの場合は全決済）

        Returns:
            BrokerResult: 決済結果
        """
        ...

    def get_symbol_specs(self, pair: str) -> Optional[SymbolSpec]:
        """
        指定通貨ペアの取引ルール（最小発注数、刻み値）を取得する。
        取得失敗時やキャッシュがない場合はNoneを返す。
        """
        ...


# ----------------------------------------------------
# B. Market Data Provider Protocol & Sub-Providers
# ----------------------------------------------------
class VixProvider(Protocol):
    """
    VIX指数を提供するインターフェース。
    取得不可またはデータが古い場合は None を返す。
    """
    def fetch_vix(self) -> Optional[float]:
        """
        VIX値を取得する。

        Returns:
            Optional[float]: VIX値。利用不可または古い場合はNone。
        """
        ...

class SwapProvider(Protocol):
    """
    スワップポイントを提供するインターフェース。
    """
    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """
        指定ペアのスワップポイントを取得する。

        Args:
            pair (str): 通貨ペア

        Returns:
            Dict[str, float]: スワップポイント辞書 (例: {"long": 10.5, "short": -15.0})。
                              データがない場合は空辞書を返す。
        """
        ...

class MarketDataProvider(Protocol):
    """
    StrategyEngineがデータを利用するための読み取り専用インターフェース。
    """
    def fetch_market_snapshot(self, pair: str) -> MarketSnapshot:
        """
        市場スナップショットを取得する。

        Args:
            pair (str): 通貨ペア

        Returns:
            MarketSnapshot: 市場データ
        """
        ...

    def fetch_positions(self) -> List[PositionSummary]:
        """
        現在の保有ポジションを取得する。

        Returns:
            List[PositionSummary]: ポジション一覧
        """
        ...

    def fetch_account_state(self) -> Any:
        """
        口座情報を取得する。

        Returns:
            Any: 口座情報
        """
        ...

    def fetch_vix(self) -> float:
        """
        市場の恐怖指数（VIX）を取得する。

        Returns:
            float: VIX指数
        """
        ...


# ----------------------------------------------------
# C. News Client Protocol
# ----------------------------------------------------

class NewsClient(Protocol):
    """
    ニュース取得機能の抽象インターフェース。
    """
    def fetch_recent_news(self, pair: str, limit: int = 20) -> List[NewsItem]:
        """
        指定通貨ペアに関連する直近のニュースを取得する。

        Args:
            pair (str): 通貨ペア
            limit (int): 取得上限数

        Returns:
            List[NewsItem]: ニュース記事のリスト
        """
        ...