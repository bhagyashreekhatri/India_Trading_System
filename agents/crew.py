"""
TradingCrew — pure Python orchestrator.
No CrewAI, no LLM except Groq for news sentiment only.

Architecture (8 logical agents):
  1. MarketScanner      — filters 150 stocks to active candidates
  2. RegimeDetector     — TRENDING/CHOPPY/RECOVERING/EVENT
  3. BreadthAnalyzer    — market breadth + sector strength
  4. SetupDetector      — 7 setup types (ORB, VWAP, breakout, etc.)
  5. VolumeRSAnalyzer   — volume + relative strength confirmation
  6. NewsSentimentAgent — NewsAPI + Groq LLM (only LLM call)
  7. ScoringAgent       — ScoringEngine → grade + score
  8. PositionManager    — TP1/TP2/trailing SL/EOD exits + Telegram

Run: TradingCrew().run_tick()
"""
import json
from math import floor
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

STATUS_FILE = Path("./system_status.json")

from data.kite_client import KiteDataClient
# Fix #197 (2026-05-19) — NewsClient import removed. Was used only by the
# now-deleted `_get_news` method (Fix #185 + Fix #197 removed it from the
# scoring hot path). Class itself remains at data/news_client.py for
# main.py's preflight health check.
from memory.trade_state import TradeStateManager, WatchlistItem
from memory.chroma_client import ChromaMemory

from scoring.engine import (
    ScoringEngine, RawSignal, VolumeData, MarketContext,
    RelativeStrengthData, NewsData,
    SetupType, RegimeType, SignalDirection,
    _round_to_tick, _round_down_tick, _round_up_tick,
)

from tools.pattern_tools import _detect_setups_multi
from tools.volume_tools   import _compute_breadth, _compute_sector_strength
from tools.pending_pullback import PendingPullbackRegistry, ready_to_signal_dict
from tools.telegram_tools import (
    alert_trade_entry, alert_tp1_hit, alert_trade_exit,
    alert_trailing_sl_moved, alert_consecutive_losses,
    alert_market_breadth, alert_eod_report, alert_system_start,
)

from config.universe import FULL_UNIVERSE, get_sector
from config.settings import (
    CAPITAL, RISK_PER_TRADE_PCT, MAX_POSITIONS, MAX_SAME_SECTOR_POSITIONS,
    MAX_CONSECUTIVE_LOSSES, CONSERVATIVE_SIZE_PCT, MAX_POSITION_VALUE_PCT,
    TARGET_R1, TARGET_R2, TIMEZONE,
    TRAILING_SL_ENABLED, TRAILING_ATR_MULTIPLIER,
    BREADTH_BULLISH, BREADTH_BEARISH, MOMENTUM_BO_MIN_RVOL, SCORE_SIZE_TIERS,
    SETUP_DISARMED_LIST, MOMENTUM_BO_MIN_CONFLUENCE, MOMENTUM_BO_REQUIRE_PRIORITY,
    PENDING_RETEST_ENABLED, PENDING_RETEST_WINDOW_MIN, PENDING_RETEST_TOLERANCE_PCT,
    PENDING_RETEST_MAX_DRIFT_PCT, PENDING_RETEST_LOG_PATH,
    LOSER_STREAK_SIZE_TIERS,
    MIN_SCORE_ENTRY, MIN_SCORE_ENTRY_CONSERVATIVE, MIN_SCORE_WATCHLIST,
    NO_ENTRY_BEFORE_MIN, NO_NEW_ENTRY_AFTER, EOD_CLOSE_TIME,
    # Fix #198 (2026-05-19) — MIDDAY_AVOID_START/END removed.
    # `_is_midday()` was DELETED by Fix #165; no remaining consumers.
    # Constants themselves stay defined in settings.py for now (other
    # code may grep for them); the import here was the only live reference.
    PROXIMITY_MAX_PCT, LEADER_PROXIMITY_MAX_PCT, LEADER_DAY_CHG_PCT, LEADER_RS_DELTA_PCT,
    DAILY_LOSS_KILL_PCT,
    CONFLUENCE_MULTIPLIER_2, CONFLUENCE_MULTIPLIER_3, SCAN_MIN_TURNOVER,
    TICK_SIZE,
    MIN_RISK_PER_TRADE_PCT, MIN_POSITION_VALUE_PCT,
    DAILY_PROFIT_LOCKOUT_PCT, DAILY_PROFIT_TIGHTEN_PCT,
    PAPER_TRADING, PAPER_SLIPPAGE_ENTRY_BPS, PAPER_SLIPPAGE_STOP_BPS,
    PAPER_SLIPPAGE_TARGET_BPS,
    ENTRY_MAX_SPREAD_PCT, RAG_VETO_MIN_TRADES, RAG_VETO_MAX_WINRATE,
    COOLDOWN_AFTER_LOSS_MIN, COOLDOWN_AFTER_WIN_MIN,
)

IST = ZoneInfo(TIMEZONE)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_ist() -> datetime:
    return datetime.now(IST)


def _entry_dt_aware(entry_time: str) -> datetime:
    """
    Convert a stored entry_time ISO string into a TZ-aware IST datetime.

    Why this exists: state.open_position() historically wrote
    datetime.now().isoformat() with no tzinfo. The wall-clock value depends on
    the host TZ — UTC on a default DigitalOcean droplet, IST on a Mac. Earlier
    code did `entry_dt.replace(tzinfo=IST)` which silently mislabels UTC values
    as IST, adding 5h30 to apparent age and tripping the 45-min stall threshold
    on the first tick.

    Handles both legacy naive ISO and new aware ISO transparently:
      - aware  → just astimezone(IST)
      - naive  → attach host's local tz (from time.localtime), then convert
    """
    import time as _t
    from datetime import timezone, timedelta
    parsed = datetime.fromisoformat(entry_time)
    if parsed.tzinfo is not None:
        return parsed.astimezone(IST)
    host_offset_sec = _t.localtime().tm_gmtoff
    host_tz = timezone(timedelta(seconds=host_offset_sec))
    return parsed.replace(tzinfo=host_tz).astimezone(IST)


def _parse_time(t: str) -> dtime:
    """'HH:MM' → time object."""
    h, m = t.split(":")
    return dtime(int(h), int(m))


def _calc_tp(entry: float, sl: float, r: float) -> float:
    """entry + (entry - sl) * R, tick-aligned (Fix #7)."""
    return _round_up_tick(entry + (entry - sl) * r, TICK_SIZE)


def _apply_paper_slippage(price: float, side: str, kind: str) -> float:
    """
    Worsen a paper fill price to simulate real broker execution (Fix #16).
      side: 'buy' = entry-LONG / exit-SHORT  → fill HIGHER than LTP (worse for buyer)
            'sell'= entry-SHORT / exit-LONG → fill LOWER than LTP (worse for seller)
      kind: 'entry' / 'stop' / 'target' picks the bps from settings.
    No-op in live mode (real broker → real slippage).
    """
    if not PAPER_TRADING or price <= 0:
        return price
    if kind == "stop":
        bps = PAPER_SLIPPAGE_STOP_BPS
    elif kind == "target":
        bps = PAPER_SLIPPAGE_TARGET_BPS
    else:
        bps = PAPER_SLIPPAGE_ENTRY_BPS
    factor = (1 + bps / 10000.0) if side == "buy" else (1 - bps / 10000.0)
    return _round_to_tick(price * factor, TICK_SIZE)


def _calc_atr_from_df(df) -> float:
    """Quick ATR from a DataFrame tail."""
    import pandas as pd
    df_t = df.tail(11)
    high, low, prev_c = df_t["high"], df_t["low"], df_t["close"].shift(1)
    tr = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return float(tr.iloc[1:].mean())


def _parse_json(text) -> dict | list:
    """Best-effort JSON parse — handles wrapped strings."""
    if isinstance(text, (dict, list)):
        return text
    text = str(text).strip()
    for s, e in [("[", "]"), ("{", "}")]:
        i, j = text.find(s), text.rfind(e)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    return {}


# ─── TradingCrew ──────────────────────────────────────────────────────────────

class TradingCrew:
    """
    Main trading loop. Call run_tick() every SCAN_INTERVAL_MIN minutes.
    Manages full lifecycle: scan → regime → breadth → setups → score → enter → manage.
    """

    def __init__(self):
        self.kite    = KiteDataClient()
        # Fix #197 (2026-05-19) — self.news removed (NewsClient field). The
        # only consumer (_get_news in scoring) was already gutted by Fix #185
        # and the method itself is deleted by Fix #197. Class stays on disk
        # at data/news_client.py for main.py's preflight check.
        self.state   = TradeStateManager()
        self.chroma  = ChromaMemory()
        self.engine  = ScoringEngine()

        # ── Phase 0 rebuild (2026-05-11) — conviction-engine pipeline ──
        # The 10:15 IST macro filter + FHH break combo replaces the deleted
        # ScoringEngine multipliers. Validated on 584 NIFTY sessions across
        # 30 months (Jan 2024 – May 2026). See docs/16_30Month_Final_Analysis.
        # Feature-flagged via USE_CONVICTION_ENGINE in config/settings.py for
        # safe shadow-mode rollout — the existing scoring path still runs;
        # the conviction engine fires as an additional gate at the top of
        # _allocate.
        from agents.market_state import MarketStateAgent
        from agents.fhh_break_detector import FhhBreakDetector
        from agents.conviction_engine import ConvictionEngine
        from agents.day_type_classifier import DayTypeClassifier
        from tools.volatility_state import VolatilityStateAgent
        from agents.discovery_engine import DiscoveryEngine
        from agents.mid_trade_reeval import MidTradeReeval

        self.market_state  = MarketStateAgent(self.kite)
        self.fhh_detector  = FhhBreakDetector(self.kite)
        self.day_type      = DayTypeClassifier(self.kite)        # Phase 1.5
        self.vol_state     = VolatilityStateAgent(self.kite)     # Phase 1.6/1.7
        self.conviction    = ConvictionEngine(self.market_state, self.fhh_detector)
        self.reeval        = MidTradeReeval(self.market_state)   # Phase 2.7
        # Inject the new agents into conviction so it can read them
        self.conviction.day_type = self.day_type
        self.conviction.vol_state = self.vol_state
        self.conviction.state_mgr = self.state   # Phase 2.6 — runway check median-TTP1 lookup
        print("[Crew] Conviction-engine pipeline loaded (Phase 0 + 1 rebuild)")
        print("[Crew] Day-type classifier + volatility state agents active")

        # Phase 2.1 — Discovery Engine. Seeds candidate pool at boot, scans
        # every DISCOVERY_SCAN_INTERVAL_SEC during market hours, surfaces
        # mid-cap movers outside the hardcoded universe (JINDRILL-class names).
        # Shadow mode default — DISCOVERY_ALLOW_TRADES gates whether names
        # actually merge into the trading pipeline.
        self.discovery = DiscoveryEngine(self.kite, FULL_UNIVERSE)
        # Fix #183 (2026-05-18) — news_client injection removed. NewsAPI
        # returns 0 articles for Indian small/mid-caps and pkscreener PyPI
        # metadata for large-caps, so catalyst enrichment was always empty.
        # NewsClient is still imported above for crew.py's own _get_news
        # (which is itself dead behind the Fix #160 conviction-bypass — to
        # be cleaned up in a future pass).
        try:
            self.discovery.seed_candidate_pool()
        except Exception as e:
            print(f"[Crew] Discovery pool seed failed (non-fatal): {e}")
        shadow_marker = "ON" if not getattr(__import__("config.settings", fromlist=["DISCOVERY_ALLOW_TRADES"]),
                                            "DISCOVERY_ALLOW_TRADES", False) else "OFF"
        print(f"[Crew] Discovery engine loaded — shadow mode {shadow_marker}")

        self._tick   = 0
        self._breadth_cache: dict = {}    # refreshed every ~15 min
        self._regime_cache:  dict = {}
        self._breadth_tick   = -99
        self._regime_tick    = -99
        # Per-tick VWAP cache — populated by _detect_setups, read by
        # _detect_breadth so breadth uses real VWAP (Fix #8) instead of the
        # change_pct proxy. Cleared at the start of every tick.
        self._vwap_cache: dict[str, float] = {}
        # Fix #168 (2026-05-18) — per-tick quote cache. Populated by
        # _scan_market from its existing batch fetch; read by every downstream
        # consumer (setup detection, volume/RS, scoring, conviction). Replaces
        # 4 single-symbol get_quotes([sym]) calls per candidate per tick —
        # ~300 Kite calls/tick → ~3 calls/tick. Also closes a real race:
        # conviction reading quote X while allocator reads quote Y for the
        # same symbol seconds apart.
        # NOTE: the 3 explicit "fresh at order time" reads (allocator entry,
        # TP1 fire, full exit) intentionally bypass the cache — they need a
        # live LTP at the moment of order placement.
        self._quote_cache: dict[str, dict] = {}
        # Fix #175 (2026-05-18) — per-tick conviction-tier histogram. Tells
        # the operator at a glance how many candidates landed at each tier
        # (S / A / B / SKIP) without grepping per-candidate [Conviction] lines.
        # Printed in _tick_summary; cleared at top of run_tick.
        self._tier_hist: dict[str, int] = {}
        # Fix #39 — per-tick rejection counters (which gate killed each candidate).
        # Cleared at the start of every tick; printed at end.
        self._reject_counts: dict[str, int] = {}
        # Fix #40 — bearish-breadth flag drives a -0.7 score penalty in scoring
        # (replaces the old tick-killing early return).
        self._breadth_bearish: bool = False
        # Fix #57 / Phase D — pending-pullback retest registry. Catches NBCC-
        # class A++ signals that proximity-failed; waits for retest instead
        # of chasing or skipping. In-memory; lost on restart by design.
        self._pending = PendingPullbackRegistry(
            window_min=PENDING_RETEST_WINDOW_MIN,
            tolerance_pct=PENDING_RETEST_TOLERANCE_PCT,
            max_drift_pct=PENDING_RETEST_MAX_DRIFT_PCT,
            log_path=PENDING_RETEST_LOG_PATH if PENDING_RETEST_ENABLED else None,
        )
        # Fix #188 (2026-05-19) — post-FHH-break re-evaluation queue.
        # Scenario this solves: 2026-05-19 — LATENTVIEW scored 8.6 at 10:22
        # but conviction rejected for `nifty_fhh_not_broken`. NIFTY's FHH
        # then broke at 10:45 (23 min later). By then LATENTVIEW's 5-min
        # setup window had closed and it was never re-evaluated.
        # The 30-month research validates GREEN+FHH = 97% (n=48) — but
        # only if signals waiting on FHH actually get re-checked when it
        # breaks. This queue stores (symbol, scored_dict, ts_iso) of every
        # signal rejected for `nifty_fhh_not_broken`. The drain runs at
        # the top of _allocate: if NIFTY FHH is now clean-broken, prepend
        # queue items to the scored list so they pass through conviction
        # again (which now finds FHH broken). Per-symbol dedup; entries
        # older than FHH_WAIT_MAX_AGE_MIN are dropped as stale.
        self._fhh_waiting_queue: list[dict] = []
        self._fhh_drained_today: bool = False  # one-shot drain per session
        # Clear yesterday's watchlist so dashboard shows only today's signals
        self.state.clear_old_watchlist()
        print("[Crew] Initialized — scanning 150 stocks, TP1+TP2+trailing SL active")
        if PENDING_RETEST_ENABLED:
            print(f"[Crew] Phase D pending-retest active: window={PENDING_RETEST_WINDOW_MIN}min, "
                  f"tolerance={PENDING_RETEST_TOLERANCE_PCT*100:.1f}%, "
                  f"max_drift={PENDING_RETEST_MAX_DRIFT_PCT*100:.1f}%")

        # ── Phase 3.0.1 — Consecutive losing days check at boot ──────────────
        # Read history once. If the prior streak has reached the configured
        # threshold (default 5), set a pause flag that _allocate() consults to
        # block new entries. Drawdown protection circuit breaker — designed to
        # be triggered ONLY in pathological cases. Manual reset by clearing
        # the flag (restart with a debug env-var or just sit out a winning day).
        try:
            from config.settings import CONSECUTIVE_LOSING_DAYS_PAUSE
        except ImportError:
            CONSECUTIVE_LOSING_DAYS_PAUSE = 5
        try:
            streak = self.state.get_consecutive_losing_days()
        except Exception as e:
            print(f"[Crew] consecutive-losses query failed (non-fatal): {e}")
            streak = 0
        self._consec_losing_days = streak
        self._paused_consec_losses = streak >= CONSECUTIVE_LOSING_DAYS_PAUSE
        if self._paused_consec_losses:
            print(f"[Crew] ⏸ CONSECUTIVE-LOSSES PAUSE — {streak} losing days in a row "
                  f"(threshold {CONSECUTIVE_LOSING_DAYS_PAUSE}). New entries blocked.")
            try:
                from tools.telegram_tools import _send
                _send(
                    f"⏸ <b>CONSECUTIVE-LOSING-DAYS PAUSE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📉 Streak: {streak} losing days in a row\n"
                    f"🚫 Threshold: {CONSECUTIVE_LOSING_DAYS_PAUSE}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"New entries blocked. Manual retrospective required."
                )
            except Exception:
                pass
        elif streak > 0:
            # Informational — surface partial streaks below threshold
            print(f"[Crew] Consecutive losing days: {streak} "
                  f"(pause at {CONSECUTIVE_LOSING_DAYS_PAUSE})")

        alert_system_start()

    # ── Main entry point ──────────────────────────────────────────────────────

    def run_tick(self, min_score: float = None) -> dict:
        self._tick += 1
        self._vwap_cache.clear()   # Fix #8 — fresh VWAPs per tick
        self._reject_counts.clear()   # Fix #39 — fresh rejection counts per tick
        self._quote_cache.clear()  # Fix #168 — fresh per-tick quote cache
        self._tier_hist.clear()    # Fix #175 — fresh conviction-tier histogram
        # Fix #188 (2026-05-19) — reset FHH-waiting state at session rollover.
        # Detected by comparing today's ISO date against the cached one.
        # Without this, _fhh_drained_today=True would persist forever, blocking
        # subsequent days' replays. Queue is also cleared (yesterday's signals
        # are irrelevant — different price levels, different setups).
        _today_iso = datetime.now(IST).date().isoformat()
        if getattr(self, "_fhh_session_date", None) != _today_iso:
            self._fhh_waiting_queue = []
            self._fhh_drained_today = False
            self._fhh_session_date = _today_iso
        # Fix #178 — clear stock-FHH candle cache so each tick gets fresh
        # 5-min bars (FHH state itself persists per symbol+date).
        try:
            self.fhh_detector.clear_tick_cache()
        except AttributeError:
            pass  # older detector without clear_tick_cache
        self._entries_this_tick = 0  # Phase 2.0 B6 — count actual entries, not scorer passes
        now = _now_ist()
        print(f"\n{'='*60}")
        print(f"[Crew] TICK #{self._tick} — {now.strftime('%H:%M:%S IST')}")
        print(f"{'='*60}")

        # 1. Always manage open positions first (SL/TP/trailing/EOD)
        self._manage_positions()

        # Phase 2.0 B5 — drive new-agent telemetry at every tick. These calls
        # are internally cached (Kite call only when the cache is stale), so
        # cost is near-zero, but the [MarketState], [Day-Type], [Vol-State],
        # [FHH NIFTY 50] log lines fire reliably. Without this poke they would
        # only emit when the conviction engine evaluates a setup — which on a
        # STRONG_RED day might be zero or one event.
        try:
            self.market_state.get_state(now)
            self.day_type.get_snapshot(now)
            self.vol_state.get_state(now)
            self.fhh_detector.get_state("NIFTY 50", now)
        except Exception as e:
            print(f"[Crew] phase-1 telemetry poke failed (non-fatal): {e}")

        # Phase 2.1 — Discovery Engine scan. Internally cadence-gated to
        # DISCOVERY_SCAN_INTERVAL_SEC, so calling every tick is cheap (early
        # return when not due). Names admitted by `run_scan` flow into
        # `get_live_universe` consumed by `_scan_market` below, IFF the
        # DISCOVERY_ALLOW_TRADES flag is True. Until then, shadow mode logs
        # adds but doesn't feed them to the trading pipeline.
        try:
            self.discovery.run_scan(now)
        except Exception as e:
            print(f"[Crew] discovery scan failed (non-fatal): {e}")

        # 2. Time gate — no new entries in certain windows
        if not self._ok_to_trade(now):
            print(f"[Crew] Time gate: no new entries at {now.strftime('%H:%M')}")
            return self._tick_summary(0, 0, 0)

        # 3. Regime + breadth — refresh every tick (Phase 2.0 B10). The old
        # 5-tick cadence (~15 min) meant the macro reading went stale on
        # adversarial days like 2026-05-12 where NIFTY drifted -30 bps after
        # the last refresh and the agent never re-locked. Both _detect_regime
        # and _detect_breadth are internally cheap (one Kite call each) and
        # the breadth detector reuses the per-tick VWAP cache.
        self._regime_cache  = self._detect_regime()
        self._regime_tick   = self._tick
        self._breadth_cache = self._detect_breadth()
        self._breadth_tick  = self._tick

        breadth_score = self._breadth_cache.get("breadth_score", 0.6)
        breadth_label = self._breadth_cache.get("breadth_label", "NEUTRAL")

        # Fix #40 — breadth-bearish DOES NOT kill the tick. The old -0.7 score
        # penalty was zeroed in Phase 0.5 because the 30-month audit showed
        # breadth-as-score-input was anti-predictive. We keep the flag for
        # downstream code that may still check it, but do NOT emit the
        # "score penalty -0.7 will apply" line (it was misleading — no penalty
        # actually applies in the post-Phase-0.5 path). Conviction engine
        # gates entries on macro state, not breadth.
        self._breadth_bearish = breadth_score <= BREADTH_BEARISH
        if self._breadth_bearish:
            print(f"[Crew] Breadth {breadth_label} ({breadth_score:.0%}) — "
                  f"informational only; conviction engine gates on macro state")

        # 4. Scan active stocks
        active = self._scan_market()
        if not active:
            return self._tick_summary(0, 0, 0)

        # Sector rotation: promote stocks from top sectors
        top_sectors = self._breadth_cache.get("top_sectors", [])
        active = self._reorder_by_sector(active, top_sectors)

        # 5. Detect setups (parallel-friendly loop)
        setups = self._detect_setups(active)
        if not setups:
            return self._tick_summary(len(active), 0, 0)

        # 6. Score signals
        scored = self._score_signals(setups, self._regime_cache, self._breadth_cache, min_score=min_score)

        # 6b. Fix #57 / Phase D — evaluate pending-retest queue. Any READY
        # entries (price retested trigger ± tolerance) get appended to the
        # scored list so the allocator's existing gates (kill switch, cooldown,
        # spread filter, sector cap, RAG veto, live LTP refetch) all run.
        if PENDING_RETEST_ENABLED and self._pending.count() > 0:
            pending_fires = self._evaluate_pending_retest()
            if pending_fires:
                scored.extend(pending_fires)
                # Re-sort so highest-score entries are placed first
                scored.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        # 7. Allocate capital
        self._allocate(scored)

        return self._tick_summary(len(active), len(setups), len(scored))

    # ── Phase D / Fix #57 — pending-retest evaluator ────────────────────────
    def _evaluate_pending_retest(self) -> list[dict]:
        """
        Check live LTPs for all symbols in pending-retest queue. If any have
        retested their trigger ± tolerance, convert them to scored-signal
        dicts and return for allocation. Expired or drift-too-far entries
        are silently dropped by the registry.
        """
        active = self._pending.get_active()
        if not active:
            return []
        syms = [e.symbol for e in active]
        try:
            quotes = self.kite.get_quotes(syms)
        except Exception as e:
            print(f"[Pending] LTP fetch failed for retest evaluation: {e}")
            return []
        ltp_map = {sym: (quotes.get(sym, {}).get("last_price") or 0) for sym in syms}
        ready_entries = self._pending.evaluate(ltp_map)
        if not ready_entries:
            return []
        out = []
        for e in ready_entries:
            print(f"[Pending] ⚡ RETEST FIRED — {e.symbol} {e.setup_type} "
                  f"score={e.score:.1f} trigger=₹{e.trigger_price:.2f} "
                  f"ltp=₹{ltp_map.get(e.symbol, 0):.2f}")
            self._rej("pending_retest_fired")
            out.append(ready_to_signal_dict(e))
        return out

    # ── Rejection telemetry (Fix #39) ────────────────────────────────────────

    def _rej(self, gate: str):
        """Increment per-tick rejection counter — tells us which gate kills trades."""
        self._reject_counts[gate] = self._reject_counts.get(gate, 0) + 1

    # ── Time gate ─────────────────────────────────────────────────────────────

    def _ok_to_trade(self, now: datetime) -> bool:
        t = now.time()
        market_open = dtime(9, 15 + NO_ENTRY_BEFORE_MIN)   # 9:20

        # Fix #174 (2026-05-18) — soften the late-session wall when Runway
        # Check is the authority. Phase 2.6 designed runway_check to REPLACE
        # the blunt 14:45 wall with per-setup `median_TTP1 × 1.5 ≤ remaining`,
        # but the wall was still hard-coded here. With RUNWAY_CHECK_ENABLED
        # (flipped True by Fix #171), runway_check has its own absolute
        # 20-min-before-EOD floor (= 14:55 given EOD_CLOSE_TIME=15:15). So
        # we widen the hard wall to 14:55 and let runway_check decide which
        # setups have enough runway. Net: +10 min of valid entry window per
        # session, and runway_check actually gets to run on late admits.
        try:
            from config.settings import RUNWAY_CHECK_ENABLED as _RWC
        except ImportError:
            _RWC = False
        if _RWC:
            no_entry = dtime(14, 55)   # runway_check's absolute floor
        else:
            no_entry = _parse_time(NO_NEW_ENTRY_AFTER)   # legacy 14:45 hard wall

        if t < market_open:
            return False
        if t >= no_entry:
            return False
        # Fix #165 (2026-05-18) — historical context:
        # The legacy midday-lull log was firing every tick 13:00-14:00 IST,
        # cluttering journalctl. Phase 2.5 removed the log message. Fix #165
        # then removed the underlying `_is_midday()` method entirely as a
        # Three-Laws Law-3 violation (clock category in code & reasoning).
        # Conviction engine reads structural state directly — no clock gate.
        return True

    # Fix #165 (2026-05-18) — `_is_midday()` DELETED.
    # Was: returned True between MIDDAY_AVOID_START and MIDDAY_AVOID_END.
    # Why deleted: clock-category gate that Phase 0.5 already neutralized
    # (no callers consult it for trading decisions anymore — only dashboard
    # status JSON did, and that has been removed too). Removing the method
    # closes the Three-Laws Law-3 violation surface for future archaeology.

    # ── Agent 1: Market Scanner ───────────────────────────────────────────────

    def _scan_market(self) -> list[str]:
        # Phase 2.1 — merge discovered names into the scanned universe (shadow-
        # gated by DISCOVERY_ALLOW_TRADES inside `get_live_universe`).
        universe = self.discovery.get_live_universe(FULL_UNIVERSE)
        extras = len(universe) - len(FULL_UNIVERSE)
        if extras > 0:
            print(f"[Scanner] Scanning {len(universe)} stocks "
                  f"({len(FULL_UNIVERSE)} core + {extras} discovery)...")
        else:
            print(f"[Scanner] Scanning {len(universe)} stocks...")
        try:
            # Batch fetch quotes for all stocks (single round-trip)
            quotes = self.kite.get_quotes(universe)
            # Fix #168 — populate per-tick quote cache from this same batch
            # so downstream consumers (setup detection, volume/RS, scoring,
            # conviction) don't fire individual get_quotes([sym]) calls.
            self._quote_cache.update(quotes)
            active = []
            for sym, q in quotes.items():
                chg   = abs(q.get("change_pct", 0))
                vol   = q.get("volume", 0)
                price = q.get("last_price", 0)
                turnover = price * vol   # ₹ traded today so far
                # Filter: meaningful move + real liquidity
                # (Fix #5: turnover-based, not raw share count — fixes the
                # bug where ₹50 stocks and ₹5,000 stocks cleared the same gate)
                if chg >= 0.3 and turnover >= SCAN_MIN_TURNOVER:
                    active.append((sym, chg, turnover))

            # Sort by absolute change, take top 60
            active.sort(key=lambda x: x[1], reverse=True)
            result = [s[0] for s in active[:60]]
            print(f"[Scanner] {len(result)} active stocks (of {len(universe)} scanned, "
                  f"turnover floor ₹{SCAN_MIN_TURNOVER/1e5:.0f}L)")
            return result
        except Exception as e:
            print(f"[Scanner] Error: {e} — using top 30 universe")
            return FULL_UNIVERSE[:30]

    def _reorder_by_sector(self, symbols: list[str], top_sectors: list[str]) -> list[str]:
        """Promote stocks from strong sectors to front of the list."""
        if not top_sectors:
            return symbols
        priority = [s for s in symbols if get_sector(s) in top_sectors]
        rest     = [s for s in symbols if s not in priority]
        return priority + rest

    # ── Fix #168 — per-tick quote cache helper ───────────────────────────────
    def _get_cached_quote(self, sym: str) -> dict:
        """
        Return the per-tick cached quote for `sym`. Cache is populated by
        `_scan_market` from the universe-wide batch fetch. Cache MISSES fall
        through to a fresh single-symbol fetch and are written back so
        subsequent reads within the same tick stay free.

        Use ONLY for setup detection / scoring / conviction reads. The 3
        order-fire paths (allocator entry refetch, TP1 fire, full exit) must
        keep their direct `self.kite.get_quotes([sym])` for moment-of-order
        freshness.
        """
        q = self._quote_cache.get(sym)
        if q is not None:
            return {sym: q}
        # Miss — fetch and backfill.
        try:
            fresh = self.kite.get_quotes([sym]) or {}
        except Exception as e:
            print(f"[Cache] miss-fetch failed for {sym}: {e}")
            return {}
        if sym in fresh:
            self._quote_cache[sym] = fresh[sym]
        return fresh

    # ── Agent 2: Regime Detector ─────────────────────────────────────────────

    def _detect_regime(self) -> dict:
        # Phase 2.5 hygiene — the LegacyRegime labels (RECOVERING/EVENT/
        # TRENDING/CHOPPY) don't match the new 5-state macro filter
        # (STRONG_GREEN/GREEN/YELLOW/RED/STRONG_RED). The [MarketState] log
        # emitted by market_state.py is the authoritative reading. This regime
        # calculation is kept because:
        #   1. trade_state.regime column (Fix #14) persists this label on every
        #      entry for RAG retrieval / EOD critique correlation
        #   2. legacy `_score_signals` consults it (now zeroed by Phase 0.5)
        # So we keep the math but tag the log clearly so it's not confused
        # with the conviction-engine macro state.
        try:
            nifty      = self.kite.get_nifty_data()
            banknifty  = self.kite.get_banknifty_data()
            n_chg      = nifty.get("change_pct", 0)
            n_above    = nifty.get("above_vwap", True)
            bn_above   = banknifty.get("above_vwap", True)

            # Regime logic (informational/storage only — does NOT gate entries)
            if abs(n_chg) > 1.5:
                regime = "event"
            elif n_above and abs(n_chg) > 0.4:
                regime = "trending"
            elif not n_above:
                regime = "recovering"
            else:
                regime = "choppy"

            confidence = 0.9 if abs(n_chg) > 0.8 else 0.7

            result = {
                "regime":               regime,
                "regime_confidence":    confidence,
                "nifty_above_vwap":     n_above,
                "banknifty_above_vwap": bn_above,
                "nifty_vwap_minutes":   20 if n_above else -20,
                "market_trend_aligned": n_above,
                "nifty_change_pct":     n_chg,
                "banknifty_change_pct": banknifty.get("change_pct", 0),
            }
            # One-line debug print — tagged [LegacyRegime] to distinguish
            # from [MarketState] which is the production decision authority.
            print(f"[LegacyRegime] {regime.upper()} | Nifty {n_chg:+.2f}% | "
                  f"above_vwap={n_above}  (informational; [MarketState] gates entries)")
            return result
        except Exception as e:
            print(f"[LegacyRegime] error: {e} — defaulting to CHOPPY (informational)")
            return {
                "regime": "choppy", "regime_confidence": 0.5,
                "nifty_above_vwap": True, "banknifty_above_vwap": True,
                "nifty_vwap_minutes": 0, "market_trend_aligned": True,
                "nifty_change_pct": 0, "banknifty_change_pct": 0,
            }

    # ── Agent 3: Breadth Analyzer ─────────────────────────────────────────────

    def _detect_breadth(self) -> dict:
        print("[Breadth] Computing market breadth...")
        try:
            # Fix #8 — pass the per-tick VWAP cache so breadth uses real VWAP
            # for active stocks; falls back to last>open proxy otherwise.
            breadth  = _compute_breadth(vwap_cache=self._vwap_cache)
            sectors  = _compute_sector_strength(vwap_cache=self._vwap_cache)
            top3     = [s["sector"] for s in sectors[:3]]
            bottom3  = [s["sector"] for s in sectors[-3:]]

            bs = breadth["breadth_score"]
            label = breadth["breadth_label"]
            real_n = breadth.get("used_real_vwap", 0)
            print(f"[Breadth] {bs:.0%} above VWAP → {label} | Top: {top3} | "
                  f"real_vwap_hits={real_n}/{breadth.get('stocks_checked', 0)}")

            # Send Telegram alert periodically (every ~15 min via tick filter)
            alert_market_breadth(breadth["breadth_pct"], label)

            return {
                **breadth,
                "top_sectors":   top3,
                "weak_sectors":  bottom3,
                "all_sectors":   sectors,
            }
        except Exception as e:
            print(f"[Breadth] Error: {e}")
            return {
                "breadth_score": 0.6, "breadth_pct": 60.0,
                "breadth_label": "NEUTRAL",
                "top_sectors":   [], "weak_sectors": [], "all_sectors": [],
            }

    # ── Agent 4: Setup Detector ───────────────────────────────────────────────

    def _detect_setups(self, active: list[str]) -> list[dict]:
        """
        Returns the PRIMARY setup per active stock, with confluence_count and
        confluence_setups attached so the scorer can apply the multiplier.
        Multi-detect (Fix #5) — each stock now reveals all matching setups,
        not just the first hit.
        """
        print(f"[Setup] Detecting setups in {len(active)} stocks...")
        setups       = []
        no_data      = 0
        few_candles  = 0
        below_vwap_count = 0
        weak_body    = 0
        confluence_n = 0   # count of stocks where 2+ setups fired

        for sym in active:
            try:
                df, vwap = self.kite.get_vwap_with_candles(sym)
                if df is None:
                    no_data += 1
                    continue
                if len(df) < 8:
                    few_candles += 1
                    continue

                # Fix #8 — share the freshly-computed VWAP with the breadth /
                # sector functions so they don't have to re-fetch candles.
                if vwap:
                    self._vwap_cache[sym] = vwap

                # Fix #168 — use per-tick cache (populated by _scan_market)
                quotes   = self._get_cached_quote(sym)
                curr     = quotes.get(sym, {}).get("last_price", 0.0)

                last = df.iloc[-1]
                br   = abs(last["close"] - last["open"]) / (last["high"] - last["low"]) \
                       if (last["high"] - last["low"]) > 0 else 0
                if last["close"] < vwap:
                    below_vwap_count += 1
                if br < 0.4:
                    weak_body += 1

                matches = _detect_setups_multi(df, vwap, curr, sym)
                if matches:
                    primary = matches[0]   # priority-highest match
                    if primary.get("confluence_count", 1) >= 2:
                        confluence_n += 1
                        print(f"[Setup] ⚡ CONFLUENCE x{primary['confluence_count']} on {sym}: "
                              f"{primary['confluence_setups']}")
                    setups.append(primary)
            except Exception:
                continue

        setups.sort(key=lambda x: x.get("candle_quality", 0), reverse=True)
        print(
            f"[Setup] Found {len(setups)} setups ({confluence_n} with confluence) | "
            f"no_data={no_data} few_candles={few_candles} | "
            f"below_vwap={below_vwap_count} weak_body={weak_body} (of {len(active)})"
        )
        return setups

    # ── Agent 5+6: Volume + RS + News ────────────────────────────────────────

    def _get_volume_rs(self, sym: str, nifty_chg: float) -> tuple[float, float, float, bool]:
        """Returns (volume_ratio, spread_pct, rs_delta, liquidity_pass).

        liquidity_pass = spread is acceptable (stock is tradeable).
        Volume ratio is NOT part of liquidity_pass — it is scored separately
        via volume_strength in the engine. This means:
          - Wide spread (>0.5%) → hard reject (can't trade — entry/exit costs eat profit)
          - Low volume (ratio < 1.2) → volume_strength = 0.0 → lower score → harder to reach 7.0
          - High volume → volume_strength up to 2.0 → boosts score
        This way a perfect setup on a liquid stock is never hard-blocked just because
        the current 5-min candle hasn't printed 1.2x average volume yet.
        """
        try:
            ratio     = self.kite.get_volume_ratio(sym) or 0.0
            spread    = self.kite.get_spread_pct(sym)
            # Fix #168 — use per-tick cache
            quotes    = self._get_cached_quote(sym)
            stock_chg = quotes.get(sym, {}).get("change_pct", 0.0)
            delta     = round(stock_chg - nifty_chg, 3)

            # spread=999.0 means Kite depth data unavailable — treat as pass
            spread_ok = True if spread >= 999.0 else (spread < 0.5)

            # Liquidity = can I trade this stock (spread-based only)
            # Volume quality is captured in volume_strength via ratio
            liq = spread_ok

            print(f"[VolumeRS] {sym}: ratio={ratio:.2f} spread={'N/A' if spread >= 999.0 else f'{spread:.3f}%'} liq={liq}")
            return ratio, spread, delta, liq
        except Exception as e:
            print(f"[VolumeRS] {sym}: error — {e}")
            return 0.0, 999.0, 0.0, True   # on error, pass liquidity — don't block on missing data

    # Fix #197 (2026-05-19) — `_get_news` method and `self.news` field DELETED.
    # Fix #185 already removed the only production call site (in _score_signals);
    # this fix removes the now-orphaned dead code. NewsClient import is also
    # removed (no remaining callers in crew.py). The class itself still lives
    # at data/news_client.py for main.py's preflight health check and for
    # future NSE-corporate-announcements infrastructure (per Fix #183 plan).
    #
    # Tombstone — if you're looking for catalyst attribution on Discovery
    # admits, see Fix #183. If you're looking for the news_sentiment field
    # in the legacy scoring pipeline, see Fix #185 (hardcoded neutral 0.5).

    # ── Agent 7: Scoring ──────────────────────────────────────────────────────

    def _score_signals(
        self,
        setups:      list[dict],
        regime_data: dict,
        breadth_data: dict,
        min_score:   float = None,
    ) -> list[dict]:
        print(f"[Scorer] Scoring {len(setups)} setups...")
        scored  = []
        regime  = regime_data.get("regime", "choppy")
        nchg    = regime_data.get("nifty_change_pct", 0.0)
        bs      = breadth_data.get("breadth_score", 0.6)

        # ── Lunch-window dynamic gate DELETED (Phase 0.5 rebuild, 2026-05-11) ─
        # 30-month NIFTY analysis showed:
        #   12-13 IST hour: 53% WR, +0.099R avg, +₹112,677 P&L
        #   13-14 IST hour: 58% WR (the "lunch gate" hour)
        # Both lunch hours had above-average win rates. The premise that
        # "lunch is dangerous" was empirically wrong. The gate was filtering
        # profitable hours.
        # On the negative-P&L morning question: the 30-month data shows
        # sequential persistence is RANDOM (48-51%). Morning losses don't
        # predict afternoon losses. Capital preservation is handled by the
        # kill-switch (-2.5% capital), not by clock-based defensive raises.
        # The conviction engine (macro + FHH) is the correct adaptive filter.

        if min_score is None:
            min_score = MIN_SCORE_ENTRY

        # Also raise threshold if consecutive losses ≥ 3
        consec = self.state.get_consecutive_losses()
        if consec >= MAX_CONSECUTIVE_LOSSES:
            min_score = max(min_score, MIN_SCORE_ENTRY_CONSERVATIVE)
            print(f"[Scorer] Conservative mode — {consec} consecutive losses, threshold={min_score}")

        # ── HOUR_GATE_NUDGES DELETED (Phase 0.5 rebuild, 2026-05-11) ─────────
        # 30-month NIFTY analysis (584 sessions) refuted the time-of-day-nudge
        # premise. The hours nudged DOWN (12 IST) had average +0.099R but the
        # hours nudged UP (9-10 IST) actually had 51-58% WR — not catastrophic.
        # More importantly, hour-of-day is a CO-FEATURE that correlates with
        # measurable structural state (NIFTY slope, breadth direction). The
        # conviction engine reads that structural state directly via the 10:15
        # IST macro filter. Clock-based nudges are now forbidden by the project
        # Three Laws (see PROJECT_MEMORY.md).
        #
        # ── Winner-streak gate shift DELETED (Phase 0.5 rebuild) ─────────────
        # Sequential daily persistence is 48-51% across 334 sessions (RANDOM).
        # Yesterday's outcomes don't predict today's. "Regression-to-mean after
        # 3 wins" is an intuition not supported by 30 months of data.
        # Anti-revenge discipline IS kept via the loser-streak dampener and
        # the asymmetric cooldown (45m after loss). Those work on capital
        # preservation, not on regression theory.

        # Write effective threshold to status file so dashboard can display it.
        # Fix #165 (2026-05-18) — `midday_mode` removed. The legacy `_is_midday()`
        # was a clock-category leakage into the dashboard (Three-Laws Law-3
        # violation). Conservative mode is now driven purely by consecutive
        # losses, which is a structural risk signal — not a wall-clock one.
        conservative = consec >= MAX_CONSECUTIVE_LOSSES
        try:
            STATUS_FILE.write_text(json.dumps({
                "effective_threshold": round(min_score, 1),
                "conservative_mode":   conservative,
                "consecutive_losses":  consec,
                "regime":              regime_data.get("regime", "unknown"),
                "breadth_label":       breadth_data.get("breadth_label", "NEUTRAL"),
                "last_tick":           _now_ist().strftime("%H:%M:%S"),
            }, indent=2))
        except Exception:
            pass

        for s in setups:
            sym = s["symbol"]
            try:
                # ── Fix #56 / Phase A — Setup gating ────────────────────────
                # 280-trade audit: only momentum_breakout shows positive gross
                # R. The 6 other setups are net-negative drags. Disarmed via
                # config flag (detection still runs for confluence_count).
                setup_type = s.get("setup_type", "")
                if setup_type in SETUP_DISARMED_LIST:
                    self._rej(f"setup_disarmed_{setup_type}"); continue

                # Volume + RS
                vol_ratio, spread, rs_delta, liq = self._get_volume_rs(sym, nchg)

                # ── A1 / Fix #22 → Fix #56 — momentum_breakout volume veto ──
                # RVOL floor 2.0 (raised back from 1.7 after 280-trade audit).
                if (setup_type == "momentum_breakout"
                        and vol_ratio < MOMENTUM_BO_MIN_RVOL):
                    print(f"[Scorer] {sym} momentum_breakout RVOL={vol_ratio:.2f} "
                          f"< {MOMENTUM_BO_MIN_RVOL} — fakeout risk, skip")
                    # Phase 2.8 — log rejection as ghost trade so the offline
                    # analyzer can compute the would-be P&L per RVOL bucket.
                    # Lets us tune the threshold from real data instead of
                    # asserting 2.0 is right.
                    try:
                        from tools.rvol_ghost import record_rejection as _ghost
                        # Pull macro state if available (best-effort)
                        macro_lbl = ""
                        try:
                            macro_lbl = self.market_state.get_state().state
                        except Exception:
                            pass
                        _ghost(
                            symbol=sym,
                            rvol=vol_ratio,
                            rvol_floor=MOMENTUM_BO_MIN_RVOL,
                            entry_price=s.get("entry_price", 0.0),
                            stop_loss=s.get("stop_loss", 0.0),
                            tp1_price=s.get("tp1_price", 0.0),
                            tp2_price=s.get("tp2_price", 0.0),
                            direction=s.get("direction", "long"),
                            setup_type=setup_type,
                            macro_state=macro_lbl,
                            score=s.get("final_score", 0.0),
                        )
                    except Exception as _e:
                        # Best-effort; never break the rejection flow
                        pass
                    self._rej("momentum_low_volume"); continue

                # ── Fix #56 / Phase A — momentum priority filter ────────────
                # ── DISABLED IN CONVICTION MODE (Fix #173, 2026-05-18) ──────
                # Original intent (Phase A, 280-trade audit, pre-conviction):
                # require either confluence ≥ 2 OR sector in top-3 breadth.
                # WHY DISABLED:
                #   1. Three-Laws Law-2 violation — pre-filters on a hardcoded
                #      top-N sector list (`breadth_data.get("top_sectors")` is
                #      a list of 3 sector strings).
                #   2. Mathematically impossible to clear "confluence ≥ 2"
                #      since SETUP_DISARMED_LIST disables 6 of 7 setups; only
                #      momentum_breakout fires, so confluence_count is always 1.
                #      The OR collapses to pure sector-priority.
                #   3. Redundant in conviction mode: sector strength is read
                #      structurally per-bar via stock_decoupling's sector-index
                #      check and the day-type classifier. Pre-filtering kills
                #      legitimate trades (e.g. ZEEL on 2026-05-18 had RVOL 2.13,
                #      momentum_breakout, valid structure — silently dropped
                #      because MEDIA wasn't in [IT, PHARMA, FINANCIAL]).
                # Behaviour: filter skipped entirely when USE_CONVICTION_ENGINE
                # is the authority. Legacy path still applies it.
                try:
                    from config.settings import USE_CONVICTION_ENGINE as _UCE_PRI
                except ImportError:
                    _UCE_PRI = False
                if (not _UCE_PRI
                        and setup_type == "momentum_breakout"
                        and MOMENTUM_BO_REQUIRE_PRIORITY):
                    conf_n     = s.get("confluence_count", 1)
                    sym_sector = s.get("sector", get_sector(sym))
                    top_secs   = breadth_data.get("top_sectors", []) or []
                    has_priority = (conf_n >= MOMENTUM_BO_MIN_CONFLUENCE) or (sym_sector in top_secs)
                    if not has_priority:
                        print(f"[Scorer] {sym} momentum_breakout no-priority "
                              f"(conf={conf_n}, sector={sym_sector} not in {top_secs}) — skip")
                        self._rej("momentum_no_priority"); continue

                # Fix #185 (2026-05-18) — News enrichment removed from hot path.
                # `_get_news` was firing per-candidate per-tick, burning Groq quota
                # and feeding NOTHING actionable downstream (conviction engine
                # doesn't read these fields; Fix #183 already removed news from
                # Discovery admits). For Indian small/mid-caps NewsAPI returns
                # zero articles, for large-caps it returns PyPI package metadata
                # (e.g. "pkscreener 0.46.20260517.912"). Hardcoding neutral
                # defaults keeps the scoring object schema stable without the
                # network round-trip. `_get_news` method + `self.news` field
                # retained as dead code on disk; can be re-enabled if/when NSE
                # corporate-announcements feed work happens later.
                has_news, news_score, catalyst, headline = False, 0.5, "none", ""

                # Quotes for current price (Fix #168 — use per-tick cache)
                quotes  = self._get_cached_quote(sym)
                stock_chg = quotes.get(sym, {}).get("change_pct", 0.0)

                # Build scoring objects
                signal = RawSignal(
                    symbol=sym,
                    setup_type=SetupType(s["setup_type"]),
                    direction=SignalDirection(s.get("direction", "long")),
                    entry_price=s["entry_price"],
                    stop_loss=s["stop_loss"],
                    target_price=s.get("tp2_price", s.get("target_price", s["entry_price"])),
                    current_price=s.get("current_price", s["entry_price"]),
                    candle_body_ratio=s.get("candle_body_ratio", 0.5),
                    close_position=s.get("close_position", 0.6),
                    sector=s.get("sector", get_sector(sym)),
                )
                volume = VolumeData(
                    symbol=sym, current_volume=0, avg_volume_20=0,
                    volume_ratio=vol_ratio, bid_ask_spread=spread,
                    liquidity_pass=liq,
                )
                context = MarketContext(
                    regime=RegimeType(regime),
                    regime_confidence=regime_data.get("regime_confidence", 0.8),
                    nifty_above_vwap=regime_data.get("nifty_above_vwap", True),
                    banknifty_above_vwap=regime_data.get("banknifty_above_vwap", True),
                    nifty_vwap_minutes=regime_data.get("nifty_vwap_minutes", 0),
                    market_trend_aligned=regime_data.get("market_trend_aligned", True),
                    breadth_score=bs,
                )
                rs = RelativeStrengthData(
                    symbol=sym,
                    stock_change_pct=stock_chg,
                    nifty_change_pct=nchg,
                    rs_delta=rs_delta,
                    outperforming=rs_delta > 0.5,
                )
                news = NewsData(
                    symbol=sym, has_news=has_news, sentiment=news_score,
                    catalyst_type=catalyst, headline=headline, llm_score=news_score,
                )

                result = self.engine.calculate(signal, volume, context, rs, news)
                comp   = result.components

                # ── Confluence multiplier (Fix #5) ───────────────────────────
                # Apply BEFORE the per-setup floor and final_score cap. The
                # engine's final_score is already raw × regime_multiplier; we
                # additionally multiply for confluence and re-cap at 10.
                conf_n = s.get("confluence_count", 1)
                if conf_n >= 3:
                    conf_mult = CONFLUENCE_MULTIPLIER_3
                elif conf_n == 2:
                    conf_mult = CONFLUENCE_MULTIPLIER_2
                else:
                    conf_mult = 1.0
                if conf_mult > 1.0:
                    boosted = round(min(10.0, comp.final_score * conf_mult), 2)
                    comp.final_score = boosted
                    # Refresh grade so dashboard / DB write are consistent
                    from scoring.engine import Grade
                    if boosted >= 9.0:   comp.grade = Grade.A_PLUS_PLUS
                    elif boosted >= 8.0: comp.grade = Grade.A_PLUS
                    elif boosted >= 7.0: comp.grade = Grade.A
                    elif boosted >= 5.0: comp.grade = Grade.B
                    else:                comp.grade = Grade.C

                # ── PDH break bonus (Fix #17) ────────────────────────────────
                # Previous day's high is a major magnet level. An entry above
                # PDH on volume is a much higher-probability long than the
                # same setup mid-range. PDL break for shorts (system is
                # long-only today; PDL nudge dormant until SHORT-01).
                pdh_nudge = 0.0
                pdh_pdl = None
                try:
                    pdh_pdl = self.kite.get_pdh_pdl(sym)
                except Exception:
                    pdh_pdl = None
                if pdh_pdl:
                    pdh, _pdl = pdh_pdl
                    if s.get("direction", "long") == "long" and s["entry_price"] > pdh:
                        pdh_nudge = 0.3

                # ── sector_nudge DELETED (Phase 0.5 rebuild) ──────────────────
                # The 280-trade DB analysis showed top-3 sector membership did
                # not correlate with trade success — REALTY/POWER/HEALTHCARE/
                # PAINTS each had positive net P&L despite rarely being in any
                # hardcoded "top-3" list. The hardcoded top-3 was overfit.
                # The macro filter (conviction engine) plus continuous sector
                # strength (Phase 1 work) replaces this naive boolean nudge.
                sym_sector = s.get("sector", get_sector(sym))
                sector_nudge = 0.0

                # ── breadth_pen DELETED (Phase 0.5 rebuild) ───────────────────
                # The 30-month analysis showed breadth alone is a coarse signal.
                # The 10:15 IST macro filter (conviction engine) captures the
                # actionable "is the market against my long bias" question with
                # 72-98% precision. A separate -0.7 nudge on top of that is
                # double-counting and produces over-filtering. Removed.
                breadth_pen = 0.0

                # ── D1 / Fix #41 — RAG read: historical WR nudge ─────────────
                # Activates the learning loop. Query ChromaDB signal_patterns
                # for past trades with the same (setup_type, regime). With ≥5
                # historical trades:
                #   WR ≥ 65 %  → +0.3 nudge (proven setup × regime fit)
                #   WR <  40 %  → −0.5 nudge (proven loser configuration)
                #   else        →  0      (not enough edge in the data)
                # Insufficient history (<5 trades) → 0 (don't act on noise).
                hist_nudge = 0.0
                hist_found = 0
                hist_wr    = None
                rag_veto   = False
                try:
                    hist = self.chroma.query_similar_signals(
                        setup_type=s.get("setup_type", ""),
                        regime=regime,
                        n_results=20,
                    )
                    hist_found = int(hist.get("found", 0) or 0)
                    if hist_found >= 5:
                        hist_wr = float(hist.get("win_rate") or 50.0)
                        if hist_wr >= 65:
                            hist_nudge = 0.3
                        elif hist_wr < 40:
                            hist_nudge = -0.5
                        if hist_nudge != 0.0:
                            print(f"[Scorer] {sym} RAG: {hist_found} similar trades, "
                                  f"WR={hist_wr:.0f}% → nudge {hist_nudge:+.1f}")
                    # ── P2 / Fix #44 — RAG proven-loser veto ──────────────
                    # If we have enough history (≥10) AND WR is below floor
                    # (35%), the (setup × regime) combo is a proven loser.
                    # Don't take it at all — stronger than the -0.5 nudge.
                    if hist_found >= RAG_VETO_MIN_TRADES and hist_wr is not None \
                            and hist_wr < RAG_VETO_MAX_WINRATE:
                        rag_veto = True
                        print(f"[Scorer] {sym} ⛔ RAG VETO — {hist_found} trades, "
                              f"WR={hist_wr:.0f}% < {RAG_VETO_MAX_WINRATE}% — skip")
                except Exception:
                    pass

                if rag_veto:
                    self._rej("rag_proven_loser"); continue

                # Combine PDH + sector + breadth + history nudges in a single
                # score update so we don't recompute grade four times.
                total_nudge = sector_nudge + pdh_nudge + breadth_pen + hist_nudge
                if total_nudge != 0.0:
                    new_score = max(0.0, min(10.0, comp.final_score + total_nudge))
                    comp.final_score = new_score
                    from scoring.engine import Grade
                    if new_score >= 9.0:   comp.grade = Grade.A_PLUS_PLUS
                    elif new_score >= 8.0: comp.grade = Grade.A_PLUS
                    elif new_score >= 7.0: comp.grade = Grade.A
                    elif new_score >= 5.0: comp.grade = Grade.B
                    else:                  comp.grade = Grade.C

                # Per-setup score overrides — raise bar for underperforming setups.
                # Fix #160 (2026-05-18): when conviction engine is the decision
                # authority (USE_CONVICTION_ENGINE=True), these per-setup score
                # gates are bypassed because conviction tier (S/A/B/SKIP) IS the
                # gate. The legacy `failed_breakdown >= 7.5` override only made
                # sense in the old 0-10 scoring world; in conviction mode every
                # admit is structurally validated by macro + FHH + stock state.
                SETUP_MIN_SCORES = {
                    "failed_breakdown": 7.5,   # 33% WR in 151-trade dataset
                }
                setup_min    = SETUP_MIN_SCORES.get(s.get("setup_type", ""), 0)
                effective_min = max(min_score, setup_min)

                # Fix #160 — Bypass the stub-score gate when conviction is on.
                # The stub `_score_signals` returns ~3-6 for most clean structural
                # admits, so `score ≥ MIN_SCORE_ENTRY (7.0)` would kill every
                # conviction-A admit before _allocate even sees it. Let validity +
                # proximity decide here; conviction in _allocate decides take/skip.
                #
                # Fix #184 (2026-05-18) — Bypass `result.is_valid` ALSO in conviction
                # mode. The stub sets `is_valid = final_score >= 5.0`
                # (scoring/engine.py:270). A clean MOMENTUM_BREAKOUT admit with body
                # ratio 0.41, low volume RS, or "news_sentiment=0.5 neutral" gets
                # raw_score ~4.5 and is_valid=False — silently killed BEFORE
                # conviction ever evaluates it. That's the most likely reason zero
                # entries have fired in shadow mode despite structurally clean
                # admits being logged. In conviction mode, conviction in _allocate
                # is the SOLE take/skip authority; we only gate on proximity here
                # so the existing proximity_failed → pending-retest path still
                # works.
                try:
                    from config.settings import USE_CONVICTION_ENGINE as _UCE
                except ImportError:
                    _UCE = False
                if _UCE:
                    will_enter = result.proximity_ok      # conviction in _allocate decides
                else:
                    will_enter = result.is_valid and comp.final_score >= effective_min
                # Always log score so we can see what's happening
                # Fix #52 — surface proximity-skips with explicit tag so we can
                # tell apart "score too low" from "scored A++ but ran past
                # entry" (NBCC-class). The latter often hits TP1 on its own.
                proximity_failed = (not result.proximity_ok) and comp.final_score >= effective_min
                tag = "✅ ENTER" if will_enter else (
                    "⚠ skip-proximity" if proximity_failed else "❌ skip"
                )
                print(
                    f"[Scorer] {sym:12} {s['setup_type']:20} "
                    f"score={comp.final_score:.1f} "
                    f"(sq={comp.setup_quality:.1f} vol={comp.volume_strength:.1f} "
                    f"mkt={comp.market_alignment:.1f} rs={comp.relative_strength:.1f} "
                    f"news={comp.news_sentiment:.1f}) "
                    f"{tag}"
                )

                if will_enter:
                    scored_item = {
                        **s,
                        "final_score": comp.final_score,
                        "grade":       comp.grade.value,
                        "confidence":  result.confidence,
                        "reason":      result.reason,
                        "score_breakdown": {
                            "setup_quality":    comp.setup_quality,
                            "volume_strength":  comp.volume_strength,
                            "market_alignment": comp.market_alignment,
                            "relative_strength": comp.relative_strength,
                            "news_sentiment":   comp.news_sentiment,
                            "confluence_count": s.get("confluence_count", 1),
                            "confluence_mult":  conf_mult,
                            "sector_nudge":     sector_nudge,
                            "pdh_nudge":        pdh_nudge,
                            "breadth_pen":      breadth_pen,
                            "hist_nudge":       hist_nudge,
                            "hist_found":       hist_found,
                            "hist_wr":          hist_wr,
                        },
                        "rs_delta":    rs_delta,
                        "news_headline": headline,
                    }
                    scored.append(scored_item)

                elif comp.final_score >= MIN_SCORE_WATCHLIST:
                    # Fix #52 — distinguish proximity-failed (high-score signals
                    # that ran past entry, often A++) from genuinely-weak signals
                    # that landed in the watchlist band. Same destination, but
                    # different counters so we can size the late-entry decision.
                    self._add_watchlist(sym, s, comp.final_score, result.reason)
                    if proximity_failed:
                        self._rej("proximity_failed_to_watchlist")
                        # ── Fix #57 / Phase D — pending-pullback retest ─────
                        # Proximity-failed signals that would have entered:
                        # mark for retest watch instead of just abandoning.
                        # Eligibility: pending must be enabled, score ≥ entry
                        # gate, drift between 0.7% (proximity threshold) and
                        # max_drift (2.0%). Closer signals already entered.
                        if PENDING_RETEST_ENABLED and comp.final_score >= effective_min:
                            cur_price = s.get("current_price", s["entry_price"])
                            drift = abs(cur_price - s["entry_price"]) / max(s["entry_price"], 1e-6)
                            if drift <= PENDING_RETEST_MAX_DRIFT_PCT:
                                # Build a complete signal dict for the registry
                                # (it caches everything needed to fire later).
                                pending_signal = {
                                    **s,
                                    "score_breakdown": {
                                        "confluence_count": s.get("confluence_count", 1),
                                        "confluence_mult":  conf_mult,
                                        "sector_nudge":     sector_nudge,
                                        "pdh_nudge":        pdh_nudge,
                                        "breadth_pen":      breadth_pen,
                                        "hist_nudge":       hist_nudge,
                                    },
                                }
                                added = self._pending.add(
                                    sym, pending_signal, comp.final_score, result.reason)
                                if added:
                                    self._rej("pending_retest_added")
                                    print(f"[Pending] ⏳ {sym} added to retest queue "
                                          f"(score={comp.final_score:.1f}, "
                                          f"drift={drift*100:.2f}%, "
                                          f"trigger=₹{s['entry_price']:.2f})")
                    else:
                        self._rej("score_below_gate_to_watchlist")
                else:
                    self._rej("score_below_watchlist")

            except Exception as e:
                print(f"[Scorer] Error on {sym}: {e}")

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        print(f"[Scorer] {len(scored)} signals above threshold {min_score}")
        return scored

    def _add_watchlist(self, sym: str, s: dict, score: float, reason: str):
        try:
            tp1 = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R1)
            tp2 = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R2)
            item = WatchlistItem(
                symbol=sym, setup_type=s["setup_type"], score=score,
                entry_price=s["entry_price"], stop_loss=s["stop_loss"],
                tp1_price=tp1, tp2_price=tp2, reason=reason[:200],
                added_at=datetime.now().isoformat(),
            )
            self.state.add_to_watchlist(item)
        except Exception:
            pass

    # ── Agent 8a: Capital Allocator ───────────────────────────────────────────

    def _allocate(self, scored: list[dict]):
        """Enter trades for top-scored signals that pass all filters."""
        open_pos = self.state.get_open_positions()
        consec   = self.state.get_consecutive_losses()

        # Fix #161 (2026-05-18) — resolve probe-mode-aware capital/positions once
        # per allocator call. Without this, flipping PROBE_MODE_ENABLED=True +
        # PAPER_TRADING=False would size against the ₹15L paper capital instead
        # of the ₹50k probe — a documented but unprotected ~30× risk footgun.
        # All percent-of-capital sizing / kill-switch / lockout thresholds use
        # `active_capital`; all max-position checks use `active_max_positions`.
        try:
            from config.settings import (
                get_active_capital, get_active_max_positions,
            )
            active_capital       = get_active_capital()
            active_max_positions = get_active_max_positions()
        except Exception:
            # Fail-safe: fall back to paper-mode constants if helpers are absent
            active_capital       = CAPITAL
            active_max_positions = MAX_POSITIONS

        # ── Daily-profit lockout (Fix #11) ───────────────────────────────────
        # Mirror of the kill-switch on the upside. Once today_pnl crosses the
        # lockout ceiling (+3% of active capital), no new entries — protect the
        # day's gains. Existing positions still managed. Auto-resets at next session.
        today_pnl       = self.state.get_today_pnl()
        lockout_ceiling = active_capital * DAILY_PROFIT_LOCKOUT_PCT
        tighten_ceiling = active_capital * DAILY_PROFIT_TIGHTEN_PCT

        if today_pnl >= lockout_ceiling:
            print(f"[Allocator] 🟢 DAILY-PROFIT LOCKOUT — "
                  f"today P&L ₹{today_pnl:+,.0f} ≥ ceiling ₹{lockout_ceiling:+,.0f} "
                  f"({DAILY_PROFIT_LOCKOUT_PCT*100:.1f}% of ₹{active_capital:,}). "
                  f"Done for the day — no new entries.")
            if not getattr(self, "_profit_lock_alerted_today", False):
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🟢 <b>DAILY-PROFIT LOCKOUT</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Today P&L: ₹{today_pnl:+,.0f}\n"
                        f"🎯 Ceiling: ₹{lockout_ceiling:+,.0f} "
                        f"({DAILY_PROFIT_LOCKOUT_PCT*100:.1f}% of capital)\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Profitable day locked in. Open positions still managed."
                    )
                except Exception:
                    pass
                self._profit_lock_alerted_today = True
            return

        # ── Daily-loss kill switch ───────────────────────────────────────────
        # Hard floor: if today_pnl drops below -DAILY_LOSS_KILL_PCT × active_capital,
        # block ALL new entries for the rest of the session. Existing positions
        # continue to be managed (SL/TP/trail/EOD). Auto-resets at next session.
        kill_floor   = -active_capital * DAILY_LOSS_KILL_PCT
        if today_pnl <= kill_floor:
            print(f"[Allocator] 🛑 DAILY-LOSS KILL SWITCH — "
                  f"today P&L ₹{today_pnl:+,.0f} ≤ floor ₹{kill_floor:+,.0f} "
                  f"({DAILY_LOSS_KILL_PCT*100:.1f}% of ₹{active_capital:,}). "
                  f"Blocking new entries for rest of session.")
            # Telegram alert (idempotent — once-per-session)
            if not getattr(self, "_kill_switch_alerted_today", False):
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🛑 <b>DAILY-LOSS KILL SWITCH ACTIVATED</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📉 Today P&L: ₹{today_pnl:+,.0f}\n"
                        f"🚫 Floor: ₹{kill_floor:+,.0f} "
                        f"({DAILY_LOSS_KILL_PCT*100:.1f}% of ₹{active_capital:,})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"No new entries today. Open positions still managed."
                    )
                except Exception:
                    pass
                self._kill_switch_alerted_today = True
            return

        # ── Phase 3.0.1 — Weekly-drawdown kill switch ────────────────────────
        # Upper-bound circuit breaker. If the cumulative ₹ P&L this trading
        # week (Mon through now) crosses -WEEKLY_LOSS_KILL_PCT of CAPITAL,
        # pause all new entries for the rest of the session AND set a flag
        # that persists through the day. Designed to halt before a chain of
        # bad days compounds. Existing positions still managed.
        try:
            from config.settings import WEEKLY_LOSS_KILL_PCT
        except ImportError:
            WEEKLY_LOSS_KILL_PCT = 0.075
        week_floor = -active_capital * WEEKLY_LOSS_KILL_PCT
        try:
            week_pnl = self.state.get_week_pnl()
        except Exception as e:
            print(f"[Allocator] week_pnl query failed (non-fatal): {e}")
            week_pnl = 0.0
        if week_pnl <= week_floor:
            print(f"[Allocator] 🔴 WEEKLY-DRAWDOWN KILL — "
                  f"this week's P&L ₹{week_pnl:+,.0f} ≤ floor ₹{week_floor:+,.0f} "
                  f"({WEEKLY_LOSS_KILL_PCT*100:.1f}% of ₹{active_capital:,}). "
                  f"BLOCKING new entries — manual review required.")
            if not getattr(self, "_week_kill_alerted_today", False):
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🔴 <b>WEEKLY DRAWDOWN KILL SWITCH</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📉 Week P&L: ₹{week_pnl:+,.0f}\n"
                        f"🚫 Floor: ₹{week_floor:+,.0f} "
                        f"({WEEKLY_LOSS_KILL_PCT*100:.1f}% of ₹{active_capital:,})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"All new entries blocked. Manual retrospective required."
                    )
                except Exception:
                    pass
                self._week_kill_alerted_today = True
            return

        # ── Phase 3.0.1 — Consecutive losing days pause ──────────────────────
        # If the boot-time check (see __init__) flagged that the prior streak
        # of losing days has reached CONSECUTIVE_LOSING_DAYS_PAUSE (default 5),
        # block entries until manual reset.
        if getattr(self, "_paused_consec_losses", False):
            print(f"[Allocator] ⏸ CONSECUTIVE-LOSSES PAUSE — "
                  f"{getattr(self, '_consec_losing_days', 0)} losing days streak. "
                  f"Manual reset required to resume.")
            return

        # ── Fix #179 (2026-05-18) — Portfolio-level post-loss cooldown ──────
        # Per-symbol cooldown protects against re-entering the loser. It does
        # NOT protect against the tilt pattern of chasing the next obvious
        # name. After any closed_loss today across the portfolio, block ALL
        # new entries (any symbol) for PORTFOLIO_LOSS_COOLDOWN_MIN minutes.
        # The -2.5% kill switch is the backstop; this is the intermediate
        # brake. Set PORTFOLIO_LOSS_COOLDOWN_MIN=0 to disable.
        try:
            from config.settings import PORTFOLIO_LOSS_COOLDOWN_MIN as _PLC
        except ImportError:
            _PLC = 0
        if _PLC > 0:
            mins_since_loss = self.state.minutes_since_last_portfolio_loss()
            if mins_since_loss is not None and mins_since_loss < _PLC:
                remaining = _PLC - mins_since_loss
                print(f"[Allocator] 🛑 PORTFOLIO REVENGE BRAKE — "
                      f"last loss {mins_since_loss:.0f}m ago, "
                      f"cooldown {_PLC}m, {remaining:.0f}m remaining. "
                      f"All new entries blocked across symbols.")
                self._rej("portfolio_revenge_cooldown")
                return

        # ── Tighten gate at +2R (Fix #11) — ride existing winners only ───────
        # Filter scored candidates to A+/A++ (≥8.0) once today_pnl crosses +2%.
        # Fix #160 (2026-05-18): in conviction mode, conviction_tier isn't
        # known until the per-symbol loop below runs. So we can't pre-filter
        # the list. Pre-filtering by stub final_score >= 8.0 would drop every
        # conviction admit silently (stub returns ~6). Defer the tighten check
        # to inside the loop (see `_tighten_after_profit` check after conviction
        # evaluation). Legacy path keeps pre-loop filter for back-compat.
        try:
            from config.settings import USE_CONVICTION_ENGINE as _UCE_T
        except ImportError:
            _UCE_T = False
        _tighten_active = today_pnl >= tighten_ceiling
        if _tighten_active and not _UCE_T:
            pre_count = len(scored)
            scored = [s for s in scored if s.get("final_score", 0) >= 8.0]
            if pre_count != len(scored):
                print(f"[Allocator] 🟡 +2R PROFIT — tightened gate to 8.0; "
                      f"{pre_count} → {len(scored)} candidates remain")
        elif _tighten_active:
            # Conviction mode: defer per-symbol; print one-time banner
            print(f"[Allocator] 🟡 +2R PROFIT — tighten active (S-tier only "
                  f"in conviction mode)")

        # ── PHASE 0 CONVICTION ENGINE — additional gate (2026-05-11) ──────
        # Replaces the deleted ScoringEngine multipliers. Fires before all the
        # existing filters as an early-skip. Validated on 584 NIFTY sessions:
        #   STRONG_GREEN macro + FHH break → 100% close positive (n=44)
        #   STRONG_RED macro              → 89% close negative, NEVER LONG
        # Feature-flagged via USE_CONVICTION_ENGINE — flip to False to roll back.
        try:
            from config.settings import USE_CONVICTION_ENGINE
        except ImportError:
            USE_CONVICTION_ENGINE = False  # fail-safe: old path

        # Fix #188 (2026-05-19) — drain "waiting on NIFTY FHH" queue once,
        # the first time NIFTY's FHH state goes from not-broken to clean-
        # broken. The queue contains scored signals that earlier in the
        # session were rejected by conviction for `nifty_fhh_not_broken`.
        # Prepend them to `scored` so they pass through the same conviction
        # loop below (which now finds FHH broken). Per-symbol dedup is
        # handled at queue-insertion time. The `_fhh_drained_today` flag
        # ensures we don't repeatedly drain on every tick post-break.
        if USE_CONVICTION_ENGINE and self._fhh_waiting_queue and not self._fhh_drained_today:
            try:
                nifty_fhh_state = self.fhh_detector.get_state("NIFTY 50")
                if getattr(nifty_fhh_state, "clean_high_break", False):
                    waiting = self._fhh_waiting_queue
                    n_waiting = len(waiting)
                    # Replay items as if they're fresh scored signals. The
                    # downstream conviction call still uses fresh quotes;
                    # the proximity check still uses fresh LTP vs the
                    # signal's entry_price; conviction now finds FHH broken.
                    scored = list(waiting) + list(scored)
                    self._fhh_waiting_queue = []
                    self._fhh_drained_today = True
                    syms = [s.get("symbol", "?") for s in waiting]
                    print(f"[Allocator] FHH broken — replaying {n_waiting} waiting "
                          f"signal(s): {syms}")
            except Exception as e:
                print(f"[Allocator] FHH-queue drain error (non-fatal): {e}")

        for s in scored:
            sym    = s["symbol"]
            sector = s.get("sector", get_sector(sym))

            # Max positions
            if len(open_pos) >= active_max_positions:
                print(f"[Allocator] Max positions reached ({active_max_positions})")
                break

            # Already in this stock
            if any(p.symbol == sym for p in open_pos):
                self._rej("already_open"); continue

            # ── Conviction engine pre-filter ──────────────────────────────
            # This is the heart of the Phase 0 rebuild. Macro state + FHH
            # break decide whether to take the trade and at what tier.
            # When the macro filter says STRONG_RED, this skips the entry
            # before any of the legacy filters run. Cheap, structural,
            # 30-month-validated.
            conviction_result = None
            if USE_CONVICTION_ENGINE:
                try:
                    # Fix #167 (2026-05-18): was firing get_quotes([sym]) TWICE here —
                    # once for stock_quote, once just to extract depth. The same
                    # full-quote response already contains depth.
                    # Fix #168 (2026-05-18): now reads from the per-tick cache
                    # populated by _scan_market's batch fetch. ~360 Kite calls
                    # per tick → ~3. And conviction reads the same price every
                    # downstream consumer reads — no race.
                    live_q_for_conv = self._get_cached_quote(sym)
                    stock_quote = live_q_for_conv.get(sym, {})
                    order_book = stock_quote.get("depth")
                    # Build minimal setup-like object the engine can read .grade from
                    class _SetupView:
                        def __init__(self, grade): self.grade = grade
                    setup_view = _SetupView(s.get("grade"))
                    conviction_result = self.conviction.evaluate(
                        symbol=sym,
                        setup=setup_view,
                        stock_quote=stock_quote,
                        order_book=order_book,
                    )
                    if conviction_result.tier == "SKIP":
                        print(f"[Conviction] {sym} SKIP — {conviction_result.reasoning}")
                        # Fix #175 (2026-05-18): bucket SKIPs by REASON TYPE,
                        # not by the value-laden reasoning string. Before,
                        # `conviction_stock_extended_off_hod_2.34%` and
                        # `..._2.41%` were separate N-of-1 buckets. Now both
                        # collapse to `conviction_stock_extended_off_hod`, so
                        # the per-tick rejection histogram is readable.
                        reason_root = (conviction_result.reasoning or "unknown").split("_")
                        # Take leading non-numeric tokens (e.g.,
                        # ["stock", "extended", "off", "hod", "2.34%"] → "stock_extended_off_hod")
                        bucket_tokens = []
                        for tok in reason_root:
                            if any(c.isdigit() for c in tok):
                                break
                            bucket_tokens.append(tok)
                        bucket = "_".join(bucket_tokens) if bucket_tokens else reason_root[0]
                        self._rej(f"conviction_{bucket}")
                        # Also track tier=SKIP for the histogram
                        self._tier_hist["SKIP"] = self._tier_hist.get("SKIP", 0) + 1
                        # Fix #188 (2026-05-19) — queue scored signal for replay
                        # when NIFTY's FHH breaks. Only applies pre-FHH-break;
                        # once drained for today, we stop accumulating. Dedup by
                        # symbol so we don't add the same name on every tick.
                        if bucket == "nifty_fhh_not_broken" and not self._fhh_drained_today:
                            already_queued = any(
                                q.get("symbol") == sym for q in self._fhh_waiting_queue
                            )
                            if not already_queued:
                                # Cap queue size at 20 to bound memory & replay cost
                                if len(self._fhh_waiting_queue) < 20:
                                    self._fhh_waiting_queue.append(s)
                                    print(f"[Allocator] {sym} queued for post-FHH replay "
                                          f"(queue size {len(self._fhh_waiting_queue)})")
                        continue
                    else:
                        print(f"[Conviction] {sym} TIER_{conviction_result.tier} — {conviction_result.reasoning}")
                        # Fix #175 — tally tier for the per-tick distribution
                        self._tier_hist[conviction_result.tier] = self._tier_hist.get(conviction_result.tier, 0) + 1
                        # Stash result on the scored dict so sizing can use it later
                        s["conviction_tier"]    = conviction_result.tier
                        s["conviction_risk"]    = conviction_result.risk_inr
                        s["conviction_target"]  = conviction_result.target_inr
                        s["conviction_size_mult"] = conviction_result.size_multiplier
                        # Fix #160 — deferred +2R tighten check (see _allocate
                        # preamble above). In conviction mode, only S-tier passes
                        # after the +2R lockout threshold.
                        if _tighten_active and conviction_result.tier != "S":
                            print(f"[Allocator] {sym} +2R tighten — tier "
                                  f"{conviction_result.tier} below S, skip")
                            self._rej("post_profit_tighten")
                            continue
                except Exception as e:
                    # Conviction engine errors should NEVER block trading — fail open
                    # to the legacy path. The error gets logged for diagnosis.
                    print(f"[Conviction] error on {sym}, falling back to legacy: {e}")

            # ── Symbol auto-blacklist (Fix #27 / D2) ─────────────────────────
            if self.state.is_symbol_blacklisted(sym):
                print(f"[Allocator] {sym} auto-blacklisted (poor rolling-30 WR) — skip")
                self._rej("blacklisted"); continue

            # ── Cooldown + smart re-entry (Fix #26 / C1) ────────────────────
            strikes_today = self.state.count_today_trades_on(sym)
            if strikes_today >= 2:
                print(f"[Allocator] {sym} 2 strikes used today — skip")
                self._rej("max_strikes"); continue
            if self.state.is_in_cooldown(
                sym,
                after_loss_minutes=COOLDOWN_AFTER_LOSS_MIN,
                after_win_minutes=COOLDOWN_AFTER_WIN_MIN,
            ):
                print(f"[Allocator] {sym} in cooldown (45m loss / 15m win) — skip")
                self._rej("cooldown"); continue
            second_strike = (strikes_today == 1)

            # Sector cap
            sec_count = sum(1 for p in open_pos if get_sector(p.symbol) == sector)
            if sec_count >= MAX_SAME_SECTOR_POSITIONS:
                print(f"[Allocator] {sym} sector {sector} full — skip")
                self._rej("sector_full"); continue

            # ── Fix #13 — fetch FRESH LTP at order time ───────────────────
            try:
                live_q = self.kite.get_quotes([sym])
                live_ltp = float(live_q.get(sym, {}).get("last_price", 0) or 0)
            except Exception as e:
                print(f"[Allocator] {sym} live quote failed ({e}) — skip")
                self._rej("live_quote_fail"); continue
            if live_ltp <= 0:
                print(f"[Allocator] {sym} no live LTP — skip")
                self._rej("live_ltp_zero"); continue

            # ── Spread filter (Fix #43 / P1) ─────────────────────────────────
            # Reject names with bid-ask spread > ENTRY_MAX_SPREAD_PCT. Wide
            # spreads silently destroy scalp R:R — a 0.10% spread on a 0.7%
            # stop eats 28% of TP1's gross. spread=999 means depth unavailable
            # → defer (treat as too-wide rather than fail-open).
            try:
                spread_pct = self.kite.get_spread_pct(sym)
            except Exception:
                spread_pct = 999.0
            if spread_pct >= 999.0:
                print(f"[Allocator] {sym} spread depth unavailable — defer")
                self._rej("spread_no_depth"); continue
            if spread_pct > ENTRY_MAX_SPREAD_PCT:
                print(f"[Allocator] {sym} spread {spread_pct:.3f}% > "
                      f"{ENTRY_MAX_SPREAD_PCT:.3f}% — bleed risk, skip")
                self._rej("spread_too_wide"); continue

            signal_px = float(s["entry_price"])
            drift = abs(live_ltp - signal_px) / signal_px if signal_px > 0 else 1.0

            # Fix #19 — leaders (strong movers with positive RS) get a relaxed
            # proximity ceiling so we don't keep rejecting trending stocks for
            # the very thing that makes them tradeable.
            is_leader = False
            try:
                live_chg = float(live_q.get(sym, {}).get("change_pct", 0) or 0)
                rs_d     = float(s.get("rs_delta", 0) or 0)
                if live_chg >= LEADER_DAY_CHG_PCT and rs_d >= LEADER_RS_DELTA_PCT:
                    is_leader = True
            except Exception:
                pass
            prox_max = LEADER_PROXIMITY_MAX_PCT if is_leader else PROXIMITY_MAX_PCT

            if drift > prox_max:
                tag = " LEADER" if is_leader else ""
                print(f"[Allocator] {sym} drifted {drift*100:.2f}% > {prox_max*100:.2f}%{tag} "
                      f"— signal ₹{signal_px:.2f} → live ₹{live_ltp:.2f} — skip")
                self._rej("proximity_drift" + ("_leader" if is_leader else "")); continue
            if is_leader and drift > PROXIMITY_MAX_PCT:
                print(f"[Allocator] ⚡ LEADER {sym} drift {drift*100:.2f}% allowed "
                      f"(chg={live_chg:.1f}% RS={rs_d:+.1f}%)")

            # ── 15-min HTF trend filter (Fix #20) ─────────────────────────────
            # Reject counter-trend scalps — these are the highest-failure
            # category in the trade-log analysis. Only veto LONGs when the
            # higher timeframe is firmly DOWN.
            try:
                htf = self.kite.get_htf_trend(sym)
            except Exception:
                htf = "neutral"
            if s.get("direction", "long") == "long" and htf == "down":
                print(f"[Allocator] {sym} 15m HTF trend is DOWN — counter-trend, skip")
                self._rej("htf_down"); continue

            # Overwrite with the actual fill price; recompute TPs from it.
            # SL stays — it's a technical level, not a price-relative offset.
            # Fix #16 — apply paper slippage so paper P&L reflects realistic
            # entry-fill quality (no-op in live mode).
            entry_side = "buy" if s.get("direction", "long") == "long" else "sell"
            s["entry_price"] = _apply_paper_slippage(live_ltp, entry_side, "entry")
            s["tp1_price"]   = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R1)
            s["tp2_price"]   = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R2)

            # ── Signal-age skip (Fix #36 / A2 — restructured by Fix #160) ────
            # If the signal bar is > 5 min old, the tape has likely moved past
            # the structural condition the setup keyed on. In legacy mode this
            # was a score-decay-and-re-gate; in conviction mode (where score
            # is not a gate) it's a hard age cap. Either way: stale signal,
            # don't act on it.
            try:
                det_iso = s.get("detected_at")
                if det_iso:
                    det_dt = datetime.fromisoformat(det_iso)
                    if det_dt.tzinfo is None:
                        det_dt = det_dt.replace(tzinfo=IST)
                    age_min = (_now_ist() - det_dt).total_seconds() / 60.0
                    if age_min > 5.0:
                        if _UCE_T:
                            # Conviction mode: stale signal is stale signal.
                            # Conviction already validated structure at the
                            # quote-fetch above, but the entry/SL prices come
                            # from a 5+ minute old bar — they're stale.
                            print(f"[Allocator] {sym} signal aged {age_min:.1f}m "
                                  f"> 5m — skip (stale entry/SL prices)")
                            self._rej("signal_too_old"); continue
                        else:
                            # Legacy path: decay score and re-gate
                            decay = 0.5
                            old_score = s.get("final_score", 0)
                            s["final_score"] = max(0.0, old_score - decay)
                            print(f"[Allocator] {sym} signal aged {age_min:.1f}m — "
                                  f"score decay {old_score:.1f} → {s['final_score']:.1f}")
                            if s["final_score"] < MIN_SCORE_ENTRY:
                                print(f"[Allocator] {sym} post-decay score below gate — skip")
                                self._rej("score_decay_below_gate"); continue
            except Exception:
                pass

            # Position sizing (uses the corrected entry)
            dist  = s["entry_price"] - s["stop_loss"]
            if dist <= 0:
                print(f"[Allocator] {sym} live LTP ≤ SL — skip")
                self._rej("ltp_below_sl"); continue

            # Fix #31 (C2) — gradient dampener replaces binary CONSERVATIVE cliff.
            # Smoothly de-risks 0→1→2→3→4+ consec losses.
            tier_idx     = min(consec, len(LOSER_STREAK_SIZE_TIERS) - 1)
            multiplier   = LOSER_STREAK_SIZE_TIERS[tier_idx]
            conservative = consec >= MAX_CONSECUTIVE_LOSSES   # kept for downstream flags
            # Fix #160 (2026-05-18): grade-based sizing tier was double-scaling
            # in conviction mode — conviction already provides `size_multiplier`
            # via `conviction_size_mult` (S=1.0, A=0.7, B=0.4, decoupling=0.5).
            # Multiplying by SCORE_SIZE_TIERS[grade] on top gave ~0.25x sizing
            # for A-tier admits (legacy grade tier from stub score ~6 = "B" tier
            # = 0.25). In conviction mode: use conviction_size_mult directly.
            if _UCE_T and "conviction_size_mult" in s:
                grade_tier = float(s.get("conviction_size_mult", 1.0))
            else:
                # Fix #23 (A6) — legacy grade-based sizing tier.
                grade_tier = SCORE_SIZE_TIERS.get(s.get("grade", ""), 0.5)
            # Fix #26 (C1) — second strike on same stock today → half size
            second_dampen = 0.5 if second_strike else 1.0
            risk_amount  = active_capital * RISK_PER_TRADE_PCT * multiplier * grade_tier * second_dampen
            if second_strike:
                print(f"[Allocator] {sym} 2nd strike today — sizing dampened ×0.5")
            qty          = floor(risk_amount / dist)
            # Cap 1: max 10% of active capital per position (prevents 1 trade
            # using all capital — and stays correct under probe mode)
            max_pos_val  = active_capital * MAX_POSITION_VALUE_PCT
            qty          = min(qty, floor(max_pos_val / s["entry_price"]))
            # Cap 2: can't exceed available capital
            qty          = min(qty, floor(self.state.get_available_capital() / s["entry_price"]))
            qty          = max(0, qty)

            if qty < 1:
                print(f"[Allocator] {sym} qty=0 — insufficient capital")
                self._rej("qty_zero"); continue

            # ── Sizing floor (Fix #9) — no qty=1 token trades ─────────────────
            # When capital is mostly deployed, the 3rd cap above can push qty
            # down to 1-2 shares. A 1-share trade can't earn the ₹1500-3000
            # net target — the cost stack alone (~₹40-200/leg) leaves nothing.
            # Reject below thresholds and watchlist instead.
            # Fix #161: thresholds now scale with active_capital so the probe
            # mode (₹50k) doesn't apply paper-sized floors that would block
            # every probe trade.
            risk_taken = qty * dist
            position_val = qty * s["entry_price"]
            min_risk = active_capital * MIN_RISK_PER_TRADE_PCT
            min_pos  = active_capital * MIN_POSITION_VALUE_PCT
            if risk_taken < min_risk or position_val < min_pos:
                reason_skip = (f"qty={qty} risk=₹{risk_taken:.0f} pos=₹{position_val:.0f} — "
                               f"below floor (need risk≥₹{min_risk:.0f} pos≥₹{min_pos:.0f}) — watchlist")
                print(f"[Allocator] {sym} {reason_skip}")
                self._add_watchlist(sym, s, s.get("final_score", 0), s.get("reason", ""))
                self._rej("below_size_floor"); continue

            # Enter!
            tp1 = s.get("tp1_price") or _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R1)
            tp2 = s.get("tp2_price") or _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R2)

            pos_id = self.state.open_position(
                symbol=sym,
                setup_type=s["setup_type"],
                grade=s["grade"],
                score=s["final_score"],
                confidence=s["confidence"],
                entry_price=s["entry_price"],
                stop_loss=s["stop_loss"],
                tp1_price=tp1,
                tp2_price=tp2,
                quantity=qty,
                entry_reason=s.get("reason", ""),
                score_breakdown=s.get("score_breakdown"),
                direction=s.get("direction", "long"),
                sector=sector,
                regime=self._regime_cache.get("regime", ""),  # Fix #14
            )

            tx = "BUY" if s.get("direction", "long") == "long" else "SELL"
            # Fix #170 (2026-05-18) — capture return value + rollback on broker
            # reject. Was: `self.kite.place_order(sym, tx, qty)` with no return
            # check. In live mode, place_order returns None on broker reject
            # (insufficient margin, frozen symbol, market-not-open, etc.).
            # Without rollback, the position row written above was a phantom:
            # state thinks we own qty shares, broker has no record. Critical
            # before flipping PAPER_TRADING=False for the live probe.
            entry_order_id = self.kite.place_order(sym, tx, qty)
            if entry_order_id is None and not PAPER_TRADING:
                # Live mode reject — roll back. Paper mode always returns a
                # fake id so this branch only fires for real broker failures.
                print(f"[Allocator] 🛑 ENTRY REJECTED by broker — {sym} "
                      f"{tx} {qty} (no order id returned). Rolling back "
                      f"phantom position row id={pos_id}.")
                try:
                    self.state.delete_position_row(pos_id)
                except Exception as _e:
                    print(f"[Allocator] rollback delete failed: {_e}")
                # Telegram alert so the operator sees this immediately
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🛑 <b>ENTRY REJECTED</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔴 {sym} {tx} {qty}\n"
                        f"Broker returned no order id. Position row deleted.\n"
                        f"Check margin / symbol-freeze / market session."
                    )
                except Exception:
                    pass
                self._rej("entry_order_rejected")
                continue

            # Broker-side SL-M (Fix #6) — opposite side, trigger at the stop
            sl_tx = "SELL" if s.get("direction", "long") == "long" else "BUY"
            sl_oid = self.kite.place_sl_order(
                symbol=sym, transaction=sl_tx, quantity=qty,
                trigger=s["stop_loss"], price=s["stop_loss"],
            )
            if sl_oid:
                self.state.update_sl_order_id(pos_id, sl_oid)
                print(f"[Allocator] 🛑 SL-M placed {sym} trigger={s['stop_loss']} id={sl_oid}")
            elif not PAPER_TRADING:
                # Fix #177 (2026-05-18) — CRITICAL pre-live safety.
                # Entry filled but SL-M placement failed (broker timeout, margin
                # pinch on the protective order, symbol frozen on stop side,
                # SEBI surveillance flip mid-session, etc.). Without this branch
                # the position lives with no broker-side stop. Market gaps
                # against us → full exposure instead of the -1R we sized for.
                # Action: immediate market exit on the just-entered position,
                # close the row as `sl_place_failed`, Telegram-alert the
                # operator so the failure is visible within seconds.
                print(f"[Allocator] 🆘 SL-M PLACEMENT FAILED for {sym} — "
                      f"firing immediate market exit to avoid unprotected position")
                exit_tx = "SELL" if s.get("direction", "long") == "long" else "BUY"
                exit_order_id = None
                try:
                    exit_order_id = self.kite.place_order(sym, exit_tx, qty)
                except Exception as _xe:
                    print(f"[Allocator] 🆘 emergency-exit place_order raised: {_xe}")
                # Compute realised P&L using the entry fill price as best-effort
                # exit reference. The real fill price will reconcile via the
                # broker; this row's pnl is a placeholder.
                try:
                    self.state.close_position(
                        pos_id,
                        exit_price=s["entry_price"],
                        pnl=0.0,
                        pnl_r=0.0,
                        status="closed_sl_place_failed",
                        exit_reason="sl_m_placement_failed_emergency_exit",
                    )
                except Exception as _ce:
                    print(f"[Allocator] 🆘 close_position after emergency exit failed: {_ce}")
                # Telegram — operator must see this immediately
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🆘 <b>SL-M PLACEMENT FAILED — emergency exit</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔴 {sym} {tx} {qty} entered @ ₹{s['entry_price']:.2f}\n"
                        f"❌ Protective SL-M order rejected by broker.\n"
                        f"⚡ Fired market exit (order id: {exit_order_id or 'NONE — VERIFY MANUALLY'})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"CHECK BROKER ACCOUNT NOW — position may still be open."
                    )
                except Exception:
                    pass
                self._rej("sl_placement_failed_emergency_exit")
                continue

            # Telegram entry alert
            try:
                alert_trade_entry(
                    symbol=sym,
                    setup_type=s["setup_type"],
                    grade=s["grade"],
                    score=s["final_score"],
                    confidence=s["confidence"],
                    entry_price=s["entry_price"],
                    stop_loss=s["stop_loss"],
                    tp1_price=tp1,
                    tp2_price=tp2,
                    quantity=qty,
                    reason=s.get("reason", ""),
                    score_breakdown=s.get("score_breakdown"),
                )
            except Exception:
                pass

            print(f"[Allocator] ✅ ENTERED {sym} qty={qty} grade={s['grade']} "
                  f"score={s['final_score']:.1f} entry={s['entry_price']}")

            # Phase 2.0 B6 — count actual entries (post-conviction, post-allocator).
            # The tick summary's "N entries" now reflects real position opens,
            # not just scorer passes.
            self._entries_this_tick += 1

            # Refresh open_pos after each entry
            open_pos = self.state.get_open_positions()

        # Alert if consecutive losses triggered conservative mode
        if consec >= MAX_CONSECUTIVE_LOSSES:
            try:
                alert_consecutive_losses(consec, MIN_SCORE_ENTRY_CONSERVATIVE)
            except Exception:
                pass

    # ── Agent 8b: Position Manager ────────────────────────────────────────────

    def _manage_positions(self):
        """
        For every open position:
          • Position is from a prior session → force-close (overnight veto)
          • Hit SL → full exit (initial = sl_hit, post-trail = sl_trail_hit)
          • Hit TP1 → 50% exit, SL → breakeven, start trailing
          • Hit TP2 (or tp1+trailing hit) → full exit (closed_win)
          • Stalled (>45 min, <0.15R move) → close
          • EOD at 15:00 → close all
        """
        open_pos = self.state.get_open_positions()
        if not open_pos:
            return

        now = _now_ist()
        eod = _parse_time(EOD_CLOSE_TIME)   # 15:00
        print(f"[PosMgr] Managing {len(open_pos)} open positions")

        # Batch quotes for all open positions
        syms = [p.symbol for p in open_pos]
        try:
            quotes = self.kite.get_quotes(syms)
        except Exception:
            quotes = {}

        today_ist = now.date()

        for p in open_pos:
            curr = quotes.get(p.symbol, {}).get("last_price", p.entry_price)

            # ── Overnight veto ────────────────────────────────────────────────
            # Any position with entry_time on a prior session must NEVER survive
            # into today. Root cause of the ASIANPAINT 19.85h paper hold:
            # 15:00 EOD force-close didn't fire on 2026-04-20. Belt-and-braces:
            # at every tick, if a position's entry date != today (IST), close it
            # immediately at LTP and tag as overnight_exit.
            if p.entry_time:
                try:
                    entry_dt_ist = _entry_dt_aware(p.entry_time)
                    if entry_dt_ist.date() != today_ist:
                        print(f"[PosMgr] ⚠ OVERNIGHT VETO {p.symbol} — "
                              f"entered {entry_dt_ist.date()}, today is {today_ist}")
                        self._full_exit(p, curr, "overnight_exit")
                        continue
                except Exception:
                    pass

            # ── EOD: close everything ──────────────────────────────────────────
            # Fix #59 — single force-close at EOD_CLOSE_TIME (15:15 IST).
            # Removed the bogus "partial unwind tied to NO_NEW_ENTRY_AFTER"
            # block (Fix #34/B9 originally 14:45) which after Fix #47 was
            # firing at 13:30 — closing positions 105 minutes before market
            # close. NSE's last 30 min (15:00-15:30) has real momentum
            # (institutional rebalancing, expiry hedging, closing prints).
            # Let each position ride its own SL/TP/trail through the natural
            # session; force-close everything at 15:15 (5 min before Zerodha
            # MIS auto-square at 15:20).
            if now.time() >= eod:
                self._full_exit(p, curr, "eod_exit")
                continue

            # ── SL hit (distinguish initial from trailed) ────────────────────
            if curr <= p.stop_loss:
                # If stop has been moved above initial_sl, it's a trailing exit
                # (price ran in our favour, we tightened, then it pulled back).
                # That should NOT be analytics-classified as a loss like an
                # initial-SL hit; the P&L is often positive.
                trailed = p.tp1_hit or (p.initial_sl and p.stop_loss > p.initial_sl + 1e-6)
                reason = "sl_trail_hit" if trailed else "sl_hit"
                self._full_exit(p, curr, reason)
                continue

            # ── TP2 hit (after TP1 already taken) ─────────────────────────────
            if p.tp1_hit and curr >= p.tp2_price:
                self._full_exit(p, curr, "tp2_hit")
                continue

            # ── TP1 hit (first time) ──────────────────────────────────────────
            if not p.tp1_hit and curr >= p.tp1_price:
                self._partial_exit_tp1(p, curr)
                # After TP1, move SL to breakeven and continue
                continue

            # ── Trailing SL (only after TP1 hit) ─────────────────────────────
            if p.tp1_hit and TRAILING_SL_ENABLED:
                self._try_trail_sl(p, curr)

            # ── Pre-TP1 trail SL (Phase 1.2 — Fix #71) ──────────────────────
            # Once a trade has been favorable by +0.5R AND has held that
            # level for ≥10 minutes, tighten the SL to entry (breakeven).
            # This protects the "MAXHEALTH-class" trades that go +₹421 then
            # reverse to -₹515 because the SL was never moved.
            #
            # Lazy state: track first-time-crossed-threshold per position in
            # self._pre_tp1_threshold_first_seen (dict, position_id → datetime).
            if not p.tp1_hit and p.entry_time:
                try:
                    from config.settings import (
                        PRE_TP1_TRAIL_ENABLED,
                        PRE_TP1_TRAIL_TRIGGER_R,
                        PRE_TP1_TRAIL_HOLD_MIN,
                    )
                    if PRE_TP1_TRAIL_ENABLED:
                        if not hasattr(self, "_pre_tp1_first_seen"):
                            self._pre_tp1_first_seen = {}
                        sl_dist  = abs(p.entry_price - p.initial_sl) or 0.01
                        pnl_r    = ((curr - p.entry_price) / sl_dist
                                    if p.direction == "long"
                                    else (p.entry_price - curr) / sl_dist)
                        already_at_be = abs(p.stop_loss - p.entry_price) < 0.05
                        if pnl_r >= PRE_TP1_TRAIL_TRIGGER_R and not already_at_be:
                            if p.id not in self._pre_tp1_first_seen:
                                self._pre_tp1_first_seen[p.id] = now
                            held_min = (now - self._pre_tp1_first_seen[p.id]).total_seconds() / 60
                            if held_min >= PRE_TP1_TRAIL_HOLD_MIN:
                                # Tighten SL to entry. Use existing trail
                                # infrastructure if available; fall back to
                                # direct state update.
                                new_sl = round(p.entry_price, 2)
                                if new_sl > p.stop_loss:
                                    print(f"[PreTP1Trail] {p.symbol} held +{PRE_TP1_TRAIL_TRIGGER_R}R "
                                          f"for {held_min:.0f}min → SL {p.stop_loss:.2f} → "
                                          f"{new_sl:.2f} (breakeven)")
                                    self.state.update_stop_loss(p.id, new_sl)
                                    p.stop_loss = new_sl
                                    # Best-effort SL-M order replacement (live mode)
                                    # Pattern mirrors _partial_exit_tp1 / _try_trail_sl: cancel
                                    # old SL-M, place new one at new trigger. modify_order isn't
                                    # in KiteDataClient — cancel+replace is the supported path.
                                    try:
                                        if not PAPER_TRADING and getattr(p, "sl_order_id", None):
                                            self.kite.cancel_order(p.sl_order_id)
                                            # Fix #159 (2026-05-18): place_sl_order signature is
                                            # (symbol, transaction, quantity, trigger, price) — the
                                            # original kwargs (trigger_price/direction) would TypeError
                                            # on every live trail; the broad except below would hide it
                                            # and the SL would stay at the original stop.
                                            sl_tx = "SELL" if p.direction == "long" else "BUY"
                                            new_oid = self.kite.place_sl_order(
                                                symbol=p.symbol,
                                                transaction=sl_tx,
                                                quantity=p.quantity_remaining,
                                                trigger=new_sl,
                                                price=new_sl,
                                            )
                                            if new_oid:
                                                self.state.update_sl_order_id(p.id, new_oid)
                                            else:
                                                # Fix #195 — SL-M returned None. Position now naked.
                                                self._alert_naked_sl(p, new_sl, "PreTP1Trail")
                                    except Exception as _e:
                                        # Fix #195 — surface the failure loudly via Telegram + retry.
                                        # Was: silent print + pass, leaving the position uncovered.
                                        print(f"[PreTP1Trail] SL-M replacement failed on {p.symbol}: {_e}")
                                        if not PAPER_TRADING:
                                            self._alert_naked_sl(p, new_sl, "PreTP1Trail exception", error=str(_e))
                        elif pnl_r < PRE_TP1_TRAIL_TRIGGER_R and p.id in self._pre_tp1_first_seen:
                            # Dropped below the trigger before we got 10 min hold
                            # — reset the timer so subsequent re-cross requires
                            # another 10 min of stable favorable territory.
                            del self._pre_tp1_first_seen[p.id]
                except Exception as _e:
                    pass

            # ── Mid-trade structural re-evaluation (Phase 2.7) ──────────────
            # At most once every MID_TRADE_REEVAL_INTERVAL_MIN per position,
            # re-check the 3-dim thesis (macro / VWAP / HOD-proximity).
            # Shadow-mode default — logs [Reeval] lines without acting until
            # MID_TRADE_REEVAL_ENABLED=True.
            try:
                from config.settings import (
                    MID_TRADE_REEVAL_ENABLED,
                    MID_TRADE_REEVAL_LOG_SHADOW,
                )
                if (MID_TRADE_REEVAL_ENABLED or MID_TRADE_REEVAL_LOG_SHADOW) \
                        and self.reeval.should_check(p.id, now):
                    # Compute VWAP — try the per-tick cache first; fall back
                    # to a fresh fetch+compute for symbols not in cache.
                    vwap = self._vwap_cache.get(p.symbol, 0.0)
                    if vwap <= 0:
                        try:
                            df = self.kite.get_candles(p.symbol, interval="5minute", days=1)
                            if df is not None and len(df) > 0:
                                df_today = self.kite._filter_to_today(df) if hasattr(self.kite, "_filter_to_today") else df
                                if df_today is not None and len(df_today) > 0:
                                    vwap_series = self.kite.calculate_vwap(df_today)
                                    if vwap_series is not None and len(vwap_series) > 0:
                                        vwap = float(vwap_series.iloc[-1])
                        except Exception:
                            vwap = 0.0

                    rr = self.reeval.evaluate(p, quotes.get(p.symbol, {"last_price": curr}), vwap, now)

                    if rr.action == "CONTINUE":
                        pass   # no log — only fires on transitions
                    elif rr.action == "TIGHTEN_TO_BE":
                        marker = "ENABLED" if MID_TRADE_REEVAL_ENABLED else "SHADOW"
                        print(f"[Reeval] {p.symbol} TIGHTEN-{marker} — "
                              f"macro={rr.macro_state} ltp={rr.ltp:.2f} vwap={rr.vwap:.2f} "
                              f"pull-from-HOD={rr.pull_from_hod_pct:.2f}% — {rr.reason}")
                        # Phase 2.9 — audit record for dashboard shadow tab
                        try:
                            from tools.shadow_log import record_shadow_event
                            record_shadow_event("reeval_tighten", {
                                "symbol": p.symbol, "marker": marker,
                                "macro_state": rr.macro_state,
                                "ltp": rr.ltp, "vwap": rr.vwap,
                                "pull_from_hod_pct": rr.pull_from_hod_pct,
                                "broken_dims": rr.broken_dims,
                                "broken_count": rr.broken_count,
                                "entry_price": p.entry_price,
                                "current_sl": p.stop_loss,
                                "reason": rr.reason,
                            }, "reeval_shadow.jsonl")
                        except Exception:
                            pass
                        if MID_TRADE_REEVAL_ENABLED and p.stop_loss < p.entry_price:
                            new_sl = round(p.entry_price, 2)
                            self.state.update_stop_loss(p.id, new_sl)
                            p.stop_loss = new_sl
                            # Best-effort SL-M replacement in live mode
                            try:
                                if not PAPER_TRADING and getattr(p, "sl_order_id", None):
                                    self.kite.cancel_order(p.sl_order_id)
                                    # Fix #159 (2026-05-18): same kwargs bug as PreTP1Trail above.
                                    sl_tx = "SELL" if p.direction == "long" else "BUY"
                                    new_oid = self.kite.place_sl_order(
                                        symbol=p.symbol,
                                        transaction=sl_tx,
                                        quantity=p.quantity_remaining,
                                        trigger=new_sl,
                                        price=new_sl,
                                    )
                                    if new_oid:
                                        self.state.update_sl_order_id(p.id, new_oid)
                                    else:
                                        # Fix #195 — SL-M returned None. Position now naked.
                                        self._alert_naked_sl(p, new_sl, "Reeval-Tighten")
                            except Exception as _e:
                                print(f"[Reeval] SL-M replacement failed on {p.symbol}: {_e}")
                                if not PAPER_TRADING:
                                    self._alert_naked_sl(p, new_sl, "Reeval-Tighten exception", error=str(_e))
                    elif rr.action == "CLOSE":
                        marker = "ENABLED" if MID_TRADE_REEVAL_ENABLED else "SHADOW"
                        print(f"[Reeval] {p.symbol} CLOSE-{marker} — "
                              f"macro={rr.macro_state} ltp={rr.ltp:.2f} vwap={rr.vwap:.2f} "
                              f"pull-from-HOD={rr.pull_from_hod_pct:.2f}% — {rr.reason}")
                        try:
                            from tools.shadow_log import record_shadow_event
                            record_shadow_event("reeval_close", {
                                "symbol": p.symbol, "marker": marker,
                                "macro_state": rr.macro_state,
                                "ltp": rr.ltp, "vwap": rr.vwap,
                                "pull_from_hod_pct": rr.pull_from_hod_pct,
                                "broken_dims": rr.broken_dims,
                                "broken_count": rr.broken_count,
                                "entry_price": p.entry_price,
                                "reason": rr.reason,
                            }, "reeval_shadow.jsonl")
                        except Exception:
                            pass
                        if MID_TRADE_REEVAL_ENABLED:
                            self._full_exit(p, curr, "thesis_invalidated")
                            # drop from re-eval state (position is closing)
                            self.reeval.drop_position(p.id)
                            continue
            except Exception as _e:
                # Re-eval is best-effort — never break position management
                print(f"[Reeval] {p.symbol} evaluator error (non-fatal): {_e}")

            # ── Stall detection — tiered (Fix #32 / B5) ──────────────────────
            # Tier 1 (early): 25 min + pnl_r ∈ [-0.5, +0.3] → exit (no momentum
            #   either way — capital better used elsewhere).
            # Tier 2 (severe): 45 min + |pnl_r| ≤ 0.3 → exit (truly stuck, was
            #   ≤0.15R which almost never fired).
            # `_entry_dt_aware()` (Fix #1) keeps elapsed math correct on UTC host.
            if not p.tp1_hit and p.entry_time:
                try:
                    entry_dt = _entry_dt_aware(p.entry_time)
                    elapsed  = (now - entry_dt).total_seconds() / 60
                    sl_dist  = abs(p.entry_price - p.initial_sl) or 0.01
                    pnl_r    = (curr - p.entry_price) / sl_dist if p.direction == "long" \
                               else (p.entry_price - curr) / sl_dist
                    if elapsed >= 25 and -0.5 <= pnl_r <= 0.3:
                        self._full_exit(p, curr, "stalled_no_movement")
                        continue
                    if elapsed >= 45 and abs(pnl_r) <= 0.3:
                        self._full_exit(p, curr, "stalled_no_movement")
                        continue
                except Exception:
                    pass

            print(f"[PosMgr] HOLD {p.symbol} @ {curr:.2f} | "
                  f"SL={p.stop_loss:.2f} TP1={p.tp1_price:.2f} TP2={p.tp2_price:.2f} "
                  f"tp1_hit={p.tp1_hit}")

    def _partial_exit_tp1(self, p, curr: float):
        """Exit 50% at TP1. Move SL to breakeven (broker-side SL-M replaced)."""
        from math import floor
        # Fix #13 — refetch live LTP for honest fill price (curr from
        # _manage_positions can be a few hundred ms stale)
        try:
            fq = self.kite.get_quotes([p.symbol])
            fresh = float(fq.get(p.symbol, {}).get("last_price", 0) or 0)
            if fresh > 0:
                curr = fresh
        except Exception:
            pass
        # Fix #16 — paper-mode target slippage (limit order, small drag)
        exit_side = "sell" if p.direction == "long" else "buy"
        curr = _apply_paper_slippage(curr, exit_side, "target")

        qty_exit      = floor(p.quantity_remaining / 2)
        qty_remaining = p.quantity_remaining - qty_exit
        if qty_exit < 1:
            return

        partial_pnl = (curr - p.entry_price) * qty_exit
        new_sl      = p.entry_price   # breakeven

        tx = "SELL" if p.direction == "long" else "BUY"
        # Fix #194 (2026-05-19) — order reversal: place market exit FIRST,
        # check return, THEN update DB. Mirrors Fix #170 (entry rollback).
        # Was: mark_tp1_hit + update_stop_loss called BEFORE place_order.
        # In live mode, if broker rejects the partial-exit MARKET order
        # (frozen symbol, daily limit reached, insufficient margin for
        # square-off etc.), the DB would record tp1_hit=1 + qty_remaining=
        # half while no shares were actually sold. The SL-M would then get
        # cancelled and re-placed for qty_remaining (half), leaving the
        # un-sold half covered only by the original SL on full size.
        # Outcome: bookkeeping shows TP1 hit, broker holds full position,
        # SL covers only half. Now we fire the order first; only update DB
        # on success or in paper.
        tp1_order_id = self.kite.place_order(p.symbol, tx, qty_exit)
        if tp1_order_id is None and not PAPER_TRADING:
            print(f"[PosMgr] 🛑 TP1 PARTIAL EXIT REJECTED by broker — {p.symbol} "
                  f"{tx} {qty_exit} (no order id returned). DB NOT updated. "
                  f"Position remains full-size on the original SL.")
            try:
                from tools.telegram_tools import _send
                _send(
                    f"🛑 <b>TP1 PARTIAL EXIT REJECTED</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔴 {p.symbol} {tx} {qty_exit} @ ~₹{curr:.2f}\n"
                    f"Broker returned no order id.\n"
                    f"Position UNCHANGED: full qty={p.quantity_remaining} "
                    f"on original SL ₹{p.stop_loss:.2f}.\n"
                    f"Check margin / freeze / square-off limits."
                )
            except Exception:
                pass
            return

        # Order succeeded (paper or live). Now safe to update DB.
        self.state.mark_tp1_hit(p.id, qty_remaining, partial_pnl)
        self.state.update_stop_loss(p.id, new_sl)

        # Replace broker-side SL-M: cancel old (was on full qty at initial_sl),
        # place new on remaining qty at breakeven (Fix #6).
        if getattr(p, "sl_order_id", ""):
            self.kite.cancel_order(p.sl_order_id)
        sl_tx = "SELL" if p.direction == "long" else "BUY"
        new_sl_oid = self.kite.place_sl_order(
            symbol=p.symbol, transaction=sl_tx, quantity=qty_remaining,
            trigger=new_sl, price=new_sl,
        )
        if new_sl_oid:
            self.state.update_sl_order_id(p.id, new_sl_oid)

        print(f"[PosMgr] 🎯 TP1 HIT {p.symbol} — exited {qty_exit} @ {curr:.2f} "
              f"partial_pnl=₹{partial_pnl:+,.0f} | SL→breakeven {new_sl:.2f}")

        try:
            alert_tp1_hit(
                symbol=p.symbol,
                tp1_price=curr,
                partial_pnl=partial_pnl,
                qty_exited=qty_exit,
                qty_remaining=qty_remaining,
                new_sl=new_sl,
            )
        except Exception:
            pass

    def _try_trail_sl(self, p, curr: float):
        """Trail SL using ATR after TP1 hit. Replaces broker-side SL-M (Fix #6).
        Fix #25 (B2) — volatility-adaptive multiplier: tighter in chop, looser
        on hot trades.
        """
        try:
            df, _ = self.kite.get_vwap_with_candles(p.symbol)
            if df is None:
                return
            atr     = _calc_atr_from_df(df)

            # Adaptive multiplier — default 0.5×ATR, tighter (0.7) in chop,
            # looser (0.4) on hot-volume trades. Lower mult = tighter trail.
            mult = TRAILING_ATR_MULTIPLIER
            try:
                if self._regime_cache.get("regime") == "choppy":
                    mult = 0.7    # tighter — chop reverses fast
                else:
                    vr = self.kite.get_volume_ratio(p.symbol) or 0.0
                    if vr >= 2.0:
                        mult = 0.4   # looser — let hot trades run
            except Exception:
                pass

            # Fix #28 (B3) — aggressive trail past +1.5R: lock more of the move.
            # Once unrealised PnL ≥ 1.5R, override mult to 0.3 (tightest).
            try:
                sl_dist = abs(p.entry_price - (p.initial_sl or p.stop_loss)) or 0.01
                pnl_r_now = (curr - p.entry_price) / sl_dist if p.direction == "long" \
                            else (p.entry_price - curr) / sl_dist
                if pnl_r_now >= 1.5:
                    mult = min(mult, 0.3)
            except Exception:
                pass

            new_sl  = _round_down_tick(curr - atr * mult, TICK_SIZE)

            if new_sl > p.stop_loss:
                self.state.update_stop_loss(p.id, new_sl)
                # Replace broker-side SL-M to track the trail
                if getattr(p, "sl_order_id", ""):
                    self.kite.cancel_order(p.sl_order_id)
                sl_tx = "SELL" if p.direction == "long" else "BUY"
                try:
                    new_oid = self.kite.place_sl_order(
                        symbol=p.symbol, transaction=sl_tx,
                        quantity=p.quantity_remaining,
                        trigger=new_sl, price=new_sl,
                    )
                    if new_oid:
                        self.state.update_sl_order_id(p.id, new_oid)
                    elif not PAPER_TRADING:
                        # Fix #195 — SL-M returned None on post-TP1 trail.
                        # Position now naked. Alert + retry.
                        self._alert_naked_sl(p, new_sl, "post-TP1 trail")
                except Exception as _e:
                    print(f"[PosMgr] post-TP1 trail SL-M failed for {p.symbol}: {_e}")
                    if not PAPER_TRADING:
                        self._alert_naked_sl(p, new_sl, "post-TP1 trail exception", error=str(_e))
                print(f"[PosMgr] 🔄 Trail SL {p.symbol}: "
                      f"{p.stop_loss:.2f} → {new_sl:.2f} "
                      f"(ATR={atr:.2f}, mult={mult:.2f})")
                try:
                    alert_trailing_sl_moved(p.symbol, p.stop_loss, new_sl, curr)
                except Exception:
                    pass
        except Exception:
            pass


    def _alert_naked_sl(self, p, intended_sl: float, context: str, error: str = ""):
        """
        Fix #195 (2026-05-19) — emergency alert for a mid-trade SL-M
        placement failure. Before Fix #195, the 3 mid-trade SL-update
        paths (PreTP1Trail, post-TP1 trail, Reeval-Tighten) silently
        swallowed broker rejects on `place_sl_order` via `except: pass`
        or `if new_oid: ...` (no else). Outcome: position has NO
        broker-side stop covering it — naked exposure with the operator
        unaware.

        We do NOT auto-emergency-exit here (unlike Fix #177 which fires
        post-entry). Mid-trade auto-exit is too aggressive: position may
        be in profit, ATR-trail may have moved SL much higher than
        original; closing at market sacrifices the runway. Right action
        is alert + retry-once + flag for operator.

        Path:
          1. Print loud red banner with context
          2. Try place_sl_order ONE more time (transient broker glitch)
          3. If second attempt also fails, Telegram alert with current
             position state — operator must intervene
        """
        sym = getattr(p, "symbol", "?")
        qty = getattr(p, "quantity_remaining", 0)
        prev_sl = getattr(p, "stop_loss", 0.0)
        print(f"[PosMgr] 🛑 SL-M REPLACEMENT FAILED — {sym} qty={qty} "
              f"intended SL=₹{intended_sl:.2f} (prev ₹{prev_sl:.2f}). "
              f"Context: {context}. Error: {error or 'no order id returned'}")
        # Retry once
        retried_oid = None
        try:
            sl_tx = "SELL" if p.direction == "long" else "BUY"
            retried_oid = self.kite.place_sl_order(
                symbol=sym, transaction=sl_tx, quantity=qty,
                trigger=intended_sl, price=intended_sl,
            )
        except Exception as e2:
            print(f"[PosMgr] SL-M retry also failed for {sym}: {e2}")
        if retried_oid:
            try:
                self.state.update_sl_order_id(p.id, retried_oid)
            except Exception:
                pass
            print(f"[PosMgr] ✅ SL-M retry succeeded for {sym} — oid={retried_oid}")
            return
        # Both attempts failed — alert operator
        try:
            from tools.telegram_tools import _send
            _send(
                f"🛑 <b>SL-M NAKED — {sym}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Context: {context}\n"
                f"qty={qty}, intended SL=₹{intended_sl:.2f}\n"
                f"Previous SL=₹{prev_sl:.2f}\n"
                f"<b>Broker rejected SL-M placement twice.</b>\n"
                f"Position is currently NOT protected by a broker-side stop.\n"
                f"Operator: manually place SL or square off from Kite."
            )
        except Exception:
            pass

    def _full_exit(self, p, curr: float, reason: str):
        """Close full remaining position. Cancel SL-M first to avoid double sell."""
        # Fix #13 — refetch live LTP for honest exit-fill price
        try:
            fq = self.kite.get_quotes([p.symbol])
            fresh = float(fq.get(p.symbol, {}).get("last_price", 0) or 0)
            if fresh > 0:
                curr = fresh
        except Exception:
            pass

        # Fix #16 — paper-mode slippage (worse for stops, lighter for targets/EOD)
        exit_side = "sell" if p.direction == "long" else "buy"
        if reason in ("sl_hit", "sl_trail_hit"):
            curr = _apply_paper_slippage(curr, exit_side, "stop")
        else:
            curr = _apply_paper_slippage(curr, exit_side, "target")

        qty      = p.quantity_remaining
        sl_dist  = abs(p.entry_price - p.initial_sl) or 0.01

        if p.direction == "long":
            trade_pnl = (curr - p.entry_price) * qty
        else:
            trade_pnl = (p.entry_price - curr) * qty

        total_pnl = round(p.pnl + trade_pnl, 2)
        pnl_r = round(total_pnl / (sl_dist * p.quantity), 2) \
                if p.quantity > 0 else 0

        status = "closed_win" if total_pnl > 0 else "closed_loss"

        # Fix #194 (2026-05-19) — order reversal: cancel SL-M → place market
        # exit → CHECK return → THEN close_position. Mirrors Fix #170 (entry
        # rollback). Was: close_position written FIRST, place_order called
        # AFTER with no return check. In live mode, if broker rejects the
        # exit MARKET order (frozen symbol, daily limit, insufficient
        # margin for square-off), DB would record closed_win/closed_loss
        # while real shares remained held. Now: only close_position on
        # successful exit. If broker rejects in live, position stays open
        # in the DB, SL-M is restored (best-effort), operator alerted.

        # Cancel any pending broker-side SL-M before placing the MARKET exit
        # (Fix #6) — prevents the "polling sees SL hit + broker SL-M also fires"
        # double-sell race in live mode. Safe no-op in paper.
        cancelled_sl_oid = getattr(p, "sl_order_id", "") or ""
        if cancelled_sl_oid and reason not in ("sl_hit", "sl_trail_hit"):
            self.kite.cancel_order(cancelled_sl_oid)
        # If reason IS sl_hit/sl_trail_hit, the broker stop may have just filled;
        # cancel is still attempted but failure is benign (already filled).
        elif cancelled_sl_oid:
            self.kite.cancel_order(cancelled_sl_oid)

        tx = "SELL" if p.direction == "long" else "BUY"
        exit_order_id = self.kite.place_order(p.symbol, tx, qty)
        if exit_order_id is None and not PAPER_TRADING:
            # Live broker rejected the exit market order. Position is STILL
            # OPEN. Do NOT write close_position. Restore the SL-M we just
            # cancelled (best-effort) so the position isn't naked.
            print(f"[PosMgr] 🛑 EXIT REJECTED by broker — {p.symbol} "
                  f"{tx} {qty} (no order id returned). DB UNCHANGED — "
                  f"position remains OPEN. Attempting SL-M restoration.")
            sl_tx = "SELL" if p.direction == "long" else "BUY"
            restored_oid = None
            try:
                restored_oid = self.kite.place_sl_order(
                    symbol=p.symbol, transaction=sl_tx, quantity=qty,
                    trigger=p.stop_loss, price=p.stop_loss,
                )
            except Exception as _e:
                print(f"[PosMgr] SL-M restoration also failed for {p.symbol}: {_e}")
            if restored_oid:
                try:
                    self.state.update_sl_order_id(p.id, restored_oid)
                except Exception:
                    pass
            # Telegram alert — operator must intervene manually
            try:
                from tools.telegram_tools import _send
                sl_status = "SL-M restored" if restored_oid else "⚠ SL-M NOT restored (naked!)"
                _send(
                    f"🛑 <b>EXIT REJECTED — {p.symbol}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔴 {tx} {qty} @ ~₹{curr:.2f}\n"
                    f"Reason: {reason}\n"
                    f"Broker returned no order id. Position remains OPEN.\n"
                    f"{sl_status}\n"
                    f"<b>Operator: square off manually from Kite if SL doesn't fire.</b>"
                )
            except Exception:
                pass
            return  # leave position open in DB

        # Order succeeded (or paper mode). Close the position row.
        self.state.close_position(p.id, curr, total_pnl, pnl_r, status, reason)

        # Phase 2.1 — report outcome to Discovery Engine so it can
        # auto-blacklist names that cause repeated losses. No-op for core
        # universe symbols (handled inside `report_trade_outcome`).
        try:
            self.discovery.report_trade_outcome(p.symbol, pnl_r)
        except Exception as e:
            print(f"[Discovery] report_trade_outcome failed (non-fatal): {e}")

        emoji = "✅" if total_pnl > 0 else "❌"
        print(f"[PosMgr] {emoji} CLOSED {p.symbol} @ {curr:.2f} | "
              f"P&L=₹{total_pnl:+,.0f} ({pnl_r:+.2f}R) | {reason}")

        # Telegram exit alert
        try:
            entry_dt  = datetime.fromisoformat(p.entry_time) if p.entry_time else datetime.now()
            hold_mins = int((datetime.now() - entry_dt).total_seconds() / 60)
            alert_trade_exit(
                symbol=p.symbol,
                setup_type=p.setup_type or "",
                exit_price=curr,
                entry_price=p.entry_price,
                pnl=total_pnl,
                pnl_r=pnl_r,
                exit_reason=reason,
                hold_minutes=hold_mins,
            )
        except Exception:
            pass

        # ChromaDB — store outcome immediately so learning is live, not just at EOD
        try:
            outcome = "hit_target" if reason in ("tp1_hit", "tp2_hit") else \
                      "hit_sl"     if reason == "sl_hit" else "expired"
            self.chroma.store_signal_outcome(
                symbol=p.symbol,
                setup_type=p.setup_type or "unknown",
                regime=(p.regime or self._regime_cache.get("regime", "unknown")),  # Fix #14 — entry-time regime first
                score=p.score or 0.0,
                grade=p.grade or "B",
                entry=p.entry_price,
                sl=p.initial_sl or p.stop_loss,
                target=p.tp2_price or p.tp1_price,
                outcome=outcome,
                pnl_r=pnl_r,
            )
            print(f"[ChromaDB] 📚 Stored {p.symbol} → {outcome} ({pnl_r:+.2f}R)")
        except Exception as e:
            print(f"[ChromaDB] Write error: {e}")

    # ── EOD Report ────────────────────────────────────────────────────────────

    def send_eod_report(self):
        """Call this at EOD to send daily summary via Telegram."""
        try:
            summary = self.state.get_summary()
            wins    = summary.get("wins", 0)
            losses  = summary.get("losses", 0)
            total   = summary.get("total", 0)

            # Best setup (by win rate)
            setup_stats = self.state.get_win_rate_by_setup()
            best_setup  = max(setup_stats, key=lambda k: setup_stats[k]["win_rate"]) \
                          if setup_stats else "n/a"

            regime_cache = self._regime_cache.get("regime", "unknown")

            alert_eod_report(
                total_trades=total,
                wins=wins,
                losses=losses,
                total_pnl=summary.get("total_pnl", 0),
                best_trade=summary.get("best_trade", 0),
                worst_trade=summary.get("worst_trade", 0),
                best_setup=best_setup,
                regime_of_day=regime_cache,
            )
        except Exception as e:
            print(f"[EOD] Error sending report: {e}")

    # ── Utility ───────────────────────────────────────────────────────────────

    def _tick_summary(self, active: int, setups: int, scored: int) -> dict:
        now      = _now_ist()
        open_pos = self.state.get_open_positions()

        # Best open position by unrealised P&L
        best_sym    = ""
        best_unreal = 0.0
        if open_pos:
            try:
                syms   = [p.symbol for p in open_pos]
                quotes = self.kite.get_quotes(syms)
                for p in open_pos:
                    curr   = quotes.get(p.symbol, {}).get("last_price", p.entry_price)
                    unreal = (curr - p.entry_price) * p.quantity_remaining \
                             if p.direction == "long" \
                             else (p.entry_price - curr) * p.quantity_remaining
                    if abs(unreal) > abs(best_unreal):
                        best_unreal = unreal
                        best_sym    = p.symbol
            except Exception:
                pass

        # Phase 2.0 B6 — `entries` now reflects ACTUAL position opens (post-
        # conviction, post-allocator), not the scorer-pass count which was
        # misleading on the 2026-05-12 GODREJCP case (1 scorer pass → 0 entry).
        entered = getattr(self, "_entries_this_tick", 0)

        s = {
            "tick":           self._tick,
            "time":           now.strftime("%H:%M:%S"),
            "active_stocks":  active,
            "setups_found":   setups,
            "signals_scored": scored,
            "entries":        entered,
            "open_positions": len(open_pos),
            "today_pnl":      round(self.state.get_today_pnl(), 2),
            "best_open_sym":  best_sym,
            "best_open_pnl":  round(best_unreal, 2),
        }

        best_str = f" | best open: {best_sym} ₹{best_unreal:+,.0f}" if best_sym else ""
        print(f"[Crew] Tick #{self._tick} done: {setups} setups | "
              f"{scored} scored | {entered} entered | "
              f"{s['open_positions']} open | "
              f"P&L ₹{s['today_pnl']:+,.0f}{best_str}")

        # Fix #175 (2026-05-18) — per-tick conviction tier distribution. One
        # line tells the operator how many candidates passed conviction (and
        # at which tier) vs were SKIPped. Helps distinguish "macro is RED so
        # idle is correct" from "filter is wrong, real signals being blocked".
        if self._tier_hist:
            order = ["S", "A", "B", "SKIP"]
            parts = []
            for tier in order:
                if self._tier_hist.get(tier, 0) > 0:
                    parts.append(f"{tier}={self._tier_hist[tier]}")
            for tier, count in self._tier_hist.items():
                if tier not in order and count > 0:
                    parts.append(f"{tier}={count}")
            if parts:
                print(f"[Conviction] tier distribution this tick: {', '.join(parts)}")

        # Fix #39 + #49 — print per-stage rejection summary EVERY tick (even
        # if empty), so the diagnostic is always visible in journalctl.
        if self._reject_counts:
            top = sorted(self._reject_counts.items(), key=lambda kv: -kv[1])
            summary = ", ".join(f"{k}={v}" for k, v in top)
            print(f"[Crew] Rejections this tick: {summary}")
        else:
            # Make absence visible — tells operator "scoring/allocate path
            # never had a candidate to reject" (vs filter-killed-everything).
            print(f"[Crew] Rejections this tick: NONE "
                  f"(setups={setups}, scored={scored} — "
                  f"{'no setups detected' if setups == 0 else 'all candidates passed' if scored > 0 else 'all setups dropped before scoring'})")
        return s
