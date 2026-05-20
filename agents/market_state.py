"""
Market State Agent — the 10:15 IST macro filter.

Validated on 584 NIFTY sessions (Jan 2024 – May 2026):
  - STRONG_GREEN (10:15 > +0.5% from prev close): 98% close positive
  - STRONG_RED  (10:15 < -0.5% from prev close): 89% close negative
  - GREEN  (>+0.3%): 72% close positive
  - RED    (<-0.3%): 74% close negative
  - YELLOW (±0.3%): coin-flip — half-size only

See docs/16_30Month_Final_Analysis_2026-05-11.md for full statistical backing.

This module replaces the deleted ScoringEngine's market-context multipliers,
hour-of-day nudges, breadth penalties, and lunch-window gates with a single
empirically-validated structural reading. No clock categories. No hardcoded
sectors. Pure structural state.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time as dtime, date
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE

IST = ZoneInfo(TIMEZONE)


# ─── Thresholds — single source of truth in config/settings.py ──────────────
# Imported lazily inside MarketStateAgent so changing settings.py at runtime
# works without re-importing this module.


MacroState = Literal[
    "WAITING",       # before 10:15 IST — not enough data yet
    "STRONG_GREEN",  # > +0.5% from prev close — 98% bullish day
    "GREEN",         # +0.3% to +0.5% — 72% bullish day
    "YELLOW",        # ±0.3% — coin-flip
    "RED",           # -0.3% to -0.5% — 74% bearish day
    "STRONG_RED",    # < -0.5% — 89% bearish day
]


@dataclass
class MarketStateSnapshot:
    """Captured at one moment in time. Used for decisions + telemetry."""
    state:                          MacroState
    nifty_dist_pct_from_prev_close: float
    nifty_prev_close:               float
    nifty_at_check_time:            float
    snapshot_time_ist:              str
    is_locked_in:                   bool   # True once the 10:15 bar closes
    reasoning:                      str    # human-readable explanation

    def allows_long_entry(self) -> bool:
        """Returns True if the macro state permits long entries at all.

        RED and STRONG_RED are hard blocks for long-only system.
        WAITING returns False — wait for the read.
        """
        return self.state in ("STRONG_GREEN", "GREEN", "YELLOW")

    def is_high_conviction(self) -> bool:
        """STRONG_GREEN is the only state with 98%+ historical positive close."""
        return self.state == "STRONG_GREEN"


class MarketStateAgent:
    """
    Computes the 10:15 IST macro state from NIFTY 50 LTP vs previous close.

    Caching strategy:
      - prev_close cached per date (single Kite call per session)
      - 10:15 close locked in once after the first hour completes
      - Re-checking after the lock-in returns the same snapshot
    """

    NIFTY_SYMBOL = "NSE:NIFTY 50"

    def __init__(self, kite):
        self.kite = kite
        self._prev_close_cache: dict[str, float] = {}     # iso date → close
        self._first_hour_close_cache: dict[str, float] = {}  # iso date → close
        self._last_snapshot: Optional[MarketStateSnapshot] = None
        # Phase 2.0 telemetry — track the last state we logged so a state
        # change (or the first non-WAITING call of the session) emits exactly
        # one `[MarketState]` line. Keyed by ISO date so we re-log fresh each day.
        self._logged_state_today: dict[str, str] = {}
        # Fix #205 — intraday recovery-unlock telemetry. Track the last upgrade
        # level we logged per date so each fresh upgrade (RED→YELLOW, later
        # YELLOW→GREEN, …) emits exactly one `[MacroRecheck]` line.
        self._logged_recheck_today: dict[str, str] = {}

    def get_state(self, now: Optional[datetime] = None) -> MarketStateSnapshot:
        """
        Compute the macro state for `now` (defaults to current IST time).

        Returns a MarketStateSnapshot. Caches:
          - WAITING before 10:15 IST
          - Locks in the actual 10:15 close once available
          - Returns the locked-in snapshot for the rest of the session
        """
        from config.settings import (
            MACRO_FILTER_TIME_IST, MACRO_STRONG_GREEN_THRESHOLD,
            MACRO_GREEN_THRESHOLD, MACRO_RED_THRESHOLD,
            MACRO_STRONG_RED_THRESHOLD,
        )
        if now is None:
            now = datetime.now(IST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=IST)

        today_iso = now.date().isoformat()
        check_time = _parse_time(MACRO_FILTER_TIME_IST)

        # Before 10:15 — return WAITING.
        if now.time() < check_time:
            return MarketStateSnapshot(
                state="WAITING",
                nifty_dist_pct_from_prev_close=0.0,
                nifty_prev_close=0.0,
                nifty_at_check_time=0.0,
                snapshot_time_ist=now.isoformat(),
                is_locked_in=False,
                reasoning=f"before {MACRO_FILTER_TIME_IST} IST — waiting for first-hour close",
            )

        # Get previous-session close (cached).
        prev_close = self._get_prev_close(today_iso)
        if prev_close is None or prev_close <= 0:
            return MarketStateSnapshot(
                state="YELLOW",  # fail-safe: treat as uncertain
                nifty_dist_pct_from_prev_close=0.0,
                nifty_prev_close=0.0,
                nifty_at_check_time=0.0,
                snapshot_time_ist=now.isoformat(),
                is_locked_in=False,
                reasoning="prev-close fetch failed — defaulting to YELLOW (no edge)",
            )

        # Get the 10:15 close (locked-in once captured).
        ltp = self._get_nifty_close_at_or_after_check(now, today_iso, check_time)
        if ltp is None or ltp <= 0:
            return MarketStateSnapshot(
                state="YELLOW",
                nifty_dist_pct_from_prev_close=0.0,
                nifty_prev_close=prev_close,
                nifty_at_check_time=0.0,
                snapshot_time_ist=now.isoformat(),
                is_locked_in=False,
                reasoning="NIFTY LTP fetch failed — defaulting to YELLOW",
            )

        # Compute distance.
        dist_pct = 100.0 * (ltp - prev_close) / prev_close

        # Classify.
        if dist_pct > MACRO_STRONG_GREEN_THRESHOLD:
            state, reason = "STRONG_GREEN", f"NIFTY +{dist_pct:.2f}% > +{MACRO_STRONG_GREEN_THRESHOLD}% (98% historical bullish)"
        elif dist_pct > MACRO_GREEN_THRESHOLD:
            state, reason = "GREEN", f"NIFTY +{dist_pct:.2f}% > +{MACRO_GREEN_THRESHOLD}% (72% historical bullish)"
        elif dist_pct < MACRO_STRONG_RED_THRESHOLD:
            state, reason = "STRONG_RED", f"NIFTY {dist_pct:+.2f}% < {MACRO_STRONG_RED_THRESHOLD}% (89% historical bearish — SKIP LONGS)"
        elif dist_pct < MACRO_RED_THRESHOLD:
            state, reason = "RED", f"NIFTY {dist_pct:+.2f}% < {MACRO_RED_THRESHOLD}% (74% historical bearish — SKIP LONGS)"
        else:
            state, reason = "YELLOW", f"NIFTY {dist_pct:+.2f}% in ±{MACRO_GREEN_THRESHOLD}% — coin-flip, half-size only"

        snap = MarketStateSnapshot(
            state=state,
            nifty_dist_pct_from_prev_close=round(dist_pct, 3),
            nifty_prev_close=prev_close,
            nifty_at_check_time=ltp,
            snapshot_time_ist=now.isoformat(),
            is_locked_in=(today_iso in self._first_hour_close_cache),
            reasoning=reason,
        )
        self._last_snapshot = snap

        # Phase 2.0 telemetry — emit one `[MarketState]` line per state
        # transition (or first non-WAITING call of the session).
        prev_logged = self._logged_state_today.get(today_iso)
        if prev_logged != state:
            lock_marker = "LOCKED" if snap.is_locked_in else "PROVISIONAL"
            print(
                f"[MarketState] {lock_marker} {state}  "
                f"NIFTY {dist_pct:+.2f}% (prev {prev_close:.2f} → "
                f"10:15 {ltp:.2f})  {reason}"
            )
            self._logged_state_today[today_iso] = state

        # Fix #205 — intraday recovery unlock. After the 10:15 lock, allow the
        # macro state to HEAL upward (never downward) if NIFTY reclaims and holds
        # a strictly-better level across N consecutive 5-min closes. Shadow-gated
        # by MACRO_RECHECK_ENABLED — in shadow it only logs, returns snap as-is.
        snap = self._maybe_upgrade(snap, now)
        return snap

    # ── Internals ────────────────────────────────────────────────────────────

    def _maybe_upgrade(
        self,
        snap: MarketStateSnapshot,
        now: datetime,
    ) -> MarketStateSnapshot:
        """
        Fix #205 — recovery unlock.

        After the 10:15 lock, re-check NIFTY. If it has reclaimed and HELD a
        strictly-better state across MACRO_RECHECK_CONFIRM_BARS consecutive
        closed 5-min bars, upgrade the snapshot to that better state.

        Only UPGRADES (the 10:15 lock is the floor). On a day that keeps
        bleeding, NIFTY never reclaims → no upgrade → capital protected.

        SHADOW (MACRO_RECHECK_ENABLED=False): logs `[MacroRecheck] WOULD-UPGRADE`
        and returns `snap` unchanged (zero behaviour change).
        LIVE (MACRO_RECHECK_ENABLED=True): returns the upgraded snapshot.
        """
        from config.settings import (
            MACRO_RECHECK_ENABLED, MACRO_RECHECK_CONFIRM_BARS,
            MACRO_RECHECK_LOG_SHADOW, MACRO_STRONG_GREEN_THRESHOLD,
            MACRO_GREEN_THRESHOLD, MACRO_RED_THRESHOLD,
        )

        # Only act after the 10:15 lock is in, and only if there's room to heal.
        if not snap.is_locked_in:
            return snap
        if _state_rank(snap.state) >= _state_rank("STRONG_GREEN"):
            return snap
        prev_close = snap.nifty_prev_close
        if prev_close <= 0:
            return snap

        held, latest_dist = self._held_state_from_candles(
            now, prev_close, MACRO_RECHECK_CONFIRM_BARS,
            MACRO_STRONG_GREEN_THRESHOLD, MACRO_GREEN_THRESHOLD,
            MACRO_RED_THRESHOLD,
        )
        # No reclaim, or not strictly better than the current state → no upgrade.
        if held is None or _state_rank(held) <= _state_rank(snap.state):
            return snap

        today_iso = now.date().isoformat()
        if MACRO_RECHECK_LOG_SHADOW and self._logged_recheck_today.get(today_iso) != held:
            marker = "UPGRADE" if MACRO_RECHECK_ENABLED else "WOULD-UPGRADE (shadow)"
            dist_str = f"{latest_dist:+.2f}%" if latest_dist is not None else "n/a"
            print(
                f"[MacroRecheck] {marker}: {snap.state} → {held}  "
                f"NIFTY now {dist_str} vs prev close, held above level for "
                f"{MACRO_RECHECK_CONFIRM_BARS}×5min closes"
            )
            self._logged_recheck_today[today_iso] = held

        if not MACRO_RECHECK_ENABLED:
            return snap  # shadow — no behaviour change

        upgraded = MarketStateSnapshot(
            state=held,
            nifty_dist_pct_from_prev_close=round(latest_dist, 3) if latest_dist is not None else snap.nifty_dist_pct_from_prev_close,
            nifty_prev_close=prev_close,
            nifty_at_check_time=snap.nifty_at_check_time,
            snapshot_time_ist=now.isoformat(),
            is_locked_in=True,
            reasoning=(
                f"recovery-upgrade {snap.state}→{held}: NIFTY reclaimed to "
                f"{(f'{latest_dist:+.2f}%' if latest_dist is not None else 'n/a')} "
                f"and held {MACRO_RECHECK_CONFIRM_BARS}×5min closes "
                f"(10:15 lock was: {snap.reasoning})"
            ),
        )
        self._last_snapshot = upgraded
        return upgraded

    def _held_state_from_candles(
        self,
        now: datetime,
        prev_close: float,
        n_bars: int,
        sg_th: float,
        g_th: float,
        r_th: float,
    ) -> tuple[Optional[MacroState], Optional[float]]:
        """
        Read the last `n_bars` CLOSED 5-min candles of today and return the best
        macro state whose threshold ALL of them cleared (vs prev close), plus the
        most recent close's distance %.

        Using the WORST of the last-N closes (min dist) enforces "held for all N
        bars" — a single spike that immediately fades will not trigger an upgrade.

        Returns (None, latest_dist) if not enough bars or no reclaim above the
        RED threshold yet.
        """
        try:
            df = self.kite.get_candles("NIFTY 50", interval="5minute", days=1)
            if df is None or len(df) == 0:
                return None, None
            today_iso = now.date().isoformat()
            df = df.copy()
            df["date"] = df["date"].apply(
                lambda d: d.replace(tzinfo=IST) if d.tzinfo is None else d
            )
            df = df[df["date"].apply(lambda d: d.date().isoformat() == today_iso)]
            # Keep only fully-closed bars: a 5-min bar starting at T closes at
            # T+5min, so exclude any bar whose start is within the current
            # incomplete window.
            from datetime import timedelta
            cutoff = now - timedelta(minutes=5)
            df = df[df["date"].apply(lambda d: d <= cutoff)]
            df = df.sort_values("date")
            if len(df) < n_bars:
                return None, None
            last = df.tail(n_bars)
            closes = [float(c) for c in last["close"].tolist()]
            dists = [100.0 * (c - prev_close) / prev_close for c in closes]
            min_dist = min(dists)
            latest_dist = dists[-1]
            if min_dist > sg_th:
                return "STRONG_GREEN", latest_dist
            if min_dist > g_th:
                return "GREEN", latest_dist
            if min_dist > r_th:
                return "YELLOW", latest_dist
            return None, latest_dist
        except Exception as e:
            print(f"[MacroRecheck] candle fetch error (non-fatal): {e}")
            return None, None

    def _get_prev_close(self, today_iso: str) -> Optional[float]:
        """Fetch (and cache) previous trading session's NIFTY close."""
        if today_iso in self._prev_close_cache:
            return self._prev_close_cache[today_iso]
        try:
            # Use 5 days of daily candles to handle weekends/holidays
            df = self.kite.get_candles("NIFTY 50", interval="day", days=5)
            if df is None or len(df) < 2:
                return None
            # The last row may be today's partial bar; take the second-to-last
            # row that is strictly before today.
            today = date.fromisoformat(today_iso)
            prev_close = None
            for _, row in df.sort_values("date", ascending=False).iterrows():
                row_date = row["date"].date() if hasattr(row["date"], "date") else row["date"]
                if row_date < today:
                    prev_close = float(row["close"])
                    break
            if prev_close:
                self._prev_close_cache[today_iso] = prev_close
            return prev_close
        except Exception as e:
            print(f"[MarketState] prev_close fetch error: {e}")
            return None

    def _get_nifty_close_at_or_after_check(
        self,
        now: datetime,
        today_iso: str,
        check_time: dtime,
    ) -> Optional[float]:
        """
        Return the 10:15 IST close (the first-hour close).

        Fix #176 (2026-05-18) — CRITICAL semantics correction.
        Previous behaviour: LTP-at-first-call after 10:15. On 3-min tick cadence
        that landed somewhere 10:15-10:18 and on a process restart at 14:30
        captured 14:30 LTP as "the 10:15 reading." The whole 30-month research
        (n=584) was sampled on the 10:15 5-min CANDLE CLOSE — a different
        statistical input than runtime LTP. Live precision claims (98%/72%/etc.)
        don't transfer to live unless the live read matches the sampled read.

        New behaviour: fetch the 10:10-10:15 5-min candle close via
        `kite.historical_data`. This is the EXACT bar the research sampled.
        Cache by date, fall back to LTP only if historical fetch fails (degraded
        mode — same as old behaviour, but flagged so we know precision is
        compromised on this session).

        Once locked in, never re-fetches — that's the entire point.
        """
        if today_iso in self._first_hour_close_cache:
            return self._first_hour_close_cache[today_iso]

        # Try the canonical path first: 5-min candle close at 10:15.
        try:
            df = self.kite.get_candles("NIFTY 50", interval="5minute", days=3)
            if df is not None and len(df) > 0:
                # Normalise tz, filter to today, look for the 10:10-10:15 bar.
                df_today = df.copy()
                df_today["date"] = df_today["date"].apply(
                    lambda d: d.replace(tzinfo=IST) if d.tzinfo is None else d
                )
                df_today = df_today[df_today["date"].apply(
                    lambda d: d.date().isoformat() == today_iso
                )]
                # The bar that CLOSES at 10:15 starts at 10:10. Depending on
                # the broker's bar convention, the timestamp on the row may
                # be the start (10:10) or the close (10:15).
                #
                # Fix #186 (2026-05-18) — widened from exact-match to a 90-second
                # window. Kite has been observed to return timestamps with
                # sub-second drift (10:09:59.xxx instead of clean 10:10:00) and
                # in rare cases shifts the convention mid-day. Exact in-tuple
                # match silently misses these and falls through to the DEGRADED
                # LTP path — the very behavior Fix #176 was meant to eliminate.
                # The window 10:09:30 ≤ t ≤ 10:15:30 covers both start (10:10)
                # and close (10:15) conventions with comfortable timestamp drift.
                # Take the LATEST matching bar to handle the (start, close)
                # duplicate edge case where the same bar might appear twice.
                def _is_1015_bar(d):
                    t = d.time()
                    return dtime(10, 9, 30) <= t <= dtime(10, 15, 30)
                ten_fifteen_bar = df_today[df_today["date"].apply(_is_1015_bar)]
                if len(ten_fifteen_bar) > 0:
                    # Fix #186 — if multiple bars matched the widened window
                    # (e.g. broker returned both start-stamped 10:10 AND
                    # close-stamped 10:15 row), the LATEST is the actual
                    # first-hour-close. Sort by date ascending and take last.
                    ten_fifteen_bar = ten_fifteen_bar.sort_values("date")
                    bar_row = ten_fifteen_bar.iloc[-1]
                    close_px = float(bar_row["close"])
                    if close_px > 0:
                        self._first_hour_close_cache[today_iso] = close_px
                        print(f"[MarketState] 10:15 candle close (canonical): "
                              f"₹{close_px:.2f} from historical_data "
                              f"(bar_ts={bar_row['date'].strftime('%H:%M:%S')})")
                        return close_px
        except Exception as e:
            print(f"[MarketState] historical_data fetch failed, "
                  f"falling back to LTP (degraded): {e}")

        # Fallback (degraded mode): we're past 10:15 but couldn't get the
        # canonical candle close. Use current LTP and flag the session.
        # This preserves pre-Fix-#176 behaviour as a safety net rather than
        # blocking the system entirely.
        try:
            quotes = self.kite.get_quotes(["NIFTY 50"])
            ltp = quotes.get("NIFTY 50", {}).get("last_price", 0.0)
            if ltp > 0:
                self._first_hour_close_cache[today_iso] = ltp
                print(f"[MarketState] ⚠️ DEGRADED — using current LTP ₹{ltp:.2f} "
                      f"as 10:15 reference (historical_data unavailable). "
                      f"Precision claims do NOT apply this session.")
            return ltp
        except Exception as e:
            print(f"[MarketState] NIFTY fallback LTP also failed: {e}")
            return None


# ─── Helpers ─────────────────────────────────────────────────────────────────

# Fix #205 — ordinal ranking of macro states (bearish → bullish). Used by the
# recovery-unlock to allow only UPGRADES (strictly higher rank), never downgrades.
_STATE_RANK: dict[str, int] = {
    "WAITING":      -1,
    "STRONG_RED":    0,
    "RED":           1,
    "YELLOW":        2,
    "GREEN":         3,
    "STRONG_GREEN":  4,
}


def _state_rank(state: str) -> int:
    """Return the bearish→bullish ordinal for a macro state (unknown → -1)."""
    return _STATE_RANK.get(state, -1)


def _parse_time(hhmm: str) -> dtime:
    """Parse "HH:MM" → datetime.time."""
    h, m = hhmm.split(":")
    return dtime(int(h), int(m))
