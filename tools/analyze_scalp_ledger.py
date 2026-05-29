"""
Scalp-ledger analyzer (2026-05-29) — the instrument that answers the only
question that matters for the scalp path: "is it GREEN after real costs, and is
the runner-capture (Fix #209) actually earning its keep?"

Reads logs/scalp_trades.jsonl (written by TradingCrew._log_scalp). Event shapes:
  entry       : {ts, event:"entry",       symbol, entry, qty, stop, target, atr, rvol, ...}
  tp1_partial : {ts, event:"tp1_partial", symbol, entry, exit, qty, qty_remaining, pnl_inr, ...}
  exit        : {ts, event:"exit",        symbol, entry, exit, qty, reason, pnl_inr, ...}

A TRADE = one entry → optional tp1_partial → one exit, grouped per symbol in
file order (FIFO). Trade P&L sums the partial leg + the final leg.

Costs: the ledger pnl_inr already includes PAPER SLIPPAGE (12/22/8 bps) but NOT
brokerage / STT / statutory charges. We subtract those here so "net" is honest:
  buy  leg : ₹20 brokerage + 0.003% stamp
  sell leg : ₹20 brokerage + ~0.037% (STT 0.025% + exch/GST/SEBI ~0.012%)
A partial trade has 1 buy + 2 sells (tp1 + final) → more brokerage legs, modelled.

Usage:
  python3 tools/analyze_scalp_ledger.py            # all days in the ledger
  python3 tools/analyze_scalp_ledger.py 2026-05-29 # one day
"""
from __future__ import annotations
import os
import sys
import json
from collections import defaultdict, Counter

LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "scalp_trades.jsonl",
)

BROKERAGE_PER_LEG = 20.0      # ₹ flat per order (Zerodha MIS)
SELL_CHARGES_PCT  = 0.00037   # STT 0.025% + exchange/GST/SEBI ~0.012%
BUY_STAMP_PCT     = 0.00003   # stamp 0.003% buy-side


def load_all(path: str | None = None, day: str | None = None) -> list[dict]:
    path = path or LEDGER_PATH
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if day and str(r.get("ts", "")).split("T")[0] != day:
                continue
            out.append(r)
    return out


def group_trades(records: list[dict]) -> list[dict]:
    """Reconstruct trades: entry opens; tp1_partial + exit legs attach P&L.
    Returns a list of {symbol, entry, legs:[...], gross_pnl, ran_runner, final_reason}."""
    open_t: dict[str, dict] = {}
    trades: list[dict] = []
    for r in records:
        sym = r.get("symbol", "")
        ev = r.get("event")
        if ev == "entry":
            # If a prior trade on this symbol never closed, flush it as incomplete.
            open_t[sym] = {
                "symbol": sym, "entry": float(r.get("entry", 0.0)),
                "qty": int(r.get("qty", 0)), "legs": [], "gross_pnl": 0.0,
                "ran_runner": False, "final_reason": None, "closed": False,
            }
        elif ev == "tp1_partial":
            t = open_t.get(sym)
            if t:
                t["legs"].append(("tp1", float(r.get("exit", 0.0)), int(r.get("qty", 0))))
                t["gross_pnl"] += float(r.get("pnl_inr", 0.0))
                t["ran_runner"] = True
        elif ev == "exit":
            t = open_t.get(sym)
            if not t:   # exit with no tracked entry (e.g. restart) → standalone trade
                t = {"symbol": sym, "entry": float(r.get("entry", 0.0)),
                     "qty": int(r.get("qty", 0)), "legs": [], "gross_pnl": 0.0,
                     "ran_runner": False, "final_reason": None, "closed": False}
            t["legs"].append(("exit", float(r.get("exit", 0.0)), int(r.get("qty", 0))))
            t["gross_pnl"] += float(r.get("pnl_inr", 0.0))
            t["final_reason"] = r.get("reason", "?")
            t["closed"] = True
            trades.append(t)
            open_t.pop(sym, None)
    return trades


def trade_cost(t: dict) -> float:
    """Brokerage + statutory cost for one trade (1 buy + N sell legs)."""
    entry_val = t["entry"] * t["qty"]
    cost = BROKERAGE_PER_LEG + BUY_STAMP_PCT * entry_val          # buy leg
    for _kind, fill, qty in t["legs"]:
        cost += BROKERAGE_PER_LEG + SELL_CHARGES_PCT * (fill * qty)  # each sell leg
    return cost


def summary_stats(trades: list[dict]) -> dict:
    """Headline net-after-cost stats. Reused by analyze() and the EOD Telegram
    summary so the printed report and the phone alert never disagree."""
    n = len(trades)
    net_pnls = [t["gross_pnl"] - trade_cost(t) for t in trades]
    gross = sum(t["gross_pnl"] for t in trades)
    costs = sum(trade_cost(t) for t in trades)
    net = sum(net_pnls)
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    wr = (100.0 * len(wins) / n) if n else 0.0
    be = (100.0 * (-avg_loss) / (avg_win - avg_loss)) if (avg_win - avg_loss) else 0.0
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "wr": wr,
        "gross": gross, "costs": costs, "net": net,
        "net_per_trade": (net / n) if n else 0.0,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "breakeven_wr": be, "above_breakeven": (wr > be),
        "net_pnls": net_pnls,
    }


def analyze(trades: list[dict]) -> None:
    n = len(trades)
    if n == 0:
        print("No closed scalp trades in the ledger yet.")
        print("→ Deploy, let the agent run live (paper) sessions, then re-run this.")
        print(f"   Ledger path: {LEDGER_PATH}")
        return

    st = summary_stats(trades)
    gross, costs, net = st["gross"], st["costs"], st["net"]
    net_pnls = st["net_pnls"]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    wr, avg_win, avg_loss = st["wr"], st["avg_win"], st["avg_loss"]

    print("=" * 60)
    print(f"SCALP LEDGER — {n} closed trades")
    print("=" * 60)
    print(f"  Net win rate (after costs) : {wr:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  GROSS P&L                  : ₹{gross:>12,.0f}")
    print(f"  Costs (brokerage+STT)      : ₹{costs:>12,.0f}")
    print(f"  NET P&L (after costs)      : ₹{net:>12,.0f}   (₹{net/n:+,.0f}/trade)")
    print(f"  Avg net win / net loss     : ₹{avg_win:+,.0f} / ₹{avg_loss:+,.0f}")
    if avg_loss != 0:
        # breakeven WR given this win/loss geometry
        be = 100.0 * (-avg_loss) / (avg_win - avg_loss) if (avg_win - avg_loss) else 0.0
        print(f"  Breakeven WR for this R:R  : {be:.1f}%  "
              f"({'ABOVE — edge' if wr > be else 'BELOW — bleeding'})")

    # by final exit reason
    print("\n  By final exit reason (net):")
    by = defaultdict(list)
    for t, npnl in zip(trades, net_pnls):
        by[t["final_reason"]].append(npnl)
    for reason, ps in sorted(by.items(), key=lambda x: -sum(x[1])):
        print(f"    {str(reason):14s} n={len(ps):3d}  net=₹{sum(ps):>10,.0f}  "
              f"avg=₹{sum(ps)/len(ps):+,.0f}")

    # runner-capture verdict (Fix #209)
    runners = [(t, npnl) for t, npnl in zip(trades, net_pnls) if t["ran_runner"]]
    flat    = [(t, npnl) for t, npnl in zip(trades, net_pnls) if not t["ran_runner"]]
    print("\n  Runner capture (Fix #209):")
    if runners:
        rnet = sum(p for _, p in runners)
        print(f"    trades that banked TP1 + trailed : {len(runners)}  net=₹{rnet:,.0f}  "
              f"avg=₹{rnet/len(runners):+,.0f}")
    else:
        print("    no runner trades yet (none reached the +target to trail)")
    if flat:
        fnet = sum(p for _, p in flat)
        print(f"    trades that stopped/timed pre-TP1: {len(flat)}  net=₹{fnet:,.0f}  "
              f"avg=₹{fnet/len(flat):+,.0f}")
    print("\n  Read: if runner-trades' avg >> a hypothetical hard-2:1 cap, Fix #209 earns")
    print("  its keep. If net P&L < 0 or WR < breakeven, the scalp path has no edge yet —")
    print("  tighten entry (ext%/rvol) or stand down in red tape before scaling size.")
    print("=" * 60)


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "all" else None
    recs = load_all(day=day)
    analyze(group_trades(recs))
