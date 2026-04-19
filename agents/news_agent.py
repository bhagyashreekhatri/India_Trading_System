"""
News Sentiment Agent.
Fetches news and scores sentiment for each signal symbol.
Runs in parallel with Volume RS Agent.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.news_tools import get_news_sentiment, get_batch_news, query_past_news


def create_news_agent() -> Agent:
    return Agent(
        role="Financial News Sentiment Analyst",
        goal=(
            "Find relevant news for each signal stock and score sentiment "
            "using LLM analysis. Flag stocks with strong catalysts or "
            "negative news. Output news_score (0-1) per symbol."
        ),
        backstory=(
            "You are a financial news analyst covering Indian markets. "
            "You read headlines from NewsAPI and score them for their "
            "likely impact on intraday price movement. "
            "You know that earnings beats, buybacks, and positive analyst "
            "upgrades are strong catalysts. You also know that regulatory "
            "actions, fraud investigations, and profit warnings are red flags. "
            "For stocks with no news, you return a neutral score of 0.5. "
            "You never make up news — if there's nothing, say nothing."
        ),
        tools=[get_batch_news, get_news_sentiment, query_past_news],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


NEWS_TASK_TEMPLATE = """
Analyze news sentiment for these signal stocks: {signal_symbols}

Use get_batch_news to fetch all at once for efficiency.
For any stock with interesting news, use get_news_sentiment for deeper analysis.
Use query_past_news to check if there's relevant context from past few days.

For each symbol return:
{{
  "symbol": "HDFCBANK",
  "has_news": true,
  "news_score": 0.85,
  "catalyst_type": "earnings",
  "headline": "HDFC Bank Q3 profit up 18%, beats estimates",
  "sentiment_label": "positive",
  "impact": "Strong earnings beat likely driving today's move"
}}

Scoring guide:
- Strong positive catalyst (earnings beat, buyback): news_score 0.8-1.0
- Mild positive news: 0.6-0.8
- No news / neutral: 0.5
- Mild negative: 0.3-0.4
- Strong negative (fraud, penalty, profit warning): 0.0-0.2 (apply -0.5 penalty flag)

Return results as JSON list.
"""
