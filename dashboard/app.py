"""
NSE Trading System Dashboard — Streamlit entry point.
Run with: streamlit run dashboard/app.py

Read-only window into the trading system.
3 human controls: kill switch, score threshold, max positions.
Auto-refreshes every 10 seconds.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

# ── Page config — MUST be first st.* call ────────────────────────────────────
st.set_page_config(
    page_title="NSE Trading",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Mobile + dark-mode CSS ────────────────────────────────────────────────────
st.markdown("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<style>
    /* ── Mobile responsive ── */
    @media (max-width: 768px) {
        .block-container { padding: 0.4rem 0.4rem !important; }
        div[data-testid="column"] { min-width: 44% !important; }
        section[data-testid="stSidebar"] { width: 85vw !important; }
        .stMetric { font-size: 0.8rem !important; }
        h1 { font-size: 1.3rem !important; }
        h3, h4 { font-size: 0.95rem !important; }
        .stTabs [data-baseweb="tab"] { font-size: 0.78rem; padding: 5px 8px; }
        div[data-testid="stDataFrame"] { font-size: 0.72rem !important; }
        .stButton button { width: 100%; }
    }
    /* ── General styling ── */
    .block-container { padding-top: 0.8rem; }
    .stMetric {
        background: #1E1E2E;
        border-radius: 10px;
        padding: 12px 16px;
        border: 1px solid #2A2A3E;
    }
    .stMetric label { font-size: 0.78rem !important; color: #9ca3af; }
    div[data-testid="stSidebar"] { min-width: 260px; }
    /* ── Larger tap targets on mobile ── */
    .stTabs [data-baseweb="tab-list"] { gap: 6px; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 14px;
        border-radius: 8px;
        min-height: 40px;
    }
    /* ── Scrollable tables on mobile ── */
    div[data-testid="stDataFrame"] { overflow-x: auto; }
</style>
""", unsafe_allow_html=True)

import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

# ── Tab imports (all at top to avoid double set_page_config) ─────────────────
from dashboard.live_tab      import render_live_tab
from dashboard.analytics_tab import render_analytics_tab
from dashboard.learning_tab  import render_learning_tab
from dashboard.shadow_tab    import render_shadow_tab

from memory.trade_state  import TradeStateManager
from memory.chroma_client import ChromaMemory
from config.settings import (
    TIMEZONE, MIN_SCORE_ENTRY, MAX_POSITIONS, CAPITAL, PAPER_TRADING,
)

IST = ZoneInfo(TIMEZONE)
CONTROL_FILE = Path("./system_controls.json")


# ── Controls persistence ──────────────────────────────────────────────────────

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


# ── Cached resources ──────────────────────────────────────────────────────────

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
    weekday     = now.weekday()
    hour        = now.hour
    minute      = now.minute
    market_open = (
        weekday < 5
        and (hour > 9 or (hour == 9 and minute >= 15))
        and (hour < 15 or (hour == 15 and minute <= 30))
    )
    st.markdown(
        f"**Status:** {'🟢 Market open' if market_open else '🔴 Market closed'}"
        f"{'  |  🧪 Paper mode' if PAPER_TRADING else '  |  🔴 LIVE mode'}"
    )
    st.caption(f"{now.strftime('%d %b %Y  %H:%M IST')}")

    # Market breadth mini-indicator in sidebar
    breadth_cache = st.session_state.get("last_breadth", {})
    if breadth_cache:
        bs  = breadth_cache.get("breadth_pct", 50)
        lbl = breadth_cache.get("breadth_label", "NEUTRAL")
        col = "#00C853" if lbl == "BULLISH" else "#F44336" if lbl == "BEARISH" else "#FFD600"
        st.markdown(
            f"<div style='font-size:0.8em;color:{col};'>Breadth: {bs:.0f}% — {lbl}</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    controls = load_controls()
    st.markdown("### ⚙️ Controls")
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
        min_value=1, max_value=10,
        value=int(controls.get("max_positions", MAX_POSITIONS)),
        step=1, key="max_positions_slider",
    )

    new_controls = {
        "kill_switch":     kill_switch,
        "min_score_entry": score_threshold,
        "max_positions":   max_pos,
    }
    if new_controls != {k: controls.get(k) for k in new_controls}:
        save_controls(new_controls)
        st.toast("Controls saved ✅")

    if kill_switch:
        st.error("🛑 KILL SWITCH ON — no new entries")

    # ── Effective threshold display ───────────────────────────────────────────
    # The slider value IS what the engine will use — show it as confirmed.
    # Only show an override warning if system_status.json is FRESH (from today,
    # written within the last 15 min) AND the engine raised the threshold above
    # what the slider says (conservative mode / midday lull).
    status_file  = Path("./system_status.json")
    today_str    = now.strftime("%H")          # hour — used to check freshness
    consec       = 0
    regime_lbl   = "—"
    last_tick_str = "—"
    override_active = False

    if status_file.exists():
        try:
            with open(status_file) as f:
                sys_status = json.load(f)

            eff_thresh   = sys_status.get("effective_threshold", score_threshold)
            consec       = sys_status.get("consecutive_losses", 0)
            is_midday    = sys_status.get("midday_mode", False)
            last_tick_str = sys_status.get("last_tick", "—")
            regime_lbl   = sys_status.get("regime", "—").upper()

            # Check freshness: status file must have been written today
            # (last_tick is "HH:MM:SS" — if market was running today the file is fresh)
            file_mtime = status_file.stat().st_mtime
            file_age_min = (datetime.now(IST).timestamp() - file_mtime) / 60

            status_is_fresh = file_age_min < 15   # written within last 15 min

            if status_is_fresh and eff_thresh > score_threshold:
                # Engine is actively overriding the slider — warn user
                reason = "midday lull" if is_midday and consec < 3 \
                         else f"{consec} consecutive losses"
                st.warning(
                    f"⚠️ Engine overriding to **{eff_thresh}** "
                    f"(your slider: {score_threshold})\n"
                    f"Reason: {reason}"
                )
                override_active = True
        except Exception:
            pass

    if not override_active:
        # Slider value is what the engine uses — confirm it clearly
        st.success(f"✅ Threshold active: **{score_threshold}**")

    if last_tick_str != "—":
        st.caption(
            f"Regime: {regime_lbl}  •  "
            f"Last tick: {last_tick_str}  •  "
            f"Streak: {consec} loss(es)"
        )

    st.divider()

    # ── Capital bar ───────────────────────────────────────────────────────────
    st.markdown("### 💰 Capital")
    deployed_pct = state.get_deployment_pct()
    st.progress(min(deployed_pct / 100, 1.0),
                text=f"{deployed_pct:.1f}% deployed")
    st.caption(
        f"Total:  ₹{CAPITAL:,.0f}\n"
        f"In use: ₹{state.get_deployed_capital():,.0f}\n"
        f"Free:   ₹{state.get_available_capital():,.0f}"
    )

    st.divider()

    # ── Quick stats ───────────────────────────────────────────────────────────
    summary = state.get_summary()
    if summary["total"] > 0:
        st.markdown("### 📊 All-time")
        st.caption(
            f"Trades: {summary['total']}  |  "
            f"Win: {summary['win_rate']}%  |  "
            f"Avg R: {summary['avg_r']:+.2f}  |  "
            f"P&L: ₹{summary['total_pnl']:+,.0f}"
        )

    st.divider()
    st.caption("Auto-refreshes every 10s")
    if st.button("🔄 Refresh now"):
        st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("# 📈 NSE Intraday Trading System")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Live Trading",
    "📈 Analytics",
    "🎓 Learning Lab",
    "👀 Shadow Mode",
])

with tab1:
    render_live_tab(state)

with tab2:
    render_analytics_tab(state, chroma)

with tab3:
    render_learning_tab()

with tab4:
    render_shadow_tab()


# ── Auto-refresh ──────────────────────────────────────────────────────────────
# Try the proper package first; if not installed fall back to a JS meta-refresh
_refreshed = False
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10_000, key="dashboard_refresh")
    _refreshed = True
except ImportError:
    pass

if not _refreshed:
    # JS fallback: reloads the page every 10 seconds without any extra package
    st.markdown(
        """
        <script>
            setTimeout(function() { window.location.reload(); }, 10000);
        </script>
        """,
        unsafe_allow_html=True,
    )
