"""
Order-flow metrics — the dynamic "scalper brain" math (2026-05-21).

This is the PURE, testable core of the dynamic order-book reading. It takes a
rolling buffer of live tick snapshots (fed by data/orderflow_stream.py from the
Kite WebSocket) and answers the question a human scalper actually asks:

    "Is the book IMPROVING and are buyers LIFTING — or is this a seller wall
     I'd get trapped behind?"

It replaces the old single frozen 5-level ratio (≥1.3) with a read of MOTION
over a short window:

  book_pressure   — current top-5 bid/ask quantity ratio (the old frozen number)
  avg_pressure    — mean pressure across the window (smooths spoof flicker)
  book_trend      — is pressure rising (buyers building / sellers leaving) or
                    falling? (latest-vs-earliest, fractional)
  lift_ratio      — of the volume traded in the window, what fraction printed on
                    UPticks vs downticks → buyers-aggressive proxy (no aggressor
                    tag on NSE equity, so we infer from price direction × volume)
  wall_absorption — is the best-ask quantity SHRINKING while price holds/rises?
                    (buyers eating the offer — the classic absorption tell)
  price_velocity  — fractional price move across the window

No Kite, no I/O — feed it Snapshots, get a FlowState. Fully unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Snapshot:
    """One tick of state captured from the WebSocket 'full' mode."""
    ts:        float   # epoch seconds (monotonic-ish; receipt time)
    ltp:       float
    cum_vol:   float   # cumulative day volume (for tape delta)
    bid5:      float   # sum of top-5 bid quantities
    ask5:      float   # sum of top-5 ask quantities
    best_bid_qty: float = 0.0
    best_ask_qty: float = 0.0


@dataclass
class FlowState:
    fresh:           bool    # enough recent samples to trust the read
    n:               int
    book_pressure:   float   # latest bid5/ask5
    avg_pressure:    float   # mean bid5/ask5 over window
    book_trend:      float   # (latest_pressure - earliest_pressure) / earliest
    lift_ratio:      float   # up_vol / (up_vol + down_vol), 0.5 = balanced
    wall_absorption: bool    # best-ask shrinking while price not falling
    price_velocity:  float   # (ltp_last - ltp_first) / ltp_first


def _ratio(bid: float, ask: float) -> float:
    if ask <= 0:
        return 99.0 if bid > 0 else 1.0
    return bid / ask


def compute_flow(samples: list[Snapshot], window_sec: float = 20.0,
                 min_samples: int = 3) -> FlowState:
    """Compute the dynamic flow read from the recent snapshot buffer.

    Only the last `window_sec` of samples are used. Needs `min_samples` within
    the window to be considered `fresh`; otherwise the caller should fall back
    to the frozen snapshot gate."""
    if not samples:
        return FlowState(False, 0, 1.0, 1.0, 0.0, 0.5, False, 0.0)

    latest_ts = samples[-1].ts
    win = [s for s in samples if latest_ts - s.ts <= window_sec]
    if len(win) < 2:
        # not enough motion to read — report the single frozen ratio, not fresh
        s = samples[-1]
        return FlowState(False, len(win), _ratio(s.bid5, s.ask5),
                         _ratio(s.bid5, s.ask5), 0.0, 0.5, False, 0.0)

    first, last = win[0], win[-1]
    pressures = [_ratio(s.bid5, s.ask5) for s in win]
    book_pressure = pressures[-1]
    avg_pressure = sum(pressures) / len(pressures)
    p0 = pressures[0] if pressures[0] > 0 else 1e-9
    book_trend = (pressures[-1] - pressures[0]) / p0

    # Tape aggression: attribute each volume delta to up/down tick direction.
    up_vol = down_vol = 0.0
    for a, b in zip(win[:-1], win[1:]):
        dv = b.cum_vol - a.cum_vol
        if dv <= 0:
            continue
        if b.ltp > a.ltp:
            up_vol += dv
        elif b.ltp < a.ltp:
            down_vol += dv
        else:
            up_vol += dv / 2.0
            down_vol += dv / 2.0
    traded = up_vol + down_vol
    lift_ratio = (up_vol / traded) if traded > 0 else 0.5

    # Wall absorption: best-ask qty shrinking while price not falling.
    wall_absorption = (last.best_ask_qty < first.best_ask_qty * 0.8
                       and last.ltp >= first.ltp)

    price_velocity = ((last.ltp - first.ltp) / first.ltp) if first.ltp > 0 else 0.0

    return FlowState(
        fresh=len(win) >= min_samples,
        n=len(win),
        book_pressure=book_pressure,
        avg_pressure=avg_pressure,
        book_trend=book_trend,
        lift_ratio=lift_ratio,
        wall_absorption=wall_absorption,
        price_velocity=price_velocity,
    )


def supportive(
    flow:          FlowState,
    min_pressure:  float = 1.0,
    min_lift:      float = 0.55,
    min_trend:     float = 0.10,
) -> tuple[bool, str]:
    """The human read: are buyers in control RIGHT NOW?

    Returns (ok, reason). A book is supportive if ANY of:
      • buyers already dominate the resting book (pressure ≥ min_pressure), OR
      • the book is IMPROVING (trend up) AND buyers are lifting (lift ≥ min_lift), OR
      • buyers are absorbing the offer wall AND lifting.
    This lets us take a sell-heavy RESTING book when the FLOW says buyers are
    eating it — exactly the trade the frozen 1.3 gate threw away (e.g. ALKEM).
    """
    if not flow.fresh:
        return False, "stream_not_warm"
    if flow.book_pressure >= min_pressure:
        return True, f"buyers_dominate_{flow.book_pressure:.2f}"
    if flow.book_trend >= min_trend and flow.lift_ratio >= min_lift:
        return True, (f"book_improving_trend{flow.book_trend:+.0%}_"
                      f"lift{flow.lift_ratio:.2f}")
    if flow.wall_absorption and flow.lift_ratio >= 0.50:
        return True, f"wall_absorbed_lift{flow.lift_ratio:.2f}"
    return False, (f"sellers_in_control_p{flow.book_pressure:.2f}_"
                   f"trend{flow.book_trend:+.0%}_lift{flow.lift_ratio:.2f}")
