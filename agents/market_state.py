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

        return snap

    # ── Internals ────────────────────────────────────────────────────────────

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
                # be the start (10:10) or the close (10:15). Look for either.
                ten_fifteen_bar = df_today[df_today["date"].apply(
                    lambda d: d.time() in (dtime(10, 10), dtime(10, 15))
                )]
                if len(ten_fifteen_bar) > 0:
                    close_px = float(ten_fifteen_bar.iloc[0]["close"])
                    if close_px > 0:
                        self._first_hour_close_cache[today_iso] = close_px
                        print(f"[MarketState] 10:15 candle close (canonical): "
                              f"₹{close_px:.2f} from historical_data")
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

def _parse_time(hhmm: str) -> dtime:
    """Parse "HH:MM" → datetime.time."""
    h, m = hhmm.split(":")
    return dtime(int(h), int(m))
