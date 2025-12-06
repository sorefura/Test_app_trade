# tests/test_safety.py
import unittest
import os
import requests
from unittest.mock import MagicMock, patch
from src.adapters.gmo_broker import GmoBrokerClient
from src.models import AiAction, BrokerResult
from src.risk_manager import RiskManager
from src.execution import ExecutionService

class TestProductionSafety(unittest.TestCase):
    """
    Production Safety (Go条件) を検証するテストスイート。
    誤発注防止、設定の安全性、監査ログの確実性などを網羅的にテストする。
    """

    def setUp(self):
        """共通セットアップ"""
        self.config = {
            "enable_live_trading": True, # YAMLではTrueだが...
            "target_pairs": ["USD_JPY"],
            "max_positions_per_pair": 1,
            "min_lot_unit": 1000
        }
        self.secrets = {
            "gmo": {"api_key": "dummy", "api_secret": "dummy"}
        }

    # ----------------------------------------------------------------
    # 1. 二段ロック (Two-Step Locking) の検証
    # ----------------------------------------------------------------

    @patch.dict(os.environ, {}, clear=True) # 環境変数を空にする
    def test_two_step_lock_blocks_place_order(self):
        """
        [Go条件A] Env変数がない場合、YAMLがTrueでも place_order はブロックされ、
        HTTPリクエストは飛ばずに 'DRY_RUN_NOT_SENT' が返されること。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1,
            rationale="Test", units=1000
        )
        
        # モックせずとも、内部フラグがFalseならHTTPリクエスト関数まで到達しないはず
        result = broker.place_order(action)
        
        self.assertEqual(result.status, "DRY_RUN_NOT_SENT")
        self.assertIn("Dry-run mode", result.details.get("msg", ""))
        self.assertFalse(broker.enable_live_trading)

    @patch.dict(os.environ, {}, clear=True)
    def test_request_method_raises_error_without_env(self):
        """
        [Go条件A強化] 万が一 enable_live_trading=True の状態で _request(POST) が呼ばれても、
        環境変数がなければ直前ガードで RuntimeError になること。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        # 強制的に内部フラグを改ざんしてバグをシミュレート
        broker.enable_live_trading = True
        
        with self.assertRaises(RuntimeError) as cm:
            broker._request("POST", "/v1/order", {"test": 1}, private=True)
        
        self.assertIn("Safety Block", str(cm.exception))

    # ----------------------------------------------------------------
    # 2. 安全なデフォルト設定 (Safe Defaults) の検証
    # ----------------------------------------------------------------

    def test_max_positions_default_is_one(self):
        """
        [Go条件B] 設定ファイルに max_positions_per_pair が欠落している場合、
        安全側に倒してデフォルト値 1 が適用されること。
        """
        empty_config = {}
        risk = RiskManager(empty_config)
        self.assertEqual(risk.max_positions_per_pair, 1, "Default should be 1")

    # ----------------------------------------------------------------
    # 3. Dry-Run時の挙動検証
    # ----------------------------------------------------------------

    @patch.dict(os.environ, {}, clear=True)
    def test_dry_run_does_not_return_closed_all_if_positions_exist(self):
        """
        [Go条件C] Dry-Run時にポジションが存在する場合、実際には閉じられないため
        'CLOSED_ALL' ではなく 'DRY_RUN_NOT_CLOSED' を返すこと。
        （偽の成功ステータスによる事故防止）
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # ポジションがあるように見せかけるモック
        mock_pos_response = {
            "list": [{"positionId": "123", "side": "BUY", "size": "1000"}]
        }
        # _request を部分的にモック
        broker._request = MagicMock(return_value=mock_pos_response)
        
        result = broker.close_position("USD_JPY")
        
        self.assertEqual(result.status, "DRY_RUN_NOT_CLOSED")
        self.assertNotEqual(result.status, "CLOSED_ALL")

    # ----------------------------------------------------------------
    # 4. POSTリトライ禁止 & エラーハンドリング (New)
    # ----------------------------------------------------------------

    @patch("requests.post")
    @patch.dict(os.environ, {"LIVE_TRADING_ARMED": "YES"}, clear=True)
    def test_no_retry_on_post_timeout(self, mock_post):
        """
        [誤発注防止] Private POSTでTimeoutが発生した場合、
        二重発注を防ぐためにリトライせず即座に例外を投げること。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # Timeout発生
        mock_post.side_effect = requests.Timeout("Mock Timeout")
        
        # POSTリクエストを実行
        with self.assertRaises(requests.Timeout):
            broker._request("POST", "/v1/order", {"test": 1}, private=True)
        
        # 重要: 呼び出し回数は 1回のみ であること（リトライしていないこと）
        self.assertEqual(mock_post.call_count, 1)

    @patch("requests.post")
    @patch.dict(os.environ, {"LIVE_TRADING_ARMED": "YES"}, clear=True)
    def test_error_if_no_order_id(self, mock_post):
        """
        [監査性] レスポンスは正常(200 OK)だが orderId が含まれていない場合、
        EXECUTED ではなく ERROR として扱うこと。
        """
        broker = GmoBrokerClient(self.config, self.secrets)
        
        # orderIdがないレスポンス
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": 0, "data": {}} # empty data
        mock_post.return_value = mock_resp
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1,
            confidence=1, risk_level=1, expected_holding_period_days=1,
            rationale="Test", units=1000
        )
        
        result = broker.place_order(action)
        
        self.assertEqual(result.status, "ERROR")
        self.assertIn("Missing orderId", str(result.details))

    # ----------------------------------------------------------------
    # 5. 監査ログ生成 (Audit Log) の検証
    # ----------------------------------------------------------------

    @patch('src.execution.jsonl_logger')
    def test_audit_log_generation(self, mock_logger):
        """
        [Go条件E] ExecutionServiceがアクション実行時に
        必ず監査ログ(JSONL)を出力しているか検証する。
        """
        # モックBrokerの準備
        broker = MagicMock()
        broker.place_order.return_value = BrokerResult(status="EXECUTED", order_id="TEST-ID")
        broker.get_account_state.return_value = {"balance": 10000}
        broker.get_market_snapshot.return_value.ask = 100
        
        svc = ExecutionService(broker, self.config)
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1,
            rationale="Test", units=100
        )
        
        result = svc.execute_action(action)
        
        self.assertEqual(result.status, "EXECUTED")
        
        # ロガーが呼ばれたか確認
        self.assertTrue(mock_logger.info.called)
        args, _ = mock_logger.info.call_args
        log_content = args[0]
        
        # 必要なフィールドが含まれているか
        self.assertIn('"action": "BUY"', log_content)
        self.assertIn('"status": "EXECUTED"', log_content)
        self.assertIn('"order_id": "TEST-ID"', log_content)

if __name__ == "__main__":
    unittest.main()
    