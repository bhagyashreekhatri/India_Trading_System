"""
Tick-size helpers for NSE equities.

NSE equities trade in ₹0.05 ticks. Live orders with non-tick prices reject.
Use _round_to_tick for nominal rounding; _round_down/_up for direction-aware
stop / target placement (always conservative — never widen risk).

Extracted from the old scoring/engine.py during the Phase 0 rebuild
(2026-05-11). These are infrastructure, kept across the score-system deletion.
"""
from math import floor, ceil

_DEFAULT_TICK = 0.05


def _round_to_tick(price: float, tick: float = _DEFAULT_TICK) -> float:
    """Round to nearest valid tick. For entry prices and similar."""
    if price <= 0 or tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 2)


def _round_down_tick(price: float, tick: float = _DEFAULT_TICK) -> float:
    """Round DOWN to a valid tick. Use for LONG stop loss (gives the stop
    breathing room — never tighter than intended)."""
    if price <= 0 or tick <= 0:
        return round(price, 2)
    return round(floor(price / tick) * tick, 2)


def _round_up_tick(price: float, tick: float = _DEFAULT_TICK) -> float:
    """Round UP to a valid tick. Use for LONG entry / TP (asks for slightly
    more, never less)."""
    if price <= 0 or tick <= 0:
        return round(price, 2)
    return round(ceil(price / tick) * tick, 2)
