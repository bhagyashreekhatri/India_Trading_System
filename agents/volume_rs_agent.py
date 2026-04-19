"""
Volume + Relative Strength Agent.
Validates volume confirmation and RS vs index for each signal.
Runs in parallel with News Sentiment Agent.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.volume_tools import analyze_volume, get_relative_strength, batch_volume_rs
from tools.kite_tools import get_spread


def create_volume_rs_agent() -> Agent:
    return Agent(
        role="Volume and Relative Strength Validator",
        goal=(
            "Confirm or reject each raw signal based on volume strength "
            "and relative performance vs Nifty. "
            "Assign volume_score (0-2) and rs_score (0-2) for each signal. "
            "Hard reject any signal with failed liquidity."
        ),
        backstory=(
            "You are a quantitative analyst who specialises in volume analysis "
            "and relative strength for NSE intraday trading. "
            "You know that a setup without volume confirmation is just noise. "
            "You compare every stock's performance to Nifty — "
            "a stock that breaks out while underperforming the index is suspect. "
            "You also check bid-ask spreads to reject illiquid stocks "
            "where slippage would kill the trade."
        ),
        tools=[batch_volume_rs, analyze_volume, get_relative_strength, get_spread],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


VOLUME_RS_TASK_TEMPLATE = """
Validate volume and relative strength for these signals: {signal_symbols}

Use batch_volume_rs to analyze all symbols at once for efficiency.
For any symbol needing more detail, use analyze_volume and get_relative_strength.
Also use get_spread to check liquidity for each symbol.

For each symbol return:
{{
  "symbol": "HDFCBANK",
  "volume_ratio": 2.1,
  "volume_score": 1.5,
  "bid_ask_spread": 0.04,
  "liquidity_pass": true,
  "rs_delta": 0.65,
  "rs_score": 1.5,
  "outperforming": true,
  "validation": "PASS",
  "reason": "Volume 2.1x avg, spread 0.04%, outperforming Nifty by 0.65%"
}}

Hard reject (liquidity_pass=false) if:
- volume_ratio < 1.2
- bid_ask_spread > 0.15%

Return results as JSON list sorted by (volume_score + rs_score) descending.
"""
