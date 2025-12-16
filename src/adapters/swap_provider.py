# src/adapters/swap_provider.py
import logging
import time
import requests
import json
from typing import Dict, Optional
from datetime import datetime
from src.interfaces import SwapProvider

logger = logging.getLogger(__name__)

class ManualSwapProvider(SwapProvider):
    """
    設定ファイル(settings.yaml)の手動設定値を返すプロバイダー。
    最後の砦（Last Resort）。
    """
    def __init__(self, config: dict):
        self.config = config
        swap_conf = config.get("manual_swap_settings", {})
        self.overrides = swap_conf.get("overrides", {})
        self.updated_at = swap_conf.get("updated_at", "2000-01-01")

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """
        手動設定のスワップポイントを取得する。
        設定が14日以上古い場合は警告を出す。
        """
        # データの鮮度チェック
        try:
            updated_date = datetime.strptime(str(self.updated_at), "%Y-%m-%d")
            days_diff = (datetime.now() - updated_date).days
            if days_diff > 14:
                logger.warning(f"Manual Swap settings are OLD ({days_diff} days). Using with caution.")
                # 安全のため空を返す選択肢もあるが、Last Resortなので警告に留める
        except ValueError:
            logger.error("Invalid date format in manual_swap_settings")

        data = self.overrides.get(pair)
        if data:
            return {"long": float(data.get("long", 0.0)), "short": float(data.get("short", 0.0))}
        return {}

class HttpJsonSwapProvider(SwapProvider):
    """
    外部のJSONエンドポイントからスワップ情報を取得するプロバイダー。
    想定フォーマット: {"MXN_JPY": {"long": 15.0, "short": -20.0}, ...}
    """
    def __init__(self, config: dict):
        self.url = config.get("swap_source_url") # settings.yamlに追加が必要
        self.cache: Dict[str, Dict[str, float]] = {}
        self.last_fetch = 0.0
        self.ttl = 3600 # 1時間

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """
        外部APIからスワップポイントを取得する。
        """
        if not self.url:
            return {}

        if time.time() - self.last_fetch > self.ttl:
            self._fetch_remote()

        return self.cache.get(pair, {})

    def _fetch_remote(self):
        try:
            resp = requests.get(self.url, timeout=5)
            if resp.status_code == 200:
                self.cache = resp.json()
                self.last_fetch = time.time()
                logger.info(f"Fetched remote swap data from {self.url}")
            else:
                logger.warning(f"Remote swap fetch failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Remote swap fetch error: {e}")

class AggregatedSwapProvider(SwapProvider):
    """
    複数のソースを順に試行し、スワップポイントを解決するプロバイダー。
    優先順位:
    1. HTTP JSON Source (もし設定にあれば)
    2. Manual Settings (settings.yaml)
    """
    def __init__(self, config: dict):
        self.providers = []
        
        # URL設定があればHTTPプロバイダーを追加
        if config.get("swap_source_url"):
            self.providers.append(HttpJsonSwapProvider(config))
            
        # 常にManualプロバイダーは追加（フォールバック）
        self.providers.append(ManualSwapProvider(config))

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """
        登録されたプロバイダーを順に検索し、最初に見つかった有効なデータを返す。
        """
        for provider in self.providers:
            data = provider.get_swap_points(pair)
            # 有効なデータ（long/shortが含まれる）なら採用
            if data and "long" in data and "short" in data:
                return data
        
        logger.warning(f"No swap data found for {pair} in any provider.")
        return {}