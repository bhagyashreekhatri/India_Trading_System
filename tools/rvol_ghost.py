"""
RVOL Ghost-Trade Telemetry — Phase 2.8.

The scorer's RVOL ≥ 2.0 floor (Fix #22 / Fix #56) is the single most prolific
trade rejection reason in the production logs:

  2026-05-12:  ONGC RVOL 1.93 → reject (closed +5.93%  — WOULD-HAVE-WON)
  2026-05-12:  ABB  RVOL 1.96 → reject (closed -0.92%  — WOULD-HAVE-LOST)
  2026-05-18:  NMDC RVOL 0.84 → reject (— way below threshold)
  2026-05-18:  SHREECEM RVOL 0.33 → reject (— way below threshold)

Anecdotally the 2.0 floor saves more losses than it misses wins, BUT we don't
have a structured dataset to make a quantitative call. This module fixes that
by recording every RVOL rejection to a JSONL audit file. A separate offline
analyzer (`scripts/rvol_backtest.py`) fetches 5-min candles for each rejection
+ computes the would-be P&L, bucketed by RVOL.

After ~30 days of data, we can confidently decide: keep 2.0, lower to 1.5, or
make it dynamic per regime.

Three Laws compliance:
  - Records facts only — no thresholds, no hardcoded outcomes
  - Generic — works on any symbol
  - Failure is non-fatal (best-effort writes; never breaks rejection flow)
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
import json
import os

DEFAULT_GHOST_PATH = "rvol_ghost.jsonl"


@dataclass
class GhostRecord:
    """One RVOL-rejection event. Schema is stable — analyzers read this."""
    ts_iso:       str                 # ISO timestamp of rejection (IST)
    symbol:       str
    rvol:         float               # the measured ratio, e.g. 1.93
    rvol_floor:   float               # threshold that rejected, e.g. 2.0
    entry_price:  float               # would-be entry (signal's trigger price)
    stop_loss:    float               # would-be SL
    tp1_price:    float               # would-be TP1
    tp2_price:    float               # would-be TP2 (if known, else 0)
    direction:    str                 # "long" or "short"
    setup_type:   str                 # always "momentum_breakout" for now
    macro_state:  str                 # "STRONG_GREEN" / "GREEN" / etc — context
    score:        float               # the scorer's final_score (telemetry only)


def record_rejection(
    symbol:       str,
    rvol:         float,
    rvol_floor:   float,
    entry_price:  float,
    stop_loss:    float,
    tp1_price:    float,
    tp2_price:    float = 0.0,
    direction:    str = "long",
    setup_type:   str = "momentum_breakout",
    macro_state:  str = "",
    score:        float = 0.0,
    path:         str = DEFAULT_GHOST_PATH,
    now:          Optional[datetime] = None,
) -> None:
    """
    Append one ghost-trade record to the JSONL audit log.

    Safe to call from the scorer's rejection branch — wraps everything in
    try/except so a disk-full / permission error never breaks the scan.
    """
    try:
        if now is None:
            ist = ZoneInfo("Asia/Kolkata")
            now = datetime.now(ist)

        rec = GhostRecord(
            ts_iso=now.isoformat(),
            symbol=symbol,
            rvol=round(float(rvol), 3),
            rvol_floor=round(float(rvol_floor), 2),
            entry_price=round(float(entry_price), 2),
            stop_loss=round(float(stop_loss), 2),
            tp1_price=round(float(tp1_price), 2),
            tp2_price=round(float(tp2_price), 2),
            direction=direction,
            setup_type=setup_type,
            macro_state=macro_state,
            score=round(float(score), 2),
        )
        with open(path, "a") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")
    except Exception as e:
        # Never break the scan on a logging failure. Print once to journalctl
        # so we know to look at disk space / permissions.
        print(f"[RvolGhost] record write failed (non-fatal): {e}")


def read_all_records(path: str = DEFAULT_GHOST_PATH) -> list[dict]:
    """Read the full ghost log for offline analysis."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue   # skip malformed lines silently
    return out
