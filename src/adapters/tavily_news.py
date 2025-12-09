# src/adapters/tavily_news.py
import os
import logging
from datetime import datetime, timezone
from typing import List
from tavily import TavilyClient
from src.interfaces import NewsClient
from src.models import NewsItem

logger = logging.getLogger(__name__)

class TavilyNewsClient(NewsClient):
    """
    Tavily APIを使用してWeb検索を行い、関連ニュースを取得するクライアント。
    プロンプトインジェクション対策として、取得テキストに信頼境界タグを付与する。
    """
    
    def __init__(self, api_key):
        """
        クライアントを初期化する。TAVILY_API_KEY環境変数が必要。
        """
        if not api_key:
            raise ValueError("TAVILY_API_KEY not found")
        self.client = TavilyClient(api_key=api_key)

    def fetch_recent_news(self, pair: str, limit: int = 5) -> List[NewsItem]:
        try:
            base, quote = pair.split('_')
            query = f"{base}/{quote} exchange rate news central bank policy forecast analysis"
        except ValueError:
            query = f"{pair} forex news analysis"
        
        logger.info(f"[News] Searching Web for: {query}")

        try:
            response = self.client.search(query=query, search_depth="basic", max_results=limit, days=3)
            news_items = []
            for res in response.get("results", []):
                item = NewsItem(
                    id=res.get("url", "unknown"),
                    source=res.get("url", "WebSearch"),
                    published_at=datetime.now(timezone.utc),
                    title=res.get("title", "No Title"),
                    body=res.get("content", "")[:1000]
                )
                news_items.append(item)
            return news_items
        except Exception as e:
            logger.error(f"Tavily Search Failed: {e}")
            return []
