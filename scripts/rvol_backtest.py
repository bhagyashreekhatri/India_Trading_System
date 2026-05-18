#!/usr/bin/env python3
"""
RVOL Threshold Backtest Analyzer — Phase 2.8 offline tool.

Reads rvol_ghost.jsonl (produced by tools/rvol_ghost.py) and computes, for
each RVOL bucket, what the agent's mean R per trade WOULD have been if it
had taken the rejected setups.

Usage:
    python3 scripts/rvol_backtest.py [--ghost-file rvol_ghost.jsonl] [--out rvol_backtest_report.md]

Output:
    Markdown report with WR + mean-R per RVOL bucket.
    Suggested threshold based on positive-expectancy cutoff.

Algorithm:
    For each ghost record:
      1. Fetch 5-min candles from rejection-time to EOD (15:30 IST) for the symbol.
      2. Walk forward bar-by-bar:
         - hit SL?       → outcome=loss, R=-1.0
         - hit TP1?      → outcome=win,  R=+0.7 (per Fix #48 — TP1 at 0.7R)
         - reached EOD?  → outcome=eod,  R=(last_close - entry) / sl_distance
      3. Bucket by RVOL: [0.5-1.0), [1.0-1.5), [1.5-1.7), [1.7-2.0), [2.0-2.5), [2.5+]
      4. Per bucket: count, win-rate, mean R, expectancy
      5. Recommend the LOWEST threshold T such that all buckets with RVOL ≥ T
         have mean-R > 0.

Failure modes handled:
  - Symbol not in Kite instruments cache → skip
  - Kite get_candles fails → skip (log warning)
  - Zero stop distance → skip (bad signal)
"""
import argparse
import json
import sys
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rvol_ghost import read_all_records


BUCKETS = [
    (0.5, 1.0, "[0.5-1.0)"),
    (1.0, 1.5, "[1.0-1.5)"),
    (1.5, 1.7, "[1.5-1.7)"),
    (1.7, 2.0, "[1.7-2.0)"),
    (2.0, 2.5, "[2.0-2.5)"),
    (2.5, 99.0, "[2.5+]"),
]


def bucket_for(rvol: float) -> str:
    for lo, hi, label in BUCKETS:
        if lo <= rvol < hi:
            return label
    return "UNKNOWN"


def compute_outcome(rec: dict, kite_client) -> dict:
    """
    Walk forward through 5-min candles from rejection time → EOD.
    Returns dict with outcome ('win'/'loss'/'eod'), pnl_r, exit_bar.

    For a LONG trade:
      - SL hit if any subsequent bar's low ≤ stop_loss
      - TP1 hit if any subsequent bar's high ≥ tp1_price
      - Otherwise outcome=eod, pnl_r computed from final close
    For SHORT, mirror.
    """
    sym = rec["symbol"]
    entry = rec["entry_price"]
    sl    = rec["stop_loss"]
    tp1   = rec["tp1_price"]
    direction = rec.get("direction", "long")

    sl_dist = abs(entry - sl)
    if sl_dist < 1e-6:
        return {"outcome": "skip_bad_sl", "pnl_r": 0.0}

    try:
        df = kite_client.get_candles(sym, interval="5minute", days=2)
    except Exception as e:
        return {"outcome": "skip_fetch_err", "pnl_r": 0.0, "err": str(e)[:80]}
    if df is None or len(df) == 0:
        return {"outcome": "skip_no_data", "pnl_r": 0.0}

    # Filter to bars after rejection-ts on the same trading day
    try:
        rej_dt = datetime.fromisoformat(rec["ts_iso"])
    except Exception:
        return {"outcome": "skip_bad_ts", "pnl_r": 0.0}

    rej_date = rej_dt.date()
    df["_d"] = df["date"].apply(lambda d: d.date() if hasattr(d, "date") else d)
    df = df[df["_d"] == rej_date]
    # Bars STRICTLY AFTER the rejection moment
    df = df[df["date"] > rej_dt.replace(tzinfo=None)]
    if len(df) == 0:
        return {"outcome": "skip_no_post_bars", "pnl_r": 0.0}

    # Walk forward
    for _, bar in df.iterrows():
        high = float(bar["high"])
        low  = float(bar["low"])
        if direction == "long":
            # Standard convention: SL hits BEFORE TP1 if both range-cross in
            # the same bar (conservative)
            if low <= sl:
                return {"outcome": "loss", "pnl_r": -1.0, "exit_bar": str(bar["date"])}
            if high >= tp1:
                return {"outcome": "win", "pnl_r": +0.7, "exit_bar": str(bar["date"])}
        else:
            if high >= sl:
                return {"outcome": "loss", "pnl_r": -1.0, "exit_bar": str(bar["date"])}
            if low <= tp1:
                return {"outcome": "win", "pnl_r": +0.7, "exit_bar": str(bar["date"])}

    # EOD without hitting SL or TP1
    final_close = float(df.iloc[-1]["close"])
    if direction == "long":
        pnl_r = (final_close - entry) / sl_dist
    else:
        pnl_r = (entry - final_close) / sl_dist
    return {"outcome": "eod", "pnl_r": round(pnl_r, 3), "exit_bar": str(df.iloc[-1]["date"])}


def aggregate(records: list[dict], outcomes: list[dict]) -> dict:
    """Bucket and stat."""
    by_bucket = defaultdict(list)
    for r, o in zip(records, outcomes):
        if o["outcome"].startswith("skip"):
            continue
        b = bucket_for(r["rvol"])
        by_bucket[b].append(o["pnl_r"])

    summary = {}
    for label in [b[2] for b in BUCKETS]:
        rs = by_bucket.get(label, [])
        if not rs:
            summary[label] = {"n": 0, "wr": None, "mean_r": None, "median_r": None}
            continue
        wins = sum(1 for r in rs if r > 0)
        summary[label] = {
            "n": len(rs),
            "wr": round(100 * wins / len(rs), 1),
            "mean_r": round(sum(rs) / len(rs), 3),
            "median_r": round(sorted(rs)[len(rs) // 2], 3),
        }
    return summary


def render_report(summary: dict, ghost_count: int, outcome_count: int) -> str:
    lines = [
        "# RVOL Threshold Backtest Report",
        "",
        f"*Generated: {datetime.now().isoformat(timespec='minutes')}*",
        "",
        f"Total ghost rejections recorded: **{ghost_count}**",
        f"Outcomes computed (after Kite fetches): **{outcome_count}**",
        "",
        "## Per-RVOL-bucket performance",
        "",
        "| RVOL bucket | N | Win rate | Mean R | Median R |",
        "|---|---|---|---|---|",
    ]
    for label in [b[2] for b in BUCKETS]:
        s = summary[label]
        if s["n"] == 0:
            lines.append(f"| `{label}` | 0 | — | — | — |")
        else:
            lines.append(
                f"| `{label}` | {s['n']} | {s['wr']}% | "
                f"{s['mean_r']:+.3f} | {s['median_r']:+.3f} |"
            )
    lines += [
        "",
        "## Recommendation",
        "",
    ]
    # Find lowest bucket with positive expectancy
    recommended = None
    for lo, hi, label in BUCKETS:
        s = summary[label]
        if s["n"] >= 5 and s["mean_r"] is not None and s["mean_r"] > 0:
            recommended = (lo, label, s)
            break

    if recommended:
        lo, label, s = recommended
        lines.append(
            f"Lowest RVOL bucket with positive mean-R AND n ≥ 5 is **`{label}`** "
            f"(n={s['n']}, WR={s['wr']}%, mean R={s['mean_r']:+.3f})."
        )
        lines.append(
            f"Suggested `MOMENTUM_BO_MIN_RVOL` setting: **{lo}** (was 2.0)."
        )
        lines.append("")
        lines.append(
            "Caveat: bucket with n < 5 is insufficient sample; we'd want n ≥ 20 "
            "before flipping the production threshold."
        )
    else:
        lines.append(
            "No bucket yet has n ≥ 5 with positive mean-R. **Keep `MOMENTUM_BO_MIN_RVOL=2.0`**. "
            "Re-run after another week of accumulated data."
        )

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ghost-file", default="rvol_ghost.jsonl")
    p.add_argument("--out", default="docs/rvol_backtest_report.md")
    p.add_argument("--limit", type=int, default=0, help="cap records processed (for testing)")
    args = p.parse_args()

    records = read_all_records(args.ghost_file)
    if args.limit:
        records = records[: args.limit]
    if not records:
        print(f"No ghost records found at {args.ghost_file}. Run the agent for "
              f"a few sessions first to accumulate data.")
        sys.exit(0)

    # Lazy-import Kite (the analyzer can run from any host with valid token)
    try:
        from data.kite_client import KiteDataClient
        kite = KiteDataClient()
    except Exception as e:
        print(f"Kite client init failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(records)} ghost records...")
    outcomes = []
    for i, r in enumerate(records):
        if i % 10 == 0 and i > 0:
            print(f"  ... {i}/{len(records)}")
        outcomes.append(compute_outcome(r, kite))

    skipped = sum(1 for o in outcomes if o["outcome"].startswith("skip"))
    computed = len(outcomes) - skipped
    print(f"Computed: {computed}  |  Skipped: {skipped}")

    summary = aggregate(records, outcomes)
    report = render_report(summary, ghost_count=len(records), outcome_count=computed)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"\nReport written to {out_path}")
    print("\n" + report)


if __name__ == "__main__":
    main()
