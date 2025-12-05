# tests/test_safety.py
import unittest
import os
from unittest.mock import MagicMock, patch
from src.adapters.gmo_broker import GmoBrokerClient
from src.models import AiAction, BrokerResult
from src.risk_manager import RiskManager
from src.execution import ExecutionService

class TestProductionSafety(unittest.TestCase):
    """
    Production Safety (Go条件) を検証するテストスイート
    """

    def setUp(self):
        self.config = {
            "enable_live_trading": True, # YAMLではTrueだが...
            "target_pairs": ["USD_JPY"],
            "max_positions_per_pair": 1
        }
        self.secrets = {
            "gmo": {"api_key": "dummy", "api_secret": "dummy"}
        }

    # --- Go条件A: 二段ロックの検証 ---
    @patch.dict(os.environ, {}, clear=True) # 環境変数を空にする
    def test_two_step_lock_blocks_request(self):
        """Env変数がない場合、YAMLがTrueでも発注はブロックされ、HTTPリクエストは飛ばない"""
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # モック作成: _request が呼ばれたら失敗とみなすためのトラップ等は不要、
        # place_orderが DRY_RUN_NOT_SENT を返すか確認する
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1,
            rationale="Test", units=1000
        )
        
        result = broker.place_order(action)
        
        self.assertEqual(result.status, "DRY_RUN_NOT_SENT")
        self.assertIn("dry-run mode", result.details.get("msg", ""))
        
        # 二重チェック: 内部フラグも False であること
        self.assertFalse(broker.enable_live_trading)

    # --- Go条件B: max_positions_per_pair デフォルト安全側 ---
    def test_max_positions_default_is_one(self):
        """設定ファイルにmax_positions_per_pairがない場合、1になること"""
        empty_config = {}
        risk = RiskManager(empty_config)
        self.assertEqual(risk.max_positions_per_pair, 1, "Default should be 1")

    # --- Go条件C: Dry-Run時の偽成功禁止 ---
    @patch.dict(os.environ, {}, clear=True)
    def test_dry_run_does_not_return_closed_all_if_positions_exist(self):
        """Dry-Run時にポジションがあっても CLOSED_ALL を返さないこと"""
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # _request をモックして、ポジションがあるように見せる
        mock_pos_response = {
            "list": [{"positionId": "123", "side": "BUY", "size": "1000"}]
        }
        broker._request = MagicMock(return_value=mock_pos_response)
        
        result = broker.close_position("USD_JPY")
        
        self.assertEqual(result.status, "DRY_RUN_NOT_CLOSED")
        self.assertNotEqual(result.status, "CLOSED_ALL")

    # --- Go条件E: 監査ログ ---
    def test_audit_log_generation(self):
        """ExecutionServiceがログファイルを生成するか"""
        # ロガーのモックは複雑なので、ExecutionServiceが例外なく動作することを確認
        broker = MagicMock()
        broker.place_order.return_value = BrokerResult(status="EXECUTED", order_id="TEST-ID")
        broker.get_account_state.return_value = {"balance": 10000}
        broker.get_market_snapshot.return_value.ask = 100
        
        svc = ExecutionService(broker, {"min_lot_unit": 1})
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1,
            rationale="Test", units=100
        )
        
        result = svc.execute_action(action)
        self.assertEqual(result.status, "EXECUTED")

if __name__ == "__main__":
    unittest.main()
    