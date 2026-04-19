"""
Position Manager Agent.
Monitors every open position every tick and decides: hold, tighten SL, or exit.
"""
from crewai import Agent
from crewai import LLM
from config.settings import GROQ_API_KEY, GROQ_MODEL
from tools.score_tools import get_open_positions, close_position
from tools.kite_tools import get_quotes


def create_position_agent() -> Agent:
    return Agent(
        role="Position Risk Manager",
        goal=(
            "Monitor all open positions every tick. "
            "Exit positions when: target hit, SL hit, thesis broken, "
            "or trade has been stalled for 20+ minutes with no movement. "
            "Never let a winning trade turn into a big loser."
        ),
        backstory=(
            "You are an intraday position manager who watches every open trade "
            "like a hawk. You know that exits determine P&L more than entries. "
            "You have clear rules: if SL is hit, exit immediately — no hoping. "
            "If target is hit, exit and take the profit. "
            "If a trade has been flat for 20+ minutes, it's dead capital — "
            "exit and free it up for better opportunities. "
            "If the setup thesis is broken (e.g. VWAP reclaim trade but "
            "stock closed back below VWAP), exit regardless of P&L. "
            "You never average down, never move SL against the trade."
        ),
        tools=[get_open_positions, close_position, get_quotes],
        verbose=True,
        llm="groq/llama-3.3-70b-versatile",
        allow_delegation=False,
    )


POSITION_TASK_TEMPLATE = """
Review all open positions and decide action for each.

Use get_open_positions to get current state of all open trades with live prices.

For each open position, evaluate:

EXIT CONDITIONS (check in this order):
1. Stop Loss hit: current_price <= stop_loss (for long)
   → close_position with reason "stop_loss_hit"

2. Target hit: current_price >= target_price (for long)
   → close_position with reason "target_hit"

3. Thesis broken — check setup type:
   - vwap_reclaim/vwap_pullback: stock closed back below VWAP
   - momentum_breakout: stock closed back below breakout level
   - recovery_setup: stock gave up all recovery gains
   → close_position with reason "thesis_broken"

4. Stalled trade: position open > 20 min AND pnl_r between -0.2 and +0.2
   → close_position with reason "stalled_no_movement"

5. End of day: time > 15:00 → close all open positions
   → close_position with reason "eod_exit"

HOLD CONDITIONS:
- Trade moving in right direction, not at target yet → HOLD
- Trade recently entered (< 10 min), giving it time → HOLD

For each position return action taken:
{{
  "position_id": 12,
  "symbol": "HDFCBANK",
  "action": "HOLD",
  "current_pnl_r": 0.8,
  "reason": "Moving toward target, pnl_r +0.8R, holding"
}}

OR:

{{
  "position_id": 13,
  "symbol": "WIPRO",
  "action": "CLOSED",
  "exit_reason": "stalled_no_movement",
  "exit_price": 463.2,
  "pnl_r": 0.1,
  "reason": "Open 25 min, no movement, freeing capital"
}}

Return all position actions as JSON list.
"""
