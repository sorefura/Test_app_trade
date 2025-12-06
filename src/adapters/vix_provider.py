# src/adapters/vix_provider.py
import logging
import time
import random
from typing import Optional
from src.interfaces import VixProvider

logger = logging.getLogger(__name__)

class FixedVixProvider(VixProvider):
    """
    固定値、または安全なデフォルト値を返すプロバイダー。
    外部接続失敗時のフォールバックとして使用する。
    """
    def __init__(self, value: float = 25.0): # 安全側に倒して高めのデフォルト
        self.value = value

    def fetch_vix(self) -> Optional[float]:
        return self.value

class MockVixProvider(VixProvider):
    """テスト用: ランダムな値を返す"""
    def fetch_vix(self) -> Optional[float]:
        return 15.0 + random.random() * 5.0

class YahooVixProvider(VixProvider):
    """
    Yahoo Finance (US) からVIXを取得する実装案。
    ※今回は外部ライブラリ(yfinance)への依存を避けるため、
    実運用では信頼できるAPIへの置き換えを推奨。現在は枠組みのみ。
    """
    def __init__(self):
        self.last_val: Optional[float] = None
        self.last_fetch_time = 0.0
        self.ttl = 3600 # 1時間キャッシュ

    def fetch_vix(self) -> Optional[float]:
        # キャッシュ有効なら返す
        if self.last_val is not None and (time.time() - self.last_fetch_time < self.ttl):
            return self.last_val
        
        try:
            # TODO: ここに実際の requests.get("https://query1.finance.yahoo.com/...") を実装
            # 安全のため、未実装段階では None を返し、Strategy側でHOLDさせる
            logger.warning("YahooVixProvider is not fully implemented. Returning None.")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch VIX: {e}")
            return None