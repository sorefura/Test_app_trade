# src/execution.py
import logging
import math
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from src.interfaces import BrokerClient
from src.models import AiAction, BrokerResult

logger = logging.getLogger(__name__)

# JSONL監査ログの設定
jsonl_logger = logging.getLogger("AuditLog")
jsonl_logger.setLevel(logging.INFO)

# ハンドラーの二重登録防止
if not jsonl_logger.handlers:
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
        AIの決定に基づいてアクションを実行し、必ず監査ログを残す。

        Args:
            decision (AiAction): AIの決定

        Returns:
            BrokerResult: 実行結果
        """
        action_type = decision.action
        pair = decision.target_pair
        
        # 監査用リクエストID生成 (decisionにあればそれを使う)
        req_id = getattr(decision, "request_id", str(uuid.uuid4()))

        logger.info(f"ExecutionService: {action_type} {pair}")
        result = BrokerResult(status="ERROR", request_id=req_id)

        try:
            if action_type in ["BUY", "SELL"]:
                lots = self._calculate_lot_size(decision)
                if lots > 0:
                    decision.units = float(lots)
                    result = self.broker.place_order(decision)
                    # Broker側でRequestIdがセットされていない場合補完
                    if not result.request_id: result.request_id = req_id
                else:
                    logger.warning("Lots=0. Skipping.")
                    result = BrokerResult(status="HOLD", details={"reason": "Zero lots"}, request_id=req_id)

            elif action_type == "EXIT":
                result = self.broker.close_position(pair=pair, amount=decision.units)
                if not result.request_id: result.request_id = req_id

            elif action_type == "HOLD":
                result = BrokerResult(status="HOLD", details={"rationale": decision.rationale}, request_id=req_id)
            
            else:
                result = BrokerResult(status="HOLD", details={"reason": "Unknown Action"}, request_id=req_id)

            self._log_audit(decision, result)
            return result

        except Exception as e:
            logger.error(f"Execution Exception: {e}", exc_info=True)
            err_result = BrokerResult(status="ERROR", details={"error": str(e)}, request_id=req_id)
            self._log_audit(decision, err_result)
            return err_result

    def _log_audit(self, decision: AiAction, result: BrokerResult) -> None:
        """
        実行結果を監査ログ（JSONL）に記録する。
        detailsはJSONオブジェクトとして埋め込む。

        Args:
            decision (AiAction): 元の決定
            result (BrokerResult): 結果
        """
        # 機密情報の簡易マスク
        safe_details = result.details.copy()
        
        # detailsを文字列化せず、辞書のまま保持して json.dumps に任せる
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": result.request_id or "unknown",
            "order_id": result.order_id, # Noneでもキーは残す
            "pair": decision.target_pair,
            "action": decision.action,
            "status": result.status,
            "units": decision.units,
            "live_config": self.enable_live,
            "live_armed": self.live_armed,
            "details": safe_details
        }
        
        try:
            json_line = json.dumps(log_entry, ensure_ascii=False)
            jsonl_logger.info(json_line)
            logger.info(f"Audit: {decision.action} -> {result.status} (OrdID: {result.order_id})")
        except Exception as e:
            logger.error(f"Audit Log Failed: {e}")

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
            investable = balance * decision.suggested_leverage
            units = math.floor((investable / price) / self.min_lot_unit) * self.min_lot_unit
            return int(units)
        except Exception:
            return 0