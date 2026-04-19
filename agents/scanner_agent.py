"""
Market Scanner Agent.
Scans 100 NSE stocks and filters to top 60 most active for the session.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.kite_tools import get_quotes, get_volume_ratio
from config.universe import FULL_UNIVERSE, get_sector


def create_scanner_agent() -> Agent:
    return Agent(
        role="NSE Market Scanner",
        goal=(
            "Scan all NSE stocks every tick and return the top 60 most active "
            "stocks based on volume spike, price movement, and liquidity. "
            "Only pass stocks worth analyzing to the next agents."
        ),
        backstory=(
            "You are an expert market scanner for NSE India. "
            "You've been filtering stocks for intraday trading for years. "
            "You know that 80% of stocks are dead on any given day — "
            "your job is to find the 20% that are actually moving with volume. "
            "You never pass illiquid or low-volume stocks to the downstream agents."
        ),
        tools=[get_quotes, get_volume_ratio],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


SCANNER_TASK_TEMPLATE = """
Scan the NSE stock universe and identify the top 60 most active stocks.

Full universe to scan: {symbols}

For each stock use get_quotes to get: last_price, volume, change_pct
Then use get_volume_ratio to get volume strength.

Filter and rank by:
1. Volume ratio >= 1.2 (minimum — reject anything below)
2. Absolute price change >= 0.3% (stock must be moving)
3. Price > 50 (avoid penny stocks)

Return the TOP 60 stocks as a JSON list with this structure:
[
  {{
    "symbol": "HDFCBANK",
    "last_price": 1742.5,
    "change_pct": 0.85,
    "volume_ratio": 2.1,
    "sector": "BANKING",
    "activity_score": 3.1
  }},
  ...
]

Sort by activity_score (change_pct + volume_ratio combined).
Do NOT include stocks with volume_ratio < 1.2 or change_pct < 0.3%.
"""
