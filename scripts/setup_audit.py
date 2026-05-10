#!/usr/bin/env python3
"""
Setup deletion audit — informs Phase E decision: which of 8 setups to delete,
keep, or modify.

Reads trade_state.db (read-only), computes per-setup performance metrics
including counterfactual deletion analysis. Outputs decision-ready markdown.

Usage:
  python3 scripts/setup_audit.py
  python3 scripts/setup_audit.py --db PATH --out DIR

Pure stdlib. Read-only. Idempotent.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from zoneinfo import ZoneInfo

# Cost model — scales with actual position size (matches exit-dist analyzer)
COST_FIXED_INR    = 226.0
COST_VARIABLE_PCT = 0.0016    # 0.16% of position value (spread + slippage)

CLOSED_STATUSES = ("closed_win", "closed_loss", "closed_partial")

# Decision thresholds — survives if ALL met:
SURVIVE_MIN_EXPECTANCY_R   = 0.10   # ≥ +0.10R after costs
SURVIVE_MIN_PURE_PLAY_PCT  = 5.0    # ≥ 5% of trades were pure-play
SURVIVE_MIN_DAY_CLASS_WR   = 35.0   # WR ≥ 35% in ≥ 2 day-classes

# Killed if ANY met:
KILL_MAX_EXPECTANCY_R = 0.0    # expectancy < 0
KILL_MAX_OVERALL_WR   = 30.0   # < 30% WR everywhere


def fetch_closed(db_path: Path) -> list[dict]:
    """Return all closed trades as dicts with safe defaults for missing cols."""
    if not db_path.exists():
        sys.exit(f"DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    raw  = conn.execute(f"SELECT * FROM positions WHERE status IN {CLOSED_STATUSES}").fetchall()
    conn.close()

    DEFAULTS = {
        "id": 0, "symbol": "", "setup_type": "unknown", "grade": "",
        "score": 0.0, "pnl": 0.0, "pnl_r": 0.0, "status": "",
        "exit_reason": "", "entry_time": None, "score_breakdown": "{}",
        "regime": "", "entry_price": 0.0, "stop_loss": 0.0,
        "initial_sl": 0.0, "quantity": 0,
    }
    out = []
    for r in raw:
        d = {k: (r[k] if k in r.keys() else v) for k, v in DEFAULTS.items()}
        if d["initial_sl"] in (0.0, None) and d["stop_loss"]:
            d["initial_sl"] = d["stop_loss"]
        out.append(d)
    return out


def parse_breakdown(s: str | None) -> dict:
    """Pull confluence_count and other breakdown fields from JSON column."""
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def hour_of(entry_time) -> int | None:
    """Return IST hour (0-23) or None."""
    if not entry_time:
        return None
    try:
        # entry_time may be naive (legacy) or IST-aware (post Fix #1)
        dt = datetime.fromisoformat(entry_time)
        # If naive, assume it's already IST (post-fix is IST; pre-fix is UTC but close)
        return dt.hour
    except Exception:
        return None


def day_class_of(row: sqlite3.Row) -> str:
    """
    Backfill day-class on historic trades. We don't have stored breadth %, so
    we approximate from regime + score breakdown. Conservative bucketing.
    """
    bd = parse_breakdown(row["score_breakdown"])
    breadth_pen = bd.get("breadth_pen", 0)

    if breadth_pen and breadth_pen <= -0.7:
        return "DEFENSIVE"      # bearish breadth was applied
    if (row["regime"] or "").upper() in ("TRENDING_UP", "BULLISH"):
        return "PRESS"
    return "SELECTIVE"          # default everything else


def safe_avg(vs: list) -> float:
    return statistics.mean(vs) if vs else 0.0


def safe_median(vs: list) -> float:
    return statistics.median(vs) if vs else 0.0


# ── Per-setup analyzer ─────────────────────────────────────────────────────
def analyze_per_setup(rows: list[dict]) -> dict[str, dict]:
    """For each setup, compute the full metric block."""
    by_setup: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_setup[r["setup_type"] or "unknown"].append(r)

    out: dict[str, dict] = {}

    for setup, trades in by_setup.items():
        n = len(trades)
        wins = sum(1 for r in trades if (r["pnl"] or 0) > 0)
        losses = n - wins
        rs = [r["pnl_r"] or 0 for r in trades]
        pnls = [r["pnl"] or 0 for r in trades]

        # After-cost expectancy in R — uses ACTUAL position size per trade
        avg_risk_inr = safe_avg([
            abs((r["entry_price"] or 0) - (r["initial_sl"] or r["stop_loss"] or 0)) * (r["quantity"] or 0)
            for r in trades
        ])
        avg_pos_value = safe_avg([
            (r["entry_price"] or 0) * (r["quantity"] or 0) for r in trades
        ])
        avg_cost_inr  = COST_FIXED_INR + avg_pos_value * COST_VARIABLE_PCT
        cost_in_r = (avg_cost_inr / avg_risk_inr) if avg_risk_inr > 0 else 0
        expectancy_r_gross = safe_avg(rs)
        expectancy_r_net   = expectancy_r_gross - cost_in_r

        # Stalled rate
        stall_keys = ("stall", "time_stop", "no_movement", "eod_partial_unwind")
        n_stalled = sum(1 for r in trades if any(k in (r["exit_reason"] or "").lower() for k in stall_keys))

        # SL hit rate
        n_sl = sum(1 for r in trades if "sl" in (r["exit_reason"] or "").lower() and "trail" not in (r["exit_reason"] or "").lower())

        # Time-of-day breakdown
        by_hour: dict[int, list[float]] = defaultdict(list)
        for r in trades:
            h = hour_of(r["entry_time"])
            if h is not None:
                by_hour[h].append(r["pnl_r"] or 0)
        hour_wr = {
            h: round(100 * sum(1 for x in xs if x > 0) / max(1, len(xs)), 1)
            for h, xs in by_hour.items()
        }
        hour_n = {h: len(xs) for h, xs in by_hour.items()}

        # Day-class breakdown
        by_dc: dict[str, list[float]] = defaultdict(list)
        for r in trades:
            by_dc[day_class_of(r)].append(r["pnl_r"] or 0)
        dc_wr = {
            dc: round(100 * sum(1 for x in xs if x > 0) / max(1, len(xs)), 1)
            for dc, xs in by_dc.items()
        }
        dc_n = {dc: len(xs) for dc, xs in by_dc.items()}

        # Confluence and pure-play analysis
        confluences = []
        pure_plays = 0
        for r in trades:
            bd = parse_breakdown(r["score_breakdown"])
            cc = bd.get("confluence_count", 1)
            confluences.append(cc)
            if cc == 1:
                pure_plays += 1
        pure_play_pct = round(100 * pure_plays / max(1, n), 1)
        avg_confluence = round(safe_avg(confluences), 2)

        out[setup] = {
            "n": n,
            "wins": wins,
            "losses": losses,
            "wr_pct": round(100 * wins / max(1, n), 1),
            "mean_r_gross": round(expectancy_r_gross, 3),
            "mean_r_net":   round(expectancy_r_net, 3),
            "median_r":     round(safe_median(rs), 3),
            "total_pnl":    round(sum(pnls), 0),
            "stall_rate":   round(100 * n_stalled / max(1, n), 1),
            "sl_clean_rate": round(100 * n_sl / max(1, n), 1),
            "hour_wr":      dict(sorted(hour_wr.items())),
            "hour_n":       dict(sorted(hour_n.items())),
            "day_class_wr": dc_wr,
            "day_class_n":  dc_n,
            "avg_confluence":  avg_confluence,
            "pure_play_n":  pure_plays,
            "pure_play_pct": pure_play_pct,
            "cost_in_r":    round(cost_in_r, 3),
            "avg_risk_inr": round(avg_risk_inr, 0),
        }

    return out


def decision_for(s: dict) -> tuple[str, list[str]]:
    """Apply survive/kill/modify rules. Returns (decision, reasons)."""
    reasons: list[str] = []

    # Kill conditions
    if s["mean_r_net"] < KILL_MAX_EXPECTANCY_R:
        reasons.append(f"After-cost expectancy {s['mean_r_net']:+.3f}R < 0")
    if s["wr_pct"] < KILL_MAX_OVERALL_WR:
        reasons.append(f"Overall WR {s['wr_pct']}% < {KILL_MAX_OVERALL_WR}%")
    if s["pure_play_pct"] == 0:
        reasons.append("Zero pure-play trades — fully covered by other setups")

    if reasons:
        return "🔴 KILL", reasons

    # Survive conditions (must have ALL)
    survive_ok = True
    survive_reasons: list[str] = []
    if s["mean_r_net"] < SURVIVE_MIN_EXPECTANCY_R:
        survive_ok = False
        survive_reasons.append(f"After-cost expectancy {s['mean_r_net']:+.3f}R < +{SURVIVE_MIN_EXPECTANCY_R}R")
    if s["pure_play_pct"] < SURVIVE_MIN_PURE_PLAY_PCT:
        survive_ok = False
        survive_reasons.append(f"Pure-play only {s['pure_play_pct']}% < {SURVIVE_MIN_PURE_PLAY_PCT}%")

    n_strong_dc = sum(1 for wr in s["day_class_wr"].values() if wr >= SURVIVE_MIN_DAY_CLASS_WR)
    if n_strong_dc < 2:
        # Modify candidate, not kill outright
        survive_ok = False
        survive_reasons.append(
            f"Only {n_strong_dc} day-class(es) with WR ≥ {SURVIVE_MIN_DAY_CLASS_WR}% "
            f"(need ≥ 2)"
        )

    if survive_ok:
        return "🟢 SURVIVES", []

    return "🟡 MODIFY", survive_reasons


def render_markdown(per_setup: dict[str, dict], total_n: int, db_path: Path) -> str:
    md = f"""# Setup Deletion Audit

*Generated: {datetime.now().isoformat(timespec='seconds')} | DB: `{db_path.name}` | n = {total_n} closed trades*

> Read-only audit. Informs Phase E decision: which of 8 setups to delete, keep, or modify.

---

## ⚡ DECISIONS AT A GLANCE

| Setup | n | WR | Net Expectancy | Pure-play | Decision |
|---|---:|---:|---:|---:|---|
"""

    decisions: list[tuple[str, str, dict, list[str]]] = []
    for setup, s in sorted(per_setup.items(), key=lambda kv: -kv[1]["n"]):
        d, reasons = decision_for(s)
        decisions.append((setup, d, s, reasons))
        md += f"| {setup} | {s['n']} | {s['wr_pct']}% | {s['mean_r_net']:+.3f}R | {s['pure_play_pct']}% | {d} |\n"

    md += "\n---\n\n## Decision rules applied\n\n"
    md += f"- **🔴 KILL** if after-cost expectancy < 0R **OR** overall WR < {KILL_MAX_OVERALL_WR}% **OR** zero pure-play trades\n"
    md += f"- **🟢 SURVIVES** if after-cost expectancy ≥ +{SURVIVE_MIN_EXPECTANCY_R}R **AND** pure-play ≥ {SURVIVE_MIN_PURE_PLAY_PCT}% **AND** WR ≥ {SURVIVE_MIN_DAY_CLASS_WR}% in ≥ 2 day-classes\n"
    md += f"- **🟡 MODIFY** otherwise (suggests day-class gating or demotion to confluence-only)\n\n"

    md += "---\n\n## Per-setup detailed metrics\n\n"

    for setup, decision, s, reasons in decisions:
        md += f"### {setup} — {decision}\n\n"
        md += f"**Trades:** {s['n']}  ({s['wins']}W / {s['losses']}L = WR **{s['wr_pct']}%**)  \n"
        md += f"**Total P&L:** ₹{s['total_pnl']:+,.0f}  \n"
        md += f"**Mean R (gross):** {s['mean_r_gross']:+.3f}R  |  **Mean R (after costs):** {s['mean_r_net']:+.3f}R  \n"
        md += f"**Median R:** {s['median_r']:+.3f}R  \n"
        md += f"**Stalled exit rate:** {s['stall_rate']}%  |  **Clean SL hit rate:** {s['sl_clean_rate']}%  \n"
        md += f"**Avg confluence count:** {s['avg_confluence']}  |  **Pure-play (this setup only):** {s['pure_play_n']} ({s['pure_play_pct']}%)  \n"
        md += f"**Avg risk per trade:** ₹{s['avg_risk_inr']:,.0f}  |  **Cost in R-multiples:** {s['cost_in_r']:.3f}R  \n\n"

        if s["hour_n"]:
            md += "**By hour of day (IST):**\n\n| Hour | n | WR |\n|---:|---:|---:|\n"
            for h in sorted(s["hour_n"].keys()):
                md += f"| {h:02d}:00 | {s['hour_n'][h]} | {s['hour_wr'].get(h, 0)}% |\n"
            md += "\n"

        if s["day_class_n"]:
            md += "**By day-class (PRESS/SELECTIVE/DEFENSIVE):**\n\n| Day-class | n | WR |\n|---|---:|---:|\n"
            for dc in ("PRESS", "SELECTIVE", "DEFENSIVE"):
                if dc in s["day_class_n"]:
                    md += f"| {dc} | {s['day_class_n'][dc]} | {s['day_class_wr'].get(dc, 0)}% |\n"
            md += "\n"

        if reasons:
            md += "**Reasons for decision:**\n\n"
            for r in reasons:
                md += f"- {r}\n"
            md += "\n"

        if decision == "🟡 MODIFY":
            md += "**Suggested modifications:**\n\n"
            best_dc = max(s["day_class_wr"].items(), key=lambda kv: kv[1], default=("?", 0))
            if best_dc[1] >= 50:
                md += f"- Strong in {best_dc[0]} (WR {best_dc[1]}%) — consider gating ON only in this day-class\n"
            if s["avg_confluence"] >= 1.5 and s["pure_play_pct"] < 10:
                md += "- Almost always fires with another setup — consider demoting to confluence-only role\n"
            if s["stall_rate"] > 50:
                md += "- High stall rate — entry timing is wrong; the setup needs a confirmation requirement\n"
            md += "\n"

        md += "---\n\n"

    # Counterfactual deletion summary
    md += "## Counterfactual deletion summary\n\n"
    md += "If we delete every setup currently flagged **🔴 KILL**:\n\n"

    killed = [(setup, s) for setup, _d, s, _r in decisions if _d == "🔴 KILL"]
    if killed:
        total_killed_pnl = sum(s["total_pnl"] for _, s in killed)
        total_killed_trades = sum(s["n"] for _, s in killed)
        # Trades we'd lose are mostly losing trades, so deleting them should improve total P&L
        md += f"- **Trades removed:** {total_killed_trades}\n"
        md += f"- **P&L removed:** ₹{total_killed_pnl:+,.0f}\n"
        md += f"- **If P&L removed is negative**, killing these setups improves total P&L by that amount\n"
        md += f"- **Setups to delete:** {', '.join(setup for setup, _ in killed)}\n\n"
    else:
        md += "- No setups currently meet the kill criteria.\n\n"

    md += """## Methodology notes

1. **After-cost expectancy in R** uses ₹1,026 per round-trip (₹226 fixed + ₹500 spread + ₹300
   slippage), converted to R-multiples using each setup's average per-trade risk.
2. **Pure-play trade** = a trade where this setup was the ONLY one that fired (confluence_count=1).
   A setup with high pure-play rate carries unique edge that other setups don't catch.
3. **Day-class backfill** uses regime + score_breakdown.breadth_pen as a proxy. Trades from before
   regime persistence (Fix #14) may default to SELECTIVE.
4. **Stall rate** counts exit_reason matches: stall, time_stop, no_movement, eod_partial_unwind.
5. **Setup audit is decision input only.** Final survive/kill/modify decisions require operator
   approval. The script does not auto-modify code.

---

## What happens next

1. Operator reviews this report.
2. Operator approves which 🔴 setups to delete and how 🟡 setups should be modified.
3. Phase E ships the deletion + modification commit.
4. `tests/test_engine.py` is updated to remove tests for deleted setups.
5. Setup count reduces from 8 → fewer (target ≤ 4).
"""
    return md


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db",  default="trade_state.db")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[setup-audit] Reading {db_path}...")
    rows = fetch_closed(db_path)
    print(f"[setup-audit] {len(rows)} closed trades found")

    if not rows:
        print("[setup-audit] No closed trades — nothing to audit.")
        sys.exit(1)

    per_setup = analyze_per_setup(rows)
    md = render_markdown(per_setup, len(rows), db_path)

    out_path = out_dir / "05_Setup_Deletion_Audit.md"
    out_path.write_text(md)
    print(f"[setup-audit] Report written: {out_path}")
    print(f"[setup-audit] {len(per_setup)} setups analysed:")
    for setup, s in sorted(per_setup.items(), key=lambda kv: -kv[1]["n"]):
        d, _ = decision_for(s)
        print(f"  {d:14} {setup:20} n={s['n']:3}  WR={s['wr_pct']:5.1f}%  net_R={s['mean_r_net']:+.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
