# src/risk_manager.py
import logging
import time
from typing import Any, Tuple
from src.models import AiAction, PositionSummary

logger = logging.getLogger(__name__)

class RiskManager:
    """
    資金管理ルール、ポジション制限、および強制ロスカット（Kill Switch）を担当するクラス。
    AIの判断を監視し、危険なアクションをオーバーライドする権限を持つ。
    """
    
    def __init__(self, config: dict):
        """
        RiskManagerを初期化する。

        Args:
            config (dict): システム設定
        """
        self.max_leverage = config.get("max_leverage", 25.0)
        self.kill_switch_margin_pct = config.get("kill_switch_margin_pct", 1.0)
        
        # 設定欠落時の安全策としてデフォルト値を1に強制
        self.max_positions_per_pair = config.get("max_positions_per_pair", 1)
        if self.max_positions_per_pair is None:
             self.max_positions_per_pair = 1
        
        # Kill Switch発動後のクールダウン管理
        self.cooldown_end_time = 0.0
        self.cooldown_duration_sec = 3600

    def check_account_health(self, account_state: Any) -> Tuple[bool, str]:
        """
        口座の健全性をチェックし、Kill Switchの発動要否を判定する。

        Args:
            account_state (Any): 口座情報（維持率等）

        Returns:
            Tuple[bool, str]: (健全か否か, 理由メッセージ)
        """
        # クールダウン期間のチェック
        if time.time() < self.cooldown_end_time:
            return False, f"COOLDOWN: Active until {self.cooldown_end_time}"

        # 証拠金維持率のチェック
        margin_ratio = account_state.get("margin_maintain_pct", 9.99)
        if margin_ratio < self.kill_switch_margin_pct:
            self.cooldown_end_time = time.time() + self.cooldown_duration_sec
            logger.critical(f"KILL SWITCH TRIGGERED. Cooldown set for {self.cooldown_duration_sec}s")
            return False, f"CRITICAL: Margin level too low ({margin_ratio:.2%})"
            
        return True, "OK"

    def validate_action(self, action: AiAction, positions: list[PositionSummary]) -> AiAction:
        """
        AIが提案したアクションをリスク管理ルールに照らして検証・修正する。

        Args:
            action (AiAction): AIの提案アクション
            positions (list[PositionSummary]): 現在の保有ポジション

        Returns:
            AiAction: 検証済み（場合によっては修正済み）のアクション
        """
        if action.action in ["EXIT", "HOLD"]:
            return action

        target_positions = [p for p in positions if p.pair == action.target_pair]

        # ポジション数上限チェック
        if len(target_positions) >= self.max_positions_per_pair:
            reason = f"Max positions reached ({len(target_positions)} >= {self.max_positions_per_pair})"
            logger.warning(f"Risk Override: {reason} for {action.target_pair}. Force HOLD.")
            return self._override_to_hold(action, reason)

        # レバレッジ上限チェック
        if action.suggested_leverage > self.max_leverage:
            logger.warning(f"Risk Override: Leverage {action.suggested_leverage} -> {self.max_leverage}")
            action.suggested_leverage = self.max_leverage

        return action

    def _override_to_hold(self, original_action: AiAction, reason: str) -> AiAction:
        """
        アクションを強制的にHOLDに書き換えるヘルパーメソッド。

        Args:
            original_action (AiAction): 元のアクション
            reason (str): 書き換え理由

        Returns:
            AiAction: HOLDに変更されたアクション
        """
        old_action_type = original_action.action
        
        original_action.action = "HOLD"
        original_action.rationale = f"[RISK MANAGER OVERRIDE] {reason}. (Original: {old_action_type})"
        return original_action