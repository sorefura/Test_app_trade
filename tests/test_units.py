# tests/test_units.py
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import time

# テスト対象のクラスをインポート
from src.models import AiAction, MarketSnapshot, PositionSummary
from src.strategy import StrategyEngine
from src.risk_manager import RiskManager
from src.execution import ExecutionService

class TestFxBotUnits(unittest.TestCase):

    def setUp(self):
        """各テスト前の共通セットアップ"""
        self.config = {
            "max_leverage": 25.0,
            "vix_threshold": 20.0,
            "kill_switch_margin_pct": 0.5,
            "ai_interval_min": 1, # 1分
            "min_lot_unit": 1000,
            "max_positions_per_pair": 1 # ★重要: ポジション上限を1に設定
        }
        # モック作成
        self.mock_broker = MagicMock()
        self.mock_ai = MagicMock()
        self.mock_news = MagicMock()
        self.mock_market_data = MagicMock()

        # 1. 口座状態: デフォルトで安全圏
        self.mock_market_data.fetch_account_state.return_value = {
            "balance": 1000000.0,
            "margin_maintain_pct": 2.0
        }
        
        # 2. ポジション: デフォルトは空リスト
        self.mock_market_data.fetch_positions.return_value = []
        
        # 3. VIX: デフォルトは安全圏
        self.mock_market_data.fetch_vix.return_value = 15.0
        # MagicMockではなく、本物の Pydantic モデル (MarketSnapshot) を返すようにする
        self.mock_market_data.fetch_market_snapshot.return_value = MarketSnapshot(
            pair="USD_JPY",
            timestamp=datetime.now(timezone.utc),
            bid=150.00,
            ask=150.05,
            swap_long_per_day=150.0,
            swap_short_per_day=-180.0,
            realized_vol_24h=0.005
        )


    # --- Test Case 1: AIコスト削減ロジック ---
    def test_strategy_skip_ai_call(self):
        risk_manager = RiskManager(self.config)
        strategy = StrategyEngine(
            self.mock_market_data, self.mock_news, self.mock_ai, risk_manager, self.config
        )

        # 1回目の呼び出し (AI呼ばれるはず)
        self.mock_market_data.fetch_vix.return_value = 15.0 # VIX低
        
        self.mock_ai.analyze.return_value.decision = AiAction(
            action="HOLD", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=0.9, risk_level=1, expected_holding_period_days=1, rationale="Test"
        )
        
        # 実行
        strategy.run_analysis_cycle("USD_JPY")
        self.assertTrue(self.mock_ai.analyze.called, "1回目はAIが呼ばれるべき")

        # 2回目の呼び出し (直後なのでAIスキップされるはず)
        self.mock_ai.reset_mock() # カウントリセット
        strategy.run_analysis_cycle("USD_JPY")
        self.assertFalse(self.mock_ai.analyze.called)

    # --- Test Case 2: ロット計算ロジック ---
    def test_execution_lot_calculation(self):
        """残高とレバレッジから正しいロット数が計算されるか"""
        exec_service = ExecutionService(self.mock_broker, self.config)
        
        # 口座状況: 100万円, レート150円
        self.mock_broker.get_account_state.return_value = {"balance": 1000000.0}
        
        # ここもBroker経由での取得を想定して MarketSnapshot を設定
        self.mock_broker.get_market_snapshot.return_value = MarketSnapshot(
            pair="USD_JPY",
            timestamp=datetime.now(timezone.utc),
            bid=150.00,
            ask=150.00,
            swap_long_per_day=0, swap_short_per_day=0
        )
        
        # AI指令: レバレッジ2倍 (つまり200万円分のポジション)
        # 2,000,000 / 150 = 13,333.33... -> 13,000 (1000通貨単位)
        action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=2.0,
            confidence=0.9, risk_level=1, expected_holding_period_days=1, rationale="Test"
        )
        
        # 内部メソッドのテスト
        lots = exec_service._calculate_lot_size(action)
        self.assertEqual(lots, 13000)

    # --- Test Case 3: Kill Switch 発動 ---
    def test_risk_kill_switch(self):
        """維持率が低い時、Kill SwitchがFalseを返すか"""
        risk_manager = RiskManager(self.config)
        
        # 維持率 40% (閾値50%より低い)
        account_state = {"margin_maintain_pct": 0.40}
        is_safe, reason = risk_manager.check_account_health(account_state)
        self.assertFalse(is_safe)
        self.assertIn("CRITICAL", reason)

    # --- Test Case 4: AIレスポンス異常系 ---
    def test_ai_validation_error(self):
        """AIクライアントがエラーを出した場合、落ちずにHOLDへフォールバックするか"""
        
        risk_manager = RiskManager(self.config)
        strategy = StrategyEngine(
            self.mock_market_data, self.mock_news, self.mock_ai, risk_manager, self.config
        )
        
        # AIが例外を吐く設定
        self.mock_ai.analyze.side_effect = Exception("AI API Error")
        
        # 正常に結果が返ることを確認
        decision = strategy.run_analysis_cycle("USD_JPY")
        
        # 検証: アクションはHOLD、理由にエラー内容が含まれているか
        self.assertEqual(decision.action, "HOLD")
        self.assertIn("AI Error Fallback", decision.rationale)
        self.assertIn("AI API Error", decision.rationale)

    # ★追加: Test Case 5: 最大ポジション数の強制 (GPT指摘対応)
    def test_max_positions_per_pair_enforced(self):
        """既に同一ペアのポジションがある場合、新規BUYがHOLDに強制されるか"""
        risk_manager = RiskManager(self.config) # configで max_positions_per_pair=1 になっている
        
        # 1. 既存ポジションがある状態をモック
        existing_position = PositionSummary(
            pair="USD_JPY", side="LONG", amount=10000,
            avg_entry_price=150.0, current_price=150.5,
            unrealized_pnl=5000, leverage=25.0
        )
        positions = [existing_position]
        
        # 2. AIが「さらに買い増し(BUY)」を指示したとする
        ai_action = AiAction(
            action="BUY", target_pair="USD_JPY", suggested_leverage=1.0,
            confidence=0.9, risk_level=1, expected_holding_period_days=1, 
            rationale="AI wants to add more positions"
        )
        
        # 3. RiskManagerで検証
        final_action = risk_manager.validate_action(ai_action, positions)
        
        # 4. 検証: アクションが HOLD に書き換わっていること
        self.assertEqual(final_action.action, "HOLD", "ポジション上限到達時はHOLDになるべき")
        self.assertIn("RISK MANAGER OVERRIDE", final_action.rationale, "理由に[RISK MANAGER OVERRIDE]が含まれるべき")
        self.assertIn("Max positions reached", final_action.rationale)

if __name__ == "__main__":
    unittest.main()