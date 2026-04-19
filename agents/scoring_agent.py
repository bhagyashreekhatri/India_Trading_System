"""
Scoring Agent — the core decision maker.
Combines all agent outputs into a final score, grade, and trade decision.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.score_tools import score_signal, add_to_watchlist
from tools.chroma_tools import query_similar_signals


def create_scoring_agent() -> Agent:
    return Agent(
        role="Trade Signal Quality Scorer",
        goal=(
            "Combine all agent inputs into a final score (0-10) and grade "
            "(A++/A+/A/B/C) for each signal. "
            "Apply regime multipliers. Check historical win rates from ChromaDB. "
            "Output a ranked list of signals ready for the Capital Allocator."
        ),
        backstory=(
            "You are the brain of this trading system. "
            "You receive setup detection, volume validation, market context, "
            "relative strength, and news sentiment data — and you combine them "
            "into a single, explainable score. "
            "You apply regime multipliers correctly: VWAP reclaim in recovering "
            "market gets a 1.4x boost, breakout in choppy market gets 0.6x penalty. "
            "You check ChromaDB for historical win rates on similar setups. "
            "Your output is the single source of truth — if a signal doesn't "
            "score >= 7.0 (grade A or above), it doesn't get traded."
        ),
        tools=[score_signal, query_similar_signals, add_to_watchlist],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


SCORING_TASK_TEMPLATE = """
Score all detected signals using inputs from all previous agents.

Inputs available:
- Detected setups: {setups}
- Volume + RS data: {volume_rs_data}
- Market context (regime): {market_context}
- News data: {news_data}

For EACH signal:
1. Use query_similar_signals to check historical win rate for this setup+regime combo
2. Use score_signal with ALL the data combined to get final score

Score each signal using score_signal tool with these parameters assembled from inputs above.

After scoring:
- Grade A++ (>=9.0): Include in final output — enter immediately
- Grade A+  (>=8.0): Include in final output — enter full size
- Grade A   (>=7.0): Include in final output — enter standard size
- Grade B   (5-7):   Use add_to_watchlist — half size only if capital idle
- Grade C   (<5.0):  Discard completely — do not include

Return final scored signals as JSON list, sorted by final_score descending:
[
  {{
    "symbol": "HDFCBANK",
    "setup_type": "vwap_reclaim",
    "final_score": 9.2,
    "grade": "A++",
    "entry_price": 1742.0,
    "stop_loss": 1727.0,
    "target_price": 1764.5,
    "confidence": 0.88,
    "breakdown": {{
      "setup_quality": 2.8,
      "volume_strength": 1.8,
      "market_alignment": 2.0,
      "relative_strength": 1.5,
      "news_sentiment": 1.0,
      "raw_score": 9.1,
      "regime_multiplier": 1.4
    }},
    "reason": "VWAP reclaim on HDFCBANK | recovering regime | strong volume | positive earnings",
    "historical_winrate": 72.0
  }}
]

Only return signals with grade A++ / A+ / A.
B-grade signals go to watchlist via add_to_watchlist tool.
C-grade signals are discarded silently.
"""
