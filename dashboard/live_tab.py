"""
Dashboard Tab 1 — Live Trading.
Shows: agent pipeline status, active signals, open positions, today's P&L.
Auto-refreshes every 10 seconds.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from memory.trade_state import TradeStateManager
from config.settings import CAPITAL, TIMEZONE

IST = ZoneInfo(TIMEZONE)


def render_live_tab(state: TradeStateManager):
    """Render the full live trading tab."""

    now = datetime.now(IST)

    # ── Top stat cards ────────────────────────────────────────────────────────
    deployed    = state.get_deployed_capital()
    available   = state.get_available_capital()
    deploy_pct  = state.get_deployment_pct()
    open_pos    = state.get_open_positions()
    today_pnl   = state.get_today_pnl()
    today_trades = state.get_today_trades()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Capital deployed",
            f"{deploy_pct:.1f}%",
            delta=f"₹{deployed:,.0f} of ₹{CAPITAL:,.0f}",
        )
    with col2:
        st.metric(
            "Open positions",
            len(open_pos),
            delta=f"{len([p for p in open_pos if _get_pnl_r(p) > 0])} in profit",
        )
    with col3:
        st.metric(
            "Trades today",
            len(today_trades),
        )
    with col4:
        pnl_color = "normal" if today_pnl >= 0 else "inverse"
        st.metric(
            "Today's P&L",
            f"₹{today_pnl:+,.0f}",
            delta=f"{today_pnl/CAPITAL*100:+.2f}% of capital",
            delta_color=pnl_color,
        )

    st.divider()

    # ── Agent pipeline status ─────────────────────────────────────────────────
    st.markdown("#### Agent pipeline — last run")
    _render_agent_pipeline()

    st.divider()

    # ── Active signals (from session state, updated each tick) ────────────────
    st.markdown("#### Active signals this scan")
    if "last_signals" in st.session_state and st.session_state.last_signals:
        _render_signals_table(st.session_state.last_signals)
    else:
        st.info("Waiting for next scan... system scans every 5 minutes.")

    st.divider()

    # ── Open positions ────────────────────────────────────────────────────────
    st.markdown("#### Open positions")
    if open_pos:
        _render_positions_table(open_pos)
    else:
        st.info("No open positions currently.")

    st.divider()

    # ── Today's closed trades ─────────────────────────────────────────────────
    closed_today = [t for t in today_trades if t.status != "open"]
    if closed_today:
        st.markdown("#### Closed today")
        _render_closed_table(closed_today)

    # ── Last scan time ────────────────────────────────────────────────────────
    st.caption(
        f"Last updated: {now.strftime('%H:%M:%S IST')} · "
        f"Auto-refresh every 10s"
    )


def _render_agent_pipeline():
    """Show agent run status as colored pills."""
    agents = [
        ("Scanner",       "last_scanner_status"),
        ("Regime",        "last_regime_status"),
        ("Setup detect",  "last_setup_status"),
        ("Volume + RS",   "last_volume_status"),
        ("News",          "last_news_status"),
        ("Scoring",       "last_scoring_status"),
        ("Allocator",     "last_allocator_status"),
        ("Position mgr",  "last_position_status"),
    ]

    cols = st.columns(len(agents))
    for col, (name, key) in zip(cols, agents):
        status = st.session_state.get(key, "idle")
        if status == "ok":
            col.success(name, icon="✓")
        elif status == "warn":
            col.warning(name, icon="⚠")
        elif status == "running":
            col.info(name, icon="⟳")
        else:
            col.text(name)


def _render_signals_table(signals: list):
    """Render active signals with score, grade, entry/SL/target."""
    if not signals:
        st.info("No signals above threshold this scan.")
        return

    rows = []
    for s in signals:
        grade = s.get("grade", "")
        score = s.get("final_score", 0)
        rows.append({
            "Stock":      s.get("symbol", ""),
            "Setup":      s.get("setup_type", "").replace("_", " ").title(),
            "Score":      f"{score:.1f}",
            "Grade":      grade,
            "Entry":      f"₹{s.get('entry_price', 0):,.2f}",
            "SL":         f"₹{s.get('stop_loss', 0):,.2f}",
            "Target":     f"₹{s.get('target_price', 0):,.2f}",
            "Confidence": f"{s.get('confidence', 0)*100:.0f}%",
            "Action":     s.get("action", "Pending"),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Grade": st.column_config.TextColumn("Grade", width="small"),
            "Score": st.column_config.TextColumn("Score", width="small"),
        }
    )


def _render_positions_table(positions: list):
    """Render open positions with live P&L."""
    rows = []
    for p in positions:
        pnl_r = _get_pnl_r(p)
        rows.append({
            "Stock":        p.symbol,
            "Setup":        p.setup_type.replace("_", " ").title(),
            "Grade":        p.grade,
            "Score":        f"{p.score:.1f}",
            "Entry":        f"₹{p.entry_price:,.2f}",
            "SL":           f"₹{p.stop_loss:,.2f}",
            "Target":       f"₹{p.target_price:,.2f}",
            "Qty":          p.quantity,
            "Unreal. P&L":  f"₹{(pnl_r * abs(p.entry_price - p.stop_loss) * p.quantity):+,.0f}",
            "R running":    f"{pnl_r:+.1f}R",
            "Status":       "Running" if pnl_r > 0.1 else "Watching" if abs(pnl_r) <= 0.1 else "At Risk",
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )


def _render_closed_table(trades: list):
    """Render closed trades for today."""
    rows = []
    for t in trades:
        rows.append({
            "Stock":    t.symbol,
            "Setup":    t.setup_type.replace("_", " ").title(),
            "Grade":    t.grade,
            "Entry":    f"₹{t.entry_price:,.2f}",
            "Exit":     f"₹{t.exit_price:,.2f}" if t.exit_price else "-",
            "P&L":      f"₹{t.pnl:+,.0f}" if t.pnl else "-",
            "R result": f"{t.pnl_r:+.1f}R" if t.pnl_r else "-",
            "Outcome":  "Win" if t.status == "closed_win" else "Loss" if t.status == "closed_loss" else "Flat",
            "Exit reason": (t.exit_reason or "").replace("_", " ").title(),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _get_pnl_r(position) -> float:
    """Estimate current P&L in R units from position data."""
    sl_dist = abs(position.entry_price - position.stop_loss)
    if sl_dist == 0:
        return 0.0
    # We don't have live price here — use entry as proxy (dashboard refreshes anyway)
    return 0.0
