"""
NSE Trading System Dashboard — Streamlit entry point.
Run with: streamlit run dashboard/app.py

Read-only window into the trading system.
3 human controls only: kill switch, score threshold, max positions.
Auto-refreshes every 10 seconds.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

# ── Page config — MUST be first st.* call ─────────────────────────────────────
st.set_page_config(
    page_title="NSE Trading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Mobile + general CSS ───────────────────────────────────────────────────────
st.markdown("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<style>
    /* ── Mobile responsive ── */
    @media (max-width: 768px) {
        .block-container { padding: 0.5rem 0.5rem !important; }
        div[data-testid="column"] { min-width: 45% !important; }
        section[data-testid="stSidebar"] { width: 85vw !important; }
        .stMetric { font-size: 0.85rem !important; }
        h1 { font-size: 1.4rem !important; }
        h3, h4 { font-size: 1rem !important; }
        .stTabs [data-baseweb="tab"] { font-size: 0.85rem; padding: 6px 10px; }
        div[data-testid="stDataFrame"] { font-size: 0.75rem !important; }
    }
    /* ── General styling ── */
    .block-container { padding-top: 0.8rem; }
    .stMetric {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 12px 16px;
        border: 1px solid #e9ecef;
    }
    .stMetric label { font-size: 0.78rem !important; color: #6c757d; }
    div[data-testid="stSidebar"] { min-width: 260px; }
    /* ── Make tabs easier to tap on mobile ── */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from dashboard.live_tab import render_live_tab
from dashboard.analytics_tab import render_analytics_tab
from memory.trade_state import TradeStateManager
from memory.chroma_client import ChromaMemory
from config.settings import TIMEZONE, MIN_SCORE_ENTRY, MAX_POSITIONS, CAPITAL

IST = ZoneInfo(TIMEZONE)
CONTROL_FILE = Path("./system_controls.json")


def load_controls() -> dict:
    defaults = {
        "kill_switch":     False,
        "min_score_entry": MIN_SCORE_ENTRY,
        "max_positions":   MAX_POSITIONS,
        "last_updated":    "",
    }
    if CONTROL_FILE.exists():
        try:
            with open(CONTROL_FILE) as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_controls(controls: dict):
    controls["last_updated"] = datetime.now(IST).isoformat()
    with open(CONTROL_FILE, "w") as f:
        json.dump(controls, f, indent=2)


@st.cache_resource
def get_state() -> TradeStateManager:
    return TradeStateManager()

@st.cache_resource
def get_chroma() -> ChromaMemory:
    return ChromaMemory()


state  = get_state()
chroma = get_chroma()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 NSE Trading")

    now = datetime.now(IST)
    market_open = (now.weekday() < 5 and
                   now.hour >= 9 and
                   (now.hour < 15 or (now.hour == 15 and now.minute <= 30)))
    status_color = "green" if market_open else "red"
    st.markdown(f"**Status:** :{status_color}[{'🟢 Market open' if market_open else '🔴 Market closed'}]")
    st.caption(f"{now.strftime('%d %b %Y  %H:%M IST')}")
    st.divider()

    controls = load_controls()
    st.markdown("### Controls")
    st.caption("3 controls only — everything else is automated")

    kill_switch = st.toggle(
        "🔴 Kill switch",
        value=controls.get("kill_switch", False),
        key="kill_switch",
        help="Stops all new entries. Open positions still managed.",
    )
    score_threshold = st.slider(
        "Min score to enter",
        min_value=5.0, max_value=9.5,
        value=float(controls.get("min_score_entry", MIN_SCORE_ENTRY)),
        step=0.5, key="score_threshold",
    )
    max_pos = st.slider(
        "Max positions",
        min_value=1, max_value=8,
        value=int(controls.get("max_positions", MAX_POSITIONS)),
        step=1, key="max_positions_slider",
    )

    new_controls = {"kill_switch": kill_switch, "min_score_entry": score_threshold, "max_positions": max_pos}
    if new_controls != {k: controls.get(k) for k in new_controls}:
        save_controls(new_controls)
        st.toast("Controls updated ✅")

    if kill_switch:
        st.error("KILL SWITCH ON — no new entries")

    st.divider()
    st.markdown("### Capital")
    deployed_pct = state.get_deployment_pct()
    st.progress(min(deployed_pct / 100, 1.0))
    st.caption(
        f"₹{state.get_deployed_capital():,.0f} deployed\n"
        f"₹{state.get_available_capital():,.0f} available"
    )
    st.divider()
    st.caption("Auto-refreshes every 10s")
    if st.button("🔄 Refresh"):
        st.rerun()

# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("# 📈 NSE Trading System")

tab1, tab2 = st.tabs(["📊 Live Trading", "📈 Analytics"])

with tab1:
    render_live_tab(state)

with tab2:
    render_analytics_tab(state, chroma)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10_000, key="dashboard_refresh")
except ImportError:
    pass
