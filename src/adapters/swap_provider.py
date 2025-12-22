# src/adapters/swap_provider.py
import logging
import requests
import json
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from src.interfaces import SwapProvider

logger = logging.getLogger(__name__)

class ManualSwapProvider(SwapProvider):
    """設定ファイルから直接スワップポイントを読み込むフォールバック用プロバイダー。"""
    def __init__(self, config: dict):
        # 新しい 'manual_swap_points' を優先的に使用
        swaps = config.get("manual_swap_points")
        
        # 新しいキーがなければ、後方互換のために古い 'manual_swap_settings' をチェック
        if not swaps:
            logger.debug("'manual_swap_points' not found, checking for legacy 'manual_swap_settings.overrides'.")
            swaps = config.get("manual_swap_settings", {}).get("overrides", {})
        
        self._manual_swaps = swaps
        logger.info(f"Initialized ManualSwapProvider with {len(self._manual_swaps)} entries.")

    def get_swap_points(self, pair: str) -> Optional[Dict[str, float]]:
        """設定で定義されたスワップポイントを取得"""
        return self._manual_swaps.get(pair)

class HttpJsonSwapProvider(SwapProvider):
    """
    外部のJSON URLからスワップポイントを取得するプロバイダー。
    TTL（Time To Live）に基づき、データの鮮度を検証する。
    """
    def __init__(self, config: dict):
        self._source_url = config.get("swap_info_url")
        self._cache: Dict[str, any] = {}
        self._cache_timestamp: Optional[datetime] = None

    def get_swap_points(self, pair: str) -> Optional[Dict[str, float]]:
        """
        URLからスワップポイントを取得し、ステール判定を行う。
        データが古い、取得失敗、URL未設定の場合はNoneを返す。
        """
        if not self._source_url:
            return None

        now = datetime.now(timezone.utc)
        
        # TTL内であればメモリキャッシュを返す
        if self._cache and self._cache_timestamp:
            ttl_seconds = self._cache.get("meta", {}).get("ttl_seconds", 3600)
            if now < self._cache_timestamp + timedelta(seconds=ttl_seconds):
                return self._cache.get("swap_points", {}).get(pair)

        try:
            logger.info(f"Fetching swap points from {self._source_url}")
            response = requests.get(self._source_url, timeout=10)
            response.raise_for_status()
            data = response.json()

            # --- データ検証とステール判定 ---
            meta = data.get("meta", {})
            timestamp_str = meta.get("timestamp_utc")
            ttl = meta.get("ttl_seconds")

            if not all([timestamp_str, isinstance(ttl, int)]):
                logger.error("Swap JSON is missing meta.timestamp_utc or meta.ttl_seconds.")
                return None
            
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            
            if now > timestamp + timedelta(seconds=ttl):
                logger.warning(f"Swap data is stale. Timestamp: {timestamp_str}, TTL: {ttl}s.")
                self._cache.clear() # 古いキャッシュをクリア
                return None

            # 成功時にキャッシュを更新
            self._cache = data
            self._cache_timestamp = timestamp
            logger.info(f"Successfully fetched and validated swap points. Timestamp: {timestamp_str}")
            
            return data.get("swap_points", {}).get(pair)

        except requests.RequestException as e:
            logger.error(f"Failed to fetch swap points from URL: {e}")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse or validate swap points JSON: {e}")
            return None

class AggregatedSwapProvider(SwapProvider):
    """
    複数のプロバイダーを集約し、最適なスワップポイントを提供するクラス。
    HTTP取得を優先し、失敗時はManualにフォールバックする。
    """
    def __init__(self, config: dict):
        self.http_provider = HttpJsonSwapProvider(config)
        self.manual_provider = ManualSwapProvider(config)

    def get_swap_points(self, pair: str) -> Optional[Dict[str, float]]:
        """
        HTTPプロバイダーからスワップポイントを取得する。
        取得に失敗（Noneが返された）した場合、手動設定にフォールバックする。
        """
        # 優先度の高いHttpJsonProviderから試行
        http_swaps = self.http_provider.get_swap_points(pair)
        if http_swaps is not None:
            return http_swaps
        
        # フォールバック
        logger.warning(f"HttpJsonSwapProvider failed for {pair}. Falling back to ManualSwapProvider.")
        manual_swaps = self.manual_provider.get_swap_points(pair)
        if manual_swaps is None:
            logger.error(f"All swap providers failed for {pair}. No swap data available.")

        return manual_swaps