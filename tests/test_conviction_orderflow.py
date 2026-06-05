"""Unit test for Fix #216 — conviction engine's order-flow override of the
frozen order-book gate. Pure logic with tiny stubs; no Kite.

    python tests/test_conviction_orderflow.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.conviction_engine import ConvictionEngine
from agents.fhh_break_detector import FirstHourState


class _MS:
    """Macro state stub → GREEN (so a clean candidate reaches the book gate)."""
    def get_state(self, now=None):
        class _S:
            state = "GREEN"
            reasoning = "test-green"
        return _S()


class _FHH:
    """FHH stub → NIFTY first-hour high cleanly broken, no whipsaw."""
    def get_state(self, sym, now=None):
        st = FirstHourState(symbol=sym)
        st.is_set = True
        st.high_broken = True
        st.low_broken = False
        return st


def _engine():
    return ConvictionEngine(_MS(), _FHH())


# A clean candidate that passes change_pct / HOD / spread, but has a SELL-HEAVY
# resting book (ratio ≈ 0.1 < 1.3).
QUOTE = {"change_pct": 2.0, "high": 100.0, "last_price": 99.5,
         "bid": 99.45, "ask": 99.50}
WEAK_BOOK = {"buy":  [{"quantity": 100}],
             "sell": [{"quantity": 1000}]}
STRONG_BOOK = {"buy":  [{"quantity": 1000}],
               "sell": [{"quantity": 100}]}

eng = _engine()

# 1. flow_ok=None (stream cold) + weak book → frozen gate kills it (as before)
r = eng.evaluate("AAA", None, QUOTE, order_book=WEAK_BOOK, flow_ok=None)
assert r.tier == "SKIP" and "weak_order_book" in r.reasoning, r
print("[PASS] cold stream + weak book → frozen gate skips (unchanged)")

# 2. flow_ok=True (live buyers lifting) + weak book → book gate BYPASSED → admits
r = eng.evaluate("AAA", None, QUOTE, order_book=WEAK_BOOK, flow_ok=True)
assert r.tier in ("S", "A", "B"), f"expected admit on live flow, got {r.tier}: {r.reasoning}"
print(f"[PASS] live flow OK + weak book → conviction ADMITS (tier {r.tier})")

# 3. flow_ok=False (live sellers in control) + strong book → dynamic VETO
r = eng.evaluate("AAA", None, QUOTE, order_book=STRONG_BOOK, flow_ok=False)
assert r.tier == "SKIP" and "orderflow" in r.reasoning, r
print("[PASS] live flow VETO + strong snapshot → conviction SKIPS (dynamic wins)")

print("=== ALL CONVICTION ORDER-FLOW TESTS PASSED ===")
