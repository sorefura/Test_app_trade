# run_live_entry_test.py
import yaml
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.adapters.gmo_broker import GmoBrokerClient
from src.models import AiAction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveEntryTest")

def main():
    # 設定読み込み
    with open("config/settings.yaml", "r", encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open("config/secrets.yaml", "r", encoding='utf-8') as f:
        secrets = yaml.safe_load(f)
        
    # 通貨ペアとロット数を設定から取得（なければデフォルト）
    target_pair = config.get("target_pairs", ["MXN_JPY"])[0]
    min_lot = config.get("min_lot_unit", 10000)

    print(f"!!! CAUTION: This script will place a REAL ORDER !!!")
    print(f"Target: {target_pair}, Units: {min_lot}")
    confirm = input("Type 'yes' to proceed: ")
    if confirm != "yes":
        print("Aborted.")
        return

    # 強制Liveモード
    config["enable_live_trading"] = True
    
    client = GmoBrokerClient(config, secrets)
    
    action = AiAction(
        action="BUY",
        target_pair=target_pair,  # <--- 自動取得したペア
        suggested_leverage=1.0,
        confidence=1.0,
        risk_level=1,
        expected_holding_period_days=0,
        rationale="Manual Live Test Entry",
        units=min_lot             # <--- 設定値を使用
    )

    try:
        print("\nSending Order...")
        res = client.place_order(action)
        print(f"Result: {res}")
        print("\nCheck your GMO Coin App/Web to confirm the position.")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    main()