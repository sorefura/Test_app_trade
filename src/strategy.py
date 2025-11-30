# src/strategy.py

import logging
import uuid
import time
from datetime import datetime, timezone

from src.interfaces import MarketDataProvider, NewsClient
from src.ai_client import GPTClient
from src.risk_manager import RiskManager
from src.models import AiInputPayload, AiAction, RiskEnvironment

logger = logging.getLogger(__name__)

class StrategyEngine:
    def __init__(self, market_data: MarketDataProvider, news_client: NewsClient, ai_client: GPTClient, risk_manager: RiskManager, config):
        self.market_data = market_data
        self.news_client = news_client
        self.ai_client = ai_client
        self.risk_manager = risk_manager
        self.config = config
        
        self.vix_threshold = config.get("vix_threshold", 20.0)
        
        self.last_ai_call_time = {} # pair -> timestamp
        self.min_interval_sec = config.get("ai_interval_min", 60) * 60

        models_config = config.get("ai_models", {})
        current_mode = config.get("current_mode", "trade")
        self.target_model = models_config.get(current_mode, "gpt-5-mini")
        
        logger.info(f"StrategyEngine initialized. AI Model Mode: {current_mode} -> {self.target_model}")

    def run_analysis_cycle(self, pair: str) -> AiAction:
        logger.info(f"=== Starting Analysis Cycle for {pair} ===")

        snapshot = self.market_data.fetch_market_snapshot(pair)
        positions = self.market_data.fetch_positions()
        account_state = self.market_data.fetch_account_state()
        current_vix = self.market_data.fetch_vix()
        
        is_safe, reason = self.risk_manager.check_account_health(account_state)
        if not is_safe:
            return self._create_emergency_exit_action(pair, reason)

        is_emergency_market = current_vix > self.vix_threshold
        last_call = self.last_ai_call_time.get(pair, 0)
        time_since_last = time.time() - last_call
        
        if not is_emergency_market and time_since_last < self.min_interval_sec:
            logger.info(f"Skipping AI: Last call was {time_since_last:.1f}s ago (Interval: {self.min_interval_sec}s)")
            return self._create_hold_action(pair, "Skipping AI to save cost (Time Interval)")

        news_list = self.news_client.fetch_recent_news(pair, limit=5)
        payload = AiInputPayload(
            request_id=str(uuid.uuid4()),
            generated_at=datetime.now(timezone.utc),
            market=snapshot,
            risk_env=RiskEnvironment(vix_index=current_vix, risk_off_flag=is_emergency_market),
            positions=positions,
            news=news_list
        )

        try:
            ai_output = self.ai_client.analyze(payload, model=self.target_model)
            decision = ai_output.decision
            
            # ★変更: 成功時のみ更新
            self.last_ai_call_time[pair] = time.time()

        except Exception as e:
            logger.error(f"AI Analysis Failed: {e}. Fallback to HOLD.")
            decision = self._create_hold_action(pair, f"AI Error Fallback: {str(e)}")

        final_decision = self.risk_manager.validate_action(decision, positions)
        
        logger.info(f"Final Decision: {final_decision.action}")
        return final_decision

    def _create_emergency_exit_action(self, pair: str, reason: str) -> AiAction:
        return AiAction(
            action="EXIT", target_pair=pair, suggested_leverage=0.0,
            confidence=1.0, risk_level=10, expected_holding_period_days=0.0,
            rationale=f"EMERGENCY EXIT: {reason}"
        )

    def _create_hold_action(self, pair: str, reason: str) -> AiAction:
        return AiAction(
            action="HOLD", target_pair=pair, suggested_leverage=1.0,
            confidence=0.0, risk_level=1, expected_holding_period_days=0.0,
            rationale=reason
        )