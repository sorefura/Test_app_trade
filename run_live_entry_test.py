# run_live_entry_test.py
import yaml
import logging
import sys
import os
import uuid
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.adapters.gmo_broker import GmoBrokerClient
from src.execution import ExecutionService
from src.models import AiAction

# ログ設定: 標準出力のみ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveEntryTest")

def main() -> None:
    """
    ExecutionService経由で単発のBUY注文を実行し、監査ログの生成を確認するスクリプト。
    """
    if not os.path.exists("config/settings.yaml") or not os.path.exists("config/secrets.yaml"):
        logger.error("Config or Secrets file missing.")
        return

    with open("config/settings.yaml", "r", encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open("config/secrets.yaml", "r", encoding='utf-8') as f:
        secrets = yaml.safe_load(f)
        
    target_pair = config.get("target_pairs", ["MXN_JPY"])[0]
    min_lot = config.get("min_lot_unit", 1000)

    print("!!! CAUTION: This script will place a REAL ORDER !!!")
    print(f"Target: {target_pair}, Units: {min_lot}")
    print("Pre-requisite: 'LIVE_TRADING_ARMED=YES' env var must be set.")
    
    confirm = input("Type 'yes' to proceed: ")
    if confirm != "yes":
        print("Aborted.")
        return

    config["enable_live_trading"] = True
    
    try:
        broker = GmoBrokerClient(config, secrets)
    except Exception as e:
        logger.error(f"Failed to init Broker: {e}")
        return

    execution = ExecutionService(broker, config)
    
    req_id = f"test-entry-{uuid.uuid4()}"
    
    # テスト用: 明示的に units を指定してロット計算をバイパスする
    test_units = float(min_lot)

    action = AiAction(
        action="BUY",
        target_pair=target_pair,
        suggested_leverage=1.0, # 計算ロジックはバイパスされるため影響しないが、低めにしておく
        confidence=1.0,
        risk_level=1,
        expected_holding_period_days=0,
        rationale="Manual Live Test Entry via ExecutionService",
        units=test_units, # ★ここで強制指定
        request_id=req_id
    )

    try:
        print("\n--- Sending Order via ExecutionService ---")
        result = execution.execute_action(action)
        
        print("\n[Result Summary]")
        print(f"Status    : {result.status}")
        print(f"Order ID  : {result.order_id}")
        print(f"Request ID: {result.request_id}")
        print(f"Details   : {result.details}")
        
        if result.status == "EXECUTED":
            print("\nSUCCESS: Order placed. Check 'execution_audit.jsonl' for the log record.")
        elif result.status == "DRY_RUN_NOT_SENT":
            print("\nWARNING: Order blocked (Dry-Run). Check env var 'LIVE_TRADING_ARMED'.")
        else:
            print(f"\nFAILED: {result.status}")

    except Exception as e:
        logger.error(f"Execution Failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()