import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""
NSE Trading System Dashboard — Streamlit entry point.
Run with: streamlit run dashboard/app.py

Read-only window into the trading system.
3 human controls only: kill switch, score threshold, max positions.
Auto-refreshes every 10 seconds.
"""
import streamlit as st
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from memory.trade_state import TradeStateManager
from memory.chroma_client import ChromaMemory
from config.settings import TIMEZONE, MIN_SCORE_ENTRY, MAX_POSITIONS, CAPITAL

IST = ZoneInfo(TIMEZONE)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Trading System",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stMetric { background: #f8f9fa; border-radius: 8px; padding: 12px; }
    .block-container { padding-top: 1rem; }
    div[data-testid="stSidebar"] { min-width: 260px; }
</style>
""", unsafe_allow_html=True)


# ── Shared state path ─────────────────────────────────────────────────────────
CONTROL_FILE = Path("./system_controls.json")


def load_controls() -> dict:
    """Load current control settings from file (shared with main.py)."""
    defaults = {
        "kill_switch":        False,
        "min_score_entry":    MIN_SCORE_ENTRY,
        "max_positions":      MAX_POSITIONS,
        "last_updated":       "",
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
    """Save control settings to file so main.py picks them up."""
    controls["last_updated"] = datetime.now(IST).isoformat()
    with open(CONTROL_FILE, "w") as f:
        json.dump(controls, f, indent=2)


# ── Init resources ────────────────────────────────────────────────────────────
@st.cache_resource
def get_state() -> TradeStateManager:
    return TradeStateManager()

@st.cache_resource
def get_chroma() -> ChromaMemory:
    return ChromaMemory()


state  = get_state()
chroma = get_chroma()


# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## NSE Trading System")

    now = datetime.now(IST)
    market_open = now.weekday() < 5 and now.hour >= 9 and (now.hour < 15 or (now.hour == 15 and now.minute <= 30))
    status_text = "Market open" if market_open else "Market closed"
    status_color = "green" if market_open else "red"
    st.markdown(f"**Status:** :{status_color}[{status_text}]")
    st.caption(f"{now.strftime('%d %b %Y  %H:%M:%S IST')}")

    st.divider()

    # Load current controls
    controls = load_controls()

    st.markdown("### System controls")
    st.caption("Only 3 controls — everything else is automated")

    # 1. Kill switch
    kill_switch = st.toggle(
        "🔴 Kill switch — stop new entries",
        value=controls.get("kill_switch", False),
        key="kill_switch",
        help="Turn ON to stop all new entries. Open positions continue to be managed.",
    )

    # 2. Score threshold
    score_threshold = st.slider(
        "Min score to enter",
        min_value=5.0,
        max_value=9.5,
        value=float(controls.get("min_score_entry", MIN_SCORE_ENTRY)),
        step=0.5,
        key="score_threshold",
        help="Raise on volatile/choppy days. Lower on slow days with good setups.",
    )

    # 3. Max positions
    max_pos = st.slider(
        "Max concurrent positions",
        min_value=1,
        max_value=8,
        value=int(controls.get("max_positions", MAX_POSITIONS)),
        step=1,
        key="max_positions_slider",
        help="Reduce on uncertain days. Increase when system is performing well.",
    )

    # Save controls when anything changes
    new_controls = {
        "kill_switch":     kill_switch,
        "min_score_entry": score_threshold,
        "max_positions":   max_pos,
    }
    if new_controls != {k: controls.get(k) for k in new_controls}:
        save_controls(new_controls)
        st.toast("Controls updated", icon="✅")

    if kill_switch:
        st.error("KILL SWITCH IS ON — No new entries will be placed")

    st.divider()

    # Capital summary
    st.markdown("### Capital")
    deployed_pct = state.get_deployment_pct()
    st.progress(min(deployed_pct / 100, 1.0))
    st.caption(
        f"₹{state.get_deployed_capital():,.0f} deployed  \n"
        f"₹{state.get_available_capital():,.0f} available"
    )

    st.divider()

    # Refresh info
    st.caption("Dashboard auto-refreshes every 10 seconds")
    if st.button("Refresh now"):
        st.rerun()


# ── Main content ──────────────────────────────────────────────────────────────
st.markdown("# 📈 NSE Trading System")

tab1, tab2 = st.tabs(["Live trading", "Setup analytics"])

with tab1:
    from dashboard.live_tab import render_live_tab
    render_live_tab(state)

with tab2:
    from dashboard.analytics_tab import render_analytics_tab
    render_analytics_tab(state, chroma)


# ── Auto-refresh every 10 seconds ────────────────────────────────────────────
# Uses streamlit-autorefresh if installed, else manual refresh button
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10_000, key="dashboard_refresh")
except ImportError:
    pass
