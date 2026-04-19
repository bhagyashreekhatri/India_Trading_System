"""
Dashboard Tab 2 — Setup Analytics.
Shows: win rate by setup/grade, learning insights, full trade log.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from memory.trade_state import TradeStateManager
from memory.chroma_client import ChromaMemory


def render_analytics_tab(state: TradeStateManager, chroma: ChromaMemory):
    """Render the full analytics tab."""

    summary  = state.get_summary()
    closed   = state.get_all_closed_trades()
    by_setup = state.get_win_rate_by_setup()
    by_grade = state.get_win_rate_by_grade()

    if not closed:
        st.info("No completed trades yet. Analytics will appear after first trades are closed.")
        return

    # ── Summary stat cards ────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total trades", summary["total"])
    with col2:
        st.metric("Win rate", f"{summary['win_rate']}%",
                  delta=f"{summary['wins']}W / {summary['losses']}L")
    with col3:
        avg_r = summary["avg_r"]
        st.metric("Avg R per trade", f"{avg_r:+.2f}R",
                  delta_color="normal" if avg_r >= 0 else "inverse")
    with col4:
        st.metric("Total P&L", f"₹{summary['total_pnl']:+,.0f}",
                  delta_color="normal" if summary["total_pnl"] >= 0 else "inverse")

    st.divider()

    # ── Charts side by side ───────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Win rate by setup type")
        _render_setup_chart(by_setup)

    with col_right:
        st.markdown("#### Win rate by grade")
        _render_grade_chart(by_grade)

    st.divider()

    # ── What the system is learning ───────────────────────────────────────────
    st.markdown("#### What the system is learning")
    _render_learning_insights(by_setup, by_grade, chroma)

    st.divider()

    # ── Full trade log ────────────────────────────────────────────────────────
    st.markdown("#### Full trade log")
    _render_trade_log(closed)


def _render_setup_chart(by_setup: dict):
    if not by_setup:
        st.info("No data yet")
        return

    data = []
    for setup, stats in by_setup.items():
        data.append({
            "Setup":    setup.replace("_", " ").title(),
            "Win rate": stats["win_rate"],
            "Trades":   stats["total"],
            "Avg R":    stats["avg_r"],
        })
    data.sort(key=lambda x: x["Win rate"], reverse=True)
    df = pd.DataFrame(data)

    colors = ["#639922" if r >= 55 else "#BA7517" if r >= 40 else "#A32D2D"
              for r in df["Win rate"]]

    fig = go.Figure(go.Bar(
        x=df["Win rate"],
        y=df["Setup"],
        orientation="h",
        marker_color=colors,
        text=[f"{r}% ({t} trades)" for r, t in zip(df["Win rate"], df["Trades"])],
        textposition="inside",
    ))
    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=10, b=10),
        xaxis=dict(range=[0, 100], title="Win rate %"),
        yaxis=dict(title=""),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_grade_chart(by_grade: dict):
    if not by_grade:
        st.info("No data yet")
        return

    grade_order = ["A++", "A+", "A", "B"]
    data = []
    for grade in grade_order:
        if grade in by_grade:
            stats = by_grade[grade]
            data.append({
                "Grade":    grade,
                "Win rate": stats["win_rate"],
                "Trades":   stats["total"],
                "Avg R":    stats["avg_r"],
            })
    df = pd.DataFrame(data)

    colors_map = {"A++": "#3C3489", "A+": "#0C447C", "A": "#085041", "B": "#633806"}
    colors = [colors_map.get(g, "#888780") for g in df["Grade"]]

    fig = go.Figure(go.Bar(
        x=df["Grade"],
        y=df["Win rate"],
        marker_color=colors,
        text=[f"{r}%\n({t} trades)" for r, t in zip(df["Win rate"], df["Trades"])],
        textposition="inside",
    ))
    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=10, b=10),
        yaxis=dict(range=[0, 100], title="Win rate %"),
        xaxis=dict(title="Grade"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_learning_insights(by_setup: dict, by_grade: dict, chroma: ChromaMemory):
    """Surface patterns the system has learned."""
    insights = []

    # Best performing setup
    if by_setup:
        best = max(by_setup.items(), key=lambda x: x[1]["win_rate"])
        if best[1]["total"] >= 3:
            insights.append({
                "type":    "positive",
                "title":   f"{best[0].replace('_', ' ').title()} has highest win rate ({best[1]['win_rate']}%)",
                "detail":  f"{best[1]['total']} trades · avg exit at {best[1]['avg_r']:+.1f}R",
            })

        # Worst performing setup
        worst = min(by_setup.items(), key=lambda x: x[1]["win_rate"])
        if worst[1]["total"] >= 3 and worst[1]["win_rate"] < 50:
            insights.append({
                "type":    "warning",
                "title":   f"{worst[0].replace('_', ' ').title()} underperforming — {worst[1]['win_rate']}% win rate",
                "detail":  f"{worst[1]['total']} trades · consider raising score threshold for this setup",
            })

    # Grade A++ check
    if "A++" in by_grade and by_grade["A++"]["total"] >= 3:
        wr = by_grade["A++"]["win_rate"]
        if wr >= 70:
            insights.append({
                "type":    "positive",
                "title":   f"A++ grade delivering {wr}% win rate — system is well calibrated",
                "detail":  f"{by_grade['A++']['total']} A++ trades · avg {by_grade['A++']['avg_r']:+.1f}R",
            })
        elif wr < 55:
            insights.append({
                "type":    "warning",
                "title":   f"A++ grade only {wr}% — scoring thresholds may need recalibration",
                "detail":  "Review regime multipliers and component weights in engine.py",
            })

    # B grade check
    if "B" in by_grade and by_grade["B"]["total"] >= 3:
        wr = by_grade["B"]["win_rate"]
        if wr < 45:
            insights.append({
                "type":    "warning",
                "title":   f"B-grade trades losing — {wr}% win rate. Consider disabling B entries.",
                "detail":  "Set MIN_SCORE_ENTRY = 7.0 in settings.py to stop B-grade entries",
            })

    if not insights:
        st.info("Insights will appear after 10+ completed trades.")
        return

    for insight in insights:
        if insight["type"] == "positive":
            st.success(f"**{insight['title']}**  \n{insight['detail']}")
        else:
            st.warning(f"**{insight['title']}**  \n{insight['detail']}")


def _render_trade_log(trades: list):
    """Full filterable trade log."""

    # Filters row
    col1, col2, col3 = st.columns(3)
    with col1:
        grade_filter = st.multiselect(
            "Filter by grade",
            ["A++", "A+", "A", "B"],
            default=["A++", "A+", "A", "B"],
            key="analytics_grade_filter",
        )
    with col2:
        outcome_filter = st.multiselect(
            "Filter by outcome",
            ["Win", "Loss", "Flat"],
            default=["Win", "Loss", "Flat"],
            key="analytics_outcome_filter",
        )
    with col3:
        setup_filter = st.multiselect(
            "Filter by setup",
            list({t.setup_type for t in trades}),
            default=list({t.setup_type for t in trades}),
            key="analytics_setup_filter",
        )

    rows = []
    for t in trades:
        outcome = "Win" if t.status == "closed_win" else "Loss" if t.status == "closed_loss" else "Flat"
        if t.grade not in grade_filter:
            continue
        if outcome not in outcome_filter:
            continue
        if t.setup_type not in setup_filter:
            continue

        rows.append({
            "Date":        t.entry_time[:10] if t.entry_time else "",
            "Stock":       t.symbol,
            "Setup":       t.setup_type.replace("_", " ").title(),
            "Grade":       t.grade,
            "Score":       f"{t.score:.1f}",
            "Entry":       f"₹{t.entry_price:,.2f}",
            "Exit":        f"₹{t.exit_price:,.2f}" if t.exit_price else "-",
            "P&L":         f"₹{t.pnl:+,.0f}" if t.pnl else "-",
            "R result":    f"{t.pnl_r:+.1f}R" if t.pnl_r else "-",
            "Outcome":     outcome,
            "Exit reason": (t.exit_reason or "").replace("_", " ").title(),
        })

    if not rows:
        st.info("No trades match your filters.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(rows)} trades")
