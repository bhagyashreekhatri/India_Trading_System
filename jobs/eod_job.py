"""
EOD Learning Job.
Runs automatically after market close (15:30 IST).
Writes all today's closed trade outcomes to ChromaDB
so the Scoring Agent can learn from them over time.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from memory.trade_state import TradeStateManager
from memory.chroma_client import ChromaMemory
from config.settings import TIMEZONE

IST = ZoneInfo(TIMEZONE)


def run_eod_job():
    """
    Main EOD job. Call this after market close.
    1. Gets all trades closed today
    2. Writes each outcome to ChromaDB signal_patterns
    3. Writes regime snapshot for today
    4. Prints summary report
    """
    state  = TradeStateManager()
    chroma = ChromaMemory()

    now   = datetime.now(IST)
    today = now.date().isoformat()

    print(f"\n{'='*55}")
    print(f"  EOD Learning Job — {today}")
    print(f"{'='*55}\n")

    # ── 1. Get today's closed trades ──────────────────────────────────────────
    today_trades = state.get_today_trades()
    closed = [t for t in today_trades if t.status != "open"]

    if not closed:
        print("No closed trades today — nothing to store.")
        return

    print(f"Processing {len(closed)} closed trades...\n")

    # ── 2. Store each outcome in ChromaDB ─────────────────────────────────────
    stored = 0
    for trade in closed:
        try:
            outcome = (
                "hit_target" if trade.status == "closed_win"
                else "hit_sl"  if trade.status == "closed_loss"
                else "expired"
            )

            # We need regime — try to get from trade reason string
            regime = _extract_regime(trade.reason)

            chroma.store_signal_outcome(
                symbol=trade.symbol,
                setup_type=trade.setup_type,
                regime=regime,
                score=trade.score,
                grade=trade.grade,
                entry=trade.entry_price,
                sl=trade.stop_loss,
                target=trade.target_price,
                outcome=outcome,
                pnl_r=trade.pnl_r or 0.0,
            )
            stored += 1
            print(
                f"  ✓ {trade.symbol:12} {trade.setup_type:20} "
                f"{trade.grade:4} {outcome:12} {trade.pnl_r:+.1f}R"
            )
        except Exception as e:
            print(f"  ✗ {trade.symbol} — {e}")

    # ── 3. Print EOD summary ──────────────────────────────────────────────────
    summary = state.get_summary()
    wins    = [t for t in closed if t.status == "closed_win"]
    losses  = [t for t in closed if t.status == "closed_loss"]
    today_pnl = state.get_today_pnl()

    print(f"\n{'─'*55}")
    print(f"  Today's results:")
    print(f"  Trades:    {len(closed)}")
    print(f"  Wins:      {len(wins)}")
    print(f"  Losses:    {len(losses)}")
    print(f"  Win rate:  {len(wins)/len(closed)*100:.1f}%")
    print(f"  P&L:       ₹{today_pnl:+,.0f}")
    avg_r = sum(t.pnl_r for t in closed if t.pnl_r) / len(closed)
    print(f"  Avg R:     {avg_r:+.2f}R")
    print(f"\n  Stored {stored}/{len(closed)} outcomes in ChromaDB")
    print(f"{'─'*55}")

    # ── 4. Win rate by setup (for manual review) ──────────────────────────────
    by_setup = state.get_win_rate_by_setup()
    if by_setup:
        print(f"\n  Win rate by setup type (all time):")
        for setup, stats in sorted(by_setup.items(), key=lambda x: x[1]["win_rate"], reverse=True):
            bar = "█" * int(stats["win_rate"] / 10)
            print(f"  {setup:22} {bar:10} {stats['win_rate']:5.1f}% ({stats['total']} trades, avg {stats['avg_r']:+.2f}R)")

    print(f"\n{'='*55}")
    print(f"  EOD job complete. System will learn from today.")
    print(f"{'='*55}\n")


def _extract_regime(reason: str) -> str:
    """Try to extract regime label from trade reason string."""
    if not reason:
        return "unknown"
    reason_lower = reason.lower()
    for regime in ["trending", "recovering", "choppy", "event"]:
        if regime in reason_lower:
            return regime
    return "unknown"


if __name__ == "__main__":
    run_eod_job()
