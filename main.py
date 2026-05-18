"""
NSE Trading System — Main Entry Point.
Runs the full trading loop from 9:15 to 15:30 IST.

Loop:
  9:00  — Pre-market: gap analysis + Telegram gap report
  9:15  — Start scanning every 3 minutes
  15:00 — Force-close all open positions (EOD_CLOSE_TIME)
  15:35 — Run EOD learning job + Telegram report
  Overnight — Sleep 1 hour, re-check

Usage:
  python main.py

Controls (via system_controls.json, updated from dashboard):
  kill_switch     — pause all new entries
  min_score_entry — raise/lower score threshold live
  max_positions   — cap positions live
"""
import time
import json
import sys
import logging
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
    PAPER_TRADING, PROBE_MODE_ENABLED, CAPITAL, PROBE_CAPITAL,
)

IST          = ZoneInfo(TIMEZONE)
CONTROL_FILE = Path("./system_controls.json")
LOG_DIR      = Path("./logs")


# ─── Logging setup ────────────────────────────────────────────────────────────

def setup_logging():
    """
    Creates a daily log file at logs/trading_YYYY-MM-DD.log.
    All stdout also goes to the log via StreamHandler.
    Returns the log file path.
    """
    LOG_DIR.mkdir(exist_ok=True)
    today    = datetime.now(IST).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"trading_{today}.log"

    fmt = logging.Formatter(
        "%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # File handler — one file per day
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)

    # Console handler — keeps terminal output unchanged
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Only add handlers once (avoid duplicates on reload)
    if not root.handlers:
        root.addHandler(fh)
        root.addHandler(ch)
    else:
        # Replace any existing handlers on re-init
        root.handlers.clear()
        root.addHandler(fh)
        root.addHandler(ch)

    # Redirect built-in print() through the logger so everything is captured
    import builtins
    _orig_print = builtins.print

    def _logged_print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        msg = sep.join(str(a) for a in args)
        logging.info(msg)

    builtins.print = _logged_print

    logging.info(f"📋 Logging to {log_file}")
    return log_file


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
    # Run until true market close (15:30) so _manage_positions() can force-close
    # all positions at EOD_CLOSE_TIME (15:00). Previously used EOD_CLOSE_TIME here
    # which meant run_tick() stopped at 15:00 and positions were never closed.
    return _parse(MARKET_OPEN) <= t <= _parse(MARKET_CLOSE)


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


# ─── Startup health check ─────────────────────────────────────────────────────

def health_check() -> bool:
    """
    Run pre-flight checks before the main loop starts.
    Tests: Kite token (live quote), Telegram config, SQLite DB, ChromaDB, news client.
    Returns True if all CRITICAL checks pass (Kite + DB).
    Sends a Telegram alert listing any failures.
    """
    from tools.telegram_tools import alert_health_failed
    issues  = []   # critical failures — will abort
    warnings = []  # non-fatal — just logged

    print("\n🔍 Running startup health check...")

    # ── 1. Kite token — actually fetch a live quote ───────────────────────────
    print("   [1/5] Kite token...")
    try:
        import os
        token = os.getenv("KITE_ACCESS_TOKEN", "")
        if not token:
            issues.append("KITE_ACCESS_TOKEN not set — run: python kite_login.py")
        else:
            from data.kite_client import KiteDataClient
            kite   = KiteDataClient()
            quotes = kite.get_quotes(["RELIANCE"])
            if not quotes or "RELIANCE" not in quotes:
                issues.append("Kite token invalid or expired — run: python kite_login.py")
            else:
                price = quotes["RELIANCE"].get("last_price", 0)
                print(f"        ✅ Kite OK — RELIANCE @ ₹{price:,.2f}")
    except Exception as e:
        issues.append(f"Kite connection failed: {e}")

    # ── 2. Telegram ───────────────────────────────────────────────────────────
    print("   [2/5] Telegram config...")
    try:
        import os
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            warnings.append("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — alerts disabled")
            print("        ⚠️  Telegram not configured (warnings only)")
        else:
            print("        ✅ Telegram configured")
    except Exception as e:
        warnings.append(f"Telegram config error: {e}")

    # ── 3. SQLite trade DB ────────────────────────────────────────────────────
    print("   [3/5] Trade database...")
    try:
        from memory.trade_state import TradeStateManager
        state = TradeStateManager()
        open_pos = state.get_open_positions()
        print(f"        ✅ SQLite OK — {len(open_pos)} open position(s) found")
    except Exception as e:
        issues.append(f"SQLite DB error: {e}")

    # ── 4. ChromaDB ───────────────────────────────────────────────────────────
    print("   [4/5] ChromaDB...")
    try:
        from memory.chroma_client import ChromaMemory
        ChromaMemory()
        print("        ✅ ChromaDB OK")
    except Exception as e:
        warnings.append(f"ChromaDB warning (non-fatal): {e}")
        print(f"        ⚠️  ChromaDB: {e}")

    # ── 5. News + Groq ────────────────────────────────────────────────────────
    print("   [5/5] News + Groq client...")
    try:
        from data.news_client import NewsClient
        nc = NewsClient()
        if nc._newsapi_ok:
            print("        ✅ NewsAPI OK")
        else:
            warnings.append("NewsAPI key missing — news scoring will return neutral 0.5")
            print("        ⚠️  NewsAPI key missing (non-fatal)")
        if nc._groq_ok:
            print("        ✅ Groq LLM OK")
        else:
            warnings.append("Groq key missing — rule-based sentiment only")
            print("        ⚠️  Groq key missing (non-fatal)")
    except Exception as e:
        warnings.append(f"News client warning: {e}")
        print(f"        ⚠️  News client: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if warnings:
        for w in warnings:
            print(f"   ⚠️  {w}")
        print()

    if issues:
        print(f"❌ Health check FAILED — {len(issues)} critical issue(s):")
        for i in issues:
            print(f"   • {i}")
        try:
            alert_health_failed(issues)
        except Exception:
            pass
        return False

    print("✅ Health check passed — all systems go!\n")
    return True


# ─── Pre-market prep ──────────────────────────────────────────────────────────

def run_premarket(crew: TradingCrew):
    """
    Run gap analysis on the full universe before market opens.
    Identifies gap-up and gap-down candidates.
    Sends a Telegram gap report.
    """
    print("\n🌅 Pre-market analysis starting...")
    try:
        from tools.pattern_tools import _gap_analysis
        from tools.telegram_tools import alert_premarket_gaps
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

        # Send Telegram gap report
        try:
            alert_premarket_gaps(big_gaps[:8])
            print("   📱 Pre-market gap report sent to Telegram")
        except Exception as e:
            print(f"   ⚠️  Telegram gap report failed: {e}")

    except Exception as e:
        print(f"   Pre-market error: {e}")


# ─── Main loop ────────────────────────────────────────────────────────────────

def _assert_safe_mode():
    """
    Fix #187 (2026-05-18) — refuse to boot if PAPER_TRADING=False AND
    PROBE_MODE_ENABLED=False simultaneously.

    Why this matters:
      Without PROBE_MODE_ENABLED=True, live mode (`PAPER_TRADING=False`)
      routes real broker orders sized against the full `CAPITAL` (₹15L)
      rather than `PROBE_CAPITAL` (₹50k) — a 30× risk footgun.

      Fix #161 wired all sizing through `get_active_capital()` /
      `get_active_max_positions()` helpers (config/settings.py), but
      that only protects when PROBE_MODE_ENABLED=True. If both flags
      are False, the system trades real money at 30× intended size.

      Both flags MUST be co-flipped for the go-live procedure (see
      PROJECT_MEMORY.md "Open / pending" section + go-live playbook).
      This assertion enforces that contract at boot time.
    """
    if not PAPER_TRADING and not PROBE_MODE_ENABLED:
        msg = (
            "\n" + "=" * 70 + "\n"
            "❌ REFUSED TO BOOT — UNSAFE FLAG COMBINATION\n"
            + "=" * 70 + "\n"
            f"  PAPER_TRADING        = False  (live broker orders enabled)\n"
            f"  PROBE_MODE_ENABLED   = False  (sizes against full ₹{CAPITAL/1e5:.1f}L)\n\n"
            f"  This would risk {CAPITAL/max(PROBE_CAPITAL,1):.0f}× your intended\n"
            f"  probe size (₹{PROBE_CAPITAL:,}) on every trade.\n\n"
            "  Fix one of the following:\n"
            "    (a) Paper test:  set PAPER_TRADING=True in config/settings.py\n"
            "    (b) Live probe:  set PROBE_MODE_ENABLED=True in config/settings.py\n\n"
            "  Both flags must be co-flipped for live probe go-live.\n"
            "  See PROJECT_MEMORY.md Fix #161 + go-live procedure for details.\n"
            + "=" * 70 + "\n"
        )
        print(msg)
        sys.exit(1)


def main():
    # Set up daily log file — must be first
    log_file = setup_logging()

    # Fix #187 — refuse to boot in the unsafe (live, full-capital) mode.
    # Must fire BEFORE any other init so no DB/Kite/ChromaDB resources
    # get touched if the configuration is unsafe.
    _assert_safe_mode()

    print("""
╔═══════════════════════════════════════════════════╗
║     NSE Intraday Trading System v2.1              ║
║     150 stocks | 7 setups | TP1+TP2+trailing SL   ║
║     Telegram alerts | Learning tab active          ║
╚═══════════════════════════════════════════════════╝
""")

    # Surface the active mode + capital so it's the first thing the
    # operator sees on every boot — no ambiguity about what's running.
    mode_label = (
        "📝 PAPER" if PAPER_TRADING
        else ("🧪 LIVE-PROBE" if PROBE_MODE_ENABLED else "🟥 LIVE-FULL")
    )
    active_cap = PROBE_CAPITAL if PROBE_MODE_ENABLED else CAPITAL
    print(f"   Mode:           {mode_label}")
    print(f"   Active capital: ₹{active_cap:,}")
    print(f"   Scan interval:  every {SCAN_INTERVAL_MIN} minutes")
    print(f"   Min score:      {MIN_SCORE_ENTRY}")
    print(f"   Max positions:  {MAX_POSITIONS}")
    print(f"   Market hours:   {MARKET_OPEN} – {MARKET_CLOSE} IST")
    print(f"   Log file:       {log_file}\n")

    # ── Health check — must pass before starting ──────────────────────────────
    ok = health_check()
    if not ok:
        print("❌ Startup blocked. Fix the issues above and restart.\n"
              "   Tip: set KITE_ACCESS_TOKEN by running:  python kite_login.py\n")
        sys.exit(1)

    print("Starting crew...\n")
    crew           = TradingCrew()
    eod_done       = False
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
                if now.weekday() >= 5:
                    # Weekend — sleep 1 hour, nothing to do
                    print(f"[{now.strftime('%H:%M')}] Weekend — sleeping 1 hour")
                    time.sleep(3600)
                    eod_done       = False
                    premarket_done = False
                else:
                    # Weekday — smart sleep based on current time
                    t = now.time()
                    if t < dt_time(9, 0):
                        # Before 9:00 — sleep until exactly 9:00 AM (pre-market)
                        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
                        secs   = max(10, (target - now).total_seconds())
                        print(f"[{now.strftime('%H:%M')}] Pre-market — waking at 09:00 "
                              f"(sleeping {secs/60:.0f} min)")
                        time.sleep(secs)
                        eod_done       = False
                        premarket_done = False
                    elif t < _parse(MARKET_OPEN):
                        # 9:00–9:15 — market opens very soon, check every 30 seconds
                        print(f"[{now.strftime('%H:%M')}] Waiting for market open at 09:15...")
                        time.sleep(30)
                    else:
                        # After market close (15:30+) — sleep 1 hour
                        print(f"[{now.strftime('%H:%M')}] Market closed (EOD) — sleeping 1 hour")
                        time.sleep(3600)
                        eod_done       = False
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
            summary = crew.run_tick(min_score=min_score)
            elapsed = time.time() - start

            # Best open position P&L
            best_str = ""
            if summary.get("best_open_sym"):
                best_str = (f" | 📌 {summary['best_open_sym']} "
                            f"₹{summary['best_open_pnl']:+,.0f}")

            print(
                f"[{now.strftime('%H:%M:%S')}] Done in {elapsed:.1f}s | "
                f"stocks={summary.get('active_stocks', 0)} | "
                f"setups={summary.get('setups_found', 0)} | "
                f"scored={summary.get('signals_scored', 0)} | "
                f"entered={summary.get('entries', 0)} | "
                f"open={summary.get('open_positions', 0)} | "
                f"P&L=₹{summary.get('today_pnl', 0):+,.0f}"
                f"{best_str}"
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
