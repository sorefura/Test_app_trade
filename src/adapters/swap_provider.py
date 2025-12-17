# src/adapters/swap_provider.py
import logging
import time
import json
import os
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta
from src.interfaces import SwapProvider

logger = logging.getLogger(__name__)

class ManualSwapProvider(SwapProvider):
    """設定ファイル依存のフォールバック用プロバイダー。"""
    def __init__(self, config: dict):
        self.config = config
        swap_conf = config.get("manual_swap_settings", {})
        self.overrides = swap_conf.get("overrides", {})
        self.updated_at = swap_conf.get("updated_at", "2000-01-01")

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """設定ファイルからスワップポイントを取得"""
        try:
            updated_date = datetime.strptime(self.updated_at, "%Y-%m-%d")
            if (datetime.now() - updated_date).days > 14:
                return {} # 古すぎるデータは危険
        except ValueError:
            return {}
        
        data = self.overrides.get(pair)
        if data:
            return {"long": float(data.get("long", 0.0)), "short": float(data.get("short", 0.0))}
        return {}

class HttpJsonSwapProvider(SwapProvider):
    """
    外部のJSONソースからスワップポイントを取得し、ローカルにキャッシュするプロバイダー。
    """
    def __init__(self, source_url: str = None):
        # デフォルトはGithub GistなどのRaw URLを想定（環境変数で上書き可）
        self.source_url = source_url or os.getenv("SWAP_JSON_URL")
        self.cache_file = "swap_cache.json"
        self._mem_cache = {}
        
    def _fetch_and_cache(self):
        if not self.source_url:
            return
            
        try:
            resp = requests.get(self.source_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # データ検証: 必須キーがあるか
            if "updated_at" in data and "swaps" in data:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                self._mem_cache = data
                logger.info("Fetched and cached swap points.")
        except Exception as e:
            logger.warning(f"Failed to fetch swap points: {e}")

    def _load_cache(self) -> dict:
        if self._mem_cache: return self._mem_cache
        
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self._mem_cache = json.load(f)
                    return self._mem_cache
            except:
                pass
        return {}

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """外部JSONまたはキャッシュからスワップポイントを取得"""
        data = self._load_cache()
        
        # 鮮度チェックと更新
        last_update_str = data.get("updated_at", "2000-01-01")
        try:
            last_update = datetime.strptime(last_update_str, "%Y-%m-%d")
            if (datetime.now() - last_update).days > 1:
                self._fetch_and_cache()
                data = self._load_cache()
        except:
            self._fetch_and_cache()
        
        # 再度鮮度チェック（7日以上古いなら無効）
        last_update_str = data.get("updated_at", "2000-01-01")
        try:
            last_update = datetime.strptime(last_update_str, "%Y-%m-%d")
            if (datetime.now() - last_update).days > 7:
                logger.warning("Swap cache is stale (>7 days). Returning empty.")
                return {} 
        except:
            return {}

        swaps = data.get("swaps", {}).get(pair)
        if swaps:
            return {"long": float(swaps.get("long", 0)), "short": float(swaps.get("short", 0))}
        return {}

class AggregatedSwapProvider(SwapProvider):
    """
    複数のプロバイダーを集約し、最適なスワップポイントを提供するクラス。
    """
    def __init__(self, config: dict):
        self.manual_provider = ManualSwapProvider(config)
        self.http_provider = HttpJsonSwapProvider()

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        """
        スワップポイントを取得する。HTTP取得を優先し、失敗時はManualにフォールバック。
        """
        res = self.http_provider.get_swap_points(pair)
        if res: return res
        return self.manual_provider.get_swap_points(pair)