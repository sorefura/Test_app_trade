# src/execution.py
import logging
import math
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from src.interfaces import BrokerClient
from src.models import AiAction, BrokerResult

logger = logging.getLogger(__name__)

# JSONL監査ログの設定
jsonl_logger = logging.getLogger("AuditLog")
jsonl_logger.setLevel(logging.INFO)

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
        self.enable_live = config.get("enable_live_trading", False)
        # 設定値はフォールバック用。基本はAPI取得値を優先
        self.fallback_min_lot = config.get("min_lot_unit", 1000)
        # レバレッジ設定の取得 (APIから取得できないため設定値を使用)
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
        
        # 監査用リクエストID生成: AiActionに含まれていればそれを使い、なければ生成
        if decision.request_id:
            req_id = decision.request_id
        else:
            req_id = str(uuid.uuid4())
            # 後続処理のためにセットしておく
            decision.request_id = req_id

        logger.info(f"ExecutionService: {action_type} {pair} (ReqID: {req_id})")
        result = BrokerResult(status="ERROR", request_id=req_id)

        try:
            if action_type in ["BUY", "SELL"]:
                # ロット計算または指定値の検証
                # 修正: 明示的にunitsが指定されている場合は計算をスキップして採用する (テスト/積立用)
                if decision.units and decision.units > 0:
                    # 指定値がある場合でも、シンボル仕様に適合するか検証
                    validated_units = self._validate_and_adjust_units(decision.target_pair, decision.units)
                    if validated_units != decision.units:
                        logger.warning(f"Specified units {decision.units} adjusted to {validated_units} (or 0 if invalid)")
                    lots = int(validated_units)
                    logger.info(f"Using provided units: {lots}")
                else:
                    lots = self._calculate_lot_size(decision)
                
                if lots > 0:
                    decision.units = float(lots)
                    result = self.broker.place_order(decision)
                    # Broker側でRequestIdがセットされていない場合補完
                    if not result.request_id: result.request_id = req_id
                else:
                    # ロットが0になるのは「資金不足」か「最小単位未満」のどちらか。HOLD扱い。
                    logger.warning("Lots=0 (Below min size or funds). Skipping.")
                    result = BrokerResult(status="HOLD", details={"reason": "Zero lots (below min or insufficient funds)"}, request_id=req_id)

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

    def _get_specs_or_default(self, pair: str):
        """
        APIからシンボル仕様を取得、失敗時はデフォルト値を返す。

        Args:
            pair (str): 通貨ペア

        Returns:
            Tuple[float, float]: (min_order_size, size_step)
        """
        specs = self.broker.get_symbol_specs(pair)
        if specs:
            return specs.min_order_size, specs.size_step
        else:
            logger.warning(f"Could not fetch symbol specs for {pair}. Using fallback min={self.fallback_min_lot}.")
            return self.fallback_min_lot, self.fallback_min_lot # stepも同値と仮定

    def _validate_and_adjust_units(self, pair: str, raw_units: float) -> int:
        """
        指定された数量がシンボル仕様（最小ロット、刻み値）に適合するか確認し、
        適合しない場合は 0 を返す（勝手に丸めない方針）。
        ただし、stepによる微小な丸め（例: 10005 -> 10000）は許容するが、min未満はNGとする。

        Args:
            pair (str): 通貨ペア
            raw_units (float): 計算された生の通貨数

        Returns:
            int: 調整後のロット数。不適合なら0。
        """
        min_size, step = self._get_specs_or_default(pair)
        
        # 刻み値で丸め（切り捨て）
        units = math.floor(raw_units / step) * step
        
        if units < min_size:
            logger.warning(f"Calculated units {units} is below min order size {min_size} for {pair}.")
            return 0
            
        return int(units)

    def _calculate_lot_size(self, decision: AiAction) -> int:
        """
        資金管理ルールとシンボル仕様に基づいて発注ロット数を計算する。

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
            
            # AIが提案するレバレッジを使用するが、口座設定(max_leverage)を超えないようにキャップする
            effective_leverage = min(decision.suggested_leverage, self.account_leverage)
            
            # 投資可能額 = 口座残高 * 実効レバレッジ
            investable = balance * effective_leverage
            
            # 購入可能数量 = 投資可能額 / 価格
            raw_units = investable / price
            
            # シンボル仕様に基づく調整
            return self._validate_and_adjust_units(decision.target_pair, raw_units)

        except Exception as e:
            logger.error(f"Lot calculation failed: {e}")
            return 0