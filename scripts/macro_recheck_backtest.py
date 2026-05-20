"""
Fix #205 — Recovery-unlock backtest.

Question this answers (the number to see BEFORE flipping MACRO_RECHECK_ENABLED=True):

    On RED / STRONG_RED locked days over the last N months, how often did NIFTY
    later RECLAIM-AND-HOLD (the recovery-unlock signal), and of those days, how
    often did the index actually close green / above the unlock level?

If unlock-fired days close green much more often than RED days in general, the
signal is selecting recovery days (good — flip it live). If they close green at
roughly the same rate as all RED days, the unlock is just whipsaw noise (keep it
in shadow / rethink).

Run where Kite Connect works (server or Mac), AFTER the daily token refresh:
    python kite_login.py            # refresh token if needed
    python scripts/macro_recheck_backtest.py
    python scripts/macro_recheck_backtest.py --months 30 --confirm-bars 3

Read-only: fetches historical candles, computes, prints. Places no orders.
"""
from __future__ import annotations
import os
import sys
import time
import argparse
import datetime as dt
from collections import Counter

# Keep thresholds in lockstep with production.
from config.settings import (
    MACRO_STRONG_GREEN_THRESHOLD, MACRO_GREEN_THRESHOLD,
    MACRO_RED_THRESHOLD, MACRO_STRONG_RED_THRESHOLD,
    MACRO_RECHECK_CONFIRM_BARS,
)

NIFTY_TOKEN = 256265
LOCK_WIN_START = dt.time(10, 9, 30)   # mirror market_state._is_1015_bar window
LOCK_WIN_END   = dt.time(10, 15, 30)

_RANK = {"STRONG_RED": 0, "RED": 1, "YELLOW": 2, "GREEN": 3, "STRONG_GREEN": 4}


def _classify(dist_pct: float) -> str:
    if dist_pct > MACRO_STRONG_GREEN_THRESHOLD:
        return "STRONG_GREEN"
    if dist_pct > MACRO_GREEN_THRESHOLD:
        return "GREEN"
    if dist_pct < MACRO_STRONG_RED_THRESHOLD:
        return "STRONG_RED"
    if dist_pct < MACRO_RED_THRESHOLD:
        return "RED"
    return "YELLOW"


def _held_state(dists: list[float], n: int) -> str | None:
    """Best state whose threshold ALL of the last `n` closes cleared (min-of-N)."""
    if len(dists) < n:
        return None
    m = min(dists[-n:])
    if m > MACRO_STRONG_GREEN_THRESHOLD:
        return "STRONG_GREEN"
    if m > MACRO_GREEN_THRESHOLD:
        return "GREEN"
    if m > MACRO_RED_THRESHOLD:
        return "YELLOW"
    return None


def _load_env() -> dict:
    env = {}
    for p in ("config/.env", ".env"):
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k] = v.strip().strip('"').strip("'")
            break
    return env


def _kite():
    from kiteconnect import KiteConnect  # imported lazily — needs the SDK env
    env = _load_env()
    k = KiteConnect(api_key=env["KITE_API_KEY"])
    k.set_access_token(env["KITE_ACCESS_TOKEN"])
    return k


def _fetch_5min(kite, start: dt.date, end: dt.date) -> list[dict]:
    """Fetch 5-min candles in <=90-day chunks (Kite intraday cap is 100 days)."""
    out, cur = [], start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=90), end)
        frm = dt.datetime.combine(cur, dt.time(9, 0))
        to  = dt.datetime.combine(chunk_end, dt.time(15, 45))
        for attempt in range(3):
            try:
                out += kite.historical_data(NIFTY_TOKEN, frm, to, "5minute")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ! 5min chunk {cur}..{chunk_end} failed: {e}")
                time.sleep(1.5 * (attempt + 1))
        cur = chunk_end + dt.timedelta(days=1)
        time.sleep(0.4)
    return out


def _fetch_daily(kite, start: dt.date, end: dt.date) -> dict:
    frm = dt.datetime.combine(start - dt.timedelta(days=7), dt.time(9, 0))
    to  = dt.datetime.combine(end, dt.time(15, 45))
    rows = kite.historical_data(NIFTY_TOKEN, frm, to, "day")
    return {r["date"].date(): float(r["close"]) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=30)
    ap.add_argument("--confirm-bars", type=int, default=MACRO_RECHECK_CONFIRM_BARS)
    args = ap.parse_args()
    n_confirm = args.confirm_bars

    end = dt.date.today()
    start = end - dt.timedelta(days=int(args.months * 30.5))
    print(f"Recovery-unlock backtest  |  {start} → {end}  "
          f"({args.months} months)  confirm_bars={n_confirm}")
    print("Fetching NIFTY daily + 5-min candles via Kite ...")

    kite = _kite()
    daily = _fetch_daily(kite, start, end)
    candles = _fetch_5min(kite, start, end)
    print(f"  daily closes: {len(daily)}   5-min bars: {len(candles)}")

    # Bucket 5-min bars by trading date.
    by_day: dict[dt.date, list] = {}
    for c in candles:
        by_day.setdefault(c["date"].date(), []).append(c)

    sorted_days = sorted(by_day.keys())
    prev_close_map = {}
    daily_dates = sorted(daily.keys())
    for d in sorted_days:
        prior = [x for x in daily_dates if x < d]
        prev_close_map[d] = daily.get(prior[-1]) if prior else None

    # Per-day evaluation.
    red_days = []         # (date, lock_state, unlock_state_or_None, close_dist_pct)
    for d in sorted_days:
        prev_close = prev_close_map.get(d)
        if not prev_close:
            continue
        bars = sorted(by_day[d], key=lambda x: x["date"])
        # 10:15 lock bar — latest bar in the [10:09:30, 10:15:30] window.
        lock_bars = [b for b in bars if LOCK_WIN_START <= b["date"].time() <= LOCK_WIN_END]
        if not lock_bars:
            continue
        lock_close = float(lock_bars[-1]["close"])
        lock_dist = 100.0 * (lock_close - prev_close) / prev_close
        lock_state = _classify(lock_dist)
        if lock_state not in ("RED", "STRONG_RED"):
            continue  # only the days the unlock could ever act on

        # Post-lock reclaim scan (mirror _held_state_from_candles per bar).
        post = [b for b in bars if b["date"].time() > dt.time(10, 15)]
        dists, best_unlock = [], None
        for b in post:
            dists.append(100.0 * (float(b["close"]) - prev_close) / prev_close)
            hs = _held_state(dists, n_confirm)
            if hs and (best_unlock is None or _RANK[hs] > _RANK[best_unlock]):
                best_unlock = hs

        close_px = daily.get(d, float(bars[-1]["close"]))
        close_dist = 100.0 * (close_px - prev_close) / prev_close
        red_days.append((d, lock_state, best_unlock, close_dist))

    # ── Aggregate ────────────────────────────────────────────────────────────
    n_red = len(red_days)
    if n_red == 0:
        print("No RED/STRONG_RED locked days in window — nothing to evaluate.")
        return

    unlocked = [r for r in red_days if r[2] is not None]
    not_unlocked = [r for r in red_days if r[2] is None]

    def pct_green(rows):
        if not rows:
            return float("nan")
        return 100.0 * sum(1 for r in rows if r[3] > 0) / len(rows)

    def avg_close(rows):
        return (sum(r[3] for r in rows) / len(rows)) if rows else float("nan")

    print("\n" + "=" * 64)
    print("RESULTS — RED / STRONG_RED locked days")
    print("=" * 64)
    print(f"Total RED/STRONG_RED days        : {n_red}")
    print(f"  ...where unlock FIRED          : {len(unlocked)} "
          f"({100.0*len(unlocked)/n_red:.0f}%)")
    print(f"  ...where it did NOT            : {len(not_unlocked)}")
    print("-" * 64)
    print(f"Closed GREEN | unlock fired      : {pct_green(unlocked):.0f}%   "
          f"(avg close {avg_close(unlocked):+.2f}%)")
    print(f"Closed GREEN | unlock did NOT    : {pct_green(not_unlocked):.0f}%   "
          f"(avg close {avg_close(not_unlocked):+.2f}%)")
    print(f"Closed GREEN | ALL red days      : {pct_green(red_days):.0f}%   "
          f"(avg close {avg_close(red_days):+.2f}%)")
    print("-" * 64)
    by_level = Counter(r[2] for r in unlocked)
    print("Unlock level reached (fired days):",
          ", ".join(f"{k}={v}" for k, v in sorted(by_level.items(),
                    key=lambda kv: _RANK[kv[0]])) or "none")
    print("=" * 64)
    edge = pct_green(unlocked) - pct_green(red_days)
    print(f"\nVERDICT: unlock-fired days close green {edge:+.0f} pts vs the RED-day "
          f"base rate.")
    print("  > +15 pts and a healthy sample (n>30): strong case to flip LIVE.")
    print("  ~  0 pts: the signal is whipsaw — keep MACRO_RECHECK_ENABLED=False.")


if __name__ == "__main__":
    sys.exit(main())
