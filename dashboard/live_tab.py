"""
Dashboard Tab 1 — Live Trading.
Shows: market breadth indicator, agent status, active signals (with SL/TP1/TP2/reason),
open positions (with TP1 hit status + trailing SL), today's closed trades.
Auto-refreshes every 10 seconds.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from memory.trade_state import TradeStateManager
from config.settings import CAPITAL, TIMEZONE
from data.kite_client import KiteDataClient

IST = ZoneInfo(TIMEZONE)

@st.cache_resource
def _get_kite():
    return KiteDataClient()

def _fetch_live_prices(symbols: list[str]) -> dict:
    """
    Batch fetch live LTP for open positions. Returns symbol → last_price (float)
    or symbol → None if fetch failed for that name. Caller distinguishes
    "missing" (None) from "valid LTP" so we don't silently fall back to
    entry_price (which produced fake +0.00% P&L rows — Fix #50).
    """
    if not symbols:
        return {}
    out = {sym: None for sym in symbols}
    try:
        quotes = _get_kite().get_quotes(symbols)
        for sym in symbols:
            ltp = quotes.get(sym, {}).get("last_price")
            if ltp and ltp > 0:
                out[sym] = float(ltp)
    except Exception as e:
        # Leave all as None — caller will show "—" so the failure is visible
        pass
    return out


def render_live_tab(state: TradeStateManager):
    """Render the full live trading tab."""
    now = datetime.now(IST)

    # ── Market breadth indicator ──────────────────────────────────────────────
    _render_breadth_bar()

    # ── Top stat cards ────────────────────────────────────────────────────────
    deployed    = state.get_deployed_capital()
    available   = state.get_available_capital()
    deploy_pct  = state.get_deployment_pct()
    open_pos    = state.get_open_positions()
    today_pnl   = state.get_today_pnl()
    today_trades = state.get_today_trades()
    consec_loss  = state.get_consecutive_losses()

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            "Capital deployed",
            f"{deploy_pct:.1f}%",
            delta=f"₹{deployed:,.0f} / ₹{CAPITAL:,.0f}",
        )
    with col2:
        profitable = sum(1 for p in open_pos if _unreal_pnl(p) > 0)
        st.metric(
            "Open positions",
            len(open_pos),
            delta=f"{profitable} in profit",
        )
    with col3:
        wins   = sum(1 for t in today_trades if t.status == "closed_win")
        losses = sum(1 for t in today_trades if t.status == "closed_loss")
        st.metric(
            "Trades today",
            len(today_trades),
            delta=f"{wins}W {losses}L",
        )
    with col4:
        pnl_delta_color = "normal" if today_pnl >= 0 else "inverse"
        st.metric(
            "Today's P&L",
            f"₹{today_pnl:+,.0f}",
            delta=f"{today_pnl / CAPITAL * 100:+.2f}% of capital",
            delta_color=pnl_delta_color,
        )
    with col5:
        mode = "⚠️ Conservative" if consec_loss >= 3 else "✅ Normal"
        st.metric(
            "Trading mode",
            mode,
            delta=f"{consec_loss} consec losses",
            delta_color="inverse" if consec_loss >= 3 else "off",
        )

    st.divider()

    # ── Agent pipeline status ─────────────────────────────────────────────────
    st.markdown("#### 🤖 Agent pipeline — last scan")
    _render_agent_pipeline()

    st.divider()

    # ── Active signals ────────────────────────────────────────────────────────
    st.markdown("#### 📡 Active signals this scan")
    if "last_signals" in st.session_state and st.session_state.last_signals:
        _render_signals_table(st.session_state.last_signals)
    else:
        st.info("Waiting for next scan... system scans every 3 minutes.")

    st.divider()

    # ── Open positions ────────────────────────────────────────────────────────
    st.markdown("#### 📂 Open positions")
    if open_pos:
        _render_positions_table(open_pos)
    else:
        st.info("No open positions currently.")

    st.divider()

    # ── Today's closed trades ─────────────────────────────────────────────────
    closed_today = [t for t in today_trades if t.status != "open"]
    if closed_today:
        st.markdown("#### ✅ Closed today")
        _render_closed_table(closed_today)

    # ── Watchlist ─────────────────────────────────────────────────────────────
    watchlist = state.get_watchlist()
    if watchlist:
        st.divider()
        st.markdown("#### 👀 Watchlist (B-grade signals waiting)")
        _render_watchlist(watchlist)

    st.caption(
        f"Last updated: {now.strftime('%H:%M:%S IST')} · Auto-refresh every 10s"
    )


# ─── Breadth indicator ────────────────────────────────────────────────────────

def _render_breadth_bar():
    """Show market breadth % as a colored progress bar."""
    breadth = st.session_state.get("last_breadth", {})
    if not breadth:
        return

    pct   = breadth.get("breadth_pct", 50.0)
    label = breadth.get("breadth_label", "NEUTRAL")
    top3  = breadth.get("top_sectors", [])

    color = "#00C853" if label == "BULLISH" else "#F44336" if label == "BEARISH" else "#FFD600"

    st.markdown(
        f"""
        <div style="background:#1A1A2E;border-radius:8px;padding:10px 16px;margin-bottom:8px;
                    border-left:4px solid {color};">
            <span style="color:{color};font-weight:bold;">Market Breadth: {pct:.0f}%</span>
            <span style="color:#aaa;font-size:0.85em;margin-left:16px;">
                {label} &nbsp;|&nbsp; Top sectors: {', '.join(top3) if top3 else 'loading...'}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── Agent pipeline ───────────────────────────────────────────────────────────

def _render_agent_pipeline():
    agents = [
        ("📡 Scanner",      "last_scanner_status"),
        ("🌐 Regime",       "last_regime_status"),
        ("📊 Breadth",      "last_breadth_status"),
        ("🕯 Setups",       "last_setup_status"),
        ("📦 Volume+RS",    "last_volume_status"),
        ("📰 News",         "last_news_status"),
        ("🏆 Scorer",       "last_scoring_status"),
        ("💼 Position Mgr", "last_position_status"),
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
            col.markdown(f"<div style='color:#666;font-size:0.8em'>{name}</div>",
                         unsafe_allow_html=True)


# ─── Signals table ────────────────────────────────────────────────────────────

def _render_signals_table(signals: list):
    """Signals with full SL / TP1 / TP2 / reason / score breakdown."""
    if not signals:
        st.info("No signals above threshold this scan.")
        return

    rows = []
    for s in signals:
        score = s.get("final_score", 0)
        bd    = s.get("score_breakdown") or {}

        rows.append({
            "Stock":      s.get("symbol", ""),
            "Setup":      s.get("setup_type", "").replace("_", " ").title(),
            "Grade":      s.get("grade", ""),
            "Score":      f"{score:.1f}",
            "Conf":       f"{s.get('confidence', 0)*100:.0f}%",
            "Entry ₹":    f"{s.get('entry_price', 0):,.2f}",
            "SL ₹":       f"{s.get('stop_loss', 0):,.2f}",
            "TP1 ₹":      f"{s.get('tp1_price', 0):,.2f}",
            "TP2 ₹":      f"{s.get('tp2_price', 0):,.2f}",
            "Setup Q":    f"{bd.get('setup_quality', 0):.1f}",
            "Vol":        f"{bd.get('volume_strength', 0):.1f}",
            "Mkt":        f"{bd.get('market_alignment', 0):.1f}",
            "RS":         f"{bd.get('relative_strength', 0):.1f}",
            "Reason":     s.get("reason", "")[:80],
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Grade": st.column_config.TextColumn("Grade", width="small"),
            "Score": st.column_config.TextColumn("Score", width="small"),
            "Reason": st.column_config.TextColumn("Reason", width="large"),
        },
    )


# ─── Open positions ───────────────────────────────────────────────────────────

def _render_positions_table(positions: list):
    """Open positions with live LTP, separate Realised + Unrealised P&L (Fix #50)."""
    # Batch fetch live prices for all open positions
    symbols   = [p.symbol for p in positions]
    live_ltps = _fetch_live_prices(symbols)

    rows = []
    total_realised   = 0.0
    total_unrealised = 0.0
    fetch_failures   = 0

    for p in positions:
        ltp_raw = live_ltps.get(p.symbol)             # None if fetch failed
        ltp     = ltp_raw if ltp_raw else p.entry_price  # for math fallback
        ltp_ok  = ltp_raw is not None
        qty     = p.quantity_remaining or p.quantity or 0

        # Realised: any P&L already booked from TP1 partial-exit
        realised = round(p.pnl or 0.0, 2)

        # Unrealised: open portion vs current LTP
        if ltp_ok and qty > 0:
            unreal = round((ltp - p.entry_price) * qty, 2)
        else:
            unreal = 0.0
            if not ltp_ok:
                fetch_failures += 1

        total_realised   += realised
        total_unrealised += unreal

        chg_pct = round((ltp - p.entry_price) / p.entry_price * 100, 2) if (ltp_ok and p.entry_price) else 0
        sl_dist = abs(p.entry_price - (p.initial_sl or p.stop_loss)) or 1
        # R-running = total (realised + unrealised) / R-per-share / initial qty
        total_now = realised + unreal
        pnl_r     = round(total_now / (sl_dist * (p.quantity or qty)), 2) if (p.quantity or qty) > 0 else 0

        rows.append({
            "Stock":         p.symbol,
            "Setup":         (p.setup_type or "").replace("_", " ").title(),
            "Grade":         p.grade or "-",
            "Score":         f"{p.score:.1f}" if p.score else "-",
            "Avg ₹":         f"{p.entry_price:,.2f}",
            "LTP ₹":         f"{ltp:,.2f}" if ltp_ok else "—",
            "Chg %":         f"{chg_pct:+.2f}%" if ltp_ok else "—",
            "SL ₹":          f"{p.stop_loss:,.2f}",
            "TP1 ₹":         f"{p.tp1_price:,.2f}",
            "TP2 ₹":         f"{p.tp2_price:,.2f}",
            "TP1":           "✅" if p.tp1_hit else "⏳",
            "Qty":           qty,
            "Realised ₹":    f"₹{realised:+,.0f}" if realised else "—",
            "Unrealised ₹":  f"₹{unreal:+,.0f}" if ltp_ok else "—",
            "R running":     f"{pnl_r:+.1f}R" if ltp_ok else "—",
            "Reason":        (p.entry_reason or "")[:60],
        })

    # Total summary row
    if rows:
        total_all = total_realised + total_unrealised
        col_total = "green" if total_all >= 0 else "red"
        col_real  = "green" if total_realised  >= 0 else "red"
        col_unr   = "green" if total_unrealised >= 0 else "red"
        st.markdown(
            f"**Realised: <span style='color:{col_real}'>₹{total_realised:+,.0f}</span>** &nbsp;|&nbsp; "
            f"**Unrealised: <span style='color:{col_unr}'>₹{total_unrealised:+,.0f}</span>** &nbsp;|&nbsp; "
            f"**Total: <span style='color:{col_total};font-size:1.2em'>₹{total_all:+,.0f}</span>**",
            unsafe_allow_html=True,
        )
        if fetch_failures > 0:
            st.warning(f"⚠️ Live LTP fetch failed for {fetch_failures} of {len(positions)} positions — "
                       f"unrealised P&L shown as '—'. Likely a Kite token / network blip; the engine "
                       f"itself uses a separate Kite client and is unaffected.")

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "TP1 Hit": st.column_config.TextColumn("TP1", width="small"),
            "Reason":  st.column_config.TextColumn("Reason", width="large"),
        },
    )

    # Expandable: show score breakdown for each position
    with st.expander("📊 Score breakdowns"):
        for p in positions:
            if p.score_breakdown and p.score_breakdown != "{}":
                try:
                    import json
                    bd = json.loads(p.score_breakdown)
                    st.markdown(f"**{p.symbol}** — {p.grade} ({p.score:.1f}/10)")
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Setup Q", f"{bd.get('setup_quality', 0):.1f}/3")
                    c2.metric("Volume",  f"{bd.get('volume_strength', 0):.1f}/2")
                    c3.metric("Market",  f"{bd.get('market_alignment', 0):.1f}/2")
                    c4.metric("RS",      f"{bd.get('relative_strength', 0):.1f}/2")
                    c5.metric("News",    f"{bd.get('news_sentiment', 0):.1f}/1")
                except Exception:
                    pass


# ─── Closed trades ────────────────────────────────────────────────────────────

def _render_closed_table(trades: list):
    rows = []
    for t in trades:
        rows.append({
            "Stock":    t.symbol,
            "Setup":    (t.setup_type or "").replace("_", " ").title(),
            "Grade":    t.grade or "-",
            "Entry ₹":  f"{t.entry_price:,.2f}",
            "Exit ₹":   f"{t.exit_price:,.2f}" if t.exit_price else "-",
            "SL ₹":     f"{t.stop_loss:,.2f}",
            "TP1 ₹":    f"{t.tp1_price:,.2f}" if t.tp1_price else "-",
            "TP2 ₹":    f"{t.tp2_price:,.2f}" if t.tp2_price else "-",
            "P&L":      f"₹{t.pnl:+,.0f}" if t.pnl else "₹0",
            "R":        f"{t.pnl_r:+.1f}R" if t.pnl_r else "0R",
            "Result":   "🟢 Win" if t.status == "closed_win"
                        else "🔴 Loss" if t.status == "closed_loss" else "⚪",
            "Reason":   (t.exit_reason or "").replace("_", " ").title(),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ─── Watchlist ────────────────────────────────────────────────────────────────

def _render_watchlist(watchlist: list):
    rows = []
    for w in watchlist:
        rows.append({
            "Stock":  w.symbol,
            "Setup":  (w.setup_type or "").replace("_", " ").title(),
            "Score":  f"{w.score:.1f}",
            "Entry ₹": f"{w.entry_price:,.2f}",
            "SL ₹":   f"{w.stop_loss:,.2f}",
            "TP1 ₹":  f"{w.tp1_price:,.2f}",
            "TP2 ₹":  f"{w.tp2_price:,.2f}",
            "Added":  (w.added_at or "")[:16],
            "Reason": (w.reason or "")[:70],
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _unreal_pnl(position) -> float:
    """Fallback P&L from DB (used for summary cards). Live table uses _fetch_live_prices()."""
    return round(position.pnl, 2) if position.pnl else 0.0
