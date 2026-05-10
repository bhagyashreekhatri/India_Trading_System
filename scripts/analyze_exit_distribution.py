#!/usr/bin/env python3
"""
Exit distribution analysis — informs single-target vs partials decision.

Reads trade_state.db (read-only), computes the metrics needed to decide:
  - Should we kill TP1 partial-exit and go single-target?
  - Or do we have enough big runners that the runner-half justifies double-cost?

Decision lives in `docs/05_Exit_Distribution_Analysis.md` (Phase A pre-flight).

Usage:
  python3 scripts/analyze_exit_distribution.py              # uses ./trade_state.db
  python3 scripts/analyze_exit_distribution.py --db PATH    # custom path
  python3 scripts/analyze_exit_distribution.py --out DIR    # custom output dir

Pure stdlib. Read-only on the DB. Idempotent.
"""
from __future__ import annotations
import argparse
import sqlite3
import statistics
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

# ── Constants — realistic Indian intraday cost stack (₹) ───────────────────
# Per round-trip on average ₹5,00,000 turnover position. See docs/07.
COST_FIXED_PER_TRADE     = 226.0   # brokerage + STT + exchange + GST + SEBI + stamp
COST_SPREAD_PER_TRADE    = 500.0   # 0.05% × 2 sides × ₹5L
COST_SLIPPAGE_PER_TRADE  = 300.0   # 1bp entry + 5bp stop on ₹5L
COST_TOTAL_PER_TRADE     = COST_FIXED_PER_TRADE + COST_SPREAD_PER_TRADE + COST_SLIPPAGE_PER_TRADE
COST_PER_PARTIAL_EXIT    = COST_FIXED_PER_TRADE * 0.5 + 250  # half-position partial booking

CLOSED_STATUSES = ("closed_win", "closed_loss", "closed_partial")


# ── Data model ─────────────────────────────────────────────────────────────
def fetch_closed(db_path: Path) -> list[dict]:
    """Return all closed trades as dicts with safe defaults for missing cols.
    Read-only. Robust to schema variation across DB snapshots."""
    if not db_path.exists():
        sys.exit(f"DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Discover available columns so script tolerates pre-migration DBs
    cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
    raw  = conn.execute(f"SELECT * FROM positions WHERE status IN {CLOSED_STATUSES}").fetchall()
    conn.close()

    # Project to a stable schema with safe defaults
    DEFAULTS = {
        "id": 0, "symbol": "", "setup_type": "unknown", "grade": "",
        "score": 0.0, "entry_price": 0.0, "stop_loss": 0.0, "initial_sl": 0.0,
        "tp1_price": 0.0, "tp2_price": 0.0, "tp1_hit": 0, "quantity": 0,
        "pnl": 0.0, "pnl_r": 0.0, "exit_reason": "", "exit_price": 0.0,
        "status": "", "entry_time": None, "exit_time": None,
    }
    out = []
    for r in raw:
        d = {k: (r[k] if k in r.keys() else v) for k, v in DEFAULTS.items()}
        # initial_sl falls back to stop_loss if column absent
        if d["initial_sl"] in (0.0, None) and d["stop_loss"]:
            d["initial_sl"] = d["stop_loss"]
        out.append(d)
    return out


# ── Metric helpers ─────────────────────────────────────────────────────────
def percentiles(values: list[float], pcts=(10, 25, 50, 75, 90)) -> dict:
    """Compute percentiles. Returns {pct: value}."""
    if not values:
        return {p: None for p in pcts}
    sv = sorted(values)
    out = {}
    for p in pcts:
        k = (len(sv) - 1) * p / 100.0
        f = int(k)
        c = min(f + 1, len(sv) - 1)
        out[p] = sv[f] + (sv[c] - sv[f]) * (k - f)
    return out


def safe_avg(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def safe_median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def classify_exit(exit_reason: str | None, status: str, tp1_hit: int) -> str:
    """Classify each trade into a high-level outcome bucket."""
    er = (exit_reason or "").lower()
    if "tp2" in er or status == "closed_win" and tp1_hit and "trail" in er:
        return "tp2_or_runner"
    if "trail" in er and tp1_hit:
        return "tp1_then_trailed"
    if tp1_hit and status == "closed_loss":
        return "tp1_then_sl"
    if tp1_hit:
        return "tp1_only"
    if "stall" in er or "time_stop" in er or "eod" in er or "no_movement" in er:
        return "stalled_no_movement"
    if "sl" in er and not tp1_hit:
        return "sl_hit_clean"
    return "other"


# ── Counterfactual simulators ──────────────────────────────────────────────
def simulate_single_target(rows: list[dict], target_r: float) -> dict:
    """
    What if every trade had a single fixed target at target_r (no partials)?

    Approximation: we use realised pnl_r as a proxy for max-favourable-excursion.
      - If realised pnl_r >= target_r: trade hits the target, P&L = target_r × position_risk
      - If realised pnl_r < target_r and < 0: trade hits SL, P&L = -1R
      - If realised pnl_r < target_r but > 0: trade exits at the actual realised R
        (this is conservative — real MFE may have been higher)

    Approximation note: WITHOUT candle replay we can only approximate. True MFE
    requires re-fetching candles, which is Phase A+ work. This gives a decent
    ranking even if absolute numbers are slightly under-counted.
    """
    n_hit = 0
    n_sl  = 0
    n_other = 0
    total_pnl = 0.0
    cost_per_trade = COST_TOTAL_PER_TRADE   # single round-trip cost (no double exit)

    for r in rows:
        pnl_r = r["pnl_r"] or 0.0
        risk_inr = abs((r["entry_price"] or 0) - (r["initial_sl"] or r["stop_loss"] or 0)) * (r["quantity"] or 0)
        if risk_inr == 0:
            n_other += 1
            continue

        if pnl_r >= target_r:
            # Trade hit the target
            simulated_pnl = target_r * risk_inr
            n_hit += 1
        elif pnl_r <= -1.0:
            # Stopped out
            simulated_pnl = -1.0 * risk_inr
            n_sl += 1
        else:
            # Stalled or partial — approximate as actual realised R
            simulated_pnl = pnl_r * risk_inr
            n_other += 1

        total_pnl += simulated_pnl - cost_per_trade

    return {
        "target_r": target_r,
        "n_hit_target": n_hit,
        "n_sl": n_sl,
        "n_other": n_other,
        "total_n": n_hit + n_sl + n_other,
        "total_pnl_net_inr": round(total_pnl, 0),
        "hit_rate_pct": round(100 * n_hit / max(1, n_hit + n_sl + n_other), 1),
        "avg_inr_per_trade": round(total_pnl / max(1, n_hit + n_sl + n_other), 0),
    }


def actual_partials_pnl(rows: list[dict]) -> dict:
    """Aggregate the actual P&L from the partials regime as it stood."""
    total_pnl_gross = sum((r["pnl"] or 0.0) for r in rows)
    # Subtract cost: for every trade that hit TP1 (had a partial), pay COST_PER_PARTIAL_EXIT extra
    n_partials = sum(1 for r in rows if r["tp1_hit"])
    total_costs = len(rows) * COST_TOTAL_PER_TRADE + n_partials * COST_PER_PARTIAL_EXIT
    return {
        "n_total":           len(rows),
        "n_partials_taken":  n_partials,
        "total_gross_pnl":   round(total_pnl_gross, 0),
        "total_costs_inr":   round(total_costs, 0),
        "total_net_pnl":     round(total_pnl_gross - total_costs, 0),
        "avg_inr_per_trade": round((total_pnl_gross - total_costs) / max(1, len(rows)), 0),
    }


# ── Main analysis ──────────────────────────────────────────────────────────
def analyze(rows: list[dict]) -> dict:
    """Compute every metric needed for the markdown report."""
    n = len(rows)
    if n == 0:
        return {"error": "No closed trades found in DB."}

    # Realised R distribution
    rs = [r["pnl_r"] for r in rows if r["pnl_r"] is not None]
    pnls = [r["pnl"] for r in rows if r["pnl"] is not None]

    pcts_r   = percentiles(rs)
    pcts_pnl = percentiles(pnls)

    # Win rate
    wins = sum(1 for r in rows if r["status"] == "closed_win" or (r["pnl"] or 0) > 0)
    losses = n - wins

    # TP1 hit rate
    tp1_hits = sum(1 for r in rows if r["tp1_hit"])

    # Outcome buckets
    buckets = Counter(classify_exit(r["exit_reason"], r["status"], r["tp1_hit"] or 0) for r in rows)

    # Of trades that hit TP1, what happened next?
    tp1_then_sl    = buckets.get("tp1_then_sl", 0)
    tp1_only       = buckets.get("tp1_only", 0)
    tp1_trailed    = buckets.get("tp1_then_trailed", 0)
    tp1_to_runner  = tp1_trailed + buckets.get("tp2_or_runner", 0)

    # Time to TP1 (where data permits)
    times_to_tp1_min: list[float] = []
    for r in rows:
        if r["tp1_hit"] and r["entry_time"] and r["exit_time"]:
            try:
                e = datetime.fromisoformat(r["entry_time"])
                x = datetime.fromisoformat(r["exit_time"])
                # tp1 was hit at-or-before exit; without partial timestamps we use exit_time as upper bound
                delta_min = (x - e).total_seconds() / 60.0
                if 0 < delta_min < 360:    # bounded sanity check
                    times_to_tp1_min.append(delta_min)
            except Exception:
                pass

    # Counterfactual single-target sims
    sim_06r = simulate_single_target(rows, 0.6)
    sim_08r = simulate_single_target(rows, 0.8)
    sim_10r = simulate_single_target(rows, 1.0)
    actual  = actual_partials_pnl(rows)

    # Setup-level summary (helpful but real audit lives in setup_audit.py)
    by_setup: dict[str, list] = {}
    for r in rows:
        by_setup.setdefault(r["setup_type"] or "unknown", []).append(r["pnl_r"] or 0)

    return {
        "n_total":            n,
        "n_wins":             wins,
        "n_losses":           losses,
        "wr_pct":             round(100 * wins / n, 1),
        "tp1_hit_rate_pct":   round(100 * tp1_hits / n, 1),

        "r_pcts":             {p: round(v, 2) if v is not None else None for p, v in pcts_r.items()},
        "pnl_pcts":           {p: round(v, 0) if v is not None else None for p, v in pcts_pnl.items()},
        "mean_r":             round(safe_avg(rs), 3),
        "median_r":           round(safe_median(rs), 3),
        "mean_pnl_inr":       round(safe_avg(pnls), 0),
        "median_pnl_inr":     round(safe_median(pnls), 0),

        "exit_buckets":       dict(buckets.most_common()),

        "tp1_then_sl_pct":     round(100 * tp1_then_sl / max(1, tp1_hits), 1),
        "tp1_only_pct":        round(100 * tp1_only / max(1, tp1_hits), 1),
        "tp1_to_runner_pct":   round(100 * tp1_to_runner / max(1, tp1_hits), 1),

        "time_to_tp1_min_p50": round(safe_median(times_to_tp1_min), 1) if times_to_tp1_min else None,
        "time_to_tp1_min_p90": round(percentiles(times_to_tp1_min, (90,))[90], 1) if times_to_tp1_min else None,

        "sim_single_target_06r": sim_06r,
        "sim_single_target_08r": sim_08r,
        "sim_single_target_10r": sim_10r,
        "actual_partials":       actual,

        "by_setup_n":         {k: len(v) for k, v in by_setup.items()},
        "by_setup_avg_r":     {k: round(safe_avg(v), 3) for k, v in by_setup.items()},
    }


# ── Markdown report ────────────────────────────────────────────────────────
def render_markdown(stats: dict, db_path: Path) -> str:
    if "error" in stats:
        return f"# Exit Distribution Analysis\n\nERROR: {stats['error']}\n"

    # Decision logic — codified per docs/07 §3.1
    median_r = stats["median_r"]
    tp1_then_sl = stats["tp1_then_sl_pct"]
    if median_r < 1.0 and tp1_then_sl > 25:
        decision = "🔴 **KILL PARTIALS — go single-target.**"
        rationale = (
            f"Median R is {median_r:.2f} (< 1.0 threshold) AND {tp1_then_sl:.1f}% of TP1 hits "
            "reverse to SL on the runner. Partials pay double round-trip costs while the runner "
            "actively bleeds. Single-target eliminates both problems."
        )
    elif median_r >= 1.0 and tp1_then_sl < 15:
        decision = "🟢 **KEEP PARTIALS — runners are earning.**"
        rationale = (
            f"Median R is {median_r:.2f} (≥ 1.0) AND only {tp1_then_sl:.1f}% of TP1 hits reverse "
            "to SL. The runner half is earning enough to justify the double cost."
        )
    else:
        decision = "🟡 **MIXED SIGNAL — compare net P&L of simulations below.**"
        rationale = (
            f"Median R {median_r:.2f}, TP1-then-SL rate {tp1_then_sl:.1f}%. Neither side wins "
            "cleanly. Use the simulation block below to decide on net P&L grounds."
        )

    actual_net = stats["actual_partials"]["total_net_pnl"]
    sim06_net  = stats["sim_single_target_06r"]["total_pnl_net_inr"]
    sim08_net  = stats["sim_single_target_08r"]["total_pnl_net_inr"]
    sim10_net  = stats["sim_single_target_10r"]["total_pnl_net_inr"]

    md = f"""# Exit Distribution Analysis

*Generated: {datetime.now().isoformat(timespec='seconds')} | DB: `{db_path.name}` | n = {stats['n_total']} closed trades*

> Read-only analysis. Informs Phase A decision: single-target vs partials.

---

## ⚡ DECISION

{decision}

{rationale}

**Net P&L comparison after realistic Indian intraday costs (₹{COST_TOTAL_PER_TRADE:.0f}/trade fixed + ₹{COST_PER_PARTIAL_EXIT:.0f}/partial-exit):**

| Strategy | Net P&L (₹) | Avg ₹/trade | Hit rate |
|---|---:|---:|---:|
| **Actual (current partials)** | {actual_net:+,.0f} | {stats['actual_partials']['avg_inr_per_trade']:+,.0f} | TP1 {stats['tp1_hit_rate_pct']}% |
| Simulated single-target @ 0.6R | {sim06_net:+,.0f} | {stats['sim_single_target_06r']['avg_inr_per_trade']:+,.0f} | {stats['sim_single_target_06r']['hit_rate_pct']}% |
| Simulated single-target @ 0.8R | {sim08_net:+,.0f} | {stats['sim_single_target_08r']['avg_inr_per_trade']:+,.0f} | {stats['sim_single_target_08r']['hit_rate_pct']}% |
| Simulated single-target @ 1.0R | {sim10_net:+,.0f} | {stats['sim_single_target_10r']['avg_inr_per_trade']:+,.0f} | {stats['sim_single_target_10r']['hit_rate_pct']}% |

---

## 1. Headline numbers

- **Total closed trades:** {stats['n_total']}
- **Win rate:** {stats['wr_pct']}% ({stats['n_wins']} W / {stats['n_losses']} L)
- **TP1 hit rate:** {stats['tp1_hit_rate_pct']}%
- **Mean R per trade:** {stats['mean_r']:+.3f}R
- **Median R per trade:** {stats['median_r']:+.3f}R
- **Mean ₹ per trade:** ₹{stats['mean_pnl_inr']:+,.0f}
- **Median ₹ per trade:** ₹{stats['median_pnl_inr']:+,.0f}

## 2. Realised R distribution

| Percentile | R-multiple |
|---|---:|
| p10 | {stats['r_pcts'][10]:+.2f}R |
| p25 | {stats['r_pcts'][25]:+.2f}R |
| **p50 (median)** | **{stats['r_pcts'][50]:+.2f}R** |
| p75 | {stats['r_pcts'][75]:+.2f}R |
| p90 | {stats['r_pcts'][90]:+.2f}R |

## 3. ₹ P&L distribution

| Percentile | ₹ |
|---|---:|
| p10 | {stats['pnl_pcts'][10]:+,.0f} |
| p25 | {stats['pnl_pcts'][25]:+,.0f} |
| **p50 (median)** | **{stats['pnl_pcts'][50]:+,.0f}** |
| p75 | {stats['pnl_pcts'][75]:+,.0f} |
| p90 | {stats['pnl_pcts'][90]:+,.0f} |

## 4. What happens AFTER TP1 hits

- TP1 hit then trade went on to runner / TP2: **{stats['tp1_to_runner_pct']}%**
- TP1 hit but trade reversed and stopped out (worst pattern): **{stats['tp1_then_sl_pct']}%**
- TP1 hit and exit at TP1 only (no runner): **{stats['tp1_only_pct']}%**

> If TP1-then-SL > 25%, partials are actively bleeding from runners that turn into losers.

## 5. Time to TP1

- Median: {stats['time_to_tp1_min_p50']} min  (from entry_time to exit_time as proxy)
- p90: {stats['time_to_tp1_min_p90']} min

## 6. Exit reason buckets

| Bucket | Count | % |
|---|---:|---:|"""

    for bucket, count in stats["exit_buckets"].items():
        pct = round(100 * count / stats['n_total'], 1)
        md += f"\n| {bucket} | {count} | {pct}% |"

    md += "\n\n## 7. Per-setup P&L summary (high-level — see setup_audit.py for full)\n\n| Setup | n | Mean R |\n|---|---:|---:|"
    for setup, n_trades in sorted(stats['by_setup_n'].items(), key=lambda x: -x[1]):
        avg_r = stats['by_setup_avg_r'].get(setup, 0)
        md += f"\n| {setup} | {n_trades} | {avg_r:+.3f}R |"

    md += f"""

---

## Methodology notes

1. **Cost model.** Per-trade total cost ₹{COST_TOTAL_PER_TRADE:.0f}: brokerage ₹40 + STT ₹125 +
   exchange charges ₹32 + GST ₹13 + SEBI ₹1 + stamp ₹15 = ₹226 fixed; plus realistic spread cost
   ₹500 (0.05% × 2 sides × ₹5L) and slippage ₹300 (1bp entry + 5bp stop). Calibrated for ₹5L
   average position size in MIS equity.
2. **Partials extra cost ₹{COST_PER_PARTIAL_EXIT:.0f}.** Half-position TP1 booking pays half-fixed +
   ₹250 spread/slip on the smaller leg.
3. **Single-target simulation** approximates max-favourable-excursion using realised pnl_r. True
   MFE requires candle replay (Phase A+ work). The approximation is conservative — it under-
   counts trades that touched a higher target and reversed before exit, so simulated single-
   target hit rates are likely undercounted.
4. **Net P&L** is gross sum minus per-trade fixed + partial-exit costs. Realistic for paper-to-
   live calibration but assumes single ₹5L sizing across the dataset.

---

## What happens next

- If decision = KILL PARTIALS: Phase A ships single-target exit logic + sizing to deliver
  ₹1k-5k per trade in the bottom-of-target band.
- If decision = KEEP PARTIALS: Phase A keeps the partial logic but tightens TP1 to the target
  derived from the median R distribution.
- If decision = MIXED: pick the simulation column with highest net P&L; that's the rule.

This decision is APPROVED by the operator before Phase A code change ships.
"""
    return md


# ── CLI ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db",  default="trade_state.db", help="Path to trade_state.db (default: ./trade_state.db)")
    ap.add_argument("--out", default="docs",            help="Output directory (default: docs)")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[exit-dist] Reading {db_path}...")
    rows = fetch_closed(db_path)
    print(f"[exit-dist] {len(rows)} closed trades found")

    if not rows:
        print("[exit-dist] No closed trades — nothing to analyse.")
        sys.exit(1)

    stats = analyze(rows)
    md = render_markdown(stats, db_path)

    out_path = out_dir / "05_Exit_Distribution_Analysis.md"
    out_path.write_text(md)
    print(f"[exit-dist] Report written: {out_path}")
    print(f"[exit-dist] Headline: median_R={stats['median_r']:+.2f}, "
          f"tp1_then_sl={stats['tp1_then_sl_pct']}%, "
          f"actual_net=₹{stats['actual_partials']['total_net_pnl']:+,.0f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
