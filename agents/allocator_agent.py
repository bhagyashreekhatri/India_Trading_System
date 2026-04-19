"""
Capital Allocator Agent.
Decides which signals to enter, at what size, enforcing all risk rules.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.score_tools import can_enter_trade, open_position, add_to_watchlist


def create_allocator_agent() -> Agent:
    return Agent(
        role="Capital Allocation and Risk Manager",
        goal=(
            "For each scored signal, check if we can enter (capital available, "
            "sector cap, cooldown, max positions), calculate position size, "
            "and place the order. Watchlist signals when capital is full. "
            "Never force trades — only enter when ALL conditions are met."
        ),
        backstory=(
            "You are a risk manager who ensures the trading system never "
            "overexposures itself. You enforce strict rules: max 5 positions, "
            "max 30% in one sector, 1% risk per trade, 30-min cooldown. "
            "When a great signal comes but capital is full, you compare it "
            "to the weakest open position — if the new signal scores significantly "
            "higher, you note it for the Position Manager to consider rotating. "
            "You never chase — if price has moved more than 0.7% from the "
            "signal entry, you skip it because the R:R is broken."
        ),
        tools=[can_enter_trade, open_position, add_to_watchlist],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


ALLOCATOR_TASK_TEMPLATE = """
Process these scored signals and decide entry/skip/watchlist for each: {scored_signals}

For each signal (highest score first):

1. Use can_enter_trade with symbol, sector, entry_price, stop_loss
   - If returns can_enter=false: use add_to_watchlist and note the reason
   - If returns can_enter=true: proceed to step 2

2. Check proximity: if current_price > entry_price * 1.007 → skip (R:R broken)

3. Use open_position to enter the trade with full details

4. Also check watchlist from previous scans:
   - If a watchlisted signal now has a score improvement → enter it
   - If a watchlisted signal's price ran away → remove from watchlist

For each signal return the action taken:
{{
  "symbol": "HDFCBANK",
  "action": "ENTERED",  
  "reason": "A++ grade, capital available, sector under 30%, within proximity",
  "quantity": 57,
  "entry_price": 1742.0,
  "position_id": 12
}}

OR:

{{
  "symbol": "ICICIBANK",
  "action": "WATCHLISTED",
  "reason": "A+ grade but max positions (5) reached",
  "score": 8.3
}}

OR:

{{
  "symbol": "AXISBANK",
  "action": "SKIPPED",
  "reason": "Price ran 0.9% from signal entry — R:R broken"
}}

Return all actions as JSON list.
Current capital status will be in the can_enter_trade response.
"""
