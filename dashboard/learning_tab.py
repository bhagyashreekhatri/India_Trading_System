"""
Learning Tab — performance analytics and pattern intelligence.
Shows: setup win-rates, grade accuracy, time heatmap, regime performance,
       best stocks, score distribution, and P&L curves.
All data comes from TradeStateManager (SQLite). Read-only.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

from memory.trade_state import TradeStateManager

_state: TradeStateManager = None

def _get_state() -> TradeStateManager:
    global _state
    if _state is None:
        _state = TradeStateManager()
    return _state


# ─── Color helpers ─────────────────────────────────────────────────────────────

def _win_color(win_rate: float) -> str:
    if win_rate >= 65: return "#00C853"
    if win_rate >= 50: return "#FFD600"
    return "#F44336"


def _r_color(avg_r: float) -> str:
    if avg_r > 0.5:  return "#00C853"
    if avg_r >= 0:   return "#FFD600"
    return "#F44336"


# ─── Main render ──────────────────────────────────────────────────────────────

def render_learning_tab():
    st.markdown("## 🎓 Learning Lab — What's Working?")
    st.caption("Powered by all historical paper trades. Use this to refine your edge.")

    state   = _get_state()
    summary = state.get_summary()
    closed  = state.get_all_closed_trades()

    if not closed:
        st.info("📭 No closed trades yet. Run the agent during market hours to build your dataset.")
        return

    # ── Overview KPIs ──────────────────────────────────────────────────────────
    st.markdown("### 📊 Overall Performance")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Trades",  summary["total"])
    col2.metric("Win Rate",      f"{summary['win_rate']}%",
                delta=f"{summary['win_rate']-50:.1f}% vs 50%",
                delta_color="normal")
    col3.metric("Avg R",         f"{summary['avg_r']:+.2f}R",
                delta_color="normal")
    col4.metric("Total P&L",     f"₹{summary['total_pnl']:+,.0f}",
                delta_color="normal")
    col5.metric("Best Trade",    f"₹{summary['best_trade']:+,.0f}")

    st.divider()

    # ── Setup Matrix ───────────────────────────────────────────────────────────
    st.markdown("### 🎯 Setup Performance Matrix")
    setup_stats = state.get_win_rate_by_setup()

    if setup_stats:
        rows = []
        for setup, v in setup_stats.items():
            rows.append({
                "Setup":    setup.replace("_", " ").title(),
                "Trades":   v["total"],
                "Wins":     v["wins"],
                "Win Rate": v["win_rate"],
                "Avg R":    v["avg_r"],
                "Total P&L": f"₹{v['total_pnl']:+,.0f}",
            })
        df_setup = pd.DataFrame(rows).sort_values("Win Rate", ascending=False)

        # Colour-coded table
        fig = go.Figure(data=[go.Table(
            header=dict(
                values=["<b>Setup</b>", "<b>Trades</b>", "<b>Win Rate %</b>",
                        "<b>Avg R</b>", "<b>Total P&L</b>"],
                fill_color="#1E1E1E",
                font=dict(color="white", size=13),
                align="left",
                height=36,
            ),
            cells=dict(
                values=[
                    df_setup["Setup"],
                    df_setup["Trades"],
                    df_setup["Win Rate"].apply(lambda x: f"{x}%"),
                    df_setup["Avg R"].apply(lambda x: f"{x:+.2f}R"),
                    df_setup["Total P&L"],
                ],
                fill_color=[
                    ["#2A2A2A"] * len(df_setup),
                    ["#2A2A2A"] * len(df_setup),
                    [_win_color(w) + "44" for w in df_setup["Win Rate"]],
                    [_r_color(r) + "44" for r in df_setup["Avg R"]],
                    ["#2A2A2A"] * len(df_setup),
                ],
                font=dict(color="white", size=12),
                align="left",
                height=32,
            ),
        )])
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=min(60 + len(df_setup) * 38, 420),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Bar chart: win rate by setup
        fig2 = px.bar(
            df_setup, x="Setup", y="Win Rate",
            color="Win Rate",
            color_continuous_scale=["#F44336", "#FFD600", "#00C853"],
            range_color=[30, 80],
            title="Win Rate by Setup Type",
        )
        fig2.add_hline(y=50, line_dash="dash", line_color="white", opacity=0.4,
                       annotation_text="50%", annotation_position="right")
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            height=320,
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Grade Accuracy ─────────────────────────────────────────────────────────
    st.markdown("### 🏆 Grade Accuracy — Does the score predict outcomes?")
    grade_stats = state.get_win_rate_by_grade()

    if grade_stats:
        grade_order = ["A++", "A+", "A", "B", "C"]
        g_rows = []
        for g in grade_order:
            if g in grade_stats:
                v = grade_stats[g]
                g_rows.append({
                    "Grade":    g,
                    "Trades":   v["total"],
                    "Win Rate": v["win_rate"],
                    "Avg R":    v["avg_r"],
                    "Total P&L": v["total_pnl"],
                })
        if g_rows:
            df_grade = pd.DataFrame(g_rows)

            col_a, col_b = st.columns(2)
            with col_a:
                fig_g = px.bar(
                    df_grade, x="Grade", y="Win Rate",
                    color="Win Rate",
                    color_continuous_scale=["#F44336", "#FFD600", "#00C853"],
                    range_color=[30, 80],
                    title="Win Rate by Grade",
                )
                fig_g.add_hline(y=50, line_dash="dash", line_color="white", opacity=0.4)
                fig_g.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white"), height=300,
                )
                st.plotly_chart(fig_g, use_container_width=True)

            with col_b:
                fig_r = px.bar(
                    df_grade, x="Grade", y="Avg R",
                    color="Avg R",
                    color_continuous_scale=["#F44336", "#FFD600", "#00C853"],
                    range_color=[-1, 2],
                    title="Avg R-Multiple by Grade",
                )
                fig_r.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.4)
                fig_r.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white"), height=300,
                )
                st.plotly_chart(fig_r, use_container_width=True)

    st.divider()

    # ── Time Heatmap ──────────────────────────────────────────────────────────
    st.markdown("### ⏰ Best Time to Trade — Win Rate by Hour")
    hour_stats = state.get_win_rate_by_hour()

    if hour_stats:
        h_rows = [{"Hour": h, "Win Rate": v["win_rate"],
                   "Trades": v["total"], "Avg P&L": v["avg_pnl"]}
                  for h, v in hour_stats.items()]
        df_hour = pd.DataFrame(h_rows)

        fig_h = px.bar(
            df_hour, x="Hour", y="Win Rate",
            color="Win Rate",
            color_continuous_scale=["#F44336", "#FFD600", "#00C853"],
            range_color=[30, 80],
            hover_data={"Trades": True, "Avg P&L": True},
            title="Win Rate by Entry Hour (IST)",
        )
        fig_h.add_hline(y=50, line_dash="dash", line_color="white", opacity=0.4)
        fig_h.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"), height=320,
        )
        st.plotly_chart(fig_h, use_container_width=True)

        # Insight callout
        if len(df_hour) >= 3:
            best_hour = df_hour.loc[df_hour["Win Rate"].idxmax(), "Hour"]
            worst_hour = df_hour.loc[df_hour["Win Rate"].idxmin(), "Hour"]
            st.info(f"💡 Best trading hour: **{best_hour}** IST  •  Weakest: **{worst_hour}** IST")

    st.divider()

    # ── Score Distribution ────────────────────────────────────────────────────
    st.markdown("### 📈 Score Distribution — Wins vs Losses")
    wins_list   = [t for t in closed if t.status == "closed_win"]
    losses_list = [t for t in closed if t.status == "closed_loss"]

    if wins_list or losses_list:
        fig_s = go.Figure()
        if wins_list:
            fig_s.add_trace(go.Histogram(
                x=[t.score for t in wins_list],
                name="Wins", nbinsx=15,
                marker_color="#00C853", opacity=0.75,
            ))
        if losses_list:
            fig_s.add_trace(go.Histogram(
                x=[t.score for t in losses_list],
                name="Losses", nbinsx=15,
                marker_color="#F44336", opacity=0.75,
            ))
        fig_s.update_layout(
            barmode="overlay",
            title="Score Distribution: Wins vs Losses",
            xaxis_title="Final Score",
            yaxis_title="Count",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            height=320,
        )
        st.plotly_chart(fig_s, use_container_width=True)

    st.divider()

    # ── Best Stocks ───────────────────────────────────────────────────────────
    st.markdown("### 🌟 Best Performing Stocks")
    best_stocks = state.get_best_stocks(top_n=10)

    if best_stocks:
        df_stocks = pd.DataFrame(best_stocks)
        df_stocks["color"] = df_stocks["total_pnl"].apply(
            lambda x: "#00C853" if x > 0 else "#F44336"
        )
        fig_st = px.bar(
            df_stocks.sort_values("total_pnl"),
            x="total_pnl", y="symbol",
            orientation="h",
            color="total_pnl",
            color_continuous_scale=["#F44336", "#333", "#00C853"],
            title="Cumulative P&L by Stock",
        )
        fig_st.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            height=340,
            showlegend=False,
        )
        st.plotly_chart(fig_st, use_container_width=True)

    st.divider()

    # ── Equity Curve ──────────────────────────────────────────────────────────
    st.markdown("### 📉 Equity Curve — Cumulative P&L")

    if closed:
        # Sort by exit time
        df_trades = pd.DataFrame([{
            "exit_time": t.exit_time,
            "pnl":       t.pnl or 0,
            "status":    t.status,
        } for t in closed if t.exit_time])

        if not df_trades.empty:
            df_trades["exit_time"] = pd.to_datetime(df_trades["exit_time"])
            df_trades = df_trades.sort_values("exit_time")
            df_trades["cumulative_pnl"] = df_trades["pnl"].cumsum()

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=df_trades["exit_time"],
                y=df_trades["cumulative_pnl"],
                mode="lines+markers",
                name="Equity",
                line=dict(color="#4FC3F7", width=2),
                marker=dict(
                    color=df_trades["status"].apply(
                        lambda s: "#00C853" if s == "closed_win" else "#F44336"
                    ),
                    size=7,
                ),
                fill="tozeroy",
                fillcolor="rgba(79,195,247,0.1)",
            ))
            fig_eq.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
            fig_eq.update_layout(
                title="Cumulative P&L over time",
                xaxis_title="Date / Time",
                yaxis_title="P&L (₹)",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="white"),
                height=350,
            )
            st.plotly_chart(fig_eq, use_container_width=True)

    st.divider()

    # ── Recent Trades Log ──────────────────────────────────────────────────────
    st.markdown("### 📋 Recent Trades (last 50)")
    recent = sorted(closed, key=lambda t: t.exit_time or "", reverse=True)[:50]

    if recent:
        log_rows = []
        for t in recent:
            log_rows.append({
                "Symbol":    t.symbol,
                "Setup":     (t.setup_type or "").replace("_", " ").title(),
                "Grade":     t.grade or "-",
                "Score":     f"{t.score:.1f}" if t.score else "-",
                "Entry":     f"₹{t.entry_price:.2f}" if t.entry_price else "-",
                "Exit":      f"₹{t.exit_price:.2f}" if t.exit_price else "-",
                "P&L":       f"₹{t.pnl:+,.0f}" if t.pnl else "₹0",
                "R":         f"{t.pnl_r:+.2f}" if t.pnl_r else "0",
                "Exit Reason": (t.exit_reason or "").replace("_", " ").title(),
                "Time":      t.exit_time[:16] if t.exit_time else "-",
            })

        df_log = pd.DataFrame(log_rows)

        def _style_row(row):
            if "Win" in row.get("Exit Reason", "") or "Tp" in row.get("Exit Reason", ""):
                return ["background-color: #003300"] * len(row)
            elif "Loss" in row.get("P&L", "") or row["P&L"].startswith("₹-"):
                return ["background-color: #330000"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df_log,
            use_container_width=True,
            height=420,
            hide_index=True,
        )

    # Footer
    st.markdown(
        "<div style='text-align:center;color:#666;font-size:12px;margin-top:20px'>"
        "🤖 Paper trading data only — not financial advice"
        "</div>",
        unsafe_allow_html=True,
    )
