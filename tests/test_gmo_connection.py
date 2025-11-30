import yaml
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.gmo_broker import GmoBrokerClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestGMO")

def main():
    print("--- GMO Coin (FX) Connection Test ---")
    
    secrets_path = "config/secrets.yaml"
    if not os.path.exists(secrets_path):
        print(f"Error: {secrets_path} not found.")
        return

    try:
        with open(secrets_path, "r", encoding='utf-8') as f:
            secrets = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading secrets.yaml: {e}")
        return

    gmo_conf = secrets.get("gmo", {})
    has_keys = bool(gmo_conf.get("api_key") and gmo_conf.get("api_secret"))
    
    if not has_keys:
        print("Warning: GMO API Key/Secret not found in secrets.yaml.")
        print("         Only Public API (Ticker) will be tested.")

    client = GmoBrokerClient(config={}, secrets=secrets)

    try:
        print("\n[1] Testing Public API (Ticker: USD_JPY)...")
        snapshot = client.get_market_snapshot("USD_JPY")
        print(f"   Success! Bid: {snapshot.bid}, Ask: {snapshot.ask}")
    except Exception as e:
        print(f"   [FAILED] Public API Error: {e}")

    if has_keys:
        try:
            print("\n[2] Testing Private API (Account Assets)...")
            account = client.get_account_state()
            print(f"   Success! Balance (Equity): {account.get('balance')}, Margin Ratio: {account.get('margin_maintain_pct')}")

            print("\n[3] Testing Private API (Position Summary)...")
            positions = client.get_positions()
            print(f"   Success! Positions Count: {len(positions)}")
            for p in positions:
                print(f"    - {p.side} {p.amount} units, PnL: {p.unrealized_pnl}")

        except Exception as e:
            print(f"   [FAILED] Private API Error: {e}")
    else:
        print("\n[2] Skipping Private API tests (No keys).")

if __name__ == "__main__":
    main()