# src/adapters/mock_news.py
from datetime import datetime, timezone
from src.interfaces import NewsClient
from src.models import NewsItem

class MockNewsClient(NewsClient):
    """テスト用のダミーニュースクライアント"""
    def fetch_recent_news(self, pair: str, limit: int = 20) -> list[NewsItem]:
        return [
            NewsItem(
                id="mock_1",
                source="MockReuters",
                published_at=datetime.now(timezone.utc),
                title="USD/JPY Stable",
                body="Market is waiting for next FOMC meeting."
            )
        ]
    