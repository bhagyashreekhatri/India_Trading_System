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
    size_position, daily_cap_hit,
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

# scratch — held past scratch_min, flat (not > +0.1%)
ex = evaluate_exit(entry, stop, tgt, cfg.scratch_min, bar_high=100.2, bar_low=99.9, bar_close=100.0, cfg=cfg)
assert ex.exit and ex.reason == "scratch", ex

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

print("=== ALL SCALP-ENGINE TESTS PASSED ===")
