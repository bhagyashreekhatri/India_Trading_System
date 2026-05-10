import os
from dotenv import load_dotenv

load_dotenv()

# ─── Broker ───────────────────────────────────────────────────────────────────
KITE_API_KEY        = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET     = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN   = os.getenv("KITE_ACCESS_TOKEN", "")

# ─── AI / LLM (Groq — used ONLY for news sentiment) ──────────────────────────
GROQ_API_KEY        = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL          = "llama-3.3-70b-versatile"

# ─── News ─────────────────────────────────────────────────────────────────────
NEWS_API_KEY        = os.getenv("NEWS_API_KEY", "")

# ─── Telegram alerts ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR  = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")

# ─── Trading parameters ───────────────────────────────────────────────────────
PAPER_TRADING           = True
CAPITAL                 = 1_500_000
MAX_POSITIONS           = 10              # raised for paper trading (was 5)
MAX_SECTOR_EXPOSURE     = 0.30
RISK_PER_TRADE_PCT      = 0.01            # 1% of capital per trade
MAX_POSITION_VALUE_PCT  = 0.10            # 10% per trade (₹1.5L at ₹15L) — fits 10 positions in capital
                                          # Was 0.20 = ran out of capital after 5-6 trades, last entries sized to qty=1
MIN_RISK_PER_TRADE_PCT  = 0.0003          # 0.03% = ₹450 — pure paranoia floor (qty=1 stops here)
                                          # The position-value floor below does the real work.
MIN_POSITION_VALUE_PCT  = 0.03            # 3% of CAPITAL = ₹45k — skip+watchlist below this
TARGET_R1               = 0.7            # TP1 — exit 50% here. Fix #48: was 1.0.
                                         # File 04 showed 71% of trades stalled
                                         # before reaching 1R. 0.7R lets us lock
                                         # partial profit on +0.5% moves which
                                         # happen far more often. Remaining 50%
                                         # trails toward TP2 risk-free (SL→BE).
TARGET_R2               = 2.0            # TP2 — exit remaining 50% here
SCAN_INTERVAL_MIN       = 3              # scan every 3 minutes (was 5)

# ─── Trailing Stop Loss ───────────────────────────────────────────────────────
TRAILING_SL_ENABLED     = True
TRAILING_ATR_MULTIPLIER = 0.5            # trail SL by 0.5× ATR after TP1 hit
BREAKEVEN_AFTER_TP1     = True           # move SL to entry after TP1 hit

# ─── Opening Range Breakout ───────────────────────────────────────────────────
ORB_MINUTES             = 15             # 15-min ORB (9:15–9:30)
ORB_MIN_RANGE_PCT       = 0.3            # minimum range to be tradeable
ORB_MAX_RANGE_PCT       = 2.5            # skip if range too wide (volatile open)

# ─── Scoring thresholds ───────────────────────────────────────────────────────
MIN_SCORE_ENTRY         = 7.0            # Grade A minimum
MIN_SCORE_ENTRY_CONSERVATIVE = 8.0      # used after 3 consecutive losses
MIN_SCORE_WATCHLIST     = 5.0
PROXIMITY_MAX_PCT       = 0.007
LEADER_PROXIMITY_MAX_PCT = 0.015          # Fix #19 — relaxed for strong movers (≥3% chg, RS≥1.5%)
LEADER_DAY_CHG_PCT      = 3.0
LEADER_RS_DELTA_PCT     = 1.5

# ─── Volume thresholds ────────────────────────────────────────────────────────
VOLUME_MIN_RATIO        = 1.2
VOLUME_STRONG_RATIO     = 1.5
VOLUME_VERY_STRONG      = 2.5
MOMENTUM_BO_MIN_RVOL    = 2.0   # Fix #22 (A1) → Fix #37 1.7 → Fix #56 back to 2.0.
                                # 280-trade audit: gross +0.075R / net -0.05R per
                                # trade. Need to lift mean R to +0.30+. Tightening
                                # RVOL floor is one lever. 1.7 was chasing fakeouts.

# ─── Phase A — Setup gating + momentum tightening (Fix #56) ──────────────────
# 280-trade audit (docs/08_Findings_From_280_Trades.md):
#   - momentum_breakout: n=147, WR 66.7%, gross +0.159R — only viable setup
#   - other 6 setups: gross-negative or break-even, paying full ₹760 cost on every fire
#   - 71% stalled-no-movement rate UNCHANGED despite 55 fixes
# Decision: disable 6 weak setups (keep their detection ON for confluence count,
# but block them from entering trades). Tighten momentum_breakout to require
# either confluence ≥ 2 OR top-3 sector membership.
SETUP_DISARMED_LIST = {
    "recovery_setup",     # n=72, gross -0.015R — bleeding
    "failed_breakdown",   # n=31, WR 29% — too low
    "vwap_reclaim",       # n=12, gross -0.022R — small sample, bleeding
    "trend_pullback",     # n=10, gross -0.132R — bleeding
    "vwap_pullback",      # n=7, WR 28.6% — too low
    "range_breakout",     # n=1, irrelevant sample
    "inside_bar_break",   # rolled into momentum_breakout via confluence
}
MOMENTUM_BO_MIN_CONFLUENCE        = 2     # require ≥ 2 confluence OR top-3 sector
MOMENTUM_BO_REQUIRE_PRIORITY      = True  # global flag — set False to bypass for emergency rollback

# ─── Score-based sizing tiers (Fix #23 / A6) ─────────────────────────────────
# Higher conviction → larger position. Scales the per-trade risk cap (and thus
# qty). A++ = full, A+ = 75%, A = 50%, B = 25%. Combines multiplicatively with
# CONSERVATIVE_SIZE_PCT after consec losses.
SCORE_SIZE_TIERS = {
    "A++": 1.00,
    "A+":  0.75,
    "A":   0.50,
    "B":   0.25,
    "C":   0.00,
}

# ─── Loser-streak gradient dampener (Fix #31 / C2) ───────────────────────────
# Smooth de-risking — replaces the binary cliff at 3 losses (was 1.0 → 0.5).
# Index = consecutive_losses; values clamp at 4+ losses.
LOSER_STREAK_SIZE_TIERS = [
    1.00,   # 0 losses
    0.85,   # 1 loss
    0.70,   # 2 losses
    0.50,   # 3 losses (matches old CONSERVATIVE_SIZE_PCT)
    0.30,   # 4+ losses
]

# ─── Time-of-day score gate nudges (Fix #24 / A5) ────────────────────────────
# From file 04 trade-log analysis (151 trades, 6 sessions):
#   Hour 12 IST: 64.7% WR, 76.7% of total P&L → BEST window
#   Hour 11 IST: 72.7% WR, +₹16k → strong
#   Hour 13 IST: 70%   WR, +₹2.5k → fine
#   Hour 14 IST: 54.5% WR
#   Hour 9  IST: 50.9% WR, 38% of trades, only 5% of P&L → noisy hour
#   Hour 10 IST: 58.8% WR, only losing hour
# Nudges applied to MIN_SCORE_ENTRY at the top of _score_signals.
HOUR_GATE_NUDGES = {
    9:  +0.3,   # Loud noise — raise the bar (was +0.5; relaxed Fix #37)
    10: +0.2,   # Only-losing hour — raise the bar (was +0.3; relaxed Fix #37)
    11: -0.0,   # Solid — neutral
    12: -0.2,   # Best hour — lower the bar
    13:  0.0,
    14:  0.0,
}

# ─── Market breadth thresholds ───────────────────────────────────────────────
BREADTH_BULLISH         = 0.65           # >65% stocks above VWAP → lean long
BREADTH_BEARISH         = 0.40           # <40% → avoid new longs
BREADTH_SAMPLE_SIZE     = 50             # stocks sampled for breadth score

# ─── Consecutive loss protection ─────────────────────────────────────────────
MAX_CONSECUTIVE_LOSSES  = 3              # after 3 losses → go conservative
CONSERVATIVE_SIZE_PCT   = 0.50          # reduce position size by 50%

# ─── Daily-loss kill switch ──────────────────────────────────────────────────
DAILY_LOSS_KILL_PCT     = 0.025          # 2.5% of CAPITAL → freeze new entries for the day
                                         # Existing positions still managed (SL/TP/trail).
                                         # Auto-resets at next session boot.

# ─── Daily-profit lockout (Fix #11) — protect the day's gains ────────────────
DAILY_PROFIT_LOCKOUT_PCT = 0.030         # 3% (₹45k) → no new entries today; manage open
DAILY_PROFIT_TIGHTEN_PCT = 0.020         # 2% (₹30k) → raise score gate to conservative (8.0)

# ─── Confluence multiplier (Fix #5) ──────────────────────────────────────────
# When multiple setup detectors fire on the same stock at the same bar, the
# Raw score is multiplied before the regime multiplier. This is PROJECT_MEMORY
# next-cycle priority #1 — confluence is one of the strongest signal-quality
# tells in scalping (e.g., "VWAP reclaim + momentum breakout + tight range
# break" all on the same candle is much stronger than any one in isolation).
CONFLUENCE_MULTIPLIER_2 = 1.15           # 2 setups on same bar → +15% Raw
CONFLUENCE_MULTIPLIER_3 = 1.25           # 3+ setups → +25% Raw

# ─── Scanner turnover filter (Fix #5) ────────────────────────────────────────
# Replaces the old "vol >= 10000 shares" check, which let ₹50 stocks and
# ₹5,000 stocks through on the same bar. Turnover (price × volume) is the
# right liquidity signal for a scalper — ensures the trade can actually fill.
SCAN_MIN_TURNOVER       = 5_000_000      # ₹50 lakh minimum on the day so far

# ─── Tick size (Fix #7) ──────────────────────────────────────────────────────
# NSE equity tick is ₹0.05 for stocks priced ≥ ₹1; sub-₹100 stocks may also use
# ₹0.05 (the exchange has been migrating toward uniform 0.05). Live orders with
# non-tick-aligned prices get rejected by Kite. Paper mode tolerates this; live
# does not. Helper functions live in scoring/engine.py.
TICK_SIZE               = 0.05

# ─── Paper-mode slippage simulation (Fix #16) ────────────────────────────────
# Real broker fills are NEVER at LTP. Even after Fix #13 (refetching live LTP),
# paper P&L is still optimistic because we're not modelling actual queue
# position or stop-fill drag. These bps figures simulate that to keep paper
# results honest and ready us for live. Skipped automatically when
# PAPER_TRADING=False (real broker provides real slippage).
PAPER_SLIPPAGE_ENTRY_BPS  = 5    # 0.05% — entry filled slightly worse than LTP
PAPER_SLIPPAGE_STOP_BPS   = 10   # 0.10% — stops fill worse (gap risk + market order)
PAPER_SLIPPAGE_TARGET_BPS = 3    # 0.03% — targets fill near LTP (limit order)

# ─── Spread filter (Fix #43 / P1) ────────────────────────────────────────────
# Hard reject if bid-ask spread exceeds this %. Wide spreads silently destroy
# scalp R:R — a 0.10% spread on a 0.7% stop eats 28% of TP1's gross. Names
# with spread > 0.10% should not be scalped at all.
ENTRY_MAX_SPREAD_PCT      = 0.10

# ─── RAG proven-loser veto (Fix #44 / P2) ────────────────────────────────────
# Hard skip if (setup_type, regime) has ≥N historical trades AND win-rate is
# below the floor. Stronger than the -0.5 score nudge in Fix #41 — proven
# losers shouldn't even be candidates.
RAG_VETO_MIN_TRADES       = 10
RAG_VETO_MAX_WINRATE      = 35.0

# ─── Asymmetric cooldown (Fix #45 / P10) ─────────────────────────────────────
# After a LOSS: longer cooldown — anti-revenge. After a WIN: shorter cooldown
# — the stock is in motion, second-leg continuation often valid.
COOLDOWN_AFTER_LOSS_MIN   = 45
COOLDOWN_AFTER_WIN_MIN    = 15

# ─── Correlation filter ───────────────────────────────────────────────────────
MAX_SAME_SECTOR_POSITIONS = 3            # max positions in same sector

# ─── Time filters ─────────────────────────────────────────────────────────────
NO_ENTRY_BEFORE_MIN     = 5              # skip 9:15–9:20 (liquidity)
ORB_WINDOW_END          = "09:30"        # ORB setups only before this
PRIME_TIME_START        = "09:30"        # best time for momentum/reclaim
PRIME_TIME_END          = "11:30"        # peak volume window
MIDDAY_AVOID_START      = "13:00"        # lunch lull — be selective
MIDDAY_AVOID_END        = "14:00"        # resume normal scanning
NO_NEW_ENTRY_AFTER      = "13:30"        # Fix #47 — was 14:45; late entries can't
                                         # reach TP1 before EOD partial-unwind window
                                         # AND the 15:00 force-close. Every entry now
                                         # gets ≥75 min runway before exit pressure.
MARKET_OPEN             = "09:15"
MARKET_CLOSE            = "15:30"
EOD_CLOSE_TIME          = "15:00"        # close all positions by 3 PM

# ─── Sector definitions ───────────────────────────────────────────────────────
SECTOR_LEADERS = {
    "BANKING":    ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN"],
    "IT":         ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "AUTO":       ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO"],
    "PHARMA":     ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP"],
    "FMCG":       ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR"],
    "METAL":      ["TATASTEEL", "HINDALCO", "JSWSTEEL", "COALINDIA", "VEDL"],
    "ENERGY":     ["RELIANCE", "ONGC", "BPCL", "IOC", "NTPC"],
    "FINANCIAL":  ["BAJFINANCE", "BAJAJFINSV", "HDFCAMC", "LICHSGFIN", "MUTHOOTFIN"],
}

# ─── Timezone ─────────────────────────────────────────────────────────────────
TIMEZONE                = "Asia/Kolkata"
