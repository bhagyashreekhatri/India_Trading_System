#!/usr/bin/env python3
"""
Phase A smoke test — replay 280 historical trades through the new filters.

Answers:
  1. How many trades would have survived?
  2. What's the new gross/net P&L?
  3. What's the new mean R?
  4. Daily trade rate after filtering?
  5. Which filter killed the most trades?

This is a BACKWARDS counterfactual: market behaviour is fixed; we're only
checking the filter logic. It cannot tell us what Phase A WILL do
tomorrow — only what it would have done yesterday.

Usage:
  python3 scripts/phase_a_smoke_test.py --db trade_state_server_snapshot.db
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── Phase A filter constants (must match config/settings.py) ───────────────
SETUP_DISARMED_LIST = {
    "recovery_setup", "failed_breakdown", "vwap_reclaim", "trend_pullback",
    "vwap_pullback", "range_breakout", "inside_bar_break",
}
MOMENTUM_BO_MIN_CONFLUENCE = 2
MOMENTUM_BO_MIN_RVOL       = 2.0    # raised from 1.7

# Cost model (matches scripts/analyze_exit_distribution.py)
COST_FIXED_INR    = 226.0
COST_VARIABLE_PCT = 0.0016


def cost_for(pos_value: float) -> float:
    return COST_FIXED_INR + pos_value * COST_VARIABLE_PCT


CLOSED = ("closed_win", "closed_loss", "closed_partial")


def fetch_closed(db_path: Path) -> list[dict]:
    if not db_path.exists():
        sys.exit(f"DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM positions WHERE status IN {CLOSED}").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        # Parse score_breakdown JSON
        try:
            d["_breakdown"] = json.loads(d.get("score_breakdown") or "{}")
        except Exception:
            d["_breakdown"] = {}
        d["_pos_value"] = (d.get("entry_price") or 0) * (d.get("quantity") or 0)
        out.append(d)
    return out


# Heuristic: which sectors are commonly "top-3" historically?
# Based on visual inspection of recent log dumps showing IT, PHARMA, AUTO,
# BANKING, METALS as frequent top sectors. This is an APPROXIMATION only.
COMMON_TOP_SECTORS = {"IT", "PHARMA", "AUTO", "BANKING", "FINANCE",
                      "METALS", "METAL", "ENERGY", "FMCG", "REALTY"}


def apply_phase_a(trade: dict, mode: str) -> tuple[bool, str]:
    """
    Returns (would_survive, kill_reason).
    mode: "strict"  → require confluence ≥ 2 (sector check skipped)
          "approx"  → confluence ≥ 2 OR sector in COMMON_TOP_SECTORS
    """
    setup = trade.get("setup_type") or ""

    # 1. Setup disarmed
    if setup in SETUP_DISARMED_LIST:
        return False, f"setup_disarmed_{setup}"

    # Only momentum_breakout survives the disarm gate; check its filters
    if setup != "momentum_breakout":
        # Some other unknown setup → leave it alone (not in disarm list = it's allowed)
        return True, "non_momentum_passthrough"

    # 2. RVOL ≥ 2.0 — we don't have raw RVOL stored, but volume_strength score
    # is a proxy. volume_strength of ≥ 1.4 ≈ RVOL ≥ 2.0 (per scoring engine).
    # If volume_strength is missing, assume it passed (conservative).
    bd = trade["_breakdown"]
    vol_str = bd.get("volume_strength", 999)   # default = pass
    if vol_str < 1.4:
        return False, "momentum_low_volume"

    # 3. Priority filter: confluence ≥ 2 OR sector in top-3
    conf  = bd.get("confluence_count", 1)
    sector = (trade.get("sector") or "").upper().strip()

    if mode == "strict":
        if conf < MOMENTUM_BO_MIN_CONFLUENCE:
            return False, "momentum_no_priority"
    elif mode == "approx":
        sector_priority = sector in COMMON_TOP_SECTORS
        if conf < MOMENTUM_BO_MIN_CONFLUENCE and not sector_priority:
            return False, "momentum_no_priority"

    return True, "survived"


def aggregate(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    rs   = [t.get("pnl_r") or 0 for t in trades]
    pnls = [t.get("pnl") or 0 for t in trades]
    wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    gross_total = sum(pnls)
    cost_total  = sum(cost_for(t["_pos_value"]) for t in trades)
    return {
        "n":          len(trades),
        "wins":       wins,
        "wr_pct":     round(100 * wins / len(trades), 1),
        "mean_r":     round(statistics.mean(rs), 3),
        "median_r":   round(statistics.median(rs), 3),
        "gross_pnl":  round(gross_total, 0),
        "total_cost": round(cost_total, 0),
        "net_pnl":    round(gross_total - cost_total, 0),
        "avg_per_trade_net": round((gross_total - cost_total) / len(trades), 0),
    }


def trade_rate_per_day(trades: list[dict]) -> float:
    """Trades per unique trading day."""
    days = set()
    for t in trades:
        et = t.get("entry_time")
        if et:
            try:
                days.add(datetime.fromisoformat(et).date())
            except Exception:
                pass
    return round(len(trades) / max(1, len(days)), 2)


def render(actual: list[dict], strict_survivors: list[dict], approx_survivors: list[dict],
           strict_kills: Counter, approx_kills: Counter) -> str:
    a = aggregate(actual)
    s = aggregate(strict_survivors)
    p = aggregate(approx_survivors)

    a_rate = trade_rate_per_day(actual)
    s_rate = trade_rate_per_day(strict_survivors)
    p_rate = trade_rate_per_day(approx_survivors)

    md = f"""# Phase A Smoke Test — Counterfactual Replay

*Generated: {datetime.now().isoformat(timespec='seconds')} | n input = {a['n']} closed trades*

> Replays historical trades through the new Phase A filters. Cannot predict
> tomorrow's tape — only shows what filter logic would have done yesterday.

---

## Headline comparison

| Metric | Actual (no Phase A) | STRICT mode | APPROX mode |
|---|---:|---:|---:|
| Trades taken | {a['n']} | {s['n']} | {p['n']} |
| Trades/day | {a_rate} | {s_rate} | {p_rate} |
| Win rate | {a['wr_pct']}% | {s['wr_pct']}% | {p['wr_pct']}% |
| **Mean R** | **{a['mean_r']:+.3f}R** | **{s['mean_r']:+.3f}R** | **{p['mean_r']:+.3f}R** |
| Median R | {a['median_r']:+.3f}R | {s['median_r']:+.3f}R | {p['median_r']:+.3f}R |
| Gross P&L | ₹{a['gross_pnl']:+,.0f} | ₹{s['gross_pnl']:+,.0f} | ₹{p['gross_pnl']:+,.0f} |
| Total costs | ₹{a['total_cost']:,.0f} | ₹{s['total_cost']:,.0f} | ₹{p['total_cost']:,.0f} |
| **Net P&L** | **₹{a['net_pnl']:+,.0f}** | **₹{s['net_pnl']:+,.0f}** | **₹{p['net_pnl']:+,.0f}** |
| Avg ₹/trade (net) | ₹{a['avg_per_trade_net']:+,.0f} | ₹{s['avg_per_trade_net']:+,.0f} | ₹{p['avg_per_trade_net']:+,.0f} |

## Filter kill counts

### STRICT mode (confluence ≥ 2 required, sector check skipped)
"""
    for reason, count in strict_kills.most_common():
        md += f"- `{reason}`: {count} trades killed\n"
    md += f"""
**Total killed: {sum(strict_kills.values())} of {a['n']}**
**Survivors: {s['n']} ({100*s['n']/max(1,a['n']):.1f}%)**

### APPROX mode (confluence ≥ 2 OR sector ∈ {{IT, PHARMA, AUTO, BANKING, FINANCE, METALS, ENERGY, FMCG, REALTY}})
"""
    for reason, count in approx_kills.most_common():
        md += f"- `{reason}`: {count} trades killed\n"
    md += f"""
**Total killed: {sum(approx_kills.values())} of {a['n']}**
**Survivors: {p['n']} ({100*p['n']/max(1,a['n']):.1f}%)**

---

## What this means

### Best case (APPROX mode — closer to real live behaviour)
- Trades drop from **{a_rate}/day → {p_rate}/day** ({100 - 100*p_rate/max(0.01,a_rate):.0f}% reduction)
- Mean R lifts from **{a['mean_r']:+.3f}R → {p['mean_r']:+.3f}R** ({(p['mean_r'] - a['mean_r']):+.3f}R improvement)
- Net P&L: **₹{a['net_pnl']:+,.0f} → ₹{p['net_pnl']:+,.0f}** (delta: ₹{p['net_pnl'] - a['net_pnl']:+,.0f})

### Worst case (STRICT mode — pure confluence requirement, no sector OR fallback)
- Trades drop to **{s_rate}/day**
- Mean R: **{s['mean_r']:+.3f}R**
- Net P&L: **₹{s['net_pnl']:+,.0f}**

### Decision criteria (from `docs/08_Findings_From_280_Trades.md`)
- Target trade rate: 3-5/day
- Target mean R: +0.30R+
- Target: net P&L ≥ break-even, ideally positive

### Verdict
"""

    # Decision logic
    if p['mean_r'] >= 0.30 and p_rate <= 5 and p_rate >= 1:
        verdict = "🟢 **PHASE A LOOKS GOOD** — APPROX projection hits both targets. Live deployment likely to perform similarly. Watch tomorrow for confirmation."
    elif p['mean_r'] >= 0.20 and p_rate <= 7:
        verdict = "🟡 **PHASE A IS DIRECTIONALLY RIGHT** — APPROX projection improves edge meaningfully but doesn't fully hit +0.30R target. Still worth shipping; may need further tightening after live data."
    elif p_rate < 0.5:
        verdict = "🔴 **PHASE A TOO TIGHT** — APPROX projection shows fewer than 0.5 trades/day. System will be near-idle. Consider loosening: drop confluence requirement OR widen sector list."
    elif p['mean_r'] < a['mean_r']:
        verdict = "🔴 **PHASE A MAKES THINGS WORSE** — APPROX mean R is lower than baseline. Filter is killing the wrong trades. Review carefully before deploying for tomorrow."
    else:
        verdict = "🟡 **PHASE A IS MARGINAL** — improvement is small. Consider whether to ship as-is or revise priority criteria."

    md += verdict + "\n\n"

    md += """---

## Methodology caveats

1. **`top_sectors` not stored historically** — STRICT mode skips sector check; APPROX mode uses
   a hand-picked list of historically-frequent top sectors. Real live behaviour falls between
   these two passes.
2. **RVOL not stored** — used `volume_strength` score from `score_breakdown` as proxy. A
   `volume_strength ≥ 1.4` roughly corresponds to RVOL ≥ 2.0 per the scoring engine's mapping.
   May misclassify edge cases.
3. **No counterfactual entry timing** — Phase A allows confluence-detection to keep running on
   disarmed setups, which means real-tomorrow `confluence_count` may differ from historical
   confluence count (the disarmed detectors fire less often if scoring filters them earlier).
   This estimate slightly overcounts surviving confluence-priority trades.
4. **Cost model** scales with actual position size. Same model as `analyze_exit_distribution.py`.
5. **APPROX sector list** is heuristic — actual top-3 changes per session. A real momentum trade
   in CEMENT (not in the list) on a day CEMENT was strong would be incorrectly killed in this
   simulation but would correctly fire live.

---

## Bottom line

If APPROX projection shows positive direction (mean R up, net P&L up, trade rate down toward
target), Phase A deserves to run. Tomorrow's data is the real test.

If projection is negative or marginal, revise filters BEFORE deployment.
"""
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",  default="trade_state.db")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[smoke-test] Reading {db_path}...")
    trades = fetch_closed(db_path)
    print(f"[smoke-test] {len(trades)} trades to replay")

    if not trades:
        sys.exit("No trades.")

    strict_survivors = []
    approx_survivors = []
    strict_kills = Counter()
    approx_kills = Counter()
    for t in trades:
        s_ok, s_reason = apply_phase_a(t, "strict")
        a_ok, a_reason = apply_phase_a(t, "approx")
        if s_ok: strict_survivors.append(t)
        else:    strict_kills[s_reason] += 1
        if a_ok: approx_survivors.append(t)
        else:    approx_kills[a_reason] += 1

    md = render(trades, strict_survivors, approx_survivors, strict_kills, approx_kills)
    out = out_dir / "09_Phase_A_Smoke_Test.md"
    out.write_text(md)
    print(f"[smoke-test] Report written: {out}")

    # CLI summary
    print()
    print(f"  ACTUAL:  n={len(trades):3}  meanR={statistics.mean(t.get('pnl_r') or 0 for t in trades):+.3f}  net=₹{sum((t.get('pnl') or 0) for t in trades) - sum(cost_for(t['_pos_value']) for t in trades):+,.0f}")
    print(f"  STRICT:  n={len(strict_survivors):3}  meanR={statistics.mean(t.get('pnl_r') or 0 for t in strict_survivors) if strict_survivors else 0:+.3f}  net=₹{sum((t.get('pnl') or 0) for t in strict_survivors) - sum(cost_for(t['_pos_value']) for t in strict_survivors):+,.0f}")
    print(f"  APPROX:  n={len(approx_survivors):3}  meanR={statistics.mean(t.get('pnl_r') or 0 for t in approx_survivors) if approx_survivors else 0:+.3f}  net=₹{sum((t.get('pnl') or 0) for t in approx_survivors) - sum(cost_for(t['_pos_value']) for t in approx_survivors):+,.0f}")


if __name__ == "__main__":
    main()
