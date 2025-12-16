# src/adapters/vix_provider.py
import logging
import time
import random
import requests
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
        """常に固定値を返す。"""
        return self.value

class MockVixProvider(VixProvider):
    """テスト用: ランダムな値を返すプロバイダー。"""
    def fetch_vix(self) -> Optional[float]:
        """ランダムなVIX値を返す。"""
        return 15.0 + random.random() * 5.0

class YahooVixProvider(VixProvider):
    """
    Yahoo Finance (US) の非公式APIエンドポイントからVIXを取得する実装。
    yfinanceライブラリ依存を避け、requestsで軽量に実装。
    """
    def __init__(self):
        self.last_val: Optional[float] = None
        self.last_fetch_time = 0.0
        self.ttl = 300 # 5分キャッシュ
        self.url = "https://query1.finance.yahoo.com/v8/finance/chart/^VIX"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def fetch_vix(self) -> Optional[float]:
        """
        VIX指数を取得する。
        
        Returns:
            Optional[float]: 取得成功時はVIX値、失敗時はNone。
        """
        # キャッシュ有効なら返す
        if self.last_val is not None and (time.time() - self.last_fetch_time < self.ttl):
            return self.last_val
        
        try:
            # interval=1d, range=5d で最新のローソク足を取得
            params = {"interval": "1d", "range": "5d"}
            resp = requests.get(self.url, headers=self.headers, params=params, timeout=5)
            resp.raise_for_status()
            
            data = resp.json()
            result = data["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            
            # 最新のClose価格を取得（Noneが含まれる場合を除外）
            closes = [c for c in quote["close"] if c is not None]
            
            if not closes:
                logger.warning("Yahoo Finance returned no valid close prices for VIX.")
                return None
                
            current_vix = float(closes[-1])
            
            self.last_val = current_vix
            self.last_fetch_time = time.time()
            logger.info(f"Fetched VIX from Yahoo: {current_vix}")
            return current_vix

        except Exception as e:
            logger.error(f"Failed to fetch VIX from Yahoo: {e}")
            return None