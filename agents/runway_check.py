"""
Runway Check — Phase 2.6.

Spec: docs/22_Runway_Check_Spec_2026-05-12.md

THE PROBLEM
───────────
The agent's `NO_NEW_ENTRY_AFTER = 14:45` is a blunt clock cutoff. It:
  • is setup-blind (fast and slow setups treated identically)
  • is the last surviving clock-category rule (violates Three Laws)

THE RULE
────────
For each entry candidate at `now`:
  1. Look up the setup's historical median time-to-TP1 from trade_state.db
     (last RUNWAY_LOOKBACK_TRADES winning trades of that setup type).
  2. Compute remaining session runway = EOD_PARTIAL_UNWIND_TIME - now
     (default unwind 14:45 IST per Fix #34).
  3. Apply safety factor: required = median_TTP1 * RUNWAY_SAFETY_FACTOR.
  4. SKIP if required > remaining_min OR remaining_min < absolute floor.
  5. Otherwise ADMIT (continue to next conviction-engine check).

BOOTSTRAP
─────────
When < 5 historical wins for a setup, use RUNWAY_SETUP_DEFAULTS hardcoded
table, then fall back to RUNWAY_DEFAULT_TTP1_MIN if not in the table.

ROLLOUT
───────
Default OFF. Set RUNWAY_CHECK_LOG_SHADOW=True to log near-misses without
blocking. After 2 sessions of clean shadow logs, flip RUNWAY_CHECK_ENABLED=True.

This module is pure — no Kite, no broker calls. State manager dependency
is injected. Easy to unit-test.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RunwayResult:
    """Output of one evaluate_runway() call."""
    ok:             bool       # True if candidate has enough runway
    median_ttp1:    float      # the median used in the decision (minutes)
    sample_size:    int        # historical sample feeding the median
    is_bootstrap:   bool       # True if fallback value used
    remaining_min:  float      # session runway remaining (minutes to EOD)
    required_min:   float      # median_ttp1 * safety_factor
    reason:         str        # human-readable summary


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def evaluate_runway(
    setup_type:      str,
    state_mgr,                       # TradeStateManager-like; needs get_median_ttp1_minutes
    settings_module=None,
    now: Optional[datetime] = None,
) -> RunwayResult:
    """
    Apply the runway check. Returns RunwayResult.

    Caller (conviction_engine) typically:
        rc = evaluate_runway(setup_type, state, settings, now)
        if RUNWAY_CHECK_ENABLED and not rc.ok:
            return _skip(...)
        elif RUNWAY_CHECK_LOG_SHADOW and not rc.ok:
            print(f"[Runway] {setup_type} would-skip — {rc.reason}")
    """
    if settings_module is None:
        from config import settings as _settings
        settings_module = _settings

    s = settings_module
    if now is None:
        ist = ZoneInfo(getattr(s, "TIMEZONE", "Asia/Kolkata"))
        now = datetime.now(ist)

    # ── 1. Median TTP1 lookup ────────────────────────────────────────────────
    lookback = getattr(s, "RUNWAY_LOOKBACK_TRADES", 50)
    bootstrap_default = getattr(s, "RUNWAY_DEFAULT_TTP1_MIN", 45)
    setup_defaults = getattr(s, "RUNWAY_SETUP_DEFAULTS", {})

    median, sample = (None, 0)
    is_bootstrap = False
    try:
        median, sample = state_mgr.get_median_ttp1_minutes(setup_type, lookback)
    except Exception as e:
        # State manager not available or DB error — bootstrap path.
        median, sample = (None, 0)

    if median is None or sample < 5:
        # Fallback ladder: setup-specific default → global default
        is_bootstrap = True
        median = float(setup_defaults.get(setup_type, bootstrap_default))

    # ── 2. Remaining session runway ──────────────────────────────────────────
    eod_unwind_str = getattr(s, "EOD_PARTIAL_UNWIND_TIME", "14:45")
    eod_t = _parse_hhmm(eod_unwind_str)
    # Build a tz-aware datetime for today's EOD unwind moment.
    eod_dt = now.replace(hour=eod_t.hour, minute=eod_t.minute,
                         second=0, microsecond=0)
    remaining_min = max(0.0, (eod_dt - now).total_seconds() / 60.0)

    # ── 3. Absolute floor ────────────────────────────────────────────────────
    abs_floor = getattr(s, "RUNWAY_MIN_REMAINING_MIN", 20)
    if remaining_min < abs_floor:
        return RunwayResult(
            ok=False,
            median_ttp1=median,
            sample_size=sample,
            is_bootstrap=is_bootstrap,
            remaining_min=round(remaining_min, 1),
            required_min=round(median * getattr(s, "RUNWAY_SAFETY_FACTOR", 1.5), 1),
            reason=(
                f"remaining {remaining_min:.0f}m < absolute floor {abs_floor}m"
            ),
        )

    # ── 4. Apply safety factor ───────────────────────────────────────────────
    safety = getattr(s, "RUNWAY_SAFETY_FACTOR", 1.5)
    required = median * safety

    if required > remaining_min:
        return RunwayResult(
            ok=False,
            median_ttp1=median,
            sample_size=sample,
            is_bootstrap=is_bootstrap,
            remaining_min=round(remaining_min, 1),
            required_min=round(required, 1),
            reason=(
                f"TTP1≈{median:.0f}m × {safety:.1f} = {required:.0f}m needed, "
                f"only {remaining_min:.0f}m left "
                f"({'bootstrap' if is_bootstrap else f'n={sample}'})"
            ),
        )

    # ── 5. ADMIT ─────────────────────────────────────────────────────────────
    return RunwayResult(
        ok=True,
        median_ttp1=median,
        sample_size=sample,
        is_bootstrap=is_bootstrap,
        remaining_min=round(remaining_min, 1),
        required_min=round(required, 1),
        reason=(
            f"TTP1≈{median:.0f}m × {safety:.1f} = {required:.0f}m ≤ "
            f"{remaining_min:.0f}m remaining "
            f"({'bootstrap' if is_bootstrap else f'n={sample}'})"
        ),
    )
