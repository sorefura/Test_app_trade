# src/execution.py
import logging
import math
import json
from datetime import datetime
from typing import Any
from src.interfaces import BrokerClient
from src.models import AiAction, BrokerResult

logger = logging.getLogger(__name__)

# JSONL監査ログの設定
jsonl_logger = logging.getLogger("AuditLog")
jsonl_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("execution_audit.jsonl", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(message)s'))
jsonl_logger.addHandler(file_handler)
jsonl_logger.propagate = False

class ExecutionService:
    """
    トレードの実行管理を行うサービスクラス。
    ロット計算、Brokerへの発注指示、および監査ログ（Audit Log）の記録を担当する。
    """
    
    def __init__(self, broker_client: BrokerClient, config: dict):
        """
        ExecutionServiceを初期化する。

        Args:
            broker_client (BrokerClient): 使用するブローカークライアント
            config (dict): 設定情報
        """
        self.broker = broker_client
        self.min_lot_unit = config.get("min_lot_unit", 1000)
        self.enable_live = config.get("enable_live_trading", False)
        
        import os
        self.live_armed = os.getenv("LIVE_TRADING_ARMED", "NO")

    def execute_action(self, decision: AiAction) -> BrokerResult:
        """
        AIの決定に基づいてアクションを実行する。

        Args:
            decision (AiAction): AIの決定

        Returns:
            BrokerResult: 実行結果
        """
        action_type = decision.action
        pair = decision.target_pair

        logger.info(f"ExecutionService received: {action_type} for {pair}")
        result = BrokerResult(status="ERROR")

        try:
            if action_type in ["BUY", "SELL"]:
                lots = self._calculate_lot_size(decision)
                if lots > 0:
                    decision.units = float(lots)
                    logger.info(f"Calculated Lots: {lots} (Lev: {decision.suggested_leverage}x)")
                    
                    result = self.broker.place_order(decision)
                else:
                    logger.warning("Calculated lot size is 0. Skipping order.")
                    result = BrokerResult(status="HOLD", details={"reason": "Zero lots"})

            elif action_type == "EXIT":
                result = self.broker.close_position(pair=pair, amount=decision.units)

            elif action_type == "HOLD":
                result = BrokerResult(status="HOLD", details={"rationale": decision.rationale})
                logger.info(f"HOLD: {decision.rationale}")
            
            else:
                result = BrokerResult(status="HOLD", details={"reason": "Unknown Action"})

            self._log_audit(decision, result)
            return result

        except Exception as e:
            logger.error(f"Order Execution Failed: {e}", exc_info=True)
            err_result = BrokerResult(status="ERROR", details={"error": str(e)})
            self._log_audit(decision, err_result)
            return err_result

    def _log_audit(self, decision: AiAction, result: BrokerResult) -> None:
        """
        実行結果を監査ログ（JSONL）に記録する。

        Args:
            decision (AiAction): 元の決定
            result (BrokerResult): 結果
        """
        safe_details = result.details.copy()
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "pair": decision.target_pair,
            "action": decision.action,
            "status": result.status,
            "order_id": result.order_id,
            "units": decision.units,
            "live_config": self.enable_live,
            "live_armed": self.live_armed,
            "details": str(safe_details)
        }
        
        jsonl_logger.info(json.dumps(log_entry, ensure_ascii=False))
        logger.info(f"Audit Log: {decision.action} -> {result.status} (ID: {result.order_id})")

    def _calculate_lot_size(self, decision: AiAction) -> int:
        """
        資金管理ルールとレバレッジに基づいて発注ロット数を計算する。

        Args:
            decision (AiAction): AIの決定

        Returns:
            int: 計算されたロット数
        """
        try:
            account = self.broker.get_account_state()
            balance = account.get("balance", 0.0)
            snapshot = self.broker.get_market_snapshot(decision.target_pair)
            price = snapshot.ask if decision.action == "BUY" else snapshot.bid
            
            if price <= 0: return 0
            
            investable_amount = balance * decision.suggested_leverage
            raw_units = investable_amount / price
            units = math.floor(raw_units / self.min_lot_unit) * self.min_lot_unit
            
            return int(units)
        except Exception as e:
            logger.error(f"Lot calculation error: {e}")
            return 0
        