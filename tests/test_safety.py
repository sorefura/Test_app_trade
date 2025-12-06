# tests/test_safety.py
import unittest
import os
import json
import requests
from unittest.mock import MagicMock, patch
from src.adapters.gmo_broker import GmoBrokerClient
from src.adapters.offline_broker import OfflineBrokerClient
from src.models import AiAction, BrokerResult
from src.risk_manager import RiskManager
from src.execution import ExecutionService

# インポート整合性チェック用
from src.adapters.vix_provider import FixedVixProvider
from src.adapters.swap_provider import ManualSwapProvider

class TestProductionSafety(unittest.TestCase):
    """
    Production Safety (Go条件) を検証する統合テストスイート。
    誤発注防止、設定の安全性、監査ログの確実性などを網羅的にテストする。
    """

    def setUp(self) -> None:
        """
        各テストケース実行前の共通セットアップ。
        """
        self.config = {
            "enable_live_trading": True,
            "target_pairs": ["USD_JPY"],
            "max_positions_per_pair": 1,
            "min_lot_unit": 1000
        }
        self.secrets = {
            "gmo": {"api_key": "dummy", "api_secret": "dummy"}
        }

    # ----------------------------------------------------------------
    # 1. インポート整合性テスト
    # ----------------------------------------------------------------
    def test_providers_import(self) -> None:
        """
        [Safety] 新規追加された VixProvider/SwapProvider が正常にインポートでき、
        インスタンス化できることを検証する。
        """
        vix = FixedVixProvider()
        self.assertIsNotNone(vix.fetch_vix())
        
        swap = ManualSwapProvider(self.config)
        self.assertIsInstance(swap.get_swap_points("USD_JPY"), dict)

    # ----------------------------------------------------------------
    # 2. 安全なデフォルト設定 (Safe Defaults) の検証
    # ----------------------------------------------------------------
    def test_max_positions_default_is_one(self) -> None:
        """
        [Go条件B] 設定ファイルに max_positions_per_pair が欠落している場合、
        安全側に倒してデフォルト値 1 が適用されることを検証する。
        """
        empty_config = {}
        risk = RiskManager(empty_config)
        self.assertEqual(risk.max_positions_per_pair, 1, "Default should be 1 for safety")

    # ----------------------------------------------------------------
    # 3. ExecutionService 監査ログテスト (Audit Log)
    # ----------------------------------------------------------------
    @patch('src.execution.jsonl_logger')
    def test_audit_log_generation(self, mock_logger: MagicMock) -> None:
        """
        [Go条件E] ExecutionServiceがBrokerResultを受け取り、
        request_id, status を含む構造化されたJSONLログを出力することを検証する。
        """
        broker = OfflineBrokerClient(self.config)
        svc = ExecutionService(broker, self.config)
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1,
            rationale="Audit Test"
        )
        
        # 実行
        result = svc.execute_action(action)
        
        # 1. 戻り値の確認
        self.assertEqual(result.status, "EXECUTED")
        self.assertIsNotNone(result.request_id)
        self.assertIsNotNone(result.order_id)
        
        # 2. ログ出力の確認
        self.assertTrue(mock_logger.info.called)
        args, _ = mock_logger.info.call_args
        log_json_str = args[0]
        
        # JSONとしてパースして必須フィールドを確認
        try:
            log_entry = json.loads(log_json_str)
        except json.JSONDecodeError:
            self.fail("Audit log is not valid JSON")
            
        self.assertIn("timestamp", log_entry)
        self.assertEqual(log_entry["request_id"], result.request_id)
        self.assertEqual(log_entry["status"], "EXECUTED")
        self.assertEqual(log_entry["action"], "BUY")
        self.assertIsInstance(log_entry["details"], dict)

    # ----------------------------------------------------------------
    # 4. 二段ロック (Two-Step Locking) の検証
    # ----------------------------------------------------------------
    @patch.dict(os.environ, {}, clear=True)
    def test_two_step_lock_blocks_place_order(self) -> None:
        """
        [Go条件A] 環境変数が未設定の場合、YAML設定がTrueであっても
        発注処理がブロックされ、DRY_RUN_NOT_SENT が返されることを検証する。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1, rationale="Test", units=1000
        )
        result = broker.place_order(action)
        self.assertEqual(result.status, "DRY_RUN_NOT_SENT")
        self.assertIn("dry-run mode", result.details.get("msg", ""))
        self.assertFalse(broker.enable_live_trading)

    @patch.dict(os.environ, {}, clear=True)
    def test_request_method_raises_error_without_env(self) -> None:
        """
        [Go条件A強化] 内部フラグがTrueの状態でも、環境変数がなければ
        HTTPリクエスト直前で RuntimeError が発生することを検証する。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        # 強制的に内部フラグをTrueにしてバグをシミュレート
        broker.enable_live_trading = True
        
        with self.assertRaises(RuntimeError) as cm:
            broker._request("POST", "/v1/order", {"test": 1}, private=True)
        self.assertIn("Safety Block", str(cm.exception))

    # ----------------------------------------------------------------
    # 5. Dry-Run時の偽成功防止
    # ----------------------------------------------------------------
    @patch.dict(os.environ, {}, clear=True)
    def test_dry_run_does_not_return_closed_all_if_positions_exist(self) -> None:
        """
        [Go条件C] Dry-Run時にポジションが存在する場合、
        CLOSED_ALL ではなく DRY_RUN_NOT_CLOSED を返すことを検証する。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # ポジションが存在するようにモック
        mock_pos_response = {
            "list": [{"positionId": "123", "side": "BUY", "size": "1000"}]
        }
        broker._request = MagicMock(return_value=mock_pos_response)
        
        result = broker.close_position("USD_JPY")
        self.assertEqual(result.status, "DRY_RUN_NOT_CLOSED")
        self.assertNotEqual(result.status, "CLOSED_ALL")

    # ----------------------------------------------------------------
    # 6. POSTリトライ禁止 & エラーハンドリング
    # ----------------------------------------------------------------
    @patch("requests.post")
    @patch.dict(os.environ, {"LIVE_TRADING_ARMED": "YES"}, clear=True)
    def test_no_retry_on_post_timeout(self, mock_post: MagicMock) -> None:
        """
        [誤発注防止] Private POSTでTimeoutが発生した場合、
        リトライを行わずに即座に例外を送出することを検証する。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        mock_post.side_effect = requests.Timeout("Mock Timeout")
        
        with self.assertRaises(requests.Timeout):
            broker._request("POST", "/v1/order", {"test": 1}, private=True)
        
        # 呼び出し回数が1回（リトライなし）であることを確認
        self.assertEqual(mock_post.call_count, 1)

    @patch("requests.post")
    @patch.dict(os.environ, {"LIVE_TRADING_ARMED": "YES"}, clear=True)
    def test_error_if_no_order_id(self, mock_post: MagicMock) -> None:
        """
        [監査性] レスポンスは正常だが orderId が含まれていない場合、
        成功扱いせず ERROR ステータスを返すことを検証する。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # orderIdが含まれないレスポンスをモック
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": 0, "data": {}}
        mock_post.return_value = mock_resp
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1,
            confidence=1, risk_level=1, expected_holding_period_days=1,
            rationale="Test", units=1000
        )
        result = broker.place_order(action)
        
        self.assertEqual(result.status, "ERROR")
        self.assertIn("Missing orderId", str(result.details))

if __name__ == "__main__":
    unittest.main()
