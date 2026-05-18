"""
Shadow Activity Dashboard Tab — Phase 2.9.

Renders four panels showing all shadow-mode activity from today's session:

  1. 🔍 Discovery Admits        — top-mover scanner picks (from discovery_admits.jsonl)
  2. 🎯 Stock Decoupling        — would-admit longs on STRONG_RED days (decoupling_shadow.jsonl)
  3. 🔄 Mid-Trade Re-evaluation — TIGHTEN_TO_BE / CLOSE shadow events (reeval_shadow.jsonl)
  4. 📉 RVOL Ghost Rejections   — momentum setups rejected for RVOL < 2.0 (rvol_ghost.jsonl)

All four read append-only JSONL files. Empty files show a friendly placeholder.

The goal: a single page where you can scan "what did the agent NEARLY do today?"
without grepping journalctl.
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st


# ─── JSONL readers ────────────────────────────────────────────────────────────

def _read_jsonl(path: str, since_iso: str = "") -> list[dict]:
    """Read all JSONL records from `path`. Optionally filter to records with
    ts_iso >= since_iso (timestamp string prefix match works for ISO dates)."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if since_iso:
                ts = rec.get("ts_iso") or rec.get("ts") or ""
                if ts < since_iso:
                    continue
            out.append(rec)
    except Exception as e:
        st.warning(f"Could not read {path}: {e}")
    return out


def _today_prefix() -> str:
    """Return today's IST date as the YYYY-MM-DD prefix for filter."""
    return date.today().isoformat()


# ─── Discovery Admits panel ───────────────────────────────────────────────────

def _render_discovery(today_only: bool):
    st.subheader("🔍 Discovery Admits")
    since = _today_prefix() if today_only else ""
    records = _read_jsonl("discovery_admits.jsonl", since_iso=since)

    if not records:
        st.info(
            "No discovery admits recorded "
            + ("today" if today_only else "ever")
            + ". Engine is in shadow mode — admits appear here when a stock "
            "crosses ±2.5% on ≥1.5× volume with adequate liquidity."
        )
        return

    rows = []
    for r in records:
        rows.append({
            "Time":      r.get("ts", "")[:19].replace("T", " "),
            "Symbol":    r.get("symbol", ""),
            "%Chg":      f"{r.get('pct_change', 0):+.2f}%",
            "Vol×":      f"{r.get('volume_ratio', 0):.2f}",
            "Turnover":  f"₹{r.get('turnover_inr', 0)/1e7:.1f}cr",
            "Spread":    f"{r.get('spread_pct', 0):.3f}%",
            "Score":     f"{r.get('score', 0):.2f}",
            "Dir":       r.get("direction", ""),
            "Catalyst":  r.get("catalyst_type", "") or "—",
            "Headline":  (r.get("headline", "") or "")[:60],
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=400)
    st.caption(f"Total: {len(rows)} admit(s) "
               + ("today" if today_only else "across all sessions"))


# ─── Decoupling Shadow panel ──────────────────────────────────────────────────

def _render_decoupling(today_only: bool):
    st.subheader("🎯 Stock Decoupling (would-admit on macro RED)")
    since = _today_prefix() if today_only else ""
    records = _read_jsonl("decoupling_shadow.jsonl", since_iso=since)

    if not records:
        st.info(
            "No decoupling shadow events recorded "
            + ("today" if today_only else "ever")
            + ". Rule fires when a stock is +4%+ on >1.5× volume with HOD-proximity ≤0.5% "
            "AND sector index ≥ -1% AND stock-FHH clean — only on macro RED/STRONG_RED days."
        )
        return

    rows = []
    for r in records:
        rows.append({
            "Time":       r.get("ts_iso", "")[:19].replace("T", " "),
            "Symbol":     r.get("symbol", ""),
            "Marker":     r.get("marker", ""),
            "Macro":      r.get("macro_state", ""),
            "Stock %":    f"{r.get('stock_pct', 0):+.2f}%",
            "Vol×":       f"{r.get('volume_ratio', 0):.2f}",
            "Sector %":   f"{r.get('sector_pct', 0):+.2f}%",
            "Pull HOD%":  f"{r.get('pull_from_hod_pct', 0):.2f}%",
            "Reason":     r.get("reason", "")[:80],
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=300)
    st.caption(f"Total: {len(rows)} would-admit(s) "
               + ("today" if today_only else "across all sessions")
               + ". 'SHADOW' = rule fired but flag is OFF; 'ENABLED' = would have actually traded.")


# ─── Reeval Shadow panel ──────────────────────────────────────────────────────

def _render_reeval(today_only: bool):
    st.subheader("🔄 Mid-Trade Re-evaluation")
    since = _today_prefix() if today_only else ""
    records = _read_jsonl("reeval_shadow.jsonl", since_iso=since)

    if not records:
        st.info(
            "No re-eval shadow events recorded "
            + ("today" if today_only else "ever")
            + ". Rule fires every 5 min per OPEN position — when 2/3 thesis dimensions break "
            "(macro / VWAP / HOD-proximity) → TIGHTEN_TO_BE; 3/3 broken → CLOSE."
        )
        return

    rows = []
    for r in records:
        action = "TIGHTEN" if r.get("event_type") == "reeval_tighten" else "CLOSE"
        rows.append({
            "Time":       r.get("ts_iso", "")[:19].replace("T", " "),
            "Symbol":     r.get("symbol", ""),
            "Action":     action,
            "Marker":     r.get("marker", ""),
            "Macro":      r.get("macro_state", ""),
            "LTP":        f"{r.get('ltp', 0):.2f}",
            "VWAP":       f"{r.get('vwap', 0):.2f}",
            "Pull HOD%":  f"{r.get('pull_from_hod_pct', 0):.2f}%",
            "Broken":     str(r.get("broken_count", 0)) + "/3",
            "Dims":       ",".join(r.get("broken_dims", []) or []),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=300)
    st.caption(f"Total: {len(rows)} re-eval event(s) "
               + ("today" if today_only else "across all sessions"))


# ─── RVOL Ghost panel ─────────────────────────────────────────────────────────

def _render_rvol_ghost(today_only: bool):
    st.subheader("📉 RVOL Ghost Rejections")
    since = _today_prefix() if today_only else ""
    records = _read_jsonl("rvol_ghost.jsonl", since_iso=since)

    if not records:
        st.info(
            "No RVOL rejections recorded "
            + ("today" if today_only else "ever")
            + ". Records appear when the scorer rejects a momentum_breakout setup for "
            "RVOL < 2.0. Use these to backtest whether the 2.0 floor is correct: "
            "`python3 scripts/rvol_backtest.py`"
        )
        return

    rows = []
    bucket_counts = {"[0.5-1.0)": 0, "[1.0-1.5)": 0, "[1.5-1.7)": 0, "[1.7-2.0)": 0}
    for r in records:
        rvol = r.get("rvol", 0)
        # Bucket label
        for lo, hi, label in [(0.5, 1.0, "[0.5-1.0)"), (1.0, 1.5, "[1.0-1.5)"),
                              (1.5, 1.7, "[1.5-1.7)"), (1.7, 2.0, "[1.7-2.0)")]:
            if lo <= rvol < hi:
                bucket_counts[label] += 1
                break

        rows.append({
            "Time":        r.get("ts_iso", "")[:19].replace("T", " "),
            "Symbol":      r.get("symbol", ""),
            "RVOL":        f"{rvol:.2f}",
            "Entry":       f"{r.get('entry_price', 0):.2f}",
            "SL":          f"{r.get('stop_loss', 0):.2f}",
            "TP1":         f"{r.get('tp1_price', 0):.2f}",
            "Macro":       r.get("macro_state", ""),
            "Score":       f"{r.get('score', 0):.2f}",
            "Dir":         r.get("direction", ""),
        })
    df = pd.DataFrame(rows)

    # Bucket summary
    cols = st.columns(4)
    for i, (label, count) in enumerate(bucket_counts.items()):
        cols[i].metric(label, count)

    st.dataframe(df, use_container_width=True, hide_index=True, height=300)
    st.caption(f"Total: {len(rows)} RVOL rejection(s) "
               + ("today" if today_only else "across all sessions")
               + ". Run `python3 scripts/rvol_backtest.py` to compute would-be P&L per bucket.")


# ─── Main render ──────────────────────────────────────────────────────────────

def render_shadow_tab():
    st.markdown(
        "Shadow-mode activity for today. These features are wired into the "
        "agent but **do not trade yet** — they log what they WOULD have done so "
        "we can validate before flipping the live-trade flags."
    )

    today_only = st.checkbox(
        "Show today only", value=True,
        help="Uncheck to see admits/rejections across all sessions",
    )

    # File-existence summary at top
    files = {
        "discovery_admits.jsonl":   "Discovery admits",
        "decoupling_shadow.jsonl":  "Decoupling shadow",
        "reeval_shadow.jsonl":      "Re-eval shadow",
        "rvol_ghost.jsonl":         "RVOL ghost rejections",
    }
    status_cols = st.columns(4)
    for i, (path, label) in enumerate(files.items()):
        p = Path(path)
        if p.exists():
            line_count = sum(1 for _ in p.open()) if p.stat().st_size > 0 else 0
            status_cols[i].metric(label, line_count, help=f"Lines in {path}")
        else:
            status_cols[i].metric(label, "—", help=f"{path} does not exist yet")

    st.markdown("---")

    _render_discovery(today_only)
    st.markdown("---")
    _render_decoupling(today_only)
    st.markdown("---")
    _render_reeval(today_only)
    st.markdown("---")
    _render_rvol_ghost(today_only)
