"""
NSE Trading System — Main Entry Point.
Runs the full trading loop from 9:15 to 15:30 IST.

Loop:
  9:00  — Pre-market: gap analysis + system startup alert
  9:15  — Start scanning every 3 minutes
  15:00 — Force-close all open positions (EOD_CLOSE_TIME)
  15:35 — Run EOD learning job + Telegram report
  Overnight — Sleep 1 hour, re-check

Usage:
  python main.py

Controls (via system_controls.json, updated from dashboard):
  kill_switch   — pause all new entries
  min_score_entry — raise/lower score threshold live
  max_positions   — cap positions live
"""
import time
import json
import sys
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from agents.crew import TradingCrew
from jobs.eod_job import run_eod_job
from config.settings import (
    TIMEZONE, SCAN_INTERVAL_MIN, MIN_SCORE_ENTRY,
    MAX_POSITIONS, EOD_CLOSE_TIME, MARKET_OPEN, MARKET_CLOSE,
)

IST          = ZoneInfo(TIMEZONE)
CONTROL_FILE = Path("./system_controls.json")


# ─── Control file ─────────────────────────────────────────────────────────────

def load_controls() -> dict:
    defaults = {
        "kill_switch":     False,
        "min_score_entry": MIN_SCORE_ENTRY,
        "max_positions":   MAX_POSITIONS,
    }
    if CONTROL_FILE.exists():
        try:
            with open(CONTROL_FILE) as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults


# ─── Time helpers ─────────────────────────────────────────────────────────────

def _parse(t: str) -> dt_time:
    h, m = t.split(":")
    return dt_time(int(h), int(m))


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:         # Saturday or Sunday
        return False
    t = now.time()
    return _parse(MARKET_OPEN) <= t <= _parse(EOD_CLOSE_TIME)


def is_pre_market() -> bool:
    """9:00–9:15 — pre-market prep window."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt_time(9, 0) <= t < dt_time(9, 15)


def is_eod_time() -> bool:
    """15:35–15:50 — run EOD job once after close."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt_time(15, 35) <= t <= dt_time(15, 50)


def sleep_until_next_tick(elapsed_secs: float):
    """Sleep for remainder of scan interval, minimum 10 seconds."""
    sleep_secs = max(10, SCAN_INTERVAL_MIN * 60 - elapsed_secs)
    print(f"   ⏱ Next tick in {sleep_secs:.0f}s...")
    time.sleep(sleep_secs)


# ─── Pre-market prep ──────────────────────────────────────────────────────────

def run_premarket(crew: TradingCrew):
    """
    Run gap analysis on the full universe before market opens.
    Identifies gap-up and gap-down candidates.
    """
    print("\n🌅 Pre-market analysis starting...")
    try:
        from tools.pattern_tools import _gap_analysis
        from config.universe import FULL_UNIVERSE

        big_gaps = []
        for sym in FULL_UNIVERSE[:50]:    # top 50 liquid stocks
            try:
                g = _gap_analysis(sym)
                if abs(g.get("gap_pct", 0)) >= 1.5 and g.get("tradeable"):
                    big_gaps.append(g)
            except Exception:
                continue

        big_gaps.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)

        if big_gaps:
            print(f"\n   📊 Gap candidates today ({len(big_gaps)}):")
            for g in big_gaps[:10]:
                emoji = "⬆" if g["gap_pct"] > 0 else "⬇"
                print(f"     {emoji} {g['symbol']:12} {g['gap_pct']:+.2f}% — {g['reason']}")
        else:
            print("   No significant gaps today")

    except Exception as e:
        print(f"   Pre-market error: {e}")


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    print("""
╔═══════════════════════════════════════════════════╗
║     NSE Intraday Trading System v2.0              ║
║     150 stocks | 7 setups | TP1+TP2+trailing SL   ║
║     Telegram alerts | Learning tab active          ║
╚═══════════════════════════════════════════════════╝
""")

    import os
    token = os.getenv("KITE_ACCESS_TOKEN", "")
    if not token:
        print("❌ KITE_ACCESS_TOKEN not set. Run: python kite_login.py")
        sys.exit(1)

    print(f"✅ Kite token found")
    print(f"   Scan interval:  every {SCAN_INTERVAL_MIN} minutes")
    print(f"   Min score:      {MIN_SCORE_ENTRY}")
    print(f"   Max positions:  {MAX_POSITIONS}")
    print(f"   Market hours:   {MARKET_OPEN} – {MARKET_CLOSE} IST")
    print(f"\nStarting crew...\n")

    crew     = TradingCrew()
    eod_done = False
    premarket_done = False

    print("✅ Engine running. Dashboard: http://localhost:8501\n"
          "   Press Ctrl+C to stop.\n")

    while True:
        try:
            now      = datetime.now(IST)
            controls = load_controls()

            # ── Kill switch ───────────────────────────────────────────────
            if controls.get("kill_switch"):
                print(f"[{now.strftime('%H:%M')}] 🔴 Kill switch ON — paused (checking again in 60s)")
                time.sleep(60)
                continue

            # ── Pre-market gap analysis ───────────────────────────────────
            if is_pre_market() and not premarket_done:
                run_premarket(crew)
                premarket_done = True
                time.sleep(60)
                continue

            # ── Market closed ─────────────────────────────────────────────
            if not is_market_open():
                if now.weekday() < 5:
                    print(f"[{now.strftime('%H:%M')}] Market closed — sleeping 1 hour")
                else:
                    print(f"[{now.strftime('%H:%M')}] Weekend — sleeping 1 hour")
                time.sleep(3600)
                eod_done      = False
                premarket_done = False
                continue

            # ── EOD job (after 15:35) ─────────────────────────────────────
            if is_eod_time() and not eod_done:
                print(f"\n[{now.strftime('%H:%M')}] 📊 Running EOD job...")
                run_eod_job()
                eod_done = True
                print("   EOD done. Sleeping 30 min.\n")
                time.sleep(1800)
                continue

            # ── Live scan tick ────────────────────────────────────────────
            min_score = controls.get("min_score_entry", MIN_SCORE_ENTRY)
            max_pos   = controls.get("max_positions", MAX_POSITIONS)
            print(f"\n[{now.strftime('%H:%M:%S')}] ──── TICK ────  "
                  f"score≥{min_score} | max_pos={max_pos}")

            start   = time.time()
            summary = crew.run_tick()
            elapsed = time.time() - start

            print(
                f"[{now.strftime('%H:%M:%S')}] Done in {elapsed:.1f}s | "
                f"stocks={summary.get('active_stocks', 0)} | "
                f"setups={summary.get('setups_found', 0)} | "
                f"entered={summary.get('signals_scored', 0)} | "
                f"open={summary.get('open_positions', 0)} | "
                f"P&L=₹{summary.get('today_pnl', 0):+,.0f}"
            )

            sleep_until_next_tick(elapsed)

        except KeyboardInterrupt:
            print("\n\n⛔ Stopped by user. Goodbye!\n")
            break
        except Exception as e:
            import traceback
            print(f"\n[ERROR] {e}")
            traceback.print_exc()
            print("   Retrying in 60 seconds...\n")
            time.sleep(60)


if __name__ == "__main__":
    main()
