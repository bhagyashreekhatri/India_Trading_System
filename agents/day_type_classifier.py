"""
Day-Type Classifier.

Validated on 584 NIFTY sessions (Jan 2024 – May 2026):
  TREND days (close in extreme 20% + |OC|≥0.5%):   31% of sessions
  RANGE days (close mid 40% + |OC|<0.3%):           20% of sessions
  BALANCED (mixed):                                  49% of sessions

By 11:00 IST we have 9 5-minute candles (or 1.75 hourly bars) — enough to
classify the day's forming structure with reasonable confidence. This lets
the conviction engine route signals:

  TREND_FORMING_UP   → favor momentum continuation (full size on tier A/B)
  TREND_FORMING_DN   → no longs (matches macro RED bias)
  RANGE_FORMING      → mean-reversion (currently disarmed) OR skip momentum
  BALANCED           → only highest-conviction (tier S) entries

See docs/15_Setup_Pattern_Library_18mo_2026-05-11.md section 1.3.

This module is dependency-light — it just consumes a list of 5-minute candles
and emits a label. No Kite calls, no state. Used by conviction_engine when
deciding tier eligibility for a given setup.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import time as dtime
from typing import Literal, Optional


DayType = Literal[
    "WAITING",           # before 11:00 IST — not enough data
    "TREND_FORMING_UP",  # NIFTY trending up cleanly so far
    "TREND_FORMING_DN",  # NIFTY trending down cleanly so far
    "RANGE_FORMING",     # tight range, low volatility forming
    "BALANCED",          # mixed — most common (~49%)
]


CLASSIFY_AFTER_IST = dtime(11, 0)


@dataclass
class DayTypeSnapshot:
    type:                  DayType
    nifty_range_pct:       float
    nifty_oc_pct:           float
    close_position_in_range: float  # 0.0 = at low, 1.0 = at high
    bars_seen:             int
    reasoning:             str


def classify_day_type(
    candles_5m: list[dict],   # [{"date","open","high","low","close"}]
    now=None,
) -> DayTypeSnapshot:
    """
    Classify the day's forming structure from 09:15 to now.

    Logic (validated on 30-month NIFTY structure):
      • Need ≥9 5-min bars (09:15-11:00 IST window completed)
      • If range_pct > 0.5% AND |OC| > 0.3% AND close in extreme 20% → TREND
      • If range_pct < 0.4% → RANGE_FORMING (tight compression)
      • Otherwise BALANCED
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")

    if now is None:
        now = datetime.now(IST)

    # Before 11:00 IST → waiting
    if now.time() < CLASSIFY_AFTER_IST:
        return DayTypeSnapshot(
            type="WAITING",
            nifty_range_pct=0.0, nifty_oc_pct=0.0,
            close_position_in_range=0.5, bars_seen=len(candles_5m),
            reasoning="before 11:00 IST — waiting for classification window",
        )

    if not candles_5m or len(candles_5m) < 9:
        return DayTypeSnapshot(
            type="WAITING",
            nifty_range_pct=0.0, nifty_oc_pct=0.0,
            close_position_in_range=0.5, bars_seen=len(candles_5m),
            reasoning=f"only {len(candles_5m)} bars seen — need ≥9",
        )

    # Compute the structural fingerprint
    day_open  = float(candles_5m[0]["open"])
    day_high  = max(float(c["high"]) for c in candles_5m)
    day_low   = min(float(c["low"]) for c in candles_5m)
    day_close = float(candles_5m[-1]["close"])

    range_pct = 100.0 * (day_high - day_low) / day_low if day_low > 0 else 0.0
    oc_pct    = 100.0 * (day_close - day_open) / day_open if day_open > 0 else 0.0
    close_pos = (day_close - day_low) / (day_high - day_low) if day_high > day_low else 0.5

    # TREND classification: |OC| meaningful AND close in extreme 20% of range
    if range_pct > 0.5 and abs(oc_pct) > 0.3:
        if oc_pct > 0 and close_pos > 0.8:
            return DayTypeSnapshot(
                type="TREND_FORMING_UP",
                nifty_range_pct=round(range_pct, 3),
                nifty_oc_pct=round(oc_pct, 3),
                close_position_in_range=round(close_pos, 2),
                bars_seen=len(candles_5m),
                reasoning=f"NIFTY range {range_pct:.2f}%, OC {oc_pct:+.2f}%, "
                          f"close pos {close_pos:.0%} of range — UP trend forming",
            )
        if oc_pct < 0 and close_pos < 0.2:
            return DayTypeSnapshot(
                type="TREND_FORMING_DN",
                nifty_range_pct=round(range_pct, 3),
                nifty_oc_pct=round(oc_pct, 3),
                close_position_in_range=round(close_pos, 2),
                bars_seen=len(candles_5m),
                reasoning=f"NIFTY range {range_pct:.2f}%, OC {oc_pct:+.2f}%, "
                          f"close pos {close_pos:.0%} of range — DOWN trend forming",
            )

    # RANGE_FORMING: tight compression so far
    if range_pct < 0.4:
        return DayTypeSnapshot(
            type="RANGE_FORMING",
            nifty_range_pct=round(range_pct, 3),
            nifty_oc_pct=round(oc_pct, 3),
            close_position_in_range=round(close_pos, 2),
            bars_seen=len(candles_5m),
            reasoning=f"NIFTY range {range_pct:.2f}% < 0.4% — compression / range day",
        )

    # Everything else
    return DayTypeSnapshot(
        type="BALANCED",
        nifty_range_pct=round(range_pct, 3),
        nifty_oc_pct=round(oc_pct, 3),
        close_position_in_range=round(close_pos, 2),
        bars_seen=len(candles_5m),
        reasoning=f"NIFTY mixed (range {range_pct:.2f}%, OC {oc_pct:+.2f}%, "
                  f"close pos {close_pos:.0%}) — no clear trend forming",
    )


class DayTypeClassifier:
    """
    Stateful wrapper that fetches NIFTY 5-min candles from Kite and caches
    the latest classification snapshot for the day. Designed to be called
    multiple times per tick without re-fetching.
    """
    NIFTY_SYMBOL = "NIFTY 50"

    def __init__(self, kite):
        self.kite = kite
        self._cache_by_date: dict[str, DayTypeSnapshot] = {}
        self._last_fetch_minute: Optional[int] = None

    def get_snapshot(self, now=None) -> DayTypeSnapshot:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        if now is None:
            now = datetime.now(IST)

        # Refresh at most once every 5 minutes — that's the bar resolution
        cur_min = now.hour * 60 + now.minute
        cache_key = now.date().isoformat()
        if self._last_fetch_minute is not None and cur_min - self._last_fetch_minute < 5 \
                and cache_key in self._cache_by_date:
            return self._cache_by_date[cache_key]

        try:
            df = self.kite.get_candles(self.NIFTY_SYMBOL, interval="5minute", days=1)
            if df is None or len(df) == 0:
                return classify_day_type([], now)
            # Filter to today only
            today_iso = now.date().isoformat()
            df["date"] = df["date"].apply(
                lambda d: d.replace(tzinfo=IST) if hasattr(d, "tzinfo") and d.tzinfo is None else d
            )
            today_bars = df[df["date"].apply(
                lambda d: (d.date().isoformat() if hasattr(d, "date") else str(d)[:10]) == today_iso
            )]
            candles = [
                {"date": r["date"], "open": r["open"], "high": r["high"],
                 "low": r["low"], "close": r["close"]}
                for _, r in today_bars.iterrows()
            ]
            snap = classify_day_type(candles, now)
            self._cache_by_date[cache_key] = snap
            self._last_fetch_minute = cur_min
            return snap
        except Exception as e:
            print(f"[DayTypeClassifier] error: {e}")
            return classify_day_type([], now)
