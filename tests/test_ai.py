# test_ai.py
import os
import uuid
from datetime import datetime, timezone
from src.ai_client import GPTClient
from src.models import (
    AiInputPayload, MarketSnapshot, RiskEnvironment, 
    PositionSummary, NewsItem
)
from dotenv import load_dotenv

# .env から API KEY を読み込む (作成していない場合は環境変数にセットしてください)
load_dotenv()

def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: Please set OPENAI_API_KEY in .env or environment variables.")
        return

    # 1. クライアント初期化
    # 注意: "gpt-5.1" がまだ使えない場合は "gpt-4o" 等が使われます
    client = GPTClient(api_key=api_key, model_name="gpt-4o-2024-08-06")

    # 2. ダミー入力データの作成
    payload = AiInputPayload(
        request_id=str(uuid.uuid4()),
        generated_at=datetime.now(timezone.utc),
        market=MarketSnapshot(
            pair="USD_JPY",
            timestamp=datetime.now(timezone.utc),
            bid=150.10,
            ask=150.15,
            swap_long_per_day=210.0,
            swap_short_per_day=-230.0,
            realized_vol_24h=0.05
        ),
        risk_env=RiskEnvironment(
            vix_index=18.5,
            risk_off_flag=False
        ),
        positions=[
            PositionSummary(
                pair="USD_JPY",
                side="LONG",
                amount=10000,
                avg_entry_price=148.50,
                current_price=150.10,
                unrealized_pnl=16000.0,
                leverage=2.5
            )
        ],
        news=[
            NewsItem(
                id="news_01",
                source="DummyNews",
                published_at=datetime.now(timezone.utc),
                title="Bank of Japan maintains current interest rates.",
                body="BOJ Governor stated that easy monetary policy will continue for the time being."
            )
        ]
    )

    # 3. 実行
    print("--- Sending Request to AI ---")
    try:
        response = client.analyze(payload)
        
        print("\n[AI Decision Result]")
        print(f"Action: {response.decision.action}")
        print(f"Confidence: {response.decision.confidence}")
        print(f"Reason: {response.decision.rationale}")
        print(f"Risk Level: {response.decision.risk_level}")
        
    except Exception as e:
        print(f"Error: {e}")
    return

if __name__ == "__main__":
    main()