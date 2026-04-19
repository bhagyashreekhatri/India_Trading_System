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
from config.settings import TIMEZONE, SCAN_INTERVAL_MIN, MIN_SCORE_ENTRY, MAX_POSITIONS

IST = ZoneInfo(TIMEZONE)
CONTROL_FILE = Path("./system_controls.json")

def load_controls():
    defaults = {"kill_switch": False, "min_score_entry": MIN_SCORE_ENTRY, "max_positions": MAX_POSITIONS}
    if CONTROL_FILE.exists():
        try:
            saved = json.load(open(CONTROL_FILE))
            defaults.update(saved)
        except: pass
    return defaults

def is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt_time(9, 20) <= t <= dt_time(15, 0)

def is_eod_time():
    now = datetime.now(IST)
    return dt_time(15, 35) <= now.time() <= dt_time(15, 45)

def main():
    print("""
╔══════════════════════════════════════════╗
║     NSE Trading System — Starting        ║
╚══════════════════════════════════════════╝
""")
    import os
    if not os.getenv("KITE_ACCESS_TOKEN"):
        print("❌ KITE_ACCESS_TOKEN missing. Run: python kite_login.py")
        sys.exit(1)
    print("✅ Kite token found")
    print(f"   Scan interval: every {SCAN_INTERVAL_MIN} minutes")
    print(f"   Min score: {MIN_SCORE_ENTRY} | Max positions: {MAX_POSITIONS}")

    crew = TradingCrew()
    eod_done = False
    print("\nEngine running. Press Ctrl+C to stop.\n")

    while True:
        try:
            now = datetime.now(IST)
            controls = load_controls()

            if controls.get("kill_switch"):
                print(f"[{now.strftime('%H:%M')}] Kill switch ON — paused")
                time.sleep(60)
                continue

            if not is_market_open():
                print(f"[{now.strftime('%H:%M')}] Market closed — sleeping 1 hour")
                time.sleep(3600)
                eod_done = False
                continue

            if is_eod_time() and not eod_done:
                print(f"[{now.strftime('%H:%M')}] Running EOD job...")
                run_eod_job()
                eod_done = True

            print(f"\n[{now.strftime('%H:%M:%S')}] Starting tick...")
            start = time.time()
            summary = crew.run_tick()
            elapsed = time.time() - start

            print(f"[{now.strftime('%H:%M:%S')}] Tick done in {elapsed:.1f}s — stocks={summary.get('active_stocks',0)} setups={summary.get('setups_found',0)} signals={summary.get('signals_scored',0)}")

            sleep_secs = max(10, SCAN_INTERVAL_MIN * 60 - elapsed)
            print(f"   Next tick in {sleep_secs:.0f}s...")
            time.sleep(sleep_secs)

        except KeyboardInterrupt:
            print("\n\n⛔ Stopped by user.")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            print("   Waiting 60s before retry...")
            time.sleep(60)

if __name__ == "__main__":
    main()
