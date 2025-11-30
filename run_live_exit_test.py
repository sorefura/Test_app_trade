# run_live_exit_test.py
import yaml
import logging
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.adapters.gmo_broker import GmoBrokerClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveExitTest")

def main():
    print("!!! CAUTION: This script will CLOSE ALL POSITIONS !!!")
    confirm = input("Type 'yes' to proceed: ")
    if confirm != "yes":
        print("Aborted.")
        return

    with open("config/settings.yaml", "r", encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open("config/secrets.yaml", "r", encoding='utf-8') as f:
        secrets = yaml.safe_load(f)

    target_pair = config.get("target_pairs", ["MXN_JPY"])[0]

    config["enable_live_trading"] = True
    client = GmoBrokerClient(config, secrets)

    try:
        print("\nClosing all positions...")
        res = client.close_position(target_pair)
        print(f"Result: {res}")
        
        # 最終確認
        print("\nVerifying...")
        time.sleep(2)
        positions = client.get_positions()
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