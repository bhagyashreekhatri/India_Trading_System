"""
Shadow Event Audit Logger — Phase 2.9.

Single-purpose helper to write structured JSONL audit records for
shadow-mode events. Used by:

  - agents/crew.py  — Reeval TIGHTEN-SHADOW / CLOSE-SHADOW events
  - agents/conviction_engine.py — Decoupling ADMIT-SHADOW events

The dashboard/shadow_tab.py reads these JSONLs alongside the existing
discovery_admits.jsonl and rvol_ghost.jsonl to render the full
shadow-activity panel.

Design rules:
  - Best-effort writes — never break the caller on I/O failure
  - Schema is just `event_type` + arbitrary `data` dict — flexible
  - Append-only — never modify past records
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
import json


def record_shadow_event(
    event_type:  str,
    data:        dict,
    path:        str,
    now:         Optional[datetime] = None,
) -> None:
    """
    Append one shadow-event record to a JSONL file.

    Args:
        event_type: short tag like "reeval_tighten" / "reeval_close" /
                    "decoupling_admit" / etc.
        data:       arbitrary dict of event-specific fields
        path:       JSONL file path (e.g. "reeval_shadow.jsonl")
        now:        timestamp; defaults to datetime.now(IST)

    Failure is silently swallowed (printed to stdout once) — never raises.
    """
    try:
        if now is None:
            ist = ZoneInfo("Asia/Kolkata")
            now = datetime.now(ist)
        rec = {
            "ts_iso":     now.isoformat(),
            "event_type": event_type,
            **data,
        }
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[ShadowLog] write failed for {path} (non-fatal): {e}")
