# tests/test_units.py
import unittest
import time
import logging
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# テスト対象モジュールのインポート
from src.models import AiAction, MarketSnapshot, PositionSummary, BrokerResult
from src.strategy import StrategyEngine
from src.risk_manager import RiskManager
from src.execution import ExecutionService

# ログ出力を抑制してテスト結果を見やすくする
logging.basicConfig(level=logging.ERROR)

class TestFxBotUnits(unittest.TestCase):
    """
    FX Swap Botの各コンポーネント（Strategy, RiskManager, Execution）の
    単体テストおよび結合テストを行うクラス。
    """

    def setUp(self):
        """各テストケース実行前の共通セットアップ処理。"""
        self.config = {
            "max_leverage": 25.0,
            "vix_threshold": 20.0,
            "kill_switch_margin_pct": 0.5,
            "ai_interval_min": 1, # テスト用に短縮
            "min_lot_unit": 1000,
            "max_positions_per_pair": 1,
            "enable_live_trading": True # モック内で有効化しておく
        }
        
        # 各コンポーネントのモック作成
        self.mock_broker = MagicMock()
        self.mock_ai = MagicMock()
        self.mock_news = MagicMock()
        self.mock_market_data = MagicMock()

        # 1. 口座状態: デフォルトで安全圏
        self.mock_market_data.fetch_account_state.return_value = {
            "balance": 1000000.0,
            "margin_maintain_pct": 2.0
        }
        self.mock_broker.get_account_state.return_value = {
            "balance": 1000000.0,
            "margin_maintain_pct": 2.0
        }
        
        # 2. ポジション: デフォルトは空リスト
        self.mock_market_data.fetch_positions.return_value = []
        
        # 3. VIX: デフォルトは安全圏
        self.mock_market_data.fetch_vix.return_value = 15.0
        
        # 4. MarketSnapshotの共通戻り値
        self.snapshot = MarketSnapshot(
            pair="USD_JPY",
            timestamp=datetime.now(timezone.utc),
            bid=150.00,
            ask=150.05,
            swap_long_per_day=150.0,
            swap_short_per_day=-180.0,
            realized_vol_24h=0.005
        )
        self.mock_market_data.fetch_market_snapshot.return_value = self.snapshot
        self.mock_broker.get_market_snapshot.return_value = self.snapshot

        # 5. SymbolSpec: デフォルトはNone（フォールバックテスト用）
        self.mock_broker.get_symbol_specs.return_value = None

    # --- Test Case 1: AIコスト削減ロジック ---
    def test_strategy_skip_ai_call(self):
        """
        AI呼び出しのインターバル制御が機能しているか検証する。
        前回呼び出しから時間が経過していない場合、AI分析をスキップしてHOLDすべき。
        """
        risk_manager = RiskManager(self.config)
        strategy = StrategyEngine(
            self.mock_market_data, self.mock_news, self.mock_ai, risk_manager, self.config
        )

        # 1回目の呼び出し (AI呼ばれるはず)
        self.mock_ai.analyze.return_value.decision = AiAction(
            action="HOLD", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=0.9, risk_level=1, expected_holding_period_days=1, rationale="Test"
        )
        
        strategy.run_analysis_cycle("USD_JPY")
        self.assertTrue(self.mock_ai.analyze.called, "初回はAIが呼ばれるべき")

        # 2回目の呼び出し (直後なのでAIスキップされるはず)
        self.mock_ai.reset_mock() # カウントリセット
        strategy.run_analysis_cycle("USD_JPY")
        self.assertFalse(self.mock_ai.analyze.called, "短期間の再呼び出しではAIはスキップされるべき")

    # --- Test Case 2: ロット計算ロジック ---
    def test_execution_lot_calculation(self):
        """
        ExecutionServiceが資金とレバレッジに基づいて適切なロット数を計算できるか検証する。
        """
        exec_service = ExecutionService(self.mock_broker, self.config)
        
        # AI指令: レバレッジ2倍 (200万円分のポジション)
        # 2,000,000 / 150 = 13,333... -> 13,000 (1000通貨単位切り捨て)
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=2.0,
            confidence=0.9, risk_level=1, expected_holding_period_days=1, rationale="Test"
        )
        
        # モックの戻り値を BrokerResult に設定（ExecutionService内部での呼び出し用）
        self.mock_broker.place_order.return_value = BrokerResult(status="EXECUTED")

        # 内部メソッド _calculate_lot_size のテスト
        lots = exec_service._calculate_lot_size(action)
        self.assertEqual(lots, 13000)

    # --- Test Case 3: Kill Switch 発動 ---
    def test_risk_kill_switch(self):
        """
        証拠金維持率が閾値を下回った場合、RiskManagerが危険信号を返すか検証する。
        """
        risk_manager = RiskManager(self.config)
        
        # 維持率 40% (閾値50%より低い)
        account_state = {"margin_maintain_pct": 0.40}
        is_safe, reason = risk_manager.check_account_health(account_state)
        
        self.assertFalse(is_safe)
        self.assertIn("CRITICAL", reason)

    # --- Test Case 4: AIレスポンス異常系 ---
    def test_ai_validation_error(self):
        """
        AIクライアントが例外を投げた場合、システムがクラッシュせずHOLDアクションを返すか検証する。
        """
        risk_manager = RiskManager(self.config)
        strategy = StrategyEngine(
            self.mock_market_data, self.mock_news, self.mock_ai, risk_manager, self.config
        )
        
        # AIが例外を吐く設定
        self.mock_ai.analyze.side_effect = Exception("AI API Error")
        
        decision = strategy.run_analysis_cycle("USD_JPY")
        
        self.assertEqual(decision.action, "HOLD")
        self.assertIn("AI Error Fallback", decision.rationale)

    # --- Test Case 5: 最大ポジション数の強制 ---
    def test_max_positions_per_pair_enforced(self):
        """
        既にポジションがある状態で新規BUYが指示された場合、RiskManagerがHOLDに書き換えるか検証する。
        """
        risk_manager = RiskManager(self.config) # max_positions_per_pair=1
        
        existing_position = PositionSummary(
            pair="USD_JPY", side="LONG", amount=10000,
            avg_entry_price=150.0, current_price=150.5,
            unrealized_pnl=5000, leverage=25.0
        )
        positions = [existing_position]
        
        ai_action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=0.9, risk_level=1, expected_holding_period_days=1, 
            rationale="Add more"
        )
        
        final_action = risk_manager.validate_action(ai_action, positions)
        
        self.assertEqual(final_action.action, "HOLD")
        self.assertIn("RISK MANAGER OVERRIDE", final_action.rationale)

    # --- 追加テスト: Risk Manager Cooldown ---
    def test_risk_cooldown_logic(self):
        """
        Kill Switch発動後、クールダウン期間中は常にFalseが返されるか検証する。
        """
        risk_manager = RiskManager(self.config)
        
        # 1. Kill Switch 発動させる
        bad_account = {"margin_maintain_pct": 0.1}
        is_safe, _ = risk_manager.check_account_health(bad_account)
        self.assertFalse(is_safe)
        
        # 2. 口座が回復しても、直後はクールダウン中でFalseになるはず
        good_account = {"margin_maintain_pct": 2.0}
        is_safe_now, reason = risk_manager.check_account_health(good_account)
        
        self.assertFalse(is_safe_now, "クールダウン中は回復してもFalseになるべき")
        self.assertIn("COOLDOWN", reason)

    # --- 追加テスト: Strategy Emergency Exit ---
    def test_strategy_triggers_emergency_exit(self):
        """
        RiskManagerが危険と判断した場合、AIを呼ばずに即座にEXITアクションが生成されるか検証する。
        """
        risk_manager = RiskManager(self.config)
        strategy = StrategyEngine(
            self.mock_market_data, self.mock_news, self.mock_ai, risk_manager, self.config
        )
        
        # 口座状態を危険に設定
        self.mock_market_data.fetch_account_state.return_value = {"margin_maintain_pct": 0.3}
        
        decision = strategy.run_analysis_cycle("USD_JPY")
        
        self.assertEqual(decision.action, "EXIT", "維持率低下時はEXITを選択すべき")
        self.assertIn("EMERGENCY EXIT", decision.rationale)
        # AIは呼ばれていないはず
        self.assertFalse(self.mock_ai.analyze.called)

    # --- 追加テスト: Execution Audit Logging ---
    @patch('src.execution.jsonl_logger')
    def test_execution_audit_logging(self, mock_logger):
        """
        ExecutionServiceがアクション実行時に監査ログ(jsonl)を出力しているか検証する。
        """
        exec_service = ExecutionService(self.mock_broker, self.config)
        
        # Brokerが正常な結果(BrokerResult)を返すと仮定
        self.mock_broker.place_order.return_value = BrokerResult(
            status="EXECUTED", order_id="TEST-ORDER-1"
        )
        
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=1.0, risk_level=1, expected_holding_period_days=1, 
            rationale="Audit Test"
        )
        
        exec_service.execute_action(action)
        
        # ロガーのinfoメソッドが呼ばれたか（JSON形式で）
        self.assertTrue(mock_logger.info.called)
        args, _ = mock_logger.info.call_args
        log_content = args[0]
        self.assertIn('"action": "BUY"', log_content)
        self.assertIn('"status": "EXECUTED"', log_content)

if __name__ == "__main__":
    unittest.main()