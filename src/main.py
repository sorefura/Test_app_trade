# src/main.py
import time
import logging
import os
import sys
import yaml
from typing import Dict, Any, List
from dotenv import load_dotenv

from src.adapters.offline_broker import OfflineBrokerClient
from src.adapters.gmo_broker import GmoBrokerClient
from src.adapters.mock_news import MockNewsClient
from src.adapters.tavily_news import TavilyNewsClient
from src.market_data import MarketDataFetcher
from src.ai_client import GPTClient
from src.risk_manager import RiskManager
from src.strategy import StrategyEngine
from src.execution import ExecutionService
from src.notifier import Notifier
from src.models import BrokerResult

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

def load_config(path: str = "config/settings.yaml") -> Dict[str, Any]:
    """
    YAML設定ファイルをロードする。

    Args:
        path (str): 設定ファイルのパス。デフォルトは "config/settings.yaml"。

    Returns:
        Dict[str, Any]: ロードされた設定辞書。

    Raises:
        SystemExit: ファイルが存在しないか、読み込みに失敗した場合にプログラムを終了する。
    """
    if not os.path.exists(path):
        logger.error(f"Config file not found: {path}")
        sys.exit(1)
    
    try:
        with open(path, "r", encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.critical(f"Failed to load config: {e}")
        sys.exit(1)

def main() -> None:
    """
    アプリケーションのメインエントリポイント。
    コンポーネントの初期化、依存性の注入、およびメイン取引ループの実行を行う。
    """
    logger.info("Starting FX Swap Bot System...")
    load_dotenv()
    
    # APIキー確認
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.critical("OPENAI_API_KEY not found in env!")
        sys.exit(1)

    notifier = Notifier()

    # 設定ロード
    config = load_config()
    
    # Secretsロード
    secrets_path = "config/secrets.yaml"
    secrets: Dict[str, Any] = {}
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding='utf-8') as f:
            secrets = yaml.safe_load(f)
    else:
        logger.warning("secrets.yaml not found. Private API calls may fail.")

    # --- Dependency Injection ---
    
    # 1. Broker の初期化
    broker_type = config.get("broker_type", "offline")
    
    if broker_type == "gmo":
        logger.info("Initializing GMO Coin Broker...")
        if not secrets.get("gmo", {}).get("api_key"):
            logger.critical("GMO API Key not found in secrets.yaml!")
            sys.exit(1)
        broker = GmoBrokerClient(config, secrets)
        
    else:
        logger.info("Initializing Offline Broker (Mock Mode)...")
        broker = OfflineBrokerClient(config)
    
    # 2. Data Sources の初期化
    market_data = MarketDataFetcher(broker)

    # ニュースクライアントの初期化
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        logger.info("Initializing Tavily News Client (Web Search Enabled)...")
        news_client = TavilyNewsClient()
    else:
        logger.warning("TAVILY_API_KEY not found. Using Mock News.")
        news_client = MockNewsClient()
    
    # 3. AI Client の初期化
    ai_client = GPTClient(api_key=openai_api_key)
    
    # 4. Logic & Safety の初期化
    risk_manager = RiskManager(config)
    strategy = StrategyEngine(market_data, news_client, ai_client, risk_manager, config)
    
    # 5. Execution Service の初期化
    execution = ExecutionService(broker, config)

    logger.info(f"All components initialized. Broker Mode: {broker_type}")
    logger.info("Entering main loop.")

    # ライブ取引時の安全カウントダウン
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
            target_pairs: List[str] = config.get("target_pairs", [])
            if not target_pairs:
                logger.critical("target pair is empty!")
                sys.exit(1)
            
            interval = config.get("interval_seconds", 60)

            for pair in target_pairs:
                try:
                    # 1. 分析と判断
                    decision = strategy.run_analysis_cycle(pair)
                    
                    # 2. 実行
                    result: BrokerResult = execution.execute_action(decision)

                    # 異常検知と緊急停止
                    if result.status == "PARTIAL_FAILURE":
                        msg = f"🚨 EMERGENCY STOP: Partial failure detected for {pair}!"
                        logger.critical(msg)
                        notifier.send(msg, level="CRITICAL")
                        sys.exit(1)
                    
                except Exception as e:
                    logger.error(f"Error in cycle for {pair}: {e}", exc_info=True)
            
            # 待機
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
    