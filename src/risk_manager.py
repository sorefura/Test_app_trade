# src/risk_manager.py
import logging
import time
from typing import Any, Tuple
from src.models import AiAction, PositionSummary

logger = logging.getLogger(__name__)

class RiskManager:
    """
    資金管理と強制ロスカットを担当するクラス。
    """
    
    def __init__(self, config: dict):
        self.max_leverage = config.get("max_leverage", 25.0)
        self.kill_switch_margin_pct = config.get("kill_switch_margin_pct", 1.0)
        self.max_positions_per_pair = config.get("max_positions_per_pair", 3)
        
        # クールダウン設定
        self.cooldown_end_time = 0.0
        self.cooldown_duration_sec = 3600  # Kill Switch発動後1時間は停止

    def check_account_health(self, account_state: Any) -> Tuple[bool, str]:
        """
        口座チェック & クールダウン管理
        """
        # 1. クールダウン中かチェック
        if time.time() < self.cooldown_end_time:
            return False, f"COOLDOWN: Active until {self.cooldown_end_time}"

        # 2. 維持率チェック
        margin_ratio = account_state.get("margin_maintain_pct", 9.99)
        if margin_ratio < self.kill_switch_margin_pct:
            # Kill Switch 発動！ クールダウンを設定
            self.cooldown_end_time = time.time() + self.cooldown_duration_sec
            logger.critical(f"KILL SWITCH TRIGGERED. Cooldown set for {self.cooldown_duration_sec}s")
            return False, f"CRITICAL: Margin level too low ({margin_ratio:.2%})"
            
        return True, "OK"

    def validate_action(self, action: AiAction, positions: list[PositionSummary]) -> AiAction:
        """
        AIのアクションを検証・修正（オーバーライド）する
        """
        # EXITやHOLDは基本通す
        if action.action in ["EXIT", "HOLD"]:
            return action

        target_positions = [p for p in positions if p.pair == action.target_pair]

        # A. ポジション数上限チェック
        if len(target_positions) >= self.max_positions_per_pair:
            logger.warning(f"Risk Override: Max positions reached for {action.target_pair}. Force HOLD.")
            return self._override_to_hold(action, "Max positions reached")

        # B. レバレッジのバウンド処理 (AIが異常なレバレッジを提案した場合のキャップ)
        if action.suggested_leverage > self.max_leverage:
            logger.warning(f"Risk Override: Leverage {action.suggested_leverage} -> {self.max_leverage}")
            action.suggested_leverage = self.max_leverage

        return action

    def _override_to_hold(self, original_action: AiAction, reason: str) -> AiAction:
        """強制的にHOLDに書き換える"""
        # ★修正: 書き換える前に元の値を退避
        old_action_type = original_action.action
        
        original_action.action = "HOLD"
        # 退避した値を使ってログを作る
        original_action.rationale = f"[RISK MANAGER OVERRIDE] {reason}. (Original: {old_action_type})"
        return original_action