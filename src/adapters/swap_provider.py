# src/adapters/swap_provider.py
import logging
import time
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
        # データの鮮度チェック
        try:
            updated_date = datetime.strptime(self.updated_at, "%Y-%m-%d")
            days_diff = (datetime.now() - updated_date).days
            if days_diff > 14:
                logger.critical(f"Manual Swap settings are CRITICALLY OLD ({days_diff} days). Unsafe to trade.")
                return {} # 空を返して呼び出し元でエラー/HOLDにする
        except ValueError:
            logger.error("Invalid date format in manual_swap_settings")
            return {}

        data = self.overrides.get(pair)
        if data:
            return {"long": float(data.get("long", 0.0)), "short": float(data.get("short", 0.0))}
        return {}

class AggregatedSwapProvider(SwapProvider):
    """
    Web取得などを試み、失敗したらManualにフォールバックするプロバイダー。
    """
    def __init__(self, config: dict):
        self.manual_provider = ManualSwapProvider(config)
        # 将来的に WebSwapProvider などをここに追加

    def get_swap_points(self, pair: str) -> Dict[str, float]:
        # 1. Web取得 (未実装のためスキップ)
        # web_swap = self.web_provider.get(pair)
        # if web_swap: return web_swap
        
        # 2. Manual Fallback
        return self.manual_provider.get_swap_points(pair)
    