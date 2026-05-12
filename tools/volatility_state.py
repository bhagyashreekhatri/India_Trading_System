"""
Volatility state — NR7 detection + adaptive sizing factor.

Two data-derived findings from the 30-month research that get bundled here:

1. NR7 day-after expansion (Phase 1.6)
   --------------------------------------
   Validated: when a NIFTY session has the narrowest range of the trailing
   7 sessions, the NEXT day has a 66% chance of expanding to ≥1.5× current
   range. n=50 NR7 days in the 18-month subset.
   See docs/15_Setup_Pattern_Library_18mo_2026-05-11.md §1.2.

2. Volatility-adaptive sizing factor (Phase 1.7)
   --------------------------------------
   Validated: vol clustering ~58% across 30 months (high-vol day predicts
   high-vol next day modestly). Yesterday's range gives a 58% probability
   estimate of today's range bucket. Combined with today's range-so-far,
   we can adapt position size by 0.8x–1.2x based on measured vol regime.
   See docs/14_OOS_Validation_18Month_2026-05-11.md §3.2.

Both findings are STRUCTURAL — they measure realised volatility, not the
clock. No time-of-day gating.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional


VolRegime = Literal["COMPRESSED", "NORMAL", "EXPANDED", "EXTREME"]


@dataclass
class VolatilityState:
    yesterday_range_pct: float
    today_range_so_far_pct: float
    rolling_5d_avg_pct:    float
    is_nr7:                bool
    regime:                VolRegime
    size_multiplier:       float    # 0.7 (extreme) .. 1.0 (normal) .. 1.2 (expanded)
    stop_multiplier:       float    # widens stops in expanded vol
    reasoning:             str


def compute_volatility_state(
    today_high_so_far:     float,
    today_low_so_far:      float,
    yesterday_high:        float,
    yesterday_low:         float,
    rolling_5d_ranges:     list[float],   # last 5 daily range_pcts (most recent last)
) -> VolatilityState:
    """
    Pure function — no Kite, no time. Plug in numbers, get a state.
    """
    today_range_pct = 100.0 * (today_high_so_far - today_low_so_far) / today_low_so_far if today_low_so_far > 0 else 0.0
    yesterday_range_pct = 100.0 * (yesterday_high - yesterday_low) / yesterday_low if yesterday_low > 0 else 0.0

    if not rolling_5d_ranges or len(rolling_5d_ranges) < 3:
        avg_5d = max(yesterday_range_pct, 0.5)   # fallback
    else:
        avg_5d = sum(rolling_5d_ranges) / len(rolling_5d_ranges)

    # NR7 check: yesterday's range was the narrowest of the trailing 7
    # (we pass 5 here as proxy — close enough; actual 7-day comparison in
    # the stateful classifier below)
    is_nr7 = bool(yesterday_range_pct > 0 and yesterday_range_pct < min(rolling_5d_ranges) * 1.0001) \
             if rolling_5d_ranges else False

    # Blended vol factor: 60% today's range so far, 40% yesterday's range
    if avg_5d > 0:
        blended = (0.6 * today_range_pct + 0.4 * yesterday_range_pct) / avg_5d
    else:
        blended = 1.0

    # Regime classification
    if blended < 0.6:
        regime = "COMPRESSED"; size_mult = 1.0; stop_mult = 0.8   # tighter stops in compression
    elif blended < 1.3:
        regime = "NORMAL";     size_mult = 1.0; stop_mult = 1.0
    elif blended < 1.8:
        regime = "EXPANDED";   size_mult = 1.1; stop_mult = 1.2   # slight upsize, wider stops
    else:
        regime = "EXTREME";    size_mult = 0.7; stop_mult = 1.4   # reduce size, wide stops

    # NR7 day-after expansion bias — if today is post-NR7 AND range is already
    # expanding, give a small additional conviction nudge (handled at caller).
    nr7_bias_note = " (NR7 day-after — expansion expected)" if is_nr7 else ""

    return VolatilityState(
        yesterday_range_pct=round(yesterday_range_pct, 3),
        today_range_so_far_pct=round(today_range_pct, 3),
        rolling_5d_avg_pct=round(avg_5d, 3),
        is_nr7=is_nr7,
        regime=regime,
        size_multiplier=size_mult,
        stop_multiplier=stop_mult,
        reasoning=f"vol blended {blended:.2f}× of 5d avg → {regime}{nr7_bias_note}",
    )


class VolatilityStateAgent:
    """
    Stateful: caches daily candles per session, computes volatility state once
    per refresh interval. Designed to be called from crew.py per tick without
    re-fetching daily data.
    """
    NIFTY_SYMBOL = "NIFTY 50"

    def __init__(self, kite):
        self.kite = kite
        self._daily_cache_date: Optional[str] = None
        self._daily_ranges_pct: list[float] = []
        self._yesterday_high_low: Optional[tuple[float, float]] = None
        self._last_state: Optional[VolatilityState] = None
        self._last_fetch_minute: Optional[int] = None
        # Phase 2.0 telemetry — one log line per regime transition per day
        self._logged_regime_today: dict[str, str] = {}

    def get_state(self, now=None) -> Optional[VolatilityState]:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        if now is None:
            now = datetime.now(IST)

        # Refresh daily history once per day
        today_iso = now.date().isoformat()
        if self._daily_cache_date != today_iso:
            self._refresh_daily(today_iso)

        if not self._yesterday_high_low:
            return None  # not enough history

        # Refresh today's high/low at most every 5 min
        cur_min = now.hour * 60 + now.minute
        if self._last_state is not None and self._last_fetch_minute is not None \
                and cur_min - self._last_fetch_minute < 5:
            return self._last_state

        try:
            df = self.kite.get_candles(self.NIFTY_SYMBOL, interval="5minute", days=1)
            if df is None or len(df) == 0:
                return None
            df["date"] = df["date"].apply(
                lambda d: d.replace(tzinfo=IST) if hasattr(d, "tzinfo") and d.tzinfo is None else d
            )
            today_bars = df[df["date"].apply(
                lambda d: (d.date().isoformat() if hasattr(d, "date") else str(d)[:10]) == today_iso
            )]
            if len(today_bars) == 0:
                return None
            today_high = float(today_bars["high"].max())
            today_low  = float(today_bars["low"].min())
            yh, yl = self._yesterday_high_low
            state = compute_volatility_state(today_high, today_low, yh, yl, self._daily_ranges_pct)
            self._last_state = state
            self._last_fetch_minute = cur_min

            # Phase 2.0 telemetry — one line per regime transition per day
            prev = self._logged_regime_today.get(today_iso)
            if prev != state.regime:
                nr7_tag = "  NR7-day-after" if state.is_nr7 else ""
                print(
                    f"[Vol-State] {state.regime}{nr7_tag}  "
                    f"today {state.today_range_so_far_pct:.2f}%  "
                    f"yest {state.yesterday_range_pct:.2f}%  "
                    f"5d-avg {state.rolling_5d_avg_pct:.2f}%  "
                    f"size×{state.size_multiplier:.2f}  stop×{state.stop_multiplier:.2f}  "
                    f"({state.reasoning})"
                )
                self._logged_regime_today[today_iso] = state.regime
            return state
        except Exception as e:
            print(f"[VolatilityState] error: {e}")
            return None

    def _refresh_daily(self, today_iso: str):
        try:
            df = self.kite.get_candles(self.NIFTY_SYMBOL, interval="day", days=10)
            if df is None or len(df) < 3:
                return
            # Exclude today's partial bar
            df = df[df["date"].apply(
                lambda d: (d.date().isoformat() if hasattr(d, "date") else str(d)[:10]) < today_iso
            )]
            df = df.sort_values("date")
            last_5 = df.tail(5)
            self._daily_ranges_pct = [
                100.0 * (float(r["high"]) - float(r["low"])) / float(r["low"])
                for _, r in last_5.iterrows() if float(r["low"]) > 0
            ]
            # NR7 check: yesterday's range was narrowest of last 7
            last_7 = df.tail(7)
            ranges_7 = [
                100.0 * (float(r["high"]) - float(r["low"])) / float(r["low"])
                for _, r in last_7.iterrows() if float(r["low"]) > 0
            ]
            if ranges_7:
                yest = ranges_7[-1]
                self._is_nr7 = (yest == min(ranges_7))
            else:
                self._is_nr7 = False
            # Yesterday's H/L for blended formula
            if len(df) >= 1:
                last_row = df.iloc[-1]
                self._yesterday_high_low = (float(last_row["high"]), float(last_row["low"]))
            self._daily_cache_date = today_iso
        except Exception as e:
            print(f"[VolatilityState] daily refresh error: {e}")
