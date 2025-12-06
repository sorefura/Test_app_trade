# run_live_exit_test.py
import yaml
import logging
import sys
import os
import time
import uuid

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.adapters.gmo_broker import GmoBrokerClient
from src.execution import ExecutionService
from src.models import AiAction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveExitTest")

def main() -> None:
    """
    ExecutionService経由で全決済(EXIT)を実行し、監査ログの生成を確認するスクリプト。
    """
    if not os.path.exists("config/settings.yaml") or not os.path.exists("config/secrets.yaml"):
        logger.error("Config or Secrets file missing.")
        return

    with open("config/settings.yaml", "r", encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open("config/secrets.yaml", "r", encoding='utf-8') as f:
        secrets = yaml.safe_load(f)

    target_pair = config.get("target_pairs", ["MXN_JPY"])[0]

    print("!!! CAUTION: This script will CLOSE ALL POSITIONS !!!")
    print(f"Target: {target_pair}")
    confirm = input("Type 'yes' to proceed: ")
    if confirm != "yes":
        print("Aborted.")
        return

    config["enable_live_trading"] = True
    
    try:
        broker = GmoBrokerClient(config, secrets)
        execution = ExecutionService(broker, config)
        
        # EXITアクションの生成
        action = AiAction(
            action="EXIT",
            target_pair=target_pair,
            suggested_leverage=0.0,
            confidence=1.0,
            risk_level=1,
            expected_holding_period_days=0,
            rationale="Manual Live Test EXIT via ExecutionService",
            units=None # None = 全決済
        )

        print("\n--- Executing EXIT via ExecutionService ---")
        result = execution.execute_action(action)
        
        print("\n[Result Summary]")
        print(f"Status    : {result.status}")
        print(f"Request ID: {result.request_id}")
        print(f"Details   : {result.details}")
        
        # 最終確認 (Broker直接)
        print("\nVerifying positions via Broker...")
        time.sleep(2)
        positions = broker.get_positions()
        if len(positions) == 0:
            print("SUCCESS: No positions remaining.")
        else:
            print(f"WARNING: {len(positions)} positions still remain!")
            for p in positions:
                print(f" - {p.amount} units")

    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    main()