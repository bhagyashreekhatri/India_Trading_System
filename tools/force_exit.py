"""
force_exit.py — Manually close any open position at current market price.

Usage:
    /root/india_trading/venv/bin/python tools/force_exit.py ASIANPAINT
    /root/india_trading/venv/bin/python tools/force_exit.py ALL
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.trade_state import TradeStateManager
from data.kite_client import KiteDataClient

def force_exit(symbol: str = None):
    state = TradeStateManager()
    kite  = KiteDataClient()

    open_pos = state.get_open_positions()
    if not open_pos:
        print("No open positions found.")
        return

    targets = open_pos if symbol == "ALL" else [p for p in open_pos if p.symbol == symbol]
    if not targets:
        print(f"No open position found for {symbol}")
        print(f"Open positions: {[p.symbol for p in open_pos]}")
        return

    # Fetch live prices for all targets
    syms   = [p.symbol for p in targets]
    quotes = kite.get_quotes(syms)

    for p in targets:
        ltp = quotes.get(p.symbol, {}).get("last_price", p.entry_price)
        qty = p.quantity_remaining or p.quantity

        if p.direction == "long":
            trade_pnl = (ltp - p.entry_price) * qty
        else:
            trade_pnl = (p.entry_price - ltp) * qty

        total_pnl = round((p.pnl or 0) + trade_pnl, 2)
        sl_dist   = abs(p.entry_price - (p.initial_sl or p.stop_loss)) or 0.01
        pnl_r     = round(total_pnl / (sl_dist * (p.quantity or 1)), 2)
        status    = "closed_win" if total_pnl > 0 else "closed_loss"

        print(f"\n{'─'*50}")
        print(f"  Symbol   : {p.symbol}")
        print(f"  Entry    : ₹{p.entry_price:.2f}")
        print(f"  LTP now  : ₹{ltp:.2f}")
        print(f"  Qty      : {qty}")
        print(f"  P&L      : ₹{total_pnl:+,.0f} ({pnl_r:+.2f}R)")
        print(f"  Status   : {status}")

        confirm = input(f"\n  Force exit {p.symbol} at ₹{ltp:.2f}? (y/n): ").strip().lower()
        if confirm != "y":
            print(f"  Skipped {p.symbol}")
            continue

        state.close_position(p.id, ltp, total_pnl, pnl_r, status, "manual_exit")
        print(f"  ✅ {p.symbol} closed at ₹{ltp:.2f} | P&L ₹{total_pnl:+,.0f}")

    print(f"\n{'─'*50}")
    print("Done. Refresh the dashboard to see updated positions.")

if __name__ == "__main__":
    sym = sys.argv[1].upper() if len(sys.argv) > 1 else None
    if not sym:
        print("Usage: python tools/force_exit.py SYMBOL")
        print("       python tools/force_exit.py ALL")
        sys.exit(1)
    force_exit(sym)
