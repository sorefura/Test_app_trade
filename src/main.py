import time
import logging
import os
import sys
import yaml
from dotenv import load_dotenv

from src.adapters.offline_broker import OfflineBrokerClient
from src.adapters.gmo_broker import GmoBrokerClient
from src.adapters.mock_news import MockNewsClient
from src.adapters.tavily_news import TavilyNewsClient # ★追加
from src.market_data import MarketDataFetcher
from src.ai_client import GPTClient
from src.risk_manager import RiskManager
from src.strategy import StrategyEngine
from src.execution import ExecutionService
from src.notifier import Notifier # ★追加

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trade_log.txt", encoding='utf-8')
    ]
)
logger = logging.getLogger("Main")

def load_config(path="config/settings.yaml"):
    """YAML設定ファイルのロード"""
    if not os.path.exists(path):
        logger.error(f"Config file not found: {path}")
        sys.exit(1)
    
    try:
        with open(path, "r", encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Failed to load config: {e}")
        sys.exit(1)

def main():
    logger.info("Starting FX Swap Bot System...")
    load_dotenv()
    
    # APIキー確認 (OpenAI)
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.critical("OPENAI_API_KEY not found in env!")
        sys.exit(1)

    notifier = Notifier()

    # 設定ロード
    config = load_config()
    
    # Secretsロード (Broker用)
    secrets_path = "config/secrets.yaml"
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding='utf-8') as f:
            secrets = yaml.safe_load(f)
    else:
        secrets = {}
        logger.warning("secrets.yaml not found. Private API calls may fail.")

    # --- Dependency Injection (依存性の注入) ---
    
    # 1. Broker の切り替え
    broker_type = config.get("broker_type", "offline")
    
    if broker_type == "gmo":
        logger.info("Initializing GMO Coin Broker...")
        # GMOキーチェック
        if not secrets.get("gmo", {}).get("api_key"):
            logger.critical("GMO API Key not found in secrets.yaml!")
            sys.exit(1)
        broker = GmoBrokerClient(config, secrets)
        
    else:
        logger.info("Initializing Offline Broker (Mock Mode)...")
        broker = OfflineBrokerClient(config)
    
    # 2. Data Sources
    market_data = MarketDataFetcher(broker)

    # ★変更: ニュースクライアントの切り替え
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        logger.info("Initializing Tavily News Client (Web Search Enabled)...")
        news_client = TavilyNewsClient()
    else:
        logger.warning("TAVILY_API_KEY not found. Using Mock News.")
        news_client = MockNewsClient()
    
    # 3. AI Brain
    # 開発用: gpt-4o-mini / 本番用: gpt-4o など切り替え推奨
    # 今回はデフォルト(gpt-4o-mini)またはコード内の指定に従う
    ai_client = GPTClient(api_key=openai_api_key)
    
    # 4. Logic & Safety
    risk_manager = RiskManager(config)
    strategy = StrategyEngine(market_data, news_client, ai_client, risk_manager, config)
    
    # 5. Execution
    execution = ExecutionService(broker, config)

    logger.info(f"All components initialized. Broker Mode: {broker_type}")
    logger.info("Entering main loop.")

    # ★追加: 起動カウントダウン (P0-1)
    if config.get("enable_live_trading", False):
        logger.warning("⚠️  LIVE TRADING IS ENABLED!  ⚠️")
        print("Starting in 5 seconds. Press Ctrl+C to ABORT.")
        for i in range(5, 0, -1):
            print(f"{i}...", end=" ", flush=True)
            time.sleep(1)
        print("START!")
        notifier.send("🤖 FX Bot Started (Live Mode)", level="INFO")
    else:
        logger.info("Running in MOCK/DRY-RUN mode.")

    # --- Main Loop ---
    try:
        while True:
            target_pairs = config.get("target_pairs", ["MXN_JPY"])
            interval = config.get("interval_seconds", 60)

            for pair in target_pairs:
                try:
                    # 1. 分析と判断
                    decision = strategy.run_analysis_cycle(pair)
                    
                    # 2. 実行
                    result = execution.execute_action(decision)

                    # ★追加: 異常時停止＋通知 (P0-3)
                    if result and isinstance(result, dict):
                        status = result.get("status", "")
                        if "PARTIAL_FAILURE" in status:
                            msg = f"🚨 EMERGENCY STOP: Partial failure detected for {pair}!"
                            logger.critical(msg)
                            notifier.send(msg, level="CRITICAL")
                            sys.exit(1)
                    
                except Exception as e:
                    logger.error(f"Error in cycle for {pair}: {e}", exc_info=True)
            
            # 次のサイクルまで待機
            logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        msg = f"Critical System Error: {e}"
        logger.critical(msg, exc_info=True)
        notifier.send(msg, level="CRITICAL")

if __name__ == "__main__":
    main()
    