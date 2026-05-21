"""
Scalp-engine replay on 2026-05-21's REAL tape.

Runs agents/scalp_engine.py bar-by-bar over the actual 5-min candles pulled
live from Kite this morning for three representative names:

    ANGELONE  — clean grinder the old pipeline never traded (the indictment)
    MTARTECH  — strong continuation runner, also never traded
    PARAS     — the "trap" the operator asked about: ran to 824 then faded

It answers the operator's question directly: as a scalper, what would we have
actually traded today, and would the trap have hurt us?

ASSUMPTIONS (stated honestly — the sandbox cannot reach Kite for live depth):
  • RVOL: the live engine uses 20-day RVOL, which Discovery logged at 8–20x for
    all three names all morning, so the replay passes rvol above the floor and
    focuses on the entry STRUCTURE + exit DISCIPLINE — the parts we changed.
  • Order book / spread: historical depth isn't replayable; passed as neutral.
    The live engine still applies the 5-level book guard and 0.15% spread cap.
  • Costs: a 0.06% round-trip (slippage + charges) is deducted per trade.
  • Fills: signal on a bar close → fill at the NEXT bar's open (realistic).

Read-only. Places no orders.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.scalp_engine import (
    ScalpConfig, evaluate_entry, evaluate_exit, stop_target,
)

ATR_LOOKBACK = 5   # bars used for the volatility-scaled stop

ROUND_TRIP_COST_PCT = 0.0006   # 0.06% slippage + charges, deducted per trade
ENTRY_SLIP_PCT      = 0.0002   # buy fills 0.02% above the bar open
BAR_MIN             = 5        # 5-minute candles

# ── REAL candles pulled from Kite at ~10:35 IST on 2026-05-21 ────────────────
# Each row: (HH:MM, open, high, low, close, volume)
CANDLES = {
    "ANGELONE": [
        ("09:15", 327.80, 333.75, 327.00, 331.65, 1039565),
        ("09:20", 331.50, 334.70, 331.40, 334.45,  915444),
        ("09:25", 334.45, 336.35, 333.75, 334.85, 1193583),
        ("09:30", 334.85, 336.95, 334.60, 335.75,  788027),
        ("09:35", 335.75, 338.65, 335.35, 338.05, 1002437),
        ("09:40", 338.05, 338.30, 336.30, 336.90,  522533),
        ("09:45", 336.90, 338.50, 336.90, 338.20,  667755),
        ("09:50", 338.30, 338.75, 337.65, 338.20,  642180),
        ("09:55", 338.20, 338.80, 337.30, 337.85,  648160),
        ("10:00", 337.85, 339.30, 337.30, 338.90,  567815),
        ("10:05", 339.00, 339.50, 337.55, 338.10,  616260),
        ("10:10", 338.10, 340.00, 338.00, 339.70,  473626),
        ("10:15", 339.75, 340.40, 338.70, 339.80,  669630),
        ("10:20", 339.80, 341.85, 339.70, 340.10,  896633),
        ("10:25", 340.10, 342.30, 339.70, 342.15,  715216),
        ("10:30", 342.05, 342.20, 341.55, 341.85,   90173),
    ],
    "MTARTECH": [
        ("09:15", 7531.0, 7776.0, 7370.0, 7742.0, 358837),
        ("09:20", 7714.0, 7766.5, 7653.5, 7706.0, 135438),
        ("09:25", 7706.5, 7820.0, 7706.0, 7767.5, 163475),
        ("09:30", 7764.5, 7849.0, 7760.5, 7835.0, 115000),
        ("09:35", 7838.5, 7900.0, 7757.0, 7879.0, 157426),
        ("09:40", 7879.5, 7915.0, 7814.5, 7854.5, 132905),
        ("09:45", 7850.5, 7867.5, 7786.0, 7818.5,  86831),
        ("09:50", 7817.5, 7834.5, 7780.5, 7796.5,  52226),
        ("09:55", 7790.5, 7800.0, 7704.5, 7713.0,  93421),
        ("10:00", 7711.0, 7749.0, 7710.0, 7748.5,  33831),
        ("10:05", 7748.5, 7814.0, 7744.0, 7806.0,  69446),
        ("10:10", 7803.0, 7805.5, 7771.5, 7797.0,  23043),
        ("10:15", 7797.0, 7855.0, 7790.0, 7847.0,  50452),
        ("10:20", 7847.0, 7880.0, 7800.0, 7864.5,  72258),
        ("10:25", 7863.5, 7869.0, 7830.0, 7865.5,  33940),
        ("10:30", 7865.5, 7904.5, 7863.5, 7900.0,  38489),
    ],
    "PARAS": [
        ("09:15", 769.05, 794.85, 768.50, 789.20, 204572),
        ("09:20", 788.15, 806.40, 784.65, 800.90, 264833),
        ("09:25", 800.75, 807.55, 798.80, 803.95, 181724),
        ("09:30", 803.50, 809.50, 803.35, 809.40, 156286),
        ("09:35", 809.45, 821.00, 807.10, 818.30, 313660),
        ("09:40", 818.90, 824.00, 816.60, 821.70, 168684),
        ("09:45", 821.70, 822.00, 810.20, 813.65, 144837),
        ("09:50", 813.60, 813.70, 808.00, 809.20,  93888),
        ("09:55", 809.15, 812.00, 806.10, 807.90,  82593),
        ("10:00", 807.50, 809.00, 805.50, 806.80,  43750),
        ("10:05", 806.85, 808.00, 805.20, 807.05,  34737),
        ("10:10", 807.00, 808.30, 806.40, 807.70,  24463),
        ("10:15", 807.70, 808.25, 805.00, 807.75,  42595),
        ("10:20", 807.80, 808.20, 806.50, 806.95,  12810),
        ("10:25", 806.95, 807.85, 801.25, 804.35,  55697),
        ("10:30", 804.35, 804.55, 801.65, 802.50,  22601),
        ("10:35", 802.50, 803.50, 802.40, 802.40,   6014),
    ],
}


def _vwap_series(bars):
    """Progressive session VWAP at each bar close."""
    out, cum_tpv, cum_v = [], 0.0, 0.0
    for (_, o, h, l, c, v) in bars:
        typical = (h + l + c) / 3.0
        cum_tpv += typical * v
        cum_v   += v
        out.append(cum_tpv / cum_v if cum_v else c)
    return out


def replay_symbol(sym, bars, cfg):
    vwaps = _vwap_series(bars)
    trades = []
    pos = None          # open position dict or None
    cooldown_until = -1 # bar index we may re-enter from

    for i, (t, o, h, l, c, v) in enumerate(bars):
        # ---- manage an open position on THIS bar first ----
        if pos is not None:
            mins = (i - pos["fill_idx"]) * BAR_MIN
            ex = evaluate_exit(pos["entry"], pos["stop"], pos["target"],
                               mins, h, l, c, cfg)
            if ex.exit:
                gross = (ex.price - pos["entry"]) / pos["entry"]
                net   = gross - ROUND_TRIP_COST_PCT
                trades.append({
                    "sym": sym, "in_t": pos["t"], "in": pos["entry"],
                    "out_t": t, "out": ex.price, "reason": ex.reason,
                    "qty": pos["qty"], "pnl_pct": net * 100,
                    "pnl_inr": net * pos["entry"] * pos["qty"],
                })
                pos = None
                cooldown_until = i + 1   # allow re-entry from next bar

        # ---- look for a new entry on this bar's close (fills next bar open) ----
        if pos is None and i >= cooldown_until and i + 1 < len(bars):
            # ATR = mean true range of the recent bars (high-low proxy)
            lo = max(0, i - ATR_LOOKBACK + 1)
            rng = [bars[k][2] - bars[k][3] for k in range(lo, i + 1)]
            atr = sum(rng) / len(rng) if rng else 0.0
            d = evaluate_entry(
                symbol=sym, ltp=c, vwap=vwaps[i],
                bar_open=o, bar_close=c,
                rvol=5.0,          # live 20-day RVOL was 8–20x all morning (Discovery log)
                ob_ratio=1.0,      # neutral — live engine applies the real book guard
                spread_pct=0.0005, # neutral — live engine applies the 0.15% cap
                day_change_pct=(c / bars[0][1] - 1) * 100,  # vs day open (proxy)
                cfg=cfg, atr=atr,
            )
            if d.enter:
                nxt = bars[i + 1]
                fill = round(nxt[1] * (1 + ENTRY_SLIP_PCT), 2)
                stop, target = stop_target(fill, atr, cfg)
                pos = {
                    "t": nxt[0], "fill_idx": i + 1, "entry": fill, "qty": d.qty,
                    "stop": stop, "target": target,
                }

    # mark any still-open position to the last close
    if pos is not None:
        last = bars[-1]
        gross = (last[4] - pos["entry"]) / pos["entry"]
        net   = gross - ROUND_TRIP_COST_PCT
        trades.append({
            "sym": sym, "in_t": pos["t"], "in": pos["entry"],
            "out_t": last[0] + "*", "out": last[4], "reason": "open_eod",
            "qty": pos["qty"], "pnl_pct": net * 100,
            "pnl_inr": net * pos["entry"] * pos["qty"],
        })
    return trades


def main():
    import config.settings as S
    cfg = ScalpConfig.from_settings(S)

    print("=" * 78)
    print("SCALP-ENGINE REPLAY — 2026-05-21 real tape (09:15–10:35 IST)")
    print(f"profile: stop -{cfg.stop_pct*100:.1f}%  tp +{cfg.tp_pct*100:.1f}%  "
          f"scratch {cfg.scratch_min}m  time-stop {cfg.time_stop_min}m  "
          f"notional ₹{cfg.notional_inr:,.0f}  max-ext {cfg.max_ext_from_vwap*100:.1f}%")
    print("=" * 78)

    all_trades, total = [], 0.0
    for sym, bars in CANDLES.items():
        trades = replay_symbol(sym, bars, cfg)
        all_trades += trades
        sub = sum(t["pnl_inr"] for t in trades)
        total += sub
        print(f"\n{sym}  ({len(trades)} trade(s), net ₹{sub:+,.0f})")
        if not trades:
            print("   — no qualifying entry —")
        for t in trades:
            print(f"   {t['in_t']}→{t['out_t']:>6}  "
                  f"buy {t['in']:>8.2f}  exit {t['out']:>8.2f}  "
                  f"{t['reason']:<9}  qty {t['qty']:>4}  "
                  f"{t['pnl_pct']:+5.2f}%  ₹{t['pnl_inr']:+,.0f}")

    wins = [t for t in all_trades if t["pnl_inr"] > 0]
    print("\n" + "=" * 78)
    print(f"TOTAL: {len(all_trades)} trades | "
          f"{len(wins)} win / {len(all_trades)-len(wins)} loss | "
          f"hit-rate {100*len(wins)/len(all_trades):.0f}%  "
          f"| net P&L ₹{total:+,.0f}")
    print("=" * 78)
    print("Read this against the live log: 0 trades, ₹0, all morning.")


if __name__ == "__main__":
    main()
