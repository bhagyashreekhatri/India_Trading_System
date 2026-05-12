"""
First-Hour-High / First-Hour-Low Break Detector.

The "FHH break" is the second-strongest empirical edge found in 30 months of
NIFTY data (n=584 sessions, Jan 2024 – May 2026):

  Combined with the 10:15 IST macro state:
    STRONG_GREEN + clean FHH break → 100% closed positive (n=44)
    GREEN        + clean FHH break →  97% closed positive (n=38)
    YELLOW       + clean FHH break →  88% closed positive (n=98)
    RED          + clean FHH break →  44% closed positive (n=9, TRAP)
    STRONG_RED   + clean FHH break →  23% closed positive (n=22, TRAP)

  Whipsaw (BOTH FHH and FHL broken): 70% close flat — chop, avoid entries.

See docs/15_Setup_Pattern_Library_18mo_2026-05-11.md and
    docs/16_30Month_Final_Analysis_2026-05-11.md.

Definitions (purely structural — no clock categories):
  - First hour = 09:15 - 10:15 IST (first 60-minute bar)
  - First-hour-high (FHH) = max(high) across that bar
  - First-hour-low  (FHL) = min(low)  across that bar
  - Clean FHH break = any subsequent bar's high > FHH AND no subsequent bar's
                      low has dropped below FHL
  - Whipsaw = both FHH broken AND FHL broken at some point during the session

The detector tracks state per-symbol so it can answer:
  "Has THIS stock broken its first hour high cleanly?"

For now we apply this to NIFTY itself (the macro signal) and reuse the
methodology per-stock later.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE

IST = ZoneInfo(TIMEZONE)

FIRST_HOUR_END_IST = dtime(10, 15)  # NSE 09:15-10:15


@dataclass
class FirstHourState:
    """Per-symbol first-hour tracking."""
    symbol:               str
    is_set:               bool   = False     # True once first hour completes
    fh_high:              float  = 0.0
    fh_low:               float  = 0.0
    fh_close:             float  = 0.0
    high_broken:          bool   = False
    low_broken:           bool   = False
    high_break_time_ist:  Optional[str] = None
    low_break_time_ist:   Optional[str] = None
    last_check_time_ist:  Optional[str] = None

    @property
    def clean_high_break(self) -> bool:
        """FHH broken but FHL NOT broken — the bullish continuation signal."""
        return self.is_set and self.high_broken and not self.low_broken

    @property
    def clean_low_break(self) -> bool:
        """FHL broken but FHH NOT broken — the bearish continuation signal."""
        return self.is_set and self.low_broken and not self.high_broken

    @property
    def whipsaw(self) -> bool:
        """Both broken — 70% historical chop. AVOID entries."""
        return self.is_set and self.high_broken and self.low_broken

    @property
    def inside_first_hour(self) -> bool:
        """Neither broken — price is still inside the first-hour range."""
        return self.is_set and not self.high_broken and not self.low_broken


class FhhBreakDetector:
    """
    Tracks first-hour-high/low state per symbol.

    Lifecycle per symbol per session:
      1. Before 10:15 IST: state.is_set = False (waiting for first bar to close)
      2. At 10:15 IST: capture FHH/FHL/close from the first 60-minute bar
      3. After 10:15: monitor each new bar — was high > FHH? low < FHL?
      4. Update state.high_broken / state.low_broken once

    Once a flag is set, it stays set for the rest of the session.
    """

    def __init__(self, kite):
        self.kite = kite
        self._states: dict[tuple[str, str], FirstHourState] = {}  # (symbol, date) → state

    def get_state(self, symbol: str, now: Optional[datetime] = None) -> FirstHourState:
        """Return current FirstHourState for `symbol`. Computes on first call,
        updates on subsequent calls."""
        if now is None:
            now = datetime.now(IST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=IST)

        today_iso = now.date().isoformat()
        key = (symbol, today_iso)

        # Initialize state for this symbol+date if first call.
        if key not in self._states:
            self._states[key] = FirstHourState(symbol=symbol)

        state = self._states[key]
        state.last_check_time_ist = now.isoformat()

        # Step 1: before 10:15 IST → can't compute first-hour range yet.
        if now.time() < FIRST_HOUR_END_IST:
            return state

        # Step 2: compute first-hour bar if not yet done.
        if not state.is_set:
            self._capture_first_hour(state, symbol, today_iso, now)
            if not state.is_set:
                return state  # data fetch failed, will retry next call

        # Step 3: monitor for breaks of FHH/FHL.
        self._update_breaks(state, symbol, now)

        return state

    # ── Internals ────────────────────────────────────────────────────────────

    def _capture_first_hour(
        self, state: FirstHourState, symbol: str, today_iso: str, now: datetime
    ) -> None:
        """Fetch the 09:15-10:15 5-minute candles and compute FHH/FHL/close."""
        try:
            df = self.kite.get_candles(symbol, interval="5minute", days=3)
            if df is None or len(df) == 0:
                return
            df = self.kite.get_today_bars(df) if hasattr(self.kite, "get_today_bars") else df
            df["date"] = df["date"].apply(lambda d: d.replace(tzinfo=IST) if d.tzinfo is None else d)
            today_bars = df[df["date"].apply(lambda d: d.date().isoformat() == today_iso)]
            if len(today_bars) == 0:
                return
            # First-hour bars: 09:15 (start) through bar ending at 10:15
            first_hour_bars = today_bars[
                today_bars["date"].apply(lambda d: d.time() < FIRST_HOUR_END_IST)
            ]
            if len(first_hour_bars) == 0:
                return
            state.fh_high = float(first_hour_bars["high"].max())
            state.fh_low  = float(first_hour_bars["low"].min())
            state.fh_close = float(first_hour_bars.iloc[-1]["close"])
            state.is_set = True
            # Phase 2.0 telemetry — emit exactly once when first-hour resolves
            print(
                f"[FHH] {symbol} captured  "
                f"FHH={state.fh_high:.2f}  FHL={state.fh_low:.2f}  "
                f"FH-close={state.fh_close:.2f}  range={state.fh_high - state.fh_low:.2f}"
            )
        except Exception as e:
            print(f"[FhhDetector] _capture_first_hour error for {symbol}: {e}")

    def _update_breaks(
        self, state: FirstHourState, symbol: str, now: datetime
    ) -> None:
        """Check if any post-10:15 bars have broken FHH or FHL."""
        if state.high_broken and state.low_broken:
            return  # nothing more to track

        try:
            df = self.kite.get_candles(symbol, interval="5minute", days=1)
            if df is None or len(df) == 0:
                return
            df["date"] = df["date"].apply(lambda d: d.replace(tzinfo=IST) if d.tzinfo is None else d)
            today_iso = now.date().isoformat()
            post_first_hour = df[
                df["date"].apply(
                    lambda d: d.date().isoformat() == today_iso and d.time() >= FIRST_HOUR_END_IST
                )
            ]
            if len(post_first_hour) == 0:
                return

            for _, bar in post_first_hour.iterrows():
                if not state.high_broken and float(bar["high"]) > state.fh_high:
                    state.high_broken = True
                    state.high_break_time_ist = (
                        bar["date"].isoformat() if hasattr(bar["date"], "isoformat") else str(bar["date"])
                    )
                    # Phase 2.0 — log once per symbol per session
                    flavor = "WHIPSAW" if state.low_broken else "CLEAN-HIGH-BREAK"
                    print(
                        f"[FHH] {symbol} {flavor}  "
                        f"high {float(bar['high']):.2f} > FHH {state.fh_high:.2f}  "
                        f"at {state.high_break_time_ist}"
                    )
                if not state.low_broken and float(bar["low"]) < state.fh_low:
                    state.low_broken = True
                    state.low_break_time_ist = (
                        bar["date"].isoformat() if hasattr(bar["date"], "isoformat") else str(bar["date"])
                    )
                    flavor = "WHIPSAW" if state.high_broken else "CLEAN-LOW-BREAK"
                    print(
                        f"[FHH] {symbol} {flavor}  "
                        f"low {float(bar['low']):.2f} < FHL {state.fh_low:.2f}  "
                        f"at {state.low_break_time_ist}"
                    )
                if state.high_broken and state.low_broken:
                    break
        except Exception as e:
            print(f"[FhhDetector] _update_breaks error for {symbol}: {e}")

    def reset_day(self, today_iso: Optional[str] = None) -> None:
        """Clear stale states from previous day (called by EOD job or on boot)."""
        if today_iso is None:
            today_iso = datetime.now(IST).date().isoformat()
        keys_to_remove = [k for k in self._states if k[1] != today_iso]
        for k in keys_to_remove:
            del self._states[k]
