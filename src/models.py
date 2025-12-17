# src/models.py
from datetime import datetime, timezone
from typing import Literal, List, Optional, Dict, Any
from pydantic import BaseModel, Field

# --- Broker Result Models ---

BrokerStatus = Literal[
    "EXECUTED",            # 注文成功
    "CLOSED_ALL",          # 全決済成功
    "PARTIAL_FAILURE",     # 一部決済失敗（要停止）
    "HOLD",                # アクションなし
    "BLOCKED_BY_SAFETY",   # 二段ロックまたはリスク管理による遮断
    "DRY_RUN_NOT_SENT",    # Dry-Runのため送信せず
    "DRY_RUN_NOT_CLOSED",  # Dry-Runのため決済せず（建玉残存の可能性あり）
    "ERROR",               # 通信エラー等
]

class BrokerResult(BaseModel):
    """
    ブローカーに対する操作（発注・決済）の結果を統一的に表現するモデル。

    Attributes:
        status (BrokerStatus): 操作の実行ステータス。
        order_id (Optional[str]): ブローカーから発行された注文ID。
        request_id (Optional[str]): 追跡用のリクエストID。
        details (Dict[str, Any]): 詳細情報やエラー内容、生レスポンス等。
        timestamp (datetime): 結果生成時刻 (UTC)。
    """
    status: BrokerStatus = Field(description="操作の実行ステータス")
    order_id: Optional[str] = Field(default=None, description="ブローカーから発行された注文ID")
    request_id: Optional[str] = Field(default=None, description="追跡用のリクエストID")
    details: Dict[str, Any] = Field(default_factory=dict, description="詳細情報やエラー内容、生レスポンス等")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="結果生成時刻 (UTC)")

# --- Broker Specific Models ---

class SymbolSpec(BaseModel):
    """
    通貨ペアごとの取引ルール（APIから取得）。

    Attributes:
        symbol (str): 通貨ペア名。
        min_order_size (float): 最小発注数量 (minOpenOrderSize)。
        size_step (float): 発注数量の刻み値 (sizeStep)。
    """
    symbol: str
    min_order_size: float = Field(description="最小発注数量 (minOpenOrderSize)")
    size_step: float = Field(description="発注数量の刻み値 (sizeStep)")

# --- AI Input Models ---

class NewsItem(BaseModel):
    """
    AI分析に入力するためのニュース記事モデル。

    Attributes:
        id (str): ログ用のユニークID。
        source (str): 情報ソース名。
        published_at (datetime): 記事の発行日時。
        title (str): 記事タイトル。
        body (str): 記事本文。
    """
    id: str = Field(description="ログ用のユニークID（URLなど）")
    source: str = Field(description="情報ソース名 (例: Reuters, WebSearch)")
    published_at: datetime = Field(description="記事の発行日時")
    title: str = Field(description="記事タイトル")
    body: str = Field(description="記事本文（信頼境界タグを含む場合あり）")

class MarketSnapshot(BaseModel):
    """
    特定時点における市場データ（価格、スワップ、ボラティリティ）のスナップショット。

    Attributes:
        pair (str): 通貨ペア。
        timestamp (datetime): データ取得日時。
        bid (float): Bidレート。
        ask (float): Askレート。
        swap_long_per_day (float): 買いポジションの1日あたりスワップポイント。
        swap_short_per_day (float): 売りポジションの1日あたりスワップポイント。
        realized_vol_24h (Optional[float]): 過去24時間の実実現ボラティリティ。
    """
    pair: str = Field(description="通貨ペア (例: 'USD_JPY')")
    timestamp: datetime = Field(description="データ取得日時")
    bid: float = Field(description="Bidレート")
    ask: float = Field(description="Askレート")
    swap_long_per_day: float = Field(description="買いポジションの1日あたりスワップポイント")
    swap_short_per_day: float = Field(description="売りポジションの1日あたりスワップポイント")
    realized_vol_24h: Optional[float] = Field(default=None, description="過去24時間の実実現ボラティリティ")

class RiskEnvironment(BaseModel):
    """
    外部要因による市場リスク環境の定義。

    Attributes:
        vix_index (float): 最新のVIX指数。
        risk_off_flag (bool): 事前に計算されたリスクオフフラグ。
    """
    vix_index: float = Field(description="最新のVIX指数")
    risk_off_flag: bool = Field(description="事前に計算されたリスクオフフラグ")

class PositionSummary(BaseModel):
    """
    現在保有しているポジションのサマリー情報。

    Attributes:
        pair (str): 通貨ペア。
        side (Literal["LONG", "SHORT"]): 売買方向。
        amount (float): 保有数量。
        avg_entry_price (float): 平均取得単価。
        current_price (float): 現在レート。
        unrealized_pnl (float): 含み損益（スワップ含む）。
        leverage (float): 実効レバレッジ。
    """
    pair: str = Field(description="通貨ペア")
    side: Literal["LONG", "SHORT"] = Field(description="売買方向")
    amount: float = Field(description="保有数量")
    avg_entry_price: float = Field(description="平均取得単価")
    current_price: float = Field(description="現在レート")
    unrealized_pnl: float = Field(description="含み損益（スワップ含む）")
    leverage: float = Field(description="実効レバレッジ")

class AiInputPayload(BaseModel):
    """
    AIモデルへ送信する分析用ペイロード。
    """
    request_id: str = Field(description="リクエスト識別子")
    generated_at: datetime = Field(description="生成日時")
    market: MarketSnapshot = Field(description="市場データ")
    risk_env: RiskEnvironment = Field(description="リスク環境データ")
    positions: List[PositionSummary] = Field(description="保有ポジション一覧")
    news: List[NewsItem] = Field(description="関連ニュース一覧")
    future_extension: Optional[dict] = Field(default=None, description="将来の拡張用フィールド")

# --- AI Output Models ---

class AiAction(BaseModel):
    """
    AIによって決定された推奨アクション。

    Attributes:
        action (Literal["BUY", "SELL", "HOLD", "EXIT"]): 推奨アクション。
        units (Optional[float]): 実行時に計算された最終的な発注数量。
        target_pair (str): 対象通貨ペア。
        suggested_leverage (float): 推奨最大レバレッジ。
        confidence (float): モデルの確信度。
        risk_level (int): リスクレベル。
        expected_holding_period_days (float): 想定保有期間。
        rationale (str): 判断根拠。
        notes_for_human (Optional[str]): 人間へのメモ。
        technical_bias (Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]]): テクニカル分析のバイアス。
        macro_bias (Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]]): マクロ経済分析のバイアス。
        request_id (Optional[str]): この決定に紐づくリクエストID。
    """
    action: Literal["BUY", "SELL", "HOLD", "EXIT"] = Field(description="推奨アクション")
    units: Optional[float] = Field(default=None, description="実行時に計算された最終的な発注数量")
    target_pair: str = Field(description="対象通貨ペア")
    suggested_leverage: float = Field(description="推奨最大レバレッジ")
    confidence: float = Field(ge=0.0, le=1.0, description="モデルの確信度 (0.0 - 1.0)")
    risk_level: int = Field(ge=1, le=10, description="リスクレベル (1:低 - 10:高)")
    expected_holding_period_days: float = Field(description="想定保有期間（日数）")
    rationale: str = Field(description="判断根拠")
    notes_for_human: Optional[str] = Field(default=None, description="人間へのメモ")
    technical_bias: Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]] = Field(default=None, description="テクニカル分析のバイアス")
    macro_bias: Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]] = Field(default=None, description="マクロ経済分析のバイアス")
    request_id: Optional[str] = Field(default=None, description="この決定に紐づくリクエストID")

class AiOutputPayload(BaseModel):
    """
    AIモデルからのレスポンスペイロード。
    """
    request_id: str = Field(description="対応するリクエストID")
    generated_at: datetime = Field(description="生成日時")
    decision: AiAction = Field(description="AIの決定内容")