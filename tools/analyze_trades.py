"""
Trade-log analytics.
Run after pulling trade_state.server.db from production.
Generates console report + 10 charts in docs/charts/.

Usage:
    python tools/analyze_trades.py [path/to/trade_state.db]
    # default: ./trade_state.server.db

Outputs:
    docs/charts/pnl_histogram.png
    docs/charts/holdtime_box.png
    docs/charts/setup_winrate_pnl.png
    docs/charts/grade_calibration.png
    docs/charts/time_of_day.png
    docs/charts/score_to_pnl.png
    docs/charts/score_calibration.png
    docs/charts/equity_curve.png
    docs/charts/daily_pnl.png
    docs/charts/stall_bug.png
"""
import os
import sys
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DB_PATH   = Path(sys.argv[1] if len(sys.argv) > 1 else "trade_state.server.db")
OUT_DIR   = Path("docs/charts")
OUT_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "figure.dpi": 130,
    "axes.facecolor": "#0d1117",
    "figure.facecolor": "#0d1117",
    "axes.edgecolor": "#777",
    "axes.labelcolor": "white",
    "xtick.color": "white",
    "ytick.color": "white",
    "text.color": "white",
    "axes.titlecolor": "white",
    "axes.grid": True,
    "grid.color": "#222",
    "grid.alpha": 0.4,
})


# ─── Load + enrich ────────────────────────────────────────────────────────────

def load(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT * FROM positions WHERE status != 'open' ORDER BY exit_time",
        conn,
    )
    conn.close()
    if df.empty:
        return df

    # Parse score_breakdown JSON into separate columns
    def parse_bd(s):
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}

    df["bd"] = df["score_breakdown"].apply(parse_bd)
    for k in ["setup_quality", "volume_strength", "market_alignment",
              "relative_strength", "news_sentiment"]:
        df[k] = df["bd"].apply(lambda d: d.get(k, 0))

    # Parse times (server stores naive UTC) → IST
    df["entry_utc"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_utc"]  = pd.to_datetime(df["exit_time"],  errors="coerce")
    df["entry_ist"] = df["entry_utc"].dt.tz_localize("UTC").dt.tz_convert(IST)
    df["exit_ist"]  = df["exit_utc"].dt.tz_localize("UTC").dt.tz_convert(IST)
    df["hold_min"]  = (df["exit_utc"] - df["entry_utc"]).dt.total_seconds() / 60
    df["date_ist"]  = df["entry_ist"].dt.date
    df["hour_ist"]  = df["entry_ist"].dt.hour
    df["weekday"]   = df["entry_ist"].dt.day_name()

    # Extract regime from entry_reason where possible
    def extract_regime(r):
        if not r:
            return "unknown"
        r = r.lower()
        for x in ["trending", "recovering", "choppy", "event"]:
            if f"regime={x}" in r:
                return x
        for x in ["trending", "recovering", "choppy", "event"]:
            if x in r:
                return x
        return "unknown"

    df["regime"] = df["entry_reason"].apply(extract_regime)
    return df


# ─── Headline + slices ────────────────────────────────────────────────────────

def headline(df: pd.DataFrame):
    print("=" * 80); print("HEADLINE METRICS"); print("=" * 80)
    n = len(df)
    wins = df[df.status == "closed_win"]
    losses = df[df.status == "closed_loss"]
    pnl = df["pnl"].fillna(0)
    print(f"Total closed trades       : {n}")
    print(f"Wins / Losses             : {len(wins)} / {len(losses)}")
    print(f"Win rate                  : {len(wins)/n*100:.1f}%")
    print(f"Trading days              : {df['date_ist'].nunique()}")
    daily = df.groupby("date_ist").size()
    print(f"Trades/day mean/median/max: {daily.mean():.1f} / {daily.median():.0f} / {daily.max()}")
    print()
    print(f"Gross P&L (paper)         : Rs {pnl.sum():+,.0f}")
    print(f"Avg / median per trade    : Rs {pnl.mean():+,.0f} / Rs {pnl.median():+,.0f}")
    print(f"Avg win / loss            : Rs {wins['pnl'].mean():+,.0f} / Rs {losses['pnl'].mean():+,.0f}")
    print(f"Largest win / loss        : Rs {pnl.max():+,.0f} ({df.loc[pnl.idxmax(),'symbol']}) "
          f"/ Rs {pnl.min():+,.0f} ({df.loc[pnl.idxmin(),'symbol']})")
    gw = wins["pnl"].sum(); gl = abs(losses["pnl"].sum())
    print(f"Profit factor (gross)     : {gw/max(gl,1):.2f}")
    print()
    print(f"Avg R / win / loss        : {df['pnl_r'].mean():+.2f}R / "
          f"{wins['pnl_r'].mean():+.2f}R / {losses['pnl_r'].mean():+.2f}R")
    print(f"Avg hold (W/L/all)        : {wins['hold_min'].mean():.0f} / "
          f"{losses['hold_min'].mean():.0f} / {df['hold_min'].mean():.0f} min")
    print()
    # Concentration
    total = pnl.sum()
    print(f"Top-1 trade  : {df.nlargest(1,'pnl')['pnl'].sum()/total*100:.1f}% of total P&L")
    print(f"Top-5 trades : {df.nlargest(5,'pnl')['pnl'].sum()/total*100:.1f}%")
    print(f"Top-10 trades: {df.nlargest(10,'pnl')['pnl'].sum()/total*100:.1f}%")


def slice_(df: pd.DataFrame, key, label: str):
    print("=" * 80); print(f"BY {label.upper()}"); print("=" * 80)
    g = df.groupby(key).agg(
        n=("pnl", "size"),
        wins=("status", lambda s: (s == "closed_win").sum()),
        losses=("status", lambda s: (s == "closed_loss").sum()),
        avg_pnl=("pnl", "mean"),
        total_pnl=("pnl", "sum"),
        avg_r=("pnl_r", "mean"),
        avg_score=("score", "mean"),
        avg_hold=("hold_min", "mean"),
    )
    g["win_rate_%"] = (g["wins"] / g["n"] * 100).round(1)
    pf = {}
    for k, sub in df.groupby(key):
        gw = sub.loc[sub.status == "closed_win", "pnl"].sum()
        gl = abs(sub.loc[sub.status == "closed_loss", "pnl"].sum())
        pf[k] = round(gw / max(gl, 1), 2)
    g["pf"] = g.index.map(pf)
    g = g.sort_values("total_pnl", ascending=False)
    print(g.to_string()); print()


def calibration(df: pd.DataFrame):
    print("=" * 80); print("SCORE-BUCKET CALIBRATION"); print("=" * 80)
    df = df.copy()
    df["bucket"] = (df["score"].fillna(0) * 2).round() / 2
    cal = df.groupby("bucket").agg(
        n=("pnl", "size"),
        win_rate=("status", lambda s: (s == "closed_win").mean() * 100),
        avg_pnl=("pnl", "mean"),
        avg_r=("pnl_r", "mean"),
    )
    print(cal.to_string()); print()


def costs_simulated(df: pd.DataFrame):
    print("=" * 80); print("ZERODHA COST-STACK SIMULATION"); print("=" * 80)
    df = df.copy()
    df["entry_val"] = df["entry_price"] * df["quantity"]
    df["exit_val"]  = df["exit_price"]  * df["quantity"]
    df["turnover"]  = df["entry_val"] + df["exit_val"]
    df["brokerage"] = df["turnover"].apply(lambda x: 2 * min(20, 0.0003 * x / 2))
    df["stt"]       = 0.00025 * df["exit_val"]
    df["exch"]      = 0.0000322 * df["turnover"]
    df["sebi"]      = 0.000001 * df["turnover"]
    df["gst"]       = 0.18 * (df["brokerage"] + df["exch"] + df["sebi"])
    df["stamp"]     = 0.00003 * df["entry_val"]
    df["costs"]     = df[["brokerage","stt","exch","sebi","gst","stamp"]].sum(axis=1)
    df["net_pnl"]   = df["pnl"].fillna(0) - df["costs"]

    print(f"Total turnover            : Rs {df['turnover'].sum():>15,.0f}")
    print(f"Total simulated costs     : Rs {df['costs'].sum():>15,.0f}")
    print(f"Effective round-trip rate : {df['costs'].sum()/df['turnover'].sum()*100:.4f}%")
    print(f"Gross P&L                 : Rs {df['pnl'].sum():>15,.0f}")
    print(f"Net-of-cost P&L           : Rs {df['net_pnl'].sum():>15,.0f}")
    flipped = df[(df["pnl"] > 0) & (df["net_pnl"] < 0)]
    print(f"Wins that flipped to loss : {len(flipped)} of {(df['pnl']>0).sum()}")
    real_wins = df[(df.status == "closed_win") & (df["net_pnl"] > 0)]
    in_band = real_wins[(real_wins["net_pnl"] >= 1500) & (real_wins["net_pnl"] <= 3000)]
    above   = real_wins[real_wins["net_pnl"] > 3000]
    print(f"Trades in 1500-3000 band  : {len(in_band)}")
    print(f"Trades > 3000 net win     : {len(above)}")


# ─── Charts ───────────────────────────────────────────────────────────────────

def chart_pnl_histogram(df, out):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    wins = df[df.status == "closed_win"]["pnl"]
    losses = df[df.status == "closed_loss"]["pnl"]
    ax.hist(losses, bins=np.linspace(-3500, 3000, 30), color="#F44336", alpha=0.75,
            label=f"Losses ({len(losses)})")
    ax.hist(wins, bins=np.linspace(-3500, max(65000, wins.max()+1), 60), color="#00C853",
            alpha=0.75, label=f"Wins ({len(wins)})")
    ax.set_yscale("log")
    ax.set_xlabel("Trade P&L (₹)"); ax.set_ylabel("Count (log)")
    ax.set_title("P&L distribution")
    ax.legend()
    plt.tight_layout(); plt.savefig(out / "pnl_histogram.png"); plt.close()


def chart_holdtime_box(df, out):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    reasons = ["stalled_no_movement", "sl_hit", "tp2_hit", "eod_exit", "manual_exit"]
    data = [df[df.exit_reason == r]["hold_min"].values for r in reasons]
    labels = [f"{r}\n(n={len(d)})" for r, d in zip(
        ["stalled", "sl_hit", "tp2_hit", "eod", "manual"], data)]
    bp = ax.boxplot(data, tick_labels=labels, patch_artist=True)
    for patch, c in zip(bp["boxes"],
                        ["#FFD600","#F44336","#00C853","#4FC3F7","#888"]):
        patch.set_facecolor(c); patch.set_alpha(0.6)
    ax.set_yscale("log"); ax.set_ylabel("Hold time (minutes, log)")
    ax.set_title("Hold time by exit reason")
    ax.axhline(45, color="white", linestyle="--", alpha=0.5,
               label="Designed stall threshold (45 min)")
    ax.legend()
    plt.tight_layout(); plt.savefig(out / "holdtime_box.png"); plt.close()


def chart_setup_perf(df, out):
    g = df.groupby("setup_type").agg(
        n=("pnl", "size"),
        wr=("status", lambda s: (s == "closed_win").mean() * 100),
        total=("pnl", "sum"),
    ).sort_values("total")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    colors = ["#F44336" if w<50 else "#FFD600" if w<60 else "#00C853" for w in g["wr"]]
    ax1.barh(g.index, g["wr"], color=colors)
    for i, (n, wr) in enumerate(zip(g["n"], g["wr"])):
        ax1.text(wr+1, i, f"{wr:.0f}% ({n})", va="center")
    ax1.set_xlabel("Win rate %"); ax1.set_xlim(0, 100)
    ax1.axvline(50, color="white", linestyle="--", alpha=0.4)
    ax1.set_title("Win rate by setup")
    colors2 = ["#F44336" if t<0 else "#00C853" for t in g["total"]]
    ax2.barh(g.index, g["total"], color=colors2)
    for i, t in enumerate(g["total"]):
        ax2.text(t + (1500 if t>=0 else -1500), i, f"₹{t:+,.0f}",
                 va="center", ha="left" if t>=0 else "right")
    ax2.set_xlabel("Total P&L (₹)")
    ax2.set_title("Total P&L by setup")
    ax2.axvline(0, color="white", alpha=0.4)
    plt.tight_layout(); plt.savefig(out / "setup_winrate_pnl.png"); plt.close()


def chart_grade_calib(df, out):
    order = ["B", "A", "A+", "A++"]
    g = df.groupby("grade").agg(
        n=("pnl", "size"),
        wr=("status", lambda s: (s == "closed_win").mean() * 100),
        avg_r=("pnl_r", "mean"),
        total=("pnl", "sum"),
    ).reindex(order).dropna()
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.5))
    palette = ["#777","#00C853","#4FC3F7","#9C27B0"][:len(g)]
    axs[0].bar(g.index, g["wr"], color=palette)
    for i, (wr, n) in enumerate(zip(g["wr"], g["n"])):
        axs[0].text(i, wr+1.5, f"{wr:.1f}%\n({int(n)})", ha="center")
    axs[0].set_title("Win rate by grade"); axs[0].set_ylabel("%"); axs[0].set_ylim(0, 100)
    axs[0].axhline(50, color="white", linestyle="--", alpha=0.4)
    axs[1].bar(g.index, g["avg_r"], color=palette)
    axs[1].axhline(0, color="white", linestyle="--", alpha=0.5)
    for i, r in enumerate(g["avg_r"]):
        axs[1].text(i, r + (0.03 if r>=0 else -0.05), f"{r:+.2f}R", ha="center")
    axs[1].set_title("Avg R by grade"); axs[1].set_ylabel("R")
    colors = ["#00C853" if t>=0 else "#F44336" for t in g["total"]]
    axs[2].bar(g.index, g["total"], color=colors)
    axs[2].axhline(0, color="white", linestyle="--", alpha=0.5)
    for i, t in enumerate(g["total"]):
        axs[2].text(i, t + (3000 if t>=0 else -3000), f"₹{t:+,.0f}", ha="center")
    axs[2].set_title("Total P&L by grade"); axs[2].set_ylabel("₹")
    plt.tight_layout(); plt.savefig(out / "grade_calibration.png"); plt.close()


def chart_time_of_day(df, out):
    hr = df.groupby("hour_ist").agg(
        n=("pnl", "size"),
        wr=("status", lambda s: (s == "closed_win").mean() * 100),
        total=("pnl", "sum"),
    )
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5))
    colors = ["#F44336" if w<50 else "#FFD600" if w<60 else "#00C853" for w in hr["wr"]]
    ax1.bar(hr.index, hr["wr"], color=colors)
    for h, (wr, n) in enumerate(zip(hr["wr"], hr["n"])):
        ax1.text(hr.index[h], wr+1.5, f"{wr:.0f}%\n({int(n)})", ha="center", fontsize=9)
    ax1.set_xlabel("Entry hour (IST)"); ax1.set_ylabel("Win rate %"); ax1.set_ylim(0, 100)
    ax1.axhline(50, color="white", linestyle="--", alpha=0.4)
    ax1.set_title("Win rate by entry hour (IST, UTC-corrected)")
    ax1.set_xticks(list(hr.index))
    colors2 = ["#00C853" if t>=0 else "#F44336" for t in hr["total"]]
    ax2.bar(hr.index, hr["total"], color=colors2)
    for h, t in zip(hr.index, hr["total"]):
        ax2.text(h, t + (3500 if t>=0 else -3500), f"₹{t/1000:+.0f}k",
                 ha="center", fontsize=9)
    ax2.axhline(0, color="white", linestyle="--", alpha=0.4)
    ax2.set_title("Total P&L by entry hour")
    ax2.set_xlabel("Hour"); ax2.set_ylabel("₹")
    ax2.set_xticks(list(hr.index))
    plt.tight_layout(); plt.savefig(out / "time_of_day.png"); plt.close()


def chart_score_to_pnl(df, out):
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.5))
    colors = ["#00C853" if s == "closed_win" else "#F44336" for s in df["status"]]
    axs[0].scatter(df["score"], df["pnl"], c=colors, alpha=0.7, s=30)
    axs[0].axhline(0, color="white", alpha=0.3)
    axs[0].set_xlabel("Final score"); axs[0].set_ylabel("P&L (₹)")
    axs[0].set_title("Score → P&L (with outliers)")
    df2 = df[df["pnl"] < 10000]
    axs[1].scatter(df2["score"], df2["pnl"],
                   c=["#00C853" if s == "closed_win" else "#F44336" for s in df2["status"]],
                   alpha=0.7, s=30)
    if len(df2) > 1:
        m, b = np.polyfit(df2["score"], df2["pnl"], 1)
        xs = np.linspace(df2["score"].min(), df2["score"].max(), 50)
        axs[1].plot(xs, m*xs + b, "cyan", alpha=0.7, label=f"slope = {m:.0f} ₹/score-pt")
        axs[1].legend()
    axs[1].axhline(0, color="white", alpha=0.3)
    axs[1].set_xlabel("Final score"); axs[1].set_ylabel("P&L (₹)")
    axs[1].set_title("Score → P&L (excl. outliers)")
    plt.tight_layout(); plt.savefig(out / "score_to_pnl.png"); plt.close()


def chart_score_calib(df, out):
    df = df.copy()
    df["bucket"] = (df["score"] * 2).round() / 2
    cal = df.groupby("bucket").agg(
        n=("pnl", "size"),
        wr=("status", lambda s: (s == "closed_win").mean() * 100),
    )
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(cal.index, cal["wr"], width=0.4,
           color=["#F44336" if w<50 else "#FFD600" if w<60 else "#00C853" for w in cal["wr"]])
    for x_, (wr, n) in zip(cal.index, zip(cal["wr"], cal["n"])):
        ax.text(x_, wr+2, f"{wr:.0f}%\n({int(n)})", ha="center", fontsize=8)
    ax.axhline(50, color="white", linestyle="--", alpha=0.4)
    ax.set_xlabel("Score bucket (0.5)"); ax.set_ylabel("Win rate %"); ax.set_ylim(0, 100)
    ax.set_title("Win rate by score bucket")
    plt.tight_layout(); plt.savefig(out / "score_calibration.png"); plt.close()


def chart_equity(df, out):
    s = df.sort_values("exit_utc").reset_index(drop=True)
    s["cum"] = s["pnl"].cumsum()
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(s.index, s["cum"], color="#4FC3F7", linewidth=1.5)
    ax.fill_between(s.index, 0, s["cum"], color="#4FC3F7", alpha=0.18)
    ax.axhline(0, color="white", alpha=0.4)
    ax.set_xlabel("Trade # (chronological)"); ax.set_ylabel("Cumulative P&L (₹)")
    ax.set_title(f"Equity curve — {len(df)} trades")
    plt.tight_layout(); plt.savefig(out / "equity_curve.png"); plt.close()


def chart_daily(df, out):
    daily = df.groupby("date_ist").agg(
        n=("pnl", "size"), pnl=("pnl", "sum"),
    )
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    colors = ["#00C853" if p>0 else "#F44336" for p in daily["pnl"]]
    ax1.bar(range(len(daily)), daily["pnl"], color=colors)
    ax1.set_xticks(range(len(daily)))
    ax1.set_xticklabels([str(d) for d in daily.index], rotation=30)
    for i, (p, n) in enumerate(zip(daily["pnl"], daily["n"])):
        ax1.text(i, p + (3000 if p>0 else -3000), f"₹{p:+,.0f}\n({int(n)} tr)",
                 ha="center", fontsize=9)
    ax1.axhline(0, color="white", alpha=0.4)
    ax1.set_ylabel("Daily P&L (₹)"); ax1.set_title("Daily P&L")
    ax2.bar(range(len(daily)), daily["n"], color="#4FC3F7")
    ax2.set_ylabel("Trades that day"); ax2.set_title("Trade count by day")
    ax2.set_xlabel("Date (IST)")
    plt.tight_layout(); plt.savefig(out / "daily_pnl.png"); plt.close()


def chart_stall_bug(df, out):
    stalled = df[df.exit_reason == "stalled_no_movement"]
    if stalled.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(stalled["hold_min"], bins=40, color="#FFD600", alpha=0.85)
    ax.axvline(45, color="red", linestyle="--", label="Designed threshold (45 min)")
    ax.axvline(stalled["hold_min"].median(), color="cyan", linestyle="--",
               label=f"Actual median ({stalled['hold_min'].median():.1f} min)")
    ax.set_xlabel("Hold time (min)"); ax.set_ylabel("Count")
    ax.set_title(f"Stall-exit hold-time distribution ({len(stalled)} of {len(df)} exits)")
    ax.legend()
    plt.tight_layout(); plt.savefig(out / "stall_bug.png"); plt.close()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not DB_PATH.exists():
        sys.exit(f"DB not found: {DB_PATH}")
    df = load(DB_PATH)
    if df.empty:
        sys.exit("No closed trades in DB.")

    headline(df); print()
    slice_(df, "setup_type", "setup type")
    slice_(df, "grade", "grade")
    slice_(df, "hour_ist", "entry hour (IST)")
    slice_(df, "weekday", "weekday")
    slice_(df, "regime", "regime (extracted)")
    slice_(df, "exit_reason", "exit reason")
    slice_(df, "tp1_hit", "tp1_hit flag")
    slice_(df, "date_ist", "date (IST)")
    calibration(df)
    costs_simulated(df)

    chart_pnl_histogram(df, OUT_DIR)
    chart_holdtime_box(df, OUT_DIR)
    chart_setup_perf(df, OUT_DIR)
    chart_grade_calib(df, OUT_DIR)
    chart_time_of_day(df, OUT_DIR)
    chart_score_to_pnl(df, OUT_DIR)
    chart_score_calib(df, OUT_DIR)
    chart_equity(df, OUT_DIR)
    chart_daily(df, OUT_DIR)
    chart_stall_bug(df, OUT_DIR)

    print()
    print(f"Charts written to {OUT_DIR}/")
    for f in sorted(os.listdir(OUT_DIR)):
        size = os.path.getsize(OUT_DIR / f) / 1024
        print(f"  {f:40s} {size:6.1f} KB")


if __name__ == "__main__":
    main()
