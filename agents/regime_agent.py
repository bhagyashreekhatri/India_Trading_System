"""
Regime Detector Agent.
Classifies current market as TRENDING / CHOPPY / RECOVERING / EVENT.
Runs in parallel with Setup Detection Agent.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.kite_tools import get_nifty_data, get_vwap, get_candles
from tools.chroma_tools import get_regime_history


def create_regime_agent() -> Agent:
    return Agent(
        role="Market Regime Analyst",
        goal=(
            "Classify the current market session as TRENDING, CHOPPY, "
            "RECOVERING, or EVENT. Output the regime and the multiplier map "
            "that the Scoring Agent will use."
        ),
        backstory=(
            "You are a market microstructure expert who reads market regimes "
            "with precision. You understand that the same setup that works "
            "perfectly in a trending market fails in a choppy one. "
            "You look at Nifty's relationship with VWAP, breadth of advancing "
            "stocks, and volume pattern to classify the session. "
            "Your regime classification is the single most important context "
            "signal for the entire scoring system."
        ),
        tools=[get_nifty_data, get_vwap, get_candles, get_regime_history],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


REGIME_TASK_TEMPLATE = """
Analyze the current market and classify the regime.

Steps:
1. Use get_nifty_data to get Nifty and BankNifty current price, change%, and VWAP position
2. Use get_candles for NIFTY 50 (interval=5minute, days=1) to see today's price action
3. Count how many candles Nifty has been above vs below VWAP today

Classification rules:
- TRENDING:   Nifty above VWAP > 60% of candles, clear directional move, change > 0.4%
- CHOPPY:     Nifty crossing VWAP frequently (>3 times), range-bound, no clear direction
- RECOVERING: Nifty was below VWAP for 30+ min then reclaimed with strong candle
- EVENT:      Expiry day (Thursday) OR major news expected OR Nifty change > 1.5% at open

Return a JSON object:
{{
  "regime": "recovering",
  "confidence": 0.85,
  "nifty_above_vwap": true,
  "banknifty_above_vwap": true,
  "nifty_vwap_minutes": 25,
  "market_trend_aligned": true,
  "breadth_score": 0.65,
  "regime_reason": "Nifty was below VWAP for 40 min, reclaimed with strong candle and volume at 10:45",
  "best_setups_for_regime": ["vwap_reclaim", "recovery_setup"],
  "avoid_setups": ["momentum_breakout", "range_breakout"]
}}

Be precise. The regime drives all scoring multipliers.
"""
