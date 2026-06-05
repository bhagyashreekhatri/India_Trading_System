"""
Funnel analyzer (2026-05-29) — answers "where do trades die, and WHY does the
conviction engine take zero while scalp fires?"

Reads logs/funnel.jsonl (written by TradingCrew._log_funnel, one row per tick):
  {ts, active, setups, scored, entries, rejects:{gate:count, ...}}

The funnel stages:
  active   — names that passed the scan (in-play, liquid)
  setups   — names where a MOMENTUM_BREAKOUT was actually DETECTED
  scored   — setups that passed scoring/pre-filters and reached the allocator
  entries  — actual conviction-engine position opens

If `setups` collapses to ~0 while `active` is high → conviction is starved at
SETUP DETECTION (the detector discards the smooth movers scalp rides). If setups
exist but entries stay 0, the `rejects` histogram names the gate doing the killing
(conviction_*, runway_too_short, weak_order_book, nifty_fhh_not_broken, ...).

Usage:
  python3 tools/analyze_funnel.py            # all days
  python3 tools/analyze_funnel.py 2026-05-29 # one day
"""
from __future__ import annotations
import os, sys, json
from collections import Counter

LEDGER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "logs", "funnel.jsonl")


def load(path=None, day=None):
    path = path or LEDGER
    out = []
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


def analyze(rows):
    if not rows:
        print("No funnel rows yet. Deploy, run a session, then re-run this.")
        print(f"  Ledger path: {LEDGER}")
        return
    ticks = len(rows)
    A = sum(r.get("active", 0)  for r in rows)
    S = sum(r.get("setups", 0)  for r in rows)
    C = sum(r.get("scored", 0)  for r in rows)
    E = sum(r.get("entries", 0) for r in rows)
    rej = Counter()
    for r in rows:
        for g, c in (r.get("rejects", {}) or {}).items():
            rej[g] += c
    ticks_with_active  = sum(1 for r in rows if r.get("active", 0) > 0)
    ticks_with_setups  = sum(1 for r in rows if r.get("setups", 0) > 0)

    def pct(n, d): return (100.0 * n / d) if d else 0.0

    print("=" * 60)
    print(f"FUNNEL — {ticks} ticks   ({rows[0]['ts'][:10]} → {rows[-1]['ts'][:10]})")
    print("=" * 60)
    print(f"  active  → setups : {A:>6} → {S:>5}   ({pct(S,A):.1f}% of active became setups)")
    print(f"  setups  → scored : {S:>6} → {C:>5}   ({pct(C,S):.1f}%)")
    print(f"  scored  → entries: {C:>6} → {E:>5}   ({pct(E,C):.1f}%)")
    print(f"  ticks with active names: {ticks_with_active}/{ticks}  |  ticks with a setup: {ticks_with_setups}/{ticks}")

    print("\n  Top drop reasons (summed across ticks):")
    for gate, c in rej.most_common(12):
        print(f"    {gate:32s} {c:>6}")

    # ── Verdict ──────────────────────────────────────────────────────────────
    print("\n  VERDICT:")
    conv_rej = {g: c for g, c in rej.items() if g.startswith("conviction_")}
    if A > 0 and pct(S, A) < 2.0:
        print("  → Conviction is STARVED AT SETUP DETECTION. Active names exist but")
        print("    almost nothing becomes a MOMENTUM_BREAKOUT setup — the detector is")
        print("    discarding the very movers the scalp engine rides. The fix lives in")
        print("    the setup detector (body/range gates), NOT in the conviction gates.")
    elif E == 0 and conv_rej:
        top = max(conv_rej.items(), key=lambda x: x[1])
        print(f"  → Setups reach conviction but it rejects them. Dominant gate: "
              f"{top[0]} ({top[1]}). Investigate THAT gate with this evidence —")
        print("    do not loosen the whole stack blind.")
    elif E == 0 and rej:
        top = rej.most_common(1)[0]
        print(f"  → Trades die at the allocator. Dominant reason: {top[0]} ({top[1]}).")
    elif E > 0:
        print(f"  → Conviction IS entering ({E} entries over {ticks} ticks). If that's"
              " still too few, widen the funnel, don't loosen the gates.")
    else:
        print("  → Not enough signal yet — collect more ticks.")
    print("=" * 60)


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "all" else None
    analyze(load(day=day))
