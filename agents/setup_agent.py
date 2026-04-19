"""
Setup Detection Agent.
Detects intraday setups on active stocks.
Runs in parallel with Regime Detector Agent.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.pattern_tools import detect_setup, scan_all_setups
from tools.kite_tools import get_vwap, get_candles


def create_setup_agent() -> Agent:
    return Agent(
        role="Intraday Setup Pattern Detector",
        goal=(
            "Scan all active stocks and detect valid intraday trading setups. "
            "Return only setups with strong candle quality — no wick breakouts, "
            "no weak closes. Quality over quantity."
        ),
        backstory=(
            "You are a technical analyst specialising in intraday setups for NSE. "
            "You have studied thousands of intraday charts and know exactly what "
            "a high-quality breakout candle looks like vs a fake one. "
            "You detect 6 setup types: momentum breakout, VWAP reclaim, "
            "VWAP pullback, failed breakdown, range breakout, recovery setup. "
            "You only flag a setup when the candle body ratio is strong and "
            "the close is in the right position. You never flag wick breakouts."
        ),
        tools=[scan_all_setups, detect_setup, get_vwap, get_candles],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


SETUP_TASK_TEMPLATE = """
Scan these active stocks for intraday trading setups: {active_symbols}

Use scan_all_setups to detect setups across all stocks at once.
For any stock where you want more detail, use detect_setup individually.

Only include setups where:
- candle_body_ratio >= 0.4 (reject wick breakouts)
- candle_quality >= 0.5 (close must be in right position)
- A clear entry, stop loss, and target can be defined

Return a JSON list of detected setups:
[
  {{
    "symbol": "HDFCBANK",
    "setup_type": "vwap_reclaim",
    "direction": "long",
    "entry_price": 1742.0,
    "stop_loss": 1727.0,
    "target_price": 1764.5,
    "current_price": 1743.0,
    "candle_body_ratio": 0.75,
    "close_position": 0.85,
    "candle_quality": 0.80,
    "sector": "BANKING",
    "reason": "Reclaimed VWAP 1738 with strong body candle after being below 35 min"
  }},
  ...
]

If no valid setups found, return empty list [].
Do NOT force setups — only return genuinely valid ones.
"""
