"""
Mid-Trade Structural Re-evaluation — Phase 2.7.

Spec: docs/24_Mid_Trade_Reeval_Spec_2026-05-18.md

WHY THIS EXISTS
───────────────
Existing position management is REACTIVE — it only fires on price events
(SL hit, TP1 hit, trailing-stop hit, EOD force-close, time-stop). It does
NOT re-check whether the original entry THESIS still holds while the
position is open. So a clean entry at 10:30 IST can ride to full SL at
12:30 IST even when the market structure invalidates at 11:00 IST.

The classic failure mode this module catches:
  1. Enter LONG STOCK_X at 10:30 IST. Macro=GREEN, FHH break clean,
     HOD-proximity 0.2%, vol×2.5.
  2. By 11:15 IST: NIFTY drops 60 bps, macro deteriorates toward YELLOW.
     Stock starts grinding lower, slips below intraday VWAP.
  3. By 12:00 IST: stock is 1.2% below HOD, no follow-through, but
     SL hasn't hit yet. Original thesis is fully invalidated, position
     still at full risk.
  4. 12:30 IST: SL fires at -1R full loss.

This module evaluates the thesis dimensions every 5 min per open position
and exits early when enough of them break — recovering some of that -1R
into a smaller loss or break-even.

THE RULE
────────
Three structural dimensions, re-checked at most once every
MID_TRADE_REEVAL_INTERVAL_MIN per position:

  1. MACRO  — market_state.allows_long_entry() must still be True
              (STRONG_GREEN / GREEN / YELLOW pass; RED / STRONG_RED fail)
  2. VWAP   — current LTP must be ≥ today's running VWAP (for longs)
  3. HOD    — current LTP within MID_TRADE_HOD_RELAX_PCT (default 1.5%)
              of today's intraday high. Relaxed vs entry's 0.5% because
              a healthy trade can pull back a bit in normal trading.

Action ladder based on how many dimensions broke:
  • 0-1 broken → CONTINUE (let existing SL/TP/trail manage)
  • 2 broken   → TIGHTEN SL to break-even (entry_price) if not already
                 above. Limits remaining downside to slippage only.
  • 3 broken   → CLOSE position at market with reason "thesis_invalidated".
                 Don't wait for SL — exit while spread is still tight.

ROLLOUT
───────
Default OFF (MID_TRADE_REEVAL_ENABLED=False). When MID_TRADE_REEVAL_LOG_SHADOW
is True, the module still evaluates and logs [Reeval] X TIGHTEN-SHADOW /
[Reeval] X CLOSE-SHADOW lines without taking action — so we can measure
how often the rule would have fired before flipping it live.

Three Laws compliance:
  - No clock categories — dimensions are pure structure
  - No symbol/sector hardcoding — works on any open position
  - All thresholds in config/settings.py
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo


ReevalAction = Literal["CONTINUE", "TIGHTEN_TO_BE", "CLOSE"]


@dataclass(frozen=True)
class ReevalResult:
    """Output of one evaluate() call."""
    action:        ReevalAction
    broken_count:  int                # 0..3
    broken_dims:   list[str]          # subset of ["macro", "vwap", "hod"]
    macro_state:   str
    ltp:           float
    vwap:          float
    pull_from_hod_pct: float
    reason:        str                # human-readable summary


class MidTradeReeval:
    """
    Stateful per-position evaluator. Tracks last-checked timestamp so we
    re-evaluate at most once every INTERVAL_MIN per position.

    Usage in crew._manage_positions, after existing SL/TP/trail checks:

        rr = self.reeval.evaluate(p, current_quote, vwap)
        if rr.action == "CLOSE" and settings.MID_TRADE_REEVAL_ENABLED:
            self._full_exit(p, current_price, "thesis_invalidated")
        elif rr.action == "TIGHTEN_TO_BE" and settings.MID_TRADE_REEVAL_ENABLED:
            # Move SL to entry price if not already above
            if p.stop_loss < p.entry_price:
                self._move_sl_to(p, p.entry_price)
        # else: log only (shadow mode handled inside evaluate)
    """

    def __init__(self, market_state_agent, settings_module=None):
        self.market_state = market_state_agent
        if settings_module is None:
            from config import settings as _settings
            settings_module = _settings
        self.s = settings_module
        # Per-position last-check tracking — keyed by position id.
        # Bounded by max-open-positions, so memory is small.
        self._last_check_at: dict[int, datetime] = {}

    def should_check(self, position_id: int, now: datetime) -> bool:
        """Returns True if this position is due for re-evaluation."""
        last = self._last_check_at.get(position_id)
        if last is None:
            return True
        interval_min = getattr(self.s, "MID_TRADE_REEVAL_INTERVAL_MIN", 5)
        return (now - last) >= timedelta(minutes=interval_min)

    def evaluate(
        self,
        position,                  # Position-like; needs .id, .entry_price, .direction
        current_quote: dict,       # {"last_price", "high", "low", ...}
        running_vwap: float,       # today's VWAP for the symbol
        now: Optional[datetime] = None,
    ) -> ReevalResult:
        """
        Apply the 3-dimension re-evaluation. Always evaluates — caller
        decides whether to act on the result based on the feature flag.

        Currently long-only (matches the rest of the system). Shorts can
        be added by mirroring the VWAP/HOD checks.
        """
        if now is None:
            tz = ZoneInfo(getattr(self.s, "TIMEZONE", "Asia/Kolkata"))
            now = datetime.now(tz)

        ltp = float(current_quote.get("last_price", 0.0) or 0.0)
        day_high = float(current_quote.get("high", 0.0) or 0.0)

        broken_dims: list[str] = []
        macro_state_str = "-"

        # ── Dimension 1: macro ───────────────────────────────────────────────
        try:
            snap = self.market_state.get_state(now)
            macro_state_str = snap.state
            if not snap.allows_long_entry():
                # WAITING / RED / STRONG_RED → macro broken
                broken_dims.append("macro")
        except Exception:
            # If macro can't be read, treat as not-broken (don't auto-exit on infra)
            macro_state_str = "?"

        # ── Dimension 2: VWAP ────────────────────────────────────────────────
        if ltp > 0 and running_vwap > 0 and ltp < running_vwap:
            broken_dims.append("vwap")

        # ── Dimension 3: HOD proximity (relaxed) ─────────────────────────────
        pull_pct = 0.0
        if day_high > 0 and ltp > 0:
            pull_pct = (day_high - ltp) / day_high
        relax = getattr(self.s, "MID_TRADE_HOD_RELAX_PCT", 0.015)
        if pull_pct > relax:
            broken_dims.append("hod")

        n_broken = len(broken_dims)
        tighten_thresh = getattr(self.s, "MID_TRADE_TIGHTEN_AT_BROKEN", 2)
        close_thresh   = getattr(self.s, "MID_TRADE_CLOSE_AT_BROKEN", 3)

        if n_broken >= close_thresh:
            action: ReevalAction = "CLOSE"
            reason = (f"thesis_invalidated — {n_broken}/3 dims broken "
                      f"({','.join(broken_dims)})")
        elif n_broken >= tighten_thresh:
            action = "TIGHTEN_TO_BE"
            reason = (f"thesis_weakening — {n_broken}/3 dims broken "
                      f"({','.join(broken_dims)})")
        else:
            action = "CONTINUE"
            reason = (f"thesis_intact — {n_broken}/3 dims broken"
                      + (f" ({','.join(broken_dims)})" if broken_dims else ""))

        # Record check timestamp so should_check() respects the interval
        self._last_check_at[position.id] = now

        return ReevalResult(
            action=action,
            broken_count=n_broken,
            broken_dims=broken_dims,
            macro_state=macro_state_str,
            ltp=ltp,
            vwap=round(running_vwap, 2),
            pull_from_hod_pct=round(pull_pct * 100, 3),
            reason=reason,
        )

    def drop_position(self, position_id: int) -> None:
        """Cleanup when a position closes — drops its last-check entry."""
        self._last_check_at.pop(position_id, None)
