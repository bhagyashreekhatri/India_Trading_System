"""
Scalp ledger reader (2026-05-21).

Shared parsing for logs/scalp_trades.jsonl, used by both the dashboard Scalp
tab and the EOD Telegram summary so they never drift. The ledger is written by
TradingCrew._log_scalp with two event shapes:

  entry: {ts, event:"entry", symbol, entry, qty, stop, target, atr, rvol, reason, live}
  exit : {ts, event:"exit",  symbol, reason, entry, exit, qty, pnl_inr, day_pnl_inr, live}

An exit event is a COMPLETE closed trade on its own (it carries entry, exit, qty
and pnl). Entry events are only needed to reconstruct still-open positions.
"""
from __future__ import annotations
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from config.settings import TIMEZONE, SCALP_DAILY_LOSS_CAP_INR
except Exception:
    TIMEZONE = "Asia/Kolkata"
    SCALP_DAILY_LOSS_CAP_INR = 30_000

IST = ZoneInfo(TIMEZONE)

LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "scalp_trades.jsonl",
)


def _today_iso() -> str:
    return datetime.now(IST).date().isoformat()


def load_records(day: str | None = None, path: str | None = None) -> list[dict]:
    """All ledger records for `day` (default today), in file order."""
    day = day or _today_iso()
    path = path or LEDGER_PATH
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if str(r.get("ts", "")).split("T")[0] == day:
                    out.append(r)
    except Exception:
        pass
    return out


def closed_trades(records: list[dict]) -> list[dict]:
    """Each exit event is one complete closed scalp trade."""
    return [r for r in records if r.get("event") == "exit"]


def open_positions(records: list[dict]) -> list[dict]:
    """FIFO-match entries to exits per symbol; leftover entries are still open."""
    queues: dict[str, list[dict]] = {}
    for r in records:
        sym = r.get("symbol", "")
        if r.get("event") == "entry":
            queues.setdefault(sym, []).append(r)
        elif r.get("event") == "exit":
            q = queues.get(sym)
            if q:
                q.pop(0)
    out: list[dict] = []
    for q in queues.values():
        out.extend(q)
    return out


def summarize(closed: list[dict]) -> dict:
    """Headline stats over a list of closed trades."""
    n = len(closed)
    pnls = [float(t.get("pnl_inr", 0.0)) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross = sum(pnls)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate": (100.0 * len(wins) / n) if n else 0.0,
        "gross_pnl": gross,
        "best": max(pnls) if pnls else 0.0,
        "worst": min(pnls) if pnls else 0.0,
        "cap": float(SCALP_DAILY_LOSS_CAP_INR),
        "cap_hit": gross <= -abs(float(SCALP_DAILY_LOSS_CAP_INR)),
    }


def today_summary(day: str | None = None, path: str | None = None) -> dict:
    """Convenience: load + summarize + attach open positions for `day`."""
    recs = load_records(day=day, path=path)
    closed = closed_trades(recs)
    s = summarize(closed)
    s["closed"] = closed
    s["open"] = open_positions(recs)
    return s
