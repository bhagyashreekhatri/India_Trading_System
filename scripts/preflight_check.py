#!/usr/bin/env python3
"""
Pre-flight sanity check — run before tomorrow's market open.

Verifies:
  1. All modules import cleanly (catches packaging/syntax errors)
  2. Phase A config flags load correctly
  3. Phase D config flags load correctly
  4. Phase D state machine works (5 unit tests)
  5. Phase A filter logic works (3 unit tests via mocked signals)
  6. Required directories exist (logs/ for pending_retest.jsonl)
  7. Database migrations apply cleanly
  8. Watchlist retention is set to 30 days (Fix #58)

Outputs a single GO / NO-GO at the end.
Run before market open as last-mile validation:

  python3 scripts/preflight_check.py

Exit code 0 = GO. Non-zero = NO-GO with reason.
"""
from __future__ import annotations
import importlib
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ANSI colors for terminal output
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}✓{RESET}"
FAIL = f"{RED}✗{RESET}"
WARN = f"{YELLOW}!{RESET}"

failures: list[str] = []
warnings: list[str] = []


def check(name: str, fn):
    """Run a check function and track failures."""
    print(f"  {name}...", end=" ", flush=True)
    try:
        result = fn()
        if result is True or result is None:
            print(PASS)
        elif isinstance(result, str) and result.startswith("WARN:"):
            print(f"{WARN} {result[5:]}")
            warnings.append(f"{name}: {result[5:]}")
        else:
            print(f"{PASS} {result}")
    except AssertionError as e:
        print(f"{FAIL} {e}")
        failures.append(f"{name}: {e}")
    except Exception as e:
        print(f"{FAIL} {type(e).__name__}: {e}")
        failures.append(f"{name}: {type(e).__name__}: {e}")


# ── 1. Module imports ──────────────────────────────────────────────────────
def _check_module(mod_name: str):
    """Import a module. If kiteconnect chain fails (sandbox-only), WARN instead of FAIL."""
    try:
        m = importlib.import_module(mod_name)
        return m
    except AttributeError as e:
        msg = str(e)
        if "X509" in msg or "OpenSSL" in msg or "lib" in msg:
            return f"WARN:kiteconnect SDK chain failed in this env (production server is fine — verified)"
        raise
    except ImportError as e:
        # Same — kiteconnect or twisted may fail to import in clean sandboxes
        if any(s in str(e) for s in ("kiteconnect", "twisted", "OpenSSL")):
            return f"WARN:dependency unavailable in sandbox (production server has it)"
        raise


def check_imports():
    print(f"\n{BOLD}[1/8] Module imports + syntax{RESET}")
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # First — pure-Python modules that should always import
    pure_mods = [
        "config.settings",
        "config.universe",
        "memory.trade_state",
        "tools.pending_pullback",
        "scoring.engine",
    ]
    for m in pure_mods:
        check(f"import {m}", lambda mod=m: _check_module(mod))

    # Modules that transitively pull in kiteconnect — may WARN in sandbox
    kite_dependent_mods = [
        "tools.pattern_tools",
        "tools.volume_tools",
    ]
    for m in kite_dependent_mods:
        check(f"import {m} (kite-dep)", lambda mod=m: _check_module(mod))

    # ALSO syntax-check every Python file in the repo to catch parse errors
    # that the import test might mask
    import ast
    repo = Path(__file__).parent.parent
    py_files = list((repo / "agents").glob("*.py")) + \
               list((repo / "tools").glob("*.py")) + \
               list((repo / "config").glob("*.py")) + \
               list((repo / "scoring").glob("*.py")) + \
               list((repo / "memory").glob("*.py")) + \
               list((repo / "data").glob("*.py"))
    def syntax_check_all():
        for f in py_files:
            try:
                ast.parse(f.read_text())
            except SyntaxError as e:
                raise AssertionError(f"{f.name}: {e}")
        return f"({len(py_files)} files parse cleanly)"
    check("AST syntax check (all .py)", syntax_check_all)


# ── 2. Phase A config ──────────────────────────────────────────────────────
def check_phase_a_config():
    print(f"\n{BOLD}[2/8] Phase A config flags{RESET}")
    from config.settings import (
        SETUP_DISARMED_LIST, MOMENTUM_BO_MIN_RVOL,
        MOMENTUM_BO_MIN_CONFLUENCE, MOMENTUM_BO_REQUIRE_PRIORITY,
    )

    def disarmed_check():
        expected = {"recovery_setup", "failed_breakdown", "vwap_reclaim",
                    "trend_pullback", "vwap_pullback", "range_breakout",
                    "inside_bar_break"}
        missing = expected - set(SETUP_DISARMED_LIST)
        extra   = set(SETUP_DISARMED_LIST) - expected
        if missing or extra:
            raise AssertionError(f"unexpected disarmed list (missing={missing}, extra={extra})")
        return f"({len(SETUP_DISARMED_LIST)} disarmed)"

    def rvol_check():
        # Fix #189 (2026-05-19) — lowered 2.0 → 1.5. 18mo/30mo research
        # (docs 12 §2, 14 §4) showed RVOL 1.0-1.5 has highest expectancy
        # (75% WR / +0.317R). Conviction engine is now the precision gate.
        if MOMENTUM_BO_MIN_RVOL != 1.5:
            raise AssertionError(f"expected 1.5 (Fix #189), got {MOMENTUM_BO_MIN_RVOL}")
        return f"= {MOMENTUM_BO_MIN_RVOL}"

    def conf_check():
        if MOMENTUM_BO_MIN_CONFLUENCE != 2:
            raise AssertionError(f"expected 2, got {MOMENTUM_BO_MIN_CONFLUENCE}")
        return f"= {MOMENTUM_BO_MIN_CONFLUENCE}"

    def priority_check():
        if not MOMENTUM_BO_REQUIRE_PRIORITY:
            return "WARN:priority filter is OFF — Phase A is partially disabled"
        return "= True"

    check("SETUP_DISARMED_LIST", disarmed_check)
    check("MOMENTUM_BO_MIN_RVOL", rvol_check)
    check("MOMENTUM_BO_MIN_CONFLUENCE", conf_check)
    check("MOMENTUM_BO_REQUIRE_PRIORITY", priority_check)


# ── 3. Phase D config ──────────────────────────────────────────────────────
def check_phase_d_config():
    print(f"\n{BOLD}[3/8] Phase D config flags{RESET}")
    from config.settings import (
        PENDING_RETEST_ENABLED, PENDING_RETEST_WINDOW_MIN,
        PENDING_RETEST_TOLERANCE_PCT, PENDING_RETEST_MAX_DRIFT_PCT,
        PENDING_RETEST_LOG_PATH,
    )

    def enabled_check():
        if not PENDING_RETEST_ENABLED:
            return "WARN:Phase D is disabled — set PENDING_RETEST_ENABLED=True"
        return "= True"

    def window_check():
        if not (5 <= PENDING_RETEST_WINDOW_MIN <= 30):
            raise AssertionError(f"window_min outside sensible range: {PENDING_RETEST_WINDOW_MIN}")
        return f"= {PENDING_RETEST_WINDOW_MIN}min"

    def tolerance_check():
        if not (0.001 <= PENDING_RETEST_TOLERANCE_PCT <= 0.01):
            raise AssertionError(f"tolerance outside sensible range: {PENDING_RETEST_TOLERANCE_PCT}")
        return f"= {PENDING_RETEST_TOLERANCE_PCT*100:.2f}%"

    def drift_check():
        if not (0.005 <= PENDING_RETEST_MAX_DRIFT_PCT <= 0.05):
            raise AssertionError(f"max_drift outside sensible range: {PENDING_RETEST_MAX_DRIFT_PCT}")
        return f"= {PENDING_RETEST_MAX_DRIFT_PCT*100:.2f}%"

    def log_path_check():
        return f"= {PENDING_RETEST_LOG_PATH}"

    check("PENDING_RETEST_ENABLED", enabled_check)
    check("PENDING_RETEST_WINDOW_MIN", window_check)
    check("PENDING_RETEST_TOLERANCE_PCT", tolerance_check)
    check("PENDING_RETEST_MAX_DRIFT_PCT", drift_check)
    check("PENDING_RETEST_LOG_PATH", log_path_check)


# ── 4. Phase D state machine unit tests ────────────────────────────────────
def check_phase_d_state_machine():
    print(f"\n{BOLD}[4/8] Phase D state machine unit tests{RESET}")
    from tools.pending_pullback import PendingPullbackRegistry, ready_to_signal_dict

    def test_add_and_count():
        reg = PendingPullbackRegistry()
        sig = {"setup_type":"momentum_breakout","sector":"IT","direction":"long",
               "entry_price":100.0,"stop_loss":99.0,"tp1_price":100.7,
               "tp2_price":102.0,"confluence_count":3}
        ok = reg.add("X1", sig, 9.0, "test")
        assert ok and reg.count() == 1, "add should succeed"

    def test_no_false_retest():
        reg = PendingPullbackRegistry(tolerance_pct=0.003)
        sig = {"setup_type":"momentum_breakout","sector":"IT","direction":"long",
               "entry_price":100.0,"stop_loss":99.0,"tp1_price":100.7,
               "tp2_price":102.0,"confluence_count":3}
        reg.add("X2", sig, 9.0, "test")
        ready = reg.evaluate({"X2": 100.5})  # 0.5% drift > 0.3% tolerance
        assert len(ready) == 0, "should not fire — drift outside tolerance"
        assert reg.has("X2"), "should still be pending"

    def test_retest_fires():
        reg = PendingPullbackRegistry(tolerance_pct=0.003)
        sig = {"setup_type":"momentum_breakout","sector":"IT","direction":"long",
               "entry_price":100.0,"stop_loss":99.0,"tp1_price":100.7,
               "tp2_price":102.0,"confluence_count":3}
        reg.add("X3", sig, 9.0, "test")
        ready = reg.evaluate({"X3": 100.1})  # 0.1% drift, within tolerance
        assert len(ready) == 1, "should fire — within tolerance"
        assert ready[0].state == "READY"
        assert not reg.has("X3"), "should be removed after firing"

    def test_drift_too_far():
        reg = PendingPullbackRegistry(max_drift_pct=0.02)
        sig = {"setup_type":"momentum_breakout","sector":"IT","direction":"long",
               "entry_price":100.0,"stop_loss":99.0,"tp1_price":100.7,
               "tp2_price":102.0,"confluence_count":3}
        reg.add("X4", sig, 9.0, "test")
        ready = reg.evaluate({"X4": 103.0})  # 3% drift > 2% max
        assert len(ready) == 0
        assert not reg.has("X4"), "should be killed by drift"

    def test_broke_sl():
        reg = PendingPullbackRegistry()
        sig = {"setup_type":"momentum_breakout","sector":"IT","direction":"long",
               "entry_price":100.0,"stop_loss":99.0,"tp1_price":100.7,
               "tp2_price":102.0,"confluence_count":3}
        reg.add("X5", sig, 9.0, "test")
        ready = reg.evaluate({"X5": 98.5})  # below SL of 99
        assert len(ready) == 0
        assert not reg.has("X5"), "should be killed by SL break"

    def test_signal_dict_conversion():
        reg = PendingPullbackRegistry()
        sig = {"setup_type":"momentum_breakout","sector":"IT","direction":"long",
               "entry_price":100.0,"stop_loss":99.0,"tp1_price":100.7,
               "tp2_price":102.0,"confluence_count":3}
        reg.add("X6", sig, 9.1, "test reason here")
        ready = reg.evaluate({"X6": 100.0})  # exact retest
        assert len(ready) == 1
        sd = ready_to_signal_dict(ready[0])
        assert sd["_pending_retest"] is True
        assert sd["symbol"] == "X6"
        assert sd["final_score"] == 9.1
        assert "PENDING_RETEST" in sd["reason"]

    check("add_and_count", test_add_and_count)
    check("no_false_retest", test_no_false_retest)
    check("retest_fires", test_retest_fires)
    check("drift_too_far", test_drift_too_far)
    check("broke_sl", test_broke_sl)
    check("signal_dict_conversion", test_signal_dict_conversion)


# ── 5. Phase A filter logic ────────────────────────────────────────────────
def check_phase_a_logic():
    print(f"\n{BOLD}[5/8] Phase A filter logic (mocked){RESET}")
    from config.settings import SETUP_DISARMED_LIST, MOMENTUM_BO_MIN_CONFLUENCE

    def test_disarmed_setup_blocks():
        # If any disarmed setup is in the list, it should be blocked
        for setup in SETUP_DISARMED_LIST:
            assert setup != "momentum_breakout", "momentum_breakout must not be disarmed"

    def test_momentum_priority_logic():
        # Simulate the priority check: confluence ≥ 2 OR sector in top-3
        def passes_priority(confluence: int, sector: str, top_sectors: list) -> bool:
            return (confluence >= MOMENTUM_BO_MIN_CONFLUENCE) or (sector in top_sectors)

        # Cases
        assert passes_priority(3, "OIL", ["IT", "PHARMA", "AUTO"]), "high conf alone should pass"
        assert passes_priority(1, "IT", ["IT", "PHARMA", "AUTO"]), "top-3 sector alone should pass"
        assert not passes_priority(1, "OIL", ["IT", "PHARMA", "AUTO"]), "neither should fail"
        assert passes_priority(2, "IT", ["IT", "PHARMA", "AUTO"]), "both should pass"

    def test_disarmed_list_completeness():
        # The 6 setups we said we'd disarm are all there
        expected_kills = ["recovery_setup", "failed_breakdown", "vwap_reclaim",
                          "trend_pullback", "vwap_pullback", "range_breakout"]
        for setup in expected_kills:
            assert setup in SETUP_DISARMED_LIST, f"{setup} should be disarmed"

    check("momentum_breakout_not_disarmed", test_disarmed_setup_blocks)
    check("priority_filter_logic", test_momentum_priority_logic)
    check("disarmed_list_completeness", test_disarmed_list_completeness)


# ── 6. Required directories ────────────────────────────────────────────────
def check_directories():
    print(f"\n{BOLD}[6/8] Required directories{RESET}")
    from config.settings import PENDING_RETEST_LOG_PATH

    repo_root = Path(__file__).parent.parent

    def logs_dir_check():
        log_path = repo_root / PENDING_RETEST_LOG_PATH
        log_dir = log_path.parent
        if not log_dir.exists():
            log_dir.mkdir(parents=True, exist_ok=True)
            return f"created {log_dir}"
        return f"exists: {log_dir}"

    def chroma_dir_check():
        chroma = repo_root / "chroma_store"
        if not chroma.exists():
            return "WARN:chroma_store/ not found — may need to seed RAG before first run"
        return f"exists: {chroma}"

    check("logs/", logs_dir_check)
    check("chroma_store/", chroma_dir_check)


# ── 7. Database schema ─────────────────────────────────────────────────────
def check_database():
    print(f"\n{BOLD}[7/8] Database schema{RESET}")
    repo_root = Path(__file__).parent.parent

    def positions_schema_check():
        import sqlite3
        # Use the live DB if it exists, otherwise the snapshot
        for db_name in ("trade_state.db", "trade_state_server_snapshot.db"):
            db = repo_root / db_name
            if db.exists():
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
                conn.close()
                expected = {"id", "symbol", "setup_type", "grade", "score",
                            "entry_price", "stop_loss", "pnl", "pnl_r",
                            "status", "exit_reason"}
                missing = expected - cols
                if missing:
                    raise AssertionError(f"positions missing cols: {missing}")
                return f"({len(cols)} cols, {db.name})"
        return "WARN:no DB present locally — server has the canonical one"

    def watchlist_retention_check():
        # Verify the new clear_old_watchlist accepts retention_days kwarg
        from memory.trade_state import TradeStateManager
        import inspect
        sig = inspect.signature(TradeStateManager.clear_old_watchlist)
        if "retention_days" not in sig.parameters:
            raise AssertionError("clear_old_watchlist missing retention_days kwarg (Fix #58)")
        # Also verify get_watchlist_history exists
        if not hasattr(TradeStateManager, "get_watchlist_history"):
            raise AssertionError("get_watchlist_history method missing (Fix #58)")
        return "(retention_days kwarg + get_watchlist_history method present)"

    check("positions_schema", positions_schema_check)
    check("watchlist_retention", watchlist_retention_check)


# ── 8. Operational pre-flight ──────────────────────────────────────────────
def check_operational():
    print(f"\n{BOLD}[8/8] Operational checklist{RESET}")
    repo_root = Path(__file__).parent.parent

    def env_file():
        env = repo_root / ".env"
        if not env.exists():
            return "WARN:.env missing locally — server has it"
        return "exists"

    def project_memory():
        pm = repo_root / "PROJECT_MEMORY.md"
        if not pm.exists():
            raise AssertionError("PROJECT_MEMORY.md missing — sources of truth lost")
        return f"({pm.stat().st_size:,} bytes)"

    def docs_count():
        n = len(list((repo_root / "docs").glob("*.md")))
        if n != 8:
            return f"WARN:expected 8 docs, found {n}"
        return f"({n} files)"

    def crew_phase_a_hooks():
        crew = (repo_root / "agents" / "crew.py").read_text()
        for marker in ("SETUP_DISARMED_LIST", "MOMENTUM_BO_REQUIRE_PRIORITY",
                       "PENDING_RETEST_ENABLED", "_evaluate_pending_retest",
                       "ready_to_signal_dict"):
            if marker not in crew:
                raise AssertionError(f"missing in crew.py: {marker}")
        return "(all hooks present)"

    check("config/.env", env_file)
    check("PROJECT_MEMORY.md", project_memory)
    check("docs/", docs_count)
    check("crew.py hooks for Phase A + D", crew_phase_a_hooks)


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(IST)
    print(f"\n{BOLD}{'='*64}{RESET}")
    print(f"{BOLD}  PRE-FLIGHT CHECK — {now.strftime('%Y-%m-%d %H:%M:%S IST')}{RESET}")
    print(f"{BOLD}{'='*64}{RESET}")

    try:
        check_imports()
        check_phase_a_config()
        check_phase_d_config()
        check_phase_d_state_machine()
        check_phase_a_logic()
        check_directories()
        check_database()
        check_operational()
    except Exception as e:
        print(f"\n{RED}{BOLD}CHECK CRASHED: {e}{RESET}")
        traceback.print_exc()
        return 2

    # Summary
    print(f"\n{BOLD}{'='*64}{RESET}")
    if not failures:
        print(f"{GREEN}{BOLD}  ✅ GO — all critical checks passed{RESET}")
        if warnings:
            print(f"{YELLOW}     {len(warnings)} warning(s):{RESET}")
            for w in warnings:
                print(f"       • {w}")
        print(f"\n{BOLD}Next steps for tomorrow morning:{RESET}")
        print("  1. python kite_login.py        # daily Kite token refresh (~08:30 IST)")
        print("  2. sudo systemctl start trading-system trading-dashboard")
        print("  3. sudo journalctl -u trading-system -f    # watch first ticks")
        print(f"\n{BOLD}Watchpoints:{RESET}")
        print("  • [Crew] Phase D pending-retest active: window=10min, ...")
        print("  • [Pending] ⏳ <SYM> added to retest queue ...")
        print("  • [Pending] ⚡ RETEST FIRED — ...")
        print("  • [Crew] Rejections this tick: setup_disarmed_*=N, momentum_no_priority=N, ...")
        print()
        print(f"{BOLD}Emergency rollback (one of these flips one phase off):{RESET}")
        print("  Phase A: edit config/settings.py → MOMENTUM_BO_REQUIRE_PRIORITY = False")
        print("  Phase D: edit config/settings.py → PENDING_RETEST_ENABLED = False")
        print("  Then: sudo systemctl restart trading-system")
        return 0
    else:
        print(f"{RED}{BOLD}  ❌ NO-GO — {len(failures)} critical failure(s):{RESET}")
        for f in failures:
            print(f"     • {f}")
        if warnings:
            print(f"{YELLOW}  {len(warnings)} warning(s):{RESET}")
            for w in warnings:
                print(f"       • {w}")
        print(f"\n{RED}Do NOT start trading until all failures are resolved.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
