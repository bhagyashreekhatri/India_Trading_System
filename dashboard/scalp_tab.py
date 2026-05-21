"""
Dashboard Tab 5 — Scalp Engine (2026-05-21).

Renders today's aggressive-scalp activity from logs/scalp_trades.jsonl next to
the conviction P&L: realized P&L, trade count, hit-rate, daily-cap usage, open
scalp positions, and the closed-trade blotter. Read-only.
"""
import streamlit as st
import pandas as pd

from tools.scalp_ledger import today_summary
try:
    from config.settings import SCALP_MODE_ENABLED, SCALP_MAX_POSITIONS
except Exception:
    SCALP_MODE_ENABLED, SCALP_MAX_POSITIONS = False, 5


def render_scalp_tab():
    st.subheader("⚡ Scalp Engine")
    mode = "🟢 LIVE (paper)" if SCALP_MODE_ENABLED else "🟡 SHADOW (logging only)"
    st.caption(f"Mode: {mode}  ·  separate ledger from the conviction pipeline")

    s = today_summary()
    n        = s["n"]
    gross    = s["gross_pnl"]
    cap      = s["cap"]
    open_pos = s["open"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Today P&L", f"₹{gross:+,.0f}")
    c2.metric("Trades", f"{n}")
    c3.metric("Win / Loss", f"{s['wins']} / {s['losses']}")
    c4.metric("Hit-rate", f"{s['hit_rate']:.0f}%" if n else "—")
    cap_used = (abs(min(gross, 0)) / cap * 100) if cap else 0
    c5.metric("Daily-cap used", f"{cap_used:.0f}%",
              help=f"Loss cap ₹{cap:,.0f}; halts new scalps when hit")

    if s["cap_hit"]:
        st.error(f"🛑 Daily loss cap ₹{cap:,.0f} hit — new scalps halted for today.")

    if n:
        b1, b2 = st.columns(2)
        b1.metric("Best trade", f"₹{s['best']:+,.0f}")
        b2.metric("Worst trade", f"₹{s['worst']:+,.0f}")

    # ── Open scalp positions ──────────────────────────────────────────────────
    st.markdown(f"**Open scalp positions** ({len(open_pos)} / {SCALP_MAX_POSITIONS})")
    if open_pos:
        df = pd.DataFrame([{
            "Symbol": p.get("symbol", ""),
            "Entry":  p.get("entry", 0.0),
            "Qty":    p.get("qty", 0),
            "Stop":   p.get("stop", 0.0),
            "Target": p.get("target", 0.0),
            "RVOL":   p.get("rvol", ""),
            "Entered": str(p.get("ts", "")).split("T")[-1][:8],
        } for p in open_pos])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("None open right now.")

    # ── Closed scalp trades (today) ──────────────────────────────────────────
    st.markdown("**Today's closed scalps**")
    closed = s["closed"]
    if closed:
        df = pd.DataFrame([{
            "Time":   str(t.get("ts", "")).split("T")[-1][:8],
            "Symbol": t.get("symbol", ""),
            "Entry":  t.get("entry", 0.0),
            "Exit":   t.get("exit", 0.0),
            "Qty":    t.get("qty", 0),
            "Reason": t.get("reason", ""),
            "P&L ₹":  round(float(t.get("pnl_inr", 0.0)), 0),
        } for t in closed])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No closed scalps yet today.")
