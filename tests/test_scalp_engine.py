"""Unit tests for agents/scalp_engine.py (2026-05-21).

Covers the volatility-scaled stop, the loosened entry gates, the exit
precedence, and the daily loss cap. Pure logic — no Kite, runs anywhere.

    python tests/test_scalp_engine.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.scalp_engine import (
    ScalpConfig, evaluate_entry, evaluate_exit, stop_target,
    size_position, daily_cap_hit, evaluate_manage,
)

cfg = ScalpConfig()   # dataclass defaults = the shipped profile


def approx(a, b, tol=0.05):
    return abs(a - b) <= tol


# ── stop_target: volatility scaling + constant R:R ───────────────────────────
# Tight grinder: ₹340, ATR ₹0.8 → 1×ATR(0.8) > floor(0.4%*340=1.36)? no, 0.8<1.36
# so the 0.4% floor wins → stop dist 1.36, target = 2× = 2.72.
s, t = stop_target(340.0, 0.8, cfg)
assert approx(340.0 - s, 1.36), f"grinder stop dist {340-s}"
assert approx(t - 340.0, 2.72), f"grinder target dist {t-340}"

# Wide high-priced name: ₹7800, ATR ₹50 → 1×ATR(50) but cap = 1.0%*7800 = 78.
# 50 < 78 and 50 > floor(0.4%*7800=31.2) → stop dist 50, target 100.
s, t = stop_target(7800.0, 50.0, cfg)
assert approx(7800.0 - s, 50.0), f"wide stop dist {7800-s}"
assert approx(t - 7800.0, 100.0), f"wide target dist {t-7800}"

# Absurd ATR must be capped at stop_max_pct (1.0%): ₹7800, ATR ₹400 → cap 78.
s, t = stop_target(7800.0, 400.0, cfg)
assert approx(7800.0 - s, 78.0), f"capped stop dist {7800-s}"
assert approx(t - 7800.0, 156.0), f"capped target dist {t-7800}"

# Reward:risk is always tp_r_mult (2.0)
for px, atr in [(340, 0.8), (7800, 50), (1200, 3)]:
    s, t = stop_target(px, atr, cfg)
    assert approx((t - px) / (px - s), cfg.tp_r_mult, 0.01), "R:R not 2:1"
print("[PASS] stop_target volatility scaling + 2:1 R:R")


# ── evaluate_entry: the loosened gates ───────────────────────────────────────
base = dict(symbol="X", vwap=100.0, bar_open=99.5, bar_close=100.5,
            rvol=5.0, ob_ratio=1.2, spread_pct=0.0005, day_change_pct=2.0, atr=0.6)

# clean long above VWAP → enter
d = evaluate_entry(ltp=100.6, cfg=cfg, **base)
assert d.enter, d.reason

# below VWAP → blocked
d = evaluate_entry(ltp=99.9, cfg=cfg, **{**base, "bar_close": 99.9})
assert not d.enter and "below_vwap" in d.reason, d.reason

# over-extended (>1.5% above VWAP) → blocked (no chasing the blowoff top)
d = evaluate_entry(ltp=102.0, cfg=cfg, **base)
assert not d.enter and "extended" in d.reason, d.reason

# sell-heavy book (ratio < 0.7) → blocked
d = evaluate_entry(ltp=100.6, cfg=cfg, **{**base, "ob_ratio": 0.4})
assert not d.enter and "book_sell_heavy" in d.reason, d.reason

# down bar → blocked
d = evaluate_entry(ltp=100.6, cfg=cfg, **{**base, "bar_open": 100.8, "bar_close": 100.5})
assert not d.enter and "not_up" in d.reason, d.reason

# thin volume (rvol < 1.2) → blocked
d = evaluate_entry(ltp=100.6, cfg=cfg, **{**base, "rvol": 0.9})
assert not d.enter and "rvol" in d.reason, d.reason

# circuit-locked (±18%) → blocked
d = evaluate_entry(ltp=100.6, cfg=cfg, **{**base, "day_change_pct": 19.0})
assert not d.enter and "circuit" in d.reason, d.reason
print("[PASS] evaluate_entry gates (vwap/ext/book/up-bar/rvol/circuit)")


# ── evaluate_exit: precedence ────────────────────────────────────────────────
entry, stop, tgt = 100.0, 99.6, 100.8

# stop hit (and even if target also touched, stop wins — conservative)
ex = evaluate_exit(entry, stop, tgt, 1, bar_high=101.0, bar_low=99.5, bar_close=99.7, cfg=cfg)
assert ex.exit and ex.reason == "stop" and ex.price == stop, ex

# target hit
ex = evaluate_exit(entry, stop, tgt, 1, bar_high=100.9, bar_low=99.9, bar_close=100.7, cfg=cfg)
assert ex.exit and ex.reason == "target" and ex.price == tgt, ex

# scratch — held past scratch_min, flat (not > +0.1%)  [only when enabled]
from dataclasses import replace as _replace
cfg_scr = _replace(cfg, scratch_enabled=True)
ex = evaluate_exit(entry, stop, tgt, cfg_scr.scratch_min, bar_high=100.2, bar_low=99.9, bar_close=100.0, cfg=cfg_scr)
assert ex.exit and ex.reason == "scratch", ex

# scratch DISABLED (the 2026-05-25 fix) → same flat bar must HOLD, ride to target/stop
cfg_noscr = _replace(cfg, scratch_enabled=False)
ex = evaluate_exit(entry, stop, tgt, cfg_noscr.scratch_min, bar_high=100.2, bar_low=99.9, bar_close=100.0, cfg=cfg_noscr)
assert not ex.exit and ex.reason == "hold", ex

# hold — early and in a small profit
ex = evaluate_exit(entry, stop, tgt, 2, bar_high=100.3, bar_low=99.9, bar_close=100.2, cfg=cfg)
assert not ex.exit and ex.reason == "hold", ex

# time stop — held past time_stop_min, no target/stop
ex = evaluate_exit(entry, stop, tgt, cfg.time_stop_min, bar_high=100.3, bar_low=99.9, bar_close=100.3, cfg=cfg)
assert ex.exit and ex.reason == "time_stop", ex
print("[PASS] evaluate_exit precedence (stop/target/scratch/hold/time)")


# ── sizing + daily cap ───────────────────────────────────────────────────────
assert size_position(340.0, cfg) == int(cfg.notional_inr // 340)
assert size_position(0, cfg) == 0
assert not daily_cap_hit(-29_999, cfg)
assert daily_cap_hit(-30_000, cfg)
assert daily_cap_hit(-50_000, cfg)
print("[PASS] sizing + daily loss cap")

# ── runner capture: evaluate_manage (partial at target + trail) ──────────────
from dataclasses import replace as _replace2
rc = _replace2(cfg, partial_trail_enabled=True, tp1_fraction=0.5,
               trail_atr_mult=1.0, scratch_enabled=False,
               pretp1_timeout_min=30, time_stop_min=90)

# entry 100, stop 99.6 (0.4%), target 100.8 (2:1), 100 sh
def _pos(**kw):
    base = {"entry": 100.0, "stop": 99.6, "target": 100.8,
            "qty": 100, "qty_remaining": 100, "tp1_done": False}
    base.update(kw); return base

# 1. pre-TP1 hard stop → exit_full "stop", whole remaining qty
md = evaluate_manage(_pos(), 3, bar_high=100.1, bar_low=99.5, bar_close=99.55, atr=0.5, cfg=rc)
assert md.action == "exit_full" and md.reason == "stop" and md.exit_qty == 100, md

# 2. pre-TP1 target touched → partial bank half, stop to breakeven
md = evaluate_manage(_pos(), 5, bar_high=100.85, bar_low=100.1, bar_close=100.8, atr=0.5, cfg=rc)
assert md.action == "partial_trail" and md.reason == "tp1", md
assert md.exit_qty == 50 and approx(md.new_stop, 100.0), md

# 3. post-TP1 (tp1_done, stop at BE 100.0) price ran to 101.5, ATR 0.5 →
#    trail up to 101.5 - 1.0×0.5 = 101.0 (ratchets above the BE stop)
md = evaluate_manage(_pos(stop=100.0, qty_remaining=50, tp1_done=True),
                     12, bar_high=101.6, bar_low=101.0, bar_close=101.5, atr=0.5, cfg=rc)
assert md.action == "trail_stop" and approx(md.new_stop, 101.0), md

# 4. post-TP1 trailed stop hit → exit_full "trail_exit" on the remainder
md = evaluate_manage(_pos(stop=101.0, qty_remaining=50, tp1_done=True),
                     15, bar_high=101.2, bar_low=100.95, bar_close=101.0, atr=0.5, cfg=rc)
assert md.action == "exit_full" and md.reason == "trail_exit" and md.exit_qty == 50, md

# 5. split time-stop (Fix #213):
#  5a. pre-TP1 dead trade hits the SHORT timer (30m) → recycle (time_stop exit)
md = evaluate_manage(_pos(), rc.pretp1_timeout_min, bar_high=100.2, bar_low=99.9, bar_close=100.0, atr=0.5, cfg=rc)
assert md.action == "exit_full" and md.reason == "time_stop", md
#  5b. pre-TP1 just BEFORE the short timer → still holding
md = evaluate_manage(_pos(), rc.pretp1_timeout_min - 1, bar_high=100.2, bar_low=99.9, bar_close=100.0, atr=0.5, cfg=rc)
assert md.action == "hold", md
#  5c. post-TP1 runner gets the LONG backstop — at 31m (past pre-timer) it still holds,
#      only exiting at time_stop_min (90m). Use a flat bar so no trail-up fires.
md = evaluate_manage(_pos(stop=100.0, qty_remaining=50, tp1_done=True),
                     rc.pretp1_timeout_min + 1, bar_high=100.05, bar_low=100.01,
                     bar_close=100.02, atr=0.0, cfg=rc)
assert md.action == "hold", f"post-TP1 runner should ride past the pre-TP1 timer: {md}"
md = evaluate_manage(_pos(stop=100.0, qty_remaining=50, tp1_done=True),
                     rc.time_stop_min, bar_high=100.05, bar_low=100.01,
                     bar_close=100.02, atr=0.0, cfg=rc)
assert md.action == "exit_full" and md.reason == "time_stop", f"runner backstop at {rc.time_stop_min}m: {md}"

# 6. pre-TP1 small profit, early → hold
md = evaluate_manage(_pos(), 4, bar_high=100.3, bar_low=99.9, bar_close=100.2, atr=0.5, cfg=rc)
assert md.action == "hold", md
print("[PASS] evaluate_manage runner capture (stop/tp1-partial/trail/trail-exit/time/hold)")


# ── live-config lock (2026-05-29) ────────────────────────────────────────────
# The blocks above test pure exit/entry LOGIC with controlled configs. This block
# verifies the AS-SHIPPED profile (ScalpConfig.from_settings) matches what the live
# engine actually trades — so the green checkmark describes the real system, not the
# dataclass defaults. If someone changes settings.py, this is the tripwire.
import config.settings as S
live = ScalpConfig.from_settings(S)
assert live.scratch_enabled is False, f"live scratch should be DISABLED, got {live.scratch_enabled}"
assert live.time_stop_min == S.SCALP_TIME_STOP_MIN, f"live time_stop {live.time_stop_min} != settings {S.SCALP_TIME_STOP_MIN}"
assert live.pretp1_timeout_min == S.SCALP_PRETP1_TIMEOUT_MIN, "live pre-TP1 timeout drift"
assert live.notional_inr == S.SCALP_NOTIONAL_INR, f"live notional {live.notional_inr} != settings {S.SCALP_NOTIONAL_INR}"
assert live.daily_loss_cap_inr == S.SCALP_DAILY_LOSS_CAP_INR, "live daily cap drift"
assert live.partial_trail_enabled == S.SCALP_PARTIAL_TRAIL_ENABLED, "live partial-trail flag drift"
assert live.tp1_fraction == S.SCALP_TP1_FRACTION, "live tp1_fraction drift"
# With scratch OFF, a flat bar past scratch_min must HOLD (not scratch) under the LIVE cfg.
ex = evaluate_exit(100.0, 99.6, 100.8, live.scratch_min + 1,
                   bar_high=100.2, bar_low=99.9, bar_close=100.0, cfg=live)
assert not ex.exit and ex.reason == "hold", f"live cfg should HOLD a flat bar (scratch off), got {ex}"
print(f"[PASS] live-config lock (scratch={live.scratch_enabled} "
      f"time_stop={live.time_stop_min}m notional=Rs{live.notional_inr:,.0f} "
      f"daily_cap=Rs{live.daily_loss_cap_inr:,.0f})")

print("=== ALL SCALP-ENGINE TESTS PASSED ===")
