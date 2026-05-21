"""
Scalp Engine — fast, stock-structural entry path (2026-05-21).

WHY THIS MODULE EXISTS
----------------------
The conviction pipeline (base-breakout setup detector → RVOL≥1.5 gate → six
conviction gates, all ANDed together) took ZERO trades across ten sessions.
On 2026-05-21 the Discovery engine *admitted* the day's real movers — ANGELONE
+5% on 12x volume, MTARTECH +5.8% on 11x volume — and the agent never traded a
single one, because a smooth high-volume uptrend prints small-bodied
continuation candles that the base-breakout detector logs as `weak_body` and
discards. The system found the winners and could not pull the trigger.

DESIGN (agreed with operator — AGGRESSIVE profile)
--------------------------------------------------
Move the strictness from the ENTRY to the EXIT.

Entry  : a pure stock-structural trigger — above VWAP, last bar up, volume
         present, order book not collapsing, and NOT over-extended from VWAP
         (so we never chase a parabolic blowoff top). No macro/FHH/HOD/day-type
         /grade gates. Take many small shots.
Exit   : hard stop −0.4%, take-profit +0.8% (2:1), a flat-trade scratch after a
         few minutes ("sneak in; if it doesn't go, leave"), and a hard time
         stop. A trap costs a 0.4% scratch instead of being pre-screened.
Risk   : small per-trade notional, more concurrent shots, and a firm daily
         realized-loss cap that halts new entries for the day.

This module is PURE: it imports nothing from Kite and holds no I/O. Callers
(the live crew loop, or scripts/scalp_replay.py) feed it plain numbers and act
on the returned decisions. That keeps it unit-testable and replay-able offline
(the sandbox cannot reach Kite).

See config/settings.py "SCALP MODE" block for the live parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ─── Configuration ───────────────────────────────────────────────────────────

@dataclass
class ScalpConfig:
    """All scalp parameters in one struct. Build from settings via from_settings()."""
    # entry
    require_above_vwap:   bool  = True
    require_up_bar:       bool  = True
    rvol_min:             float = 1.2
    ob_ratio_min:         float = 0.7
    spread_max_pct:       float = 0.0015
    max_ext_from_vwap:    float = 0.015
    circuit_veto_pct:     float = 0.18
    # exit
    stop_pct:             float = 0.004    # floor — stop never tighter than this
    stop_atr_mult:        float = 1.0      # stop = max(stop_pct, atr_mult × ATR)
    stop_max_pct:         float = 0.010    # cap — stop never wider than this
    tp_r_mult:            float = 2.0      # target = tp_r_mult × actual stop distance
    tp_pct:               float = 0.008    # fallback target when ATR unavailable
    scratch_min:          int   = 6
    time_stop_min:        int   = 20
    # sizing / risk
    notional_inr:         float = 200_000
    max_positions:        int   = 5
    daily_loss_cap_inr:   float = 30_000

    @classmethod
    def from_settings(cls, s) -> "ScalpConfig":
        """Build from a settings module, falling back to the dataclass defaults."""
        g = lambda name, default: getattr(s, name, default)
        return cls(
            require_above_vwap=g("SCALP_REQUIRE_ABOVE_VWAP", True),
            require_up_bar=g("SCALP_REQUIRE_UP_BAR", True),
            rvol_min=g("SCALP_RVOL_MIN", 1.2),
            ob_ratio_min=g("SCALP_OB_RATIO_MIN", 0.7),
            spread_max_pct=g("SCALP_SPREAD_MAX_PCT", 0.0015),
            max_ext_from_vwap=g("SCALP_MAX_EXT_FROM_VWAP_PCT", 0.015),
            circuit_veto_pct=g("SCALP_CIRCUIT_VETO_PCT", 0.18),
            stop_pct=g("SCALP_STOP_PCT", 0.004),
            stop_atr_mult=g("SCALP_STOP_ATR_MULT", 1.0),
            stop_max_pct=g("SCALP_STOP_MAX_PCT", 0.010),
            tp_r_mult=g("SCALP_TP_R_MULT", 2.0),
            tp_pct=g("SCALP_TP_PCT", 0.008),
            scratch_min=g("SCALP_SCRATCH_MIN", 6),
            time_stop_min=g("SCALP_TIME_STOP_MIN", 20),
            notional_inr=g("SCALP_NOTIONAL_INR", 200_000),
            max_positions=g("SCALP_MAX_POSITIONS", 5),
            daily_loss_cap_inr=g("SCALP_DAILY_LOSS_CAP_INR", 30_000),
        )


# ─── Decision results ────────────────────────────────────────────────────────

@dataclass
class EntryDecision:
    enter:   bool
    reason:  str
    entry:   float = 0.0
    stop:    float = 0.0
    target:  float = 0.0
    qty:     int   = 0


@dataclass
class ExitDecision:
    exit:    bool
    reason:  str          # "stop" | "target" | "scratch" | "time_stop" | "hold"
    price:   float = 0.0


# ─── Sizing ──────────────────────────────────────────────────────────────────

def size_position(entry: float, cfg: ScalpConfig) -> int:
    """Fixed-notional sizing. Tight stops would blow up risk-based qty, so we
    cap by notional instead: qty = floor(notional / entry). Risk per trade is
    then ≈ notional × stop_dist_pct (bounded by stop_max_pct)."""
    if entry <= 0:
        return 0
    return int(cfg.notional_inr // entry)


def stop_target(entry: float, atr: float, cfg: ScalpConfig) -> tuple[float, float]:
    """
    Volatility-scaled stop with a constant reward:risk target.

    stop distance = clamp( atr_mult × ATR ,  floor = stop_pct×entry ,
                                              cap   = stop_max_pct×entry )
    target        = entry + tp_r_mult × stop_distance

    When atr ≤ 0 (unavailable), falls back to the flat stop_pct / tp_pct.
    A ₹7800 wide-range name gets a wider stop (room to breathe); a ₹340 grinder
    keeps its tight one. R:R is identical for both.
    """
    if entry <= 0:
        return 0.0, 0.0
    floor_d = cfg.stop_pct * entry
    cap_d   = cfg.stop_max_pct * entry
    if atr and atr > 0:
        stop_d = min(max(cfg.stop_atr_mult * atr, floor_d), cap_d)
        target_d = cfg.tp_r_mult * stop_d
    else:
        stop_d   = floor_d
        target_d = cfg.tp_pct * entry
    return round(entry - stop_d, 2), round(entry + target_d, 2)


# ─── Entry ───────────────────────────────────────────────────────────────────

def evaluate_entry(
    symbol:          str,
    ltp:             float,
    vwap:            float,
    bar_open:        float,
    bar_close:       float,
    rvol:            float,
    ob_ratio:        float,
    spread_pct:      float,
    day_change_pct:  float,
    cfg:             ScalpConfig,
    atr:             float = 0.0,
) -> EntryDecision:
    """
    The loosened scalp trigger. Returns enter=True with entry/stop/target/qty
    when ALL of the following hold:

      1. above VWAP                  (buyers above fair value)
      2. last completed bar is up    (momentum right now)
      3. volume present              (rvol ≥ rvol_min)
      4. order book not collapsing   (5-level bid/sell ≥ ob_ratio_min)
      5. spread sane                 (≤ spread_max_pct)
      6. not over-extended from VWAP (≤ max_ext_from_vwap — no chasing blowoffs)
      7. not circuit-locked          (|day move| < circuit_veto_pct)

    Everything the old pipeline demanded — near-HOD, big body, prev-green,
    range-expansion, 6-bar-high break, macro GREEN, NIFTY/stock FHH, day-type,
    runway, setup grade — is intentionally GONE. The exit discipline carries
    the risk now.
    """
    if ltp <= 0 or vwap <= 0:
        return EntryDecision(False, "no_price")

    # 7. circuit veto (cheap, decisive)
    if abs(day_change_pct) >= cfg.circuit_veto_pct * 100.0:
        return EntryDecision(False, f"circuit_locked_{day_change_pct:+.1f}%")

    # 1. above VWAP
    if cfg.require_above_vwap and ltp <= vwap:
        return EntryDecision(False, f"below_vwap_{(ltp/vwap-1)*100:+.2f}%")

    # 6. not over-extended (the smart-risk guard — skip the parabolic top)
    ext = (ltp - vwap) / vwap
    if ext > cfg.max_ext_from_vwap:
        return EntryDecision(False, f"extended_{ext*100:.2f}%_above_vwap")

    # 2. last bar up
    if cfg.require_up_bar and not (bar_close > bar_open):
        return EntryDecision(False, "last_bar_not_up")

    # 3. volume present
    if rvol < cfg.rvol_min:
        return EntryDecision(False, f"rvol_{rvol:.2f}<{cfg.rvol_min}")

    # 4. order book not collapsing
    if ob_ratio < cfg.ob_ratio_min:
        return EntryDecision(False, f"book_sell_heavy_{ob_ratio:.2f}")

    # 5. spread sane
    if spread_pct > cfg.spread_max_pct:
        return EntryDecision(False, f"spread_{spread_pct*100:.2f}%")

    # All clear → build the trade with a volatility-scaled stop / constant R:R.
    entry  = round(ltp, 2)
    stop, target = stop_target(entry, atr, cfg)
    qty    = size_position(entry, cfg)
    if qty <= 0:
        return EntryDecision(False, "qty_zero")
    return EntryDecision(
        True,
        f"scalp_long above_vwap ext={ext*100:.2f}% rvol={rvol:.2f} ob={ob_ratio:.2f}",
        entry=entry, stop=stop, target=target, qty=qty,
    )


# ─── Exit ────────────────────────────────────────────────────────────────────

def evaluate_exit(
    entry:        float,
    stop:         float,
    target:       float,
    minutes_held: float,
    bar_high:     float,
    bar_low:      float,
    bar_close:    float,
    cfg:          ScalpConfig,
) -> ExitDecision:
    """
    Exit precedence within a bar (conservative): stop first, then target, then
    the time-based rules on the bar close.

      stop      — bar_low ≤ stop                          → exit at stop
      target    — bar_high ≥ target                       → exit at target
      scratch   — held ≥ scratch_min and not > +0.1%      → exit at close
      time_stop — held ≥ time_stop_min                    → exit at close
      hold      — otherwise
    """
    # Hard stop (assume the worst — stop fills before target if both touched)
    if bar_low <= stop:
        return ExitDecision(True, "stop", price=stop)
    # Take profit
    if bar_high >= target:
        return ExitDecision(True, "target", price=target)
    # Flat-trade scratch — sneak in, no follow-through, leave
    in_profit = bar_close >= entry * 1.001
    if minutes_held >= cfg.scratch_min and not in_profit:
        return ExitDecision(True, "scratch", price=round(bar_close, 2))
    # Hard time stop
    if minutes_held >= cfg.time_stop_min:
        return ExitDecision(True, "time_stop", price=round(bar_close, 2))
    return ExitDecision(False, "hold")


# ─── Daily loss cap ──────────────────────────────────────────────────────────

def daily_cap_hit(realized_pnl_today: float, cfg: ScalpConfig) -> bool:
    """True once the day's realized scalp P&L has lost more than the cap.
    Caller halts NEW entries for the day; open positions keep their exits."""
    return realized_pnl_today <= -abs(cfg.daily_loss_cap_inr)
