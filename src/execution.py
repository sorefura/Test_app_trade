# src/execution.py
import logging
import math
import json
import uuid
import os
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
    トレードの実行管理を行うサービスクラス (Production Safety Edition)。
    
    【主な機能】
    - ロット計算: Brokerから取得したSymbolSpec(最小ロット・刻み値)に基づく厳密な計算。
    - 発注指示: Brokerへの発注、決済。
    - 監査ログ: 全てのアクション結果をJSONL形式で記録。
    """
    
    def __init__(self, broker_client: BrokerClient, config: dict):
        """
        ExecutionServiceを初期化する。

        Args:
            broker_client (BrokerClient): 使用するブローカークライアント
            config (dict): 設定情報
        """
        self.broker = broker_client
        # configのmin_lot_unitはフォールバックとしてのみ使用
        self.fallback_min_lot = config.get("min_lot_unit", 1000)
        self.enable_live = config.get("enable_live_trading", False)
        
        # レバレッジ設定 (APIから取得できない場合の上限キャップ)
        self.account_leverage = config.get("max_leverage", 25.0)
        
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
        
        # 監査用リクエストID取得
        req_id = decision.request_id or str(uuid.uuid4())
        decision.request_id = req_id # 確実にセット

        logger.info(f"ExecutionService: {action_type} {pair} (ReqID: {req_id})")
        result = BrokerResult(status="ERROR", request_id=req_id)

        try:
            if action_type in ["BUY", "SELL"]:
                # テスト/積立用: 明示的にunitsが指定されている場合は計算をスキップ
                if decision.units and decision.units > 0:
                    lots = float(decision.units)
                    logger.info(f"Using provided units (bypass calc): {lots}")
                else:
                    lots = self._calculate_lot_size(decision)
                
                if lots > 0:
                    # 決定された数量をdecisionに書き戻して発注
                    decision.units = float(lots)
                    result = self.broker.place_order(decision)
                    if not result.request_id: result.request_id = req_id
                else:
                    logger.warning("Calculated Lots=0. Skipping order.")
                    result = BrokerResult(status="HOLD", details={"reason": "Zero lots calculated"}, request_id=req_id)

            elif action_type == "EXIT":
                result = self.broker.close_position(pair=pair, amount=decision.units)
                if not result.request_id: result.request_id = req_id

            elif action_type == "HOLD":
                result = BrokerResult(status="HOLD", details={"rationale": decision.rationale}, request_id=req_id)
            
            else:
                result = BrokerResult(status="HOLD", details={"reason": f"Unknown Action {action_type}"}, request_id=req_id)

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
        safe_details = result.details.copy()
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": result.request_id or "unknown",
            "order_id": result.order_id,
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

    def _calculate_lot_size(self, decision: AiAction) -> float:
        """
        資金管理ルール、レバレッジ、およびBrokerのシンボル仕様に基づいて発注ロット数を計算する。

        Args:
            decision (AiAction): AIの決定

        Returns:
            float: 計算されたロット数 (0の場合は発注不可)
        """
        try:
            pair = decision.target_pair
            
            # 1. Brokerから最新のシンボル仕様を取得 (キャッシュ付き)
            spec = self.broker.get_symbol_specs(pair)
            
            if spec:
                min_size = spec.min_order_size
                step = spec.size_step
                logger.info(f"Using Symbol Spec for {pair}: Min={min_size}, Step={step}")
            else:
                # 取得失敗時はConfigのフォールバック値を使用
                min_size = self.fallback_min_lot
                step = self.fallback_min_lot
                logger.warning(f"Symbol Spec not found for {pair}. Using fallback: {min_size}")

            # 2. 口座情報の取得
            account = self.broker.get_account_state()
            balance = account.get("balance", 0.0)
            
            # 3. 現在価格の取得
            snapshot = self.broker.get_market_snapshot(pair)
            price = snapshot.ask if decision.action == "BUY" else snapshot.bid
            
            if price <= 0:
                logger.error("Invalid price (<=0). Cannot calculate lots.")
                return 0.0
            
            # 4. レバレッジ計算 (AI提案 vs 口座設定の低い方)
            effective_leverage = min(decision.suggested_leverage, self.account_leverage)
            
            # 5. 投資可能額 = 口座残高 * 実効レバレッジ
            # ※本来は「使用可能証拠金」を使うべきだが、簡易的に残高ベースで計算し、
            #   RiskManagerの余力チェックに任せる設計とする。
            investable = balance * effective_leverage
            
            # 6. 生の購入可能数量
            raw_units = investable / price
            
            # 7. 丸め処理 (Step単位で切り捨て)
            if step > 0:
                units = math.floor(raw_units / step) * step
            else:
                units = int(raw_units) # Step未定義時は整数化
                
            # 8. 最小発注数量チェック
            if units < min_size:
                logger.info(f"Calculated units ({units}) < Min Order Size ({min_size}). Result: 0")
                return 0.0
            
            logger.info(f"Lot Calc: Bal={balance:.0f}, Lev={effective_leverage}x, Price={price:.3f} -> Units={units}")
            return float(units)

        except Exception as e:
            logger.error(f"Lot calculation failed: {e}", exc_info=True)
            return 0.0