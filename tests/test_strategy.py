# test_strategy.py
import os
import logging
from dotenv import load_dotenv

from src.adapters.offline_broker import OfflineBrokerClient
from src.adapters.mock_news import MockNewsClient
from src.market_data import MarketDataFetcher
from src.ai_client import GPTClient
from src.risk_manager import RiskManager
from src.strategy import StrategyEngine

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    
    # 1. コンポーネントの初期化 (Dependency Injection)
    config = {
        "max_leverage": 25, 
        "vix_threshold": 20,
        "kill_switch_margin_pct": 0.4 
    }
    
    # Broker & DataFetcher
    broker = OfflineBrokerClient(config)
    market_data = MarketDataFetcher(broker)
    
    # News
    news = MockNewsClient()
    
    # AI
    ai = GPTClient(api_key=api_key)
    
    # Risk Manager
    risk = RiskManager(config)
    
    # 2. StrategyEngine の起動
    engine = StrategyEngine(
        market_data=market_data,
        news_client=news,
        ai_client=ai,
        risk_manager=risk,
        config=config
    )
    
    # 3. 分析サイクルの実行
    print("\n--- Running Strategy Cycle ---")
    try:
        decision = engine.run_analysis_cycle("USD_JPY")
        
        print("\n[Strategy Output]")
        print(f"Action: {decision.action}")
        print(f"Rationale: {decision.rationale}")
        print(f"Confidence: {decision.confidence}")
        
    except Exception as e:
        print(f"Strategy Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
    