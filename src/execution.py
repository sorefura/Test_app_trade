# src/execution.py
import logging
import math
from typing import Any
from src.interfaces import BrokerClient
from src.models import AiAction

logger = logging.getLogger(__name__)

class ExecutionService:
    def __init__(self, broker_client: BrokerClient, config: dict):
        self.broker = broker_client
        # ブローカーの最小取引単位 (例: 1,000通貨)
        self.min_lot_unit = config.get("min_lot_unit", 1000) 

    def execute_action(self, decision: AiAction) -> None:
        action_type = decision.action
        pair = decision.target_pair

        logger.info(f"ExecutionService received: {action_type} for {pair}")

        try:
            if action_type in ["BUY", "SELL"]:
                # ロット計算
                lots = self._calculate_lot_size(decision)
                if lots > 0:
                    # decisionオブジェクトにはロット情報がないため、Broker側へ渡す際に工夫が必要だが
                    # ここではBrokerClient.place_orderの引数を拡張せず、
                    # decisionに一時的に属性を追加するか、Broker側で計算させる設計もあり。
                    # 今回はMVP互換のため「decision + lots」を渡す形ではなく、
                    # place_order内で再計算等はせず、OfflineBroker側が受け取れるよう拡張するか、
                    # 簡易的にここでのログ出力にとどめ、Brokerへはdecisionをそのまま渡す（Broker側で固定ロジック解除が必要）
                    
                    # ★修正: 計算結果をモデルに注入
                    decision.units = float(lots)

                    # ★修正: BrokerClientプロトコルを厳密に守るなら、AiActionにamountを含めるべきだが
                    # ここでは計算したlotsをログに出し、Brokerにはシミュレーションとして渡す
                    logger.info(f"Calculated Lots: {lots} (Lev: {decision.suggested_leverage}x)")
                    
                    # 本来は broker.place_order(decision, amount=lots) とすべきだが
                    # プロトコル変更を避けるため、decision.notes_for_human にロット情報を埋め込む等のハック、
                    # またはBrokerの実装側で「suggested_leverage」を見てロット計算させるのが正しい。
                    # 今回は後者（Brokerがdecision内のレバレッジを見て計算）を想定し、そのまま渡す。
                    
                    result = self.broker.place_order(decision)
                    self._log_result(action_type, result)
                else:
                    result = {"status": ""}
                    logger.warning("Calculated lot size is 0. Skipping order.")

            elif action_type == "EXIT":
                result = self.broker.close_position(position_id=pair)
                self._log_result(action_type, result)

            elif action_type == "HOLD":
                result = {"status": "hold"}
                logger.info(f"HOLD: {decision.rationale}")
            else:
                result = {"status": ""}

            return result

        except Exception as e:
            logger.error(f"Order Execution Failed: {e}", exc_info=True)
            return {"status": "ERROR", "details": str(e)}

    def _calculate_lot_size(self, decision: AiAction) -> int:
        """
        資金管理ルールに基づきロット数を計算する
        Lot = (口座残高 * 推奨レバレッジ) / 現在レート
        """
        try:
            account = self.broker.get_account_state()
            balance = account.get("balance", 0.0)
            
            snapshot = self.broker.get_market_snapshot(decision.target_pair)
            price = snapshot.ask if decision.action == "BUY" else snapshot.bid
            
            if price <= 0: return 0

            # 投資可能額
            investable_amount = balance * decision.suggested_leverage
            
            # 生の通貨数
            raw_units = investable_amount / price
            
            # 最小単位で丸める (切り捨て)
            units = math.floor(raw_units / self.min_lot_unit) * self.min_lot_unit
            
            return int(units)
        except Exception as e:
            logger.error(f"Lot calculation error: {e}")
            return 0

    def _log_result(self, action: str, result: Any):
        status = result.get("status", "UNKNOWN") if isinstance(result, dict) else str(result)
        logger.info(f"Order {action} executed. Status: {status}")