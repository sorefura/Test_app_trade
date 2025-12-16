# tests/test_safety.py
import unittest
import os
import json
import requests
from unittest.mock import MagicMock, patch
from src.adapters.gmo_broker import GmoBrokerClient
from src.adapters.offline_broker import OfflineBrokerClient
from src.models import AiAction, BrokerResult, SymbolSpec
from src.risk_manager import RiskManager
from src.execution import ExecutionService

# インポート整合性チェック用
from src.adapters.vix_provider import FixedVixProvider, WebVixProvider
from src.adapters.swap_provider import ManualSwapProvider, HttpJsonSwapProvider

class TestProductionSafety(unittest.TestCase):
    """
    Production Safety (Go条件) を検証する統合テストスイート。
    """

    def setUp(self) -> None:
        self.config = {
            "enable_live_trading": True,
            "target_pairs": ["USD_JPY"],
            "max_positions_per_pair": 1,
            "min_lot_unit": 1000 # フォールバック用
        }
        self.secrets = {"gmo": {"api_key": "dummy", "api_secret": "dummy"}}

    # ----------------------------------------------------------------
    # 1. インポート & プロバイダー検証
    # ----------------------------------------------------------------
    def test_providers_structure(self) -> None:
        """VixProvider/SwapProviderが正常に動作し、失敗時に安全側(None/{})を返すか検証"""
        vix = WebVixProvider()
        with patch('requests.get') as mock_get:
            mock_get.side_effect = Exception("Network Down")
            self.assertIsNone(vix.fetch_vix(), "Fetch失敗時はNoneを返すべき")

        swap = HttpJsonSwapProvider()
        self.assertEqual(swap.get_swap_points("USD_JPY"), {}, "URL未設定/失敗時は空辞書")

    # ----------------------------------------------------------------
    # 2. ロット自動計算 & 安全丸め
    # ----------------------------------------------------------------
    def test_lot_calculation_with_symbol_specs(self) -> None:
        """
        [Safety] ExecutionServiceがBrokerのSymbolSpecに従って
        ロットを正しく丸め、最小単位未満なら0を返すか検証。
        """
        broker = OfflineBrokerClient(self.config)
        svc = ExecutionService(broker, self.config)
        
        # OfflineBrokerは USD_JPY: min=100, step=1 を返す (mocks)
        
        # Case A: 正常 (150 -> 150)
        units_a = svc._validate_and_adjust_units("USD_JPY", 150)
        self.assertEqual(units_a, 150)
        
        # Case B: 最小未満 (50 -> 0)
        units_b = svc._validate_and_adjust_units("USD_JPY", 50)
        self.assertEqual(units_b, 0, "最小ロット未満は0になるべき")
        
        # OfflineBroker MXN_JPY: min=10000, step=10
        
        # Case C: Step丸め (10005 -> 10000)
        units_c = svc._validate_and_adjust_units("MXN_JPY", 10005)
        self.assertEqual(units_c, 10000, "Step単位で切り捨てられるべき")

    # ----------------------------------------------------------------
    # 3. ExecutionService 監査ログ
    # ----------------------------------------------------------------
    @patch('src.execution.jsonl_logger')
    def test_audit_log_generation(self, mock_logger: MagicMock) -> None:
        """監査ログがJSONL形式で正しく出力されるか検証"""
        broker = OfflineBrokerClient(self.config)
        svc = ExecutionService(broker, self.config)
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1,
            rationale="Audit Test"
        )
        
        svc.execute_action(action)
        self.assertTrue(mock_logger.info.called)
        
        log_json_str = mock_logger.info.call_args[0][0]
        log_entry = json.loads(log_json_str)
        
        self.assertIn("timestamp", log_entry)
        self.assertEqual(log_entry["status"], "EXECUTED")

    # ----------------------------------------------------------------
    # 4. 二段ロック (Two-Step Locking)
    # ----------------------------------------------------------------
    @patch.dict(os.environ, {}, clear=True)
    def test_two_step_lock_blocks_place_order(self) -> None:
        """環境変数なしで発注がブロックされるか検証"""
        broker = GmoBrokerClient(self.config, self.secrets)
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1, rationale="Test", units=1000
        )
        result = broker.place_order(action)
        self.assertEqual(result.status, "DRY_RUN_NOT_SENT")

    # ----------------------------------------------------------------
    # 5. POSTリトライ禁止
    # ----------------------------------------------------------------
    @patch("requests.post")
    @patch.dict(os.environ, {"LIVE_TRADING_ARMED": "YES"}, clear=True)
    def test_no_retry_on_post_timeout(self, mock_post: MagicMock) -> None:
        """Private POSTでタイムアウト時にリトライしないか検証"""
        broker = GmoBrokerClient(self.config, self.secrets)
        mock_post.side_effect = requests.Timeout("Mock Timeout")
        
        with self.assertRaises(requests.Timeout):
            broker._request("POST", "/v1/order", {"test": 1}, private=True)
        self.assertEqual(mock_post.call_count, 1)

if __name__ == "__main__":
    unittest.main()