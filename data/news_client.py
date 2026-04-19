"""
NewsAPI client + Groq LLM sentiment scorer.
Fetches Indian market news and scores sentiment per stock.
"""
import os
from datetime import datetime, timedelta
from newsapi import NewsApiClient
from groq import Groq

from config.settings import NEWS_API_KEY, GROQ_API_KEY, GROQ_MODEL
from scoring.engine import NewsData


SENTIMENT_PROMPT = """You are a financial news analyst for Indian stock markets.

Analyze this news headline for the stock {symbol} and return ONLY a JSON object.

Headline: "{headline}"

Return ONLY this JSON (no explanation):
{{
  "sentiment": 0.8,
  "event_type": "earnings",
  "reason": "brief reason in 10 words"
}}

Rules:
- sentiment: 0.0 to 1.0 (0=very negative, 0.5=neutral, 1.0=very positive)
- event_type: one of: earnings, split, buyback, news, regulatory, results, dividend, none
- reason: max 10 words
"""


class NewsClient:

    def __init__(self):
        self._cache: dict = {}     # symbol → NewsData, refreshed every 30 min
        self._newsapi_ok  = False
        self._groq_ok     = False

        try:
            self.newsapi     = NewsApiClient(api_key=NEWS_API_KEY)
            self._newsapi_ok = bool(NEWS_API_KEY)
        except Exception as e:
            print(f"[News] NewsAPI init failed (non-fatal): {e}")
            self.newsapi = None

        try:
            self.groq     = Groq(api_key=GROQ_API_KEY)
            self._groq_ok = bool(GROQ_API_KEY)
        except Exception as e:
            print(f"[News] Groq init failed (non-fatal): {e}")
            self.groq = None

    def _fetch_headlines(self, symbol: str, company_name: str = "") -> list[str]:
        """Fetch recent news headlines for a stock."""
        if not self._newsapi_ok or self.newsapi is None:
            return []
        query = company_name if company_name else symbol
        try:
            response = self.newsapi.get_everything(
                q=f"{query} stock India NSE",
                language="en",
                sort_by="publishedAt",
                from_param=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
                page_size=5,
            )
            articles = response.get("articles", [])
            return [a["title"] for a in articles if a.get("title")]
        except Exception as e:
            print(f"[News] Fetch error for {symbol}: {e}")
            return []

    def _score_sentiment_with_llm(self, symbol: str, headline: str) -> tuple[float, str, str]:
        """
        Use Groq LLM to score sentiment.
        Returns (llm_score, event_type, reason)
        """
        if not self._groq_ok or self.groq is None:
            return 0.5, "news", ""
        import json
        try:
            prompt = SENTIMENT_PROMPT.format(symbol=symbol, headline=headline)
            response = self.groq.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=100,
            )
            content = response.choices[0].message.content.strip()
            # clean up any markdown fences
            content = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
            return (
                float(data.get("sentiment", 0.5)),
                str(data.get("event_type", "news")),
                str(data.get("reason", "")),
            )
        except Exception as e:
            print(f"[News] LLM scoring error: {e}")
            return 0.5, "news", ""

    def get_news_for_symbol(
        self,
        symbol:       str,
        company_name: str = "",
    ) -> NewsData:
        """
        Main method. Returns NewsData for a symbol.
        Uses cache to avoid re-fetching within 30 min.
        """
        cache_key = f"{symbol}_{datetime.now().strftime('%Y%m%d%H')}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        headlines = self._fetch_headlines(symbol, company_name)

        if not headlines:
            result = NewsData(
                symbol=symbol,
                has_news=False,
                sentiment=0.5,
                catalyst_type="none",
                headline="",
                llm_score=0.5,
            )
            self._cache[cache_key] = result
            return result

        # Score the most recent/relevant headline
        best_headline = headlines[0]
        llm_score, event_type, reason = self._score_sentiment_with_llm(symbol, best_headline)

        # Simple rule-based sentiment as fallback check
        negative_keywords = ["loss", "fraud", "penalty", "fine", "probe", "decline", "fall"]
        positive_keywords = ["profit", "beat", "growth", "surge", "record", "win", "strong"]

        headline_lower = best_headline.lower()
        rule_sentiment = 0.5
        if any(k in headline_lower for k in positive_keywords):
            rule_sentiment = 0.75
        elif any(k in headline_lower for k in negative_keywords):
            rule_sentiment = 0.25

        # Blend LLM score with rule-based (LLM gets 80% weight)
        final_score = (llm_score * 0.8) + (rule_sentiment * 0.2)

        result = NewsData(
            symbol=symbol,
            has_news=True,
            sentiment=final_score,
            catalyst_type=event_type,
            headline=best_headline,
            llm_score=round(final_score, 3),
        )
        self._cache[cache_key] = result
        return result

    def get_news_batch(self, symbols: list[str]) -> dict[str, NewsData]:
        """Fetch news for multiple symbols. Returns dict symbol → NewsData."""
        results = {}
        for symbol in symbols:
            results[symbol] = self.get_news_for_symbol(symbol)
        return results
