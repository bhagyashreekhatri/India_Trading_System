"""Unit tests for tools/orderflow_metrics.py — the dynamic scalper brain.

    python tests/test_orderflow_metrics.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.orderflow_metrics import Snapshot, compute_flow, supportive


def approx(a, b, tol=0.02):
    return abs(a - b) <= tol


# ── freshness / fallback ─────────────────────────────────────────────────────
f = compute_flow([])
assert not f.fresh and supportive(f)[0] is False
f = compute_flow([Snapshot(0, 100, 1000, 500, 500)])
assert not f.fresh, "single sample must not be fresh"
ok, why = supportive(f)
assert ok is False and why == "stream_not_warm"
print("[PASS] empty / single-sample → not fresh, falls back")


# ── improving book + buyers lifting (sell-heavy RESTING book, but flow bullish)
# pressure climbs 0.60→0.95 (still <1.0), every delta on an uptick. This is the
# ALKEM-type trade the frozen 1.3 gate threw away — flow says buyers are eating it.
improving = [
    Snapshot(0,  100.0, 1000, 600, 1000),
    Snapshot(5,  100.2, 1300, 700, 1000),
    Snapshot(10, 100.5, 1700, 850, 1000),
    Snapshot(15, 100.8, 2200, 950, 1000),
]
f = compute_flow(improving)
assert f.fresh and f.n == 4
assert f.book_pressure < 1.0, "resting book still sell-leaning"
assert f.book_trend > 0.1, f"book should be improving, got {f.book_trend}"
assert approx(f.lift_ratio, 1.0), f"all upticks → lift≈1.0, got {f.lift_ratio}"
ok, why = supportive(f)
assert ok is True and "book_improving" in why, why
print(f"[PASS] improving book + lifting → ENTER ({why})")


# ── seller wall, price bleeding, sellers hitting → blocked ───────────────────
falling = [
    Snapshot(0,  100.0, 1000, 400, 1200),
    Snapshot(5,   99.8, 1400, 380, 1300),
    Snapshot(10,  99.5, 1900, 350, 1400),
    Snapshot(15,  99.3, 2300, 300, 1500),
]
f = compute_flow(falling)
assert f.fresh
assert f.book_pressure < 0.5 and f.book_trend < 0
assert approx(f.lift_ratio, 0.0), f"all downticks → lift≈0, got {f.lift_ratio}"
ok, why = supportive(f)
assert ok is False and "sellers_in_control" in why, why
print(f"[PASS] seller wall + bleeding → SKIP ({why})")


# ── buyers already dominate the resting book → ENTER (frozen-style) ──────────
strong = [
    Snapshot(0,  50.0, 1000, 2000, 800),
    Snapshot(5,  50.1, 1100, 2100, 800),
    Snapshot(10, 50.2, 1250, 2200, 800),
]
f = compute_flow(strong)
ok, why = supportive(f)
assert ok is True and "buyers_dominate" in why, why
print(f"[PASS] buyers dominate resting book → ENTER ({why})")


# ── wall absorption: best-ask qty collapsing while price holds/rises ─────────
absorb = [
    Snapshot(0,  100.0, 1000, 500, 2000, best_ask_qty=5000),
    Snapshot(5,  100.0, 1200, 500, 1500, best_ask_qty=3000),
    Snapshot(10, 100.1, 1500, 500, 1000, best_ask_qty=1500),
    Snapshot(15, 100.2, 1900, 500,  800, best_ask_qty=800),
]
f = compute_flow(absorb)
assert f.wall_absorption is True, "best-ask collapsing while price up = absorption"
ok, why = supportive(f)
assert ok is True, why
print(f"[PASS] wall absorption → ENTER ({why})")


# ── lift_ratio arithmetic check (mixed up/down volume) ───────────────────────
mixed = [
    Snapshot(0, 100.0, 1000, 500, 500),
    Snapshot(5, 100.2, 1300, 500, 500),   # +300 up
    Snapshot(10, 100.0, 1500, 500, 500),  # +200 down
    Snapshot(15, 100.1, 1600, 500, 500),  # +100 up
]
f = compute_flow(mixed)
# up = 300 + 100 = 400 ; down = 200 ; lift = 400/600 = 0.667
assert approx(f.lift_ratio, 0.667), f"lift math, got {f.lift_ratio}"
print(f"[PASS] lift_ratio arithmetic ({f.lift_ratio:.3f})")


# ── window trimming: stale samples outside window dropped ─────────────────────
stale = [Snapshot(0, 100, 1000, 100, 900)] + [
    Snapshot(100 + i*5, 100 + i*0.1, 2000 + i*300, 900, 800) for i in range(4)
]
f = compute_flow(stale, window_sec=20)
assert f.n == 4, f"old sample should be trimmed, n={f.n}"
print("[PASS] window trimming")

print("=== ALL ORDER-FLOW METRIC TESTS PASSED ===")
