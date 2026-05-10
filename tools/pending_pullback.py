"""
Phase D — Pending pullback retest state machine.

When a setup fires with a high score but proximity_failed (price has run
past the trigger), we DON'T chase. We mark the signal PENDING_RETEST,
then watch for the price to come back to the trigger ± tolerance within
a time window. If retest happens, fire entry at the retest. Real scalper
behaviour — wait for the pullback, don't chase the breakout.

State machine:
    (signal arrives, proximity_failed, drift ≤ max) → PENDING_RETEST
    PENDING_RETEST + price within ±tolerance of trigger → READY (fire entry)
    PENDING_RETEST + window_min elapsed                  → DEAD (timeout)
    PENDING_RETEST + drift > max_drift                   → DEAD (chased too far)
    PENDING_RETEST + ltp < SL                            → DEAD (broke down)

In-memory only for v1. Server restart loses pending entries — acceptable
because pending entries are < 10 min old and the next tick reseeds from
fresh setup detection. Logs every transition to a JSONL file for EOD
review and telemetry.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
import json
import os

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class PendingEntry:
    """One pending-retest entry, stored in registry by symbol."""
    symbol:           str
    setup_type:       str
    sector:           str
    direction:        str
    trigger_price:    float       # original signal entry trigger
    stop_loss:        float
    tp1_price:        float
    tp2_price:        float
    score:            float       # original computed score
    confluence_count: int
    added_at:         datetime
    reason:           str
    score_breakdown:  dict        # original breakdown to carry into entry
    state:            str = "PENDING_RETEST"
    retest_low:       float = 0.0


class PendingPullbackRegistry:
    """
    In-memory registry of pending-retest signals.

    Single instance owned by TradingCrew. Thread-safe for the single-threaded
    tick loop. Not safe for concurrent ticks (which we don't do).
    """

    def __init__(self,
                 window_min: int = 10,
                 tolerance_pct: float = 0.003,
                 max_drift_pct: float = 0.020,
                 log_path: Optional[str] = None):
        self._entries: dict[str, PendingEntry] = {}
        self.window_min = window_min
        self.tolerance_pct = tolerance_pct
        self.max_drift_pct = max_drift_pct
        self.log_path = log_path

        # Ensure log dir exists (best effort)
        if log_path:
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
            except Exception:
                pass

    # ── Add ────────────────────────────────────────────────────────────────
    def add(self, sym: str, signal: dict, score: float, reason: str) -> bool:
        """
        Add a proximity-failed signal to the pending registry.
        Returns True if added, False if symbol was already pending (newer
        wins — overwrite).
        """
        was_pending = sym in self._entries
        entry = PendingEntry(
            symbol=sym,
            setup_type=signal.get("setup_type", ""),
            sector=signal.get("sector", ""),
            direction=signal.get("direction", "long"),
            trigger_price=float(signal.get("entry_price") or 0),
            stop_loss=float(signal.get("stop_loss") or 0),
            tp1_price=float(signal.get("tp1_price") or 0),
            tp2_price=float(signal.get("tp2_price") or 0),
            score=float(score),
            confluence_count=int(signal.get("confluence_count", 1)),
            added_at=datetime.now(IST),
            reason=reason[:120],
            score_breakdown=signal.get("score_breakdown") or {},
        )
        self._entries[sym] = entry
        self._log_event("added" if not was_pending else "replaced", entry)
        return not was_pending

    # ── Evaluate ───────────────────────────────────────────────────────────
    def evaluate(self, ltp_map: dict[str, float]) -> list[PendingEntry]:
        """
        Check all pending entries against current LTPs. Returns READY
        entries (price has retested trigger ± tolerance). Removes DEAD
        entries from the registry.

        Caller is responsible for converting READY entries into scored
        signal dicts and routing them to the allocator.
        """
        now = datetime.now(IST)
        ready: list[PendingEntry] = []
        to_remove: list[str] = []

        for sym, entry in self._entries.items():
            ltp = ltp_map.get(sym)
            if ltp is None or ltp <= 0:
                continue                # no live price — leave entry in pending

            age_min = (now - entry.added_at).total_seconds() / 60.0

            # Track lowest seen since pending — useful telemetry
            if entry.retest_low == 0.0 or ltp < entry.retest_low:
                entry.retest_low = ltp

            # ── Dead conditions (any one ends the entry) ──────────────────

            # Time expired
            if age_min >= self.window_min:
                self._log_event("expired", entry, extra=f"age_min={age_min:.1f}")
                to_remove.append(sym)
                continue

            # Drifted too far past trigger (long-only logic for now)
            drift_pct = (ltp - entry.trigger_price) / max(entry.trigger_price, 1e-6)
            if drift_pct > self.max_drift_pct:
                self._log_event("drifted", entry, extra=f"drift_pct={drift_pct:.3f}")
                to_remove.append(sym)
                continue

            # Broke below stop loss before retest happened — invalidated
            if ltp < entry.stop_loss:
                self._log_event("broke_sl", entry, extra=f"ltp={ltp}")
                to_remove.append(sym)
                continue

            # ── Ready condition ────────────────────────────────────────────
            tolerance_band = entry.trigger_price * self.tolerance_pct
            if abs(ltp - entry.trigger_price) <= tolerance_band:
                entry.state = "READY"
                self._log_event("retested_ready", entry, extra=f"ltp={ltp}")
                ready.append(entry)
                to_remove.append(sym)

        for sym in to_remove:
            self._entries.pop(sym, None)

        return ready

    # ── Inspection ─────────────────────────────────────────────────────────
    def has(self, sym: str) -> bool:
        return sym in self._entries

    def count(self) -> int:
        return len(self._entries)

    def get_active(self) -> list[PendingEntry]:
        """Snapshot for dashboard / telemetry."""
        return list(self._entries.values())

    def clear(self) -> None:
        """Used at EOD or for emergency clear via operator."""
        self._entries.clear()

    # ── Logging ────────────────────────────────────────────────────────────
    def _log_event(self, action: str, entry: PendingEntry, extra: str = "") -> None:
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps({
                    "t":        datetime.now(IST).isoformat(timespec="seconds"),
                    "action":   action,
                    "sym":      entry.symbol,
                    "setup":    entry.setup_type,
                    "trigger":  entry.trigger_price,
                    "sl":       entry.stop_loss,
                    "score":    round(entry.score, 2),
                    "conf":     entry.confluence_count,
                    "extra":    extra,
                }) + "\n")
        except Exception:
            pass    # never fail the trading loop because logging broke


def ready_to_signal_dict(entry: PendingEntry) -> dict:
    """
    Convert a READY pending-entry into a scored-signal dict that
    `_allocate` already knows how to consume. The allocator's existing
    gates (kill switch, cooldown, position cap, sector cap, RAG veto,
    spread filter, live LTP refetch) all run unchanged on this.
    """
    return {
        "symbol":           entry.symbol,
        "setup_type":       entry.setup_type,
        "direction":        entry.direction,
        "sector":           entry.sector,
        "entry_price":      entry.trigger_price,
        "stop_loss":        entry.stop_loss,
        "tp1_price":        entry.tp1_price,
        "tp2_price":        entry.tp2_price,
        "final_score":      entry.score,
        "confluence_count": entry.confluence_count,
        "grade":            "A+" if entry.score >= 8 else "A",
        "confidence":       0.7,
        "reason":           f"PENDING_RETEST → {entry.reason[:80]}",
        "score_breakdown":  {**(entry.score_breakdown or {}), "pending_retest": True},
        "rs_delta":         0.0,
        "news_headline":    "",
        "_pending_retest":  True,    # marker for downstream telemetry / logs
    }
