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

# ─── Phase D — Pending pullback retest (Fix #57) ─────────────────────────────
# 280-trade smoke test (docs/09_Phase_A_Smoke_Test.md) showed Phase A filters
# improve mean R only +0.04 (0.075→0.114). 71% stall rate is structural —
# entries land at exhaustion points after the move has already happened.
# Phase D addresses entry timing: when a high-score signal fires but the price
# has run past the trigger (proximity_failed), instead of skipping, mark it
# PENDING_RETEST and watch 10 min for price to come back to the trigger ± 0.3%.
# On retest, fire the entry. This catches NBCC-class moves cleanly.
PENDING_RETEST_ENABLED         = True
PENDING_RETEST_WINDOW_MIN      = 10      # watch for retest up to 10 min
PENDING_RETEST_TOLERANCE_PCT   = 0.003   # retest = price within ±0.3% of trigger
PENDING_RETEST_MAX_DRIFT_PCT   = 0.020   # if price runs > 2% past trigger, drop (chase no longer viable)
PENDING_RETEST_LOG_PATH        = "logs/pending_retest.jsonl"

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


# ─── Phase 3.0.1 — Weekly / Monthly safety nets (Phase 3 live probe prep) ────
# See docs/23_Phase3_Live_Probe_Operations_2026-05-12.md §5 + §11.
# These are upper-bound circuit breakers that should NEVER fire in normal
# operation. Their job is to pause the system before a chain of bad sessions
# compounds. All thresholds are pct of CAPITAL, scale automatically.
WEEKLY_LOSS_KILL_PCT      = 0.075        # 7.5% of CAPITAL → auto-pause until manual review
CONSECUTIVE_LOSING_DAYS_PAUSE = 5        # 5 losing days in a row → auto-pause
MONTHLY_NEG_R_REVIEW      = True         # on last trading day of month, EOD job flags if mean R<0

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
NO_NEW_ENTRY_AFTER      = "14:45"        # Fix #47 set this to 13:30 because the
                                         # BUGGY partial-unwind block (Fix #34) was
                                         # also firing at the same time, killing
                                         # late entries with 15 min runway. Fix #59
                                         # removed that bug. Fix #60: roll the entry
                                         # cutoff back to 14:45 — captures the
                                         # 13:30-14:45 window we were forfeiting,
                                         # gives 30 min runway to 15:15 force-close.
MARKET_OPEN             = "09:15"
MARKET_CLOSE            = "15:30"
EOD_CLOSE_TIME          = "15:15"        # Fix #59 — was 15:00, gave up the final 30 min
                                         # of intraday closing momentum unnecessarily.
                                         # NSE closing 30 min has institutional flows,
                                         # expiry hedging, closing-print activity.
                                         # 15:15 force-close gives us 5 min control buffer
                                         # before Zerodha MIS auto-square at 15:20.

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


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 0 REBUILD — new constants (2026-05-11)
# These replace the deleted ScoringEngine. Validated on 584 NIFTY sessions
# across 30 months (Jan 2024 – May 2026). See docs/16_30Month_Final_Analysis.
# ═══════════════════════════════════════════════════════════════════════════

# ── 10:15 IST macro filter ────────────────────────────────────────────────────
# The clean read of where institutional money has positioned itself for the day.
# Statistical backing (n=584 sessions):
#   >+0.5%  → 98% close positive (n=82)   STRONG_GREEN — full size
#   >+0.3%  → 72% close positive (n=158)  GREEN — full size
#   ±0.3%  → coin-flip (n=212)            YELLOW — half size, A++ only
#   <-0.3% → 74% close negative (n=141)   RED — skip longs
#   <-0.5% → 89% close negative (n=83)    STRONG_RED — definitely skip
MACRO_FILTER_TIME_IST          = "10:15"
MACRO_STRONG_GREEN_THRESHOLD   = 0.5    # %, NIFTY vs prev close
MACRO_GREEN_THRESHOLD          = 0.3
MACRO_RED_THRESHOLD            = -0.3
MACRO_STRONG_RED_THRESHOLD     = -0.5


# ── Order book depth filter (universal pre-entry) ────────────────────────────
# 5-level aggregate bid_qty / sell_qty (NOT top-of-book, which can be spoofed
# by a single large order). Validated finding: top-of-book ratio is noise,
# 5-level depth is structural commitment.
ORDER_BOOK_RATIO_MIN           = 1.5


# ── Universal spread filter ──────────────────────────────────────────────────
# (Same threshold as Fix #43's ENTRY_MAX_SPREAD_PCT but used by conviction_engine.)
# 0.10% spread on a 0.7% stop eats 28% of TP1 — wide spreads silently destroy
# scalp R:R. Hard skip.
SPREAD_MAX_PCT                 = 0.0010   # 0.10%


# ── Stock-level HOD proximity (Phase 1.1) ────────────────────────────────────
# A stock trading > 0.5% below today's high is structurally extended off the
# top — chasing risk. Validated by the 30-month research: entries should fire
# at fresh HOD prints, not after the move has already happened. Max distance
# from HOD for a valid entry candidate.
STOCK_HOD_PROXIMITY_PCT        = 0.005    # 0.5% — must be near fresh HOD


# ── Per-stock FHH break requirement (Phase 1.1) ──────────────────────────────
# When True, the conviction engine requires the SYMBOL's own first-hour-high
# to be cleanly broken (not just NIFTY's). This is the validated 30-month
# entry trigger: NIFTY macro context + individual stock breaking its own
# structural level. Set False to fall back to NIFTY-only FHH (Phase 0).
REQUIRE_STOCK_FHH_BREAK        = True


# ── Pre-TP1 trail SL (Phase 1.2) ──────────────────────────────────────────
# When a trade is favorable by +0.5R AND has held that level for ≥10 minutes,
# tighten SL to entry (breakeven). This is the "lock in conviction" move that
# protected the MAXHEALTH-class trades that went +₹421 then reversed to -₹515
# in the original observation set. Fixes the worst-loss mode where a trade
# was profitable mid-flight but the SL was never moved.
PRE_TP1_TRAIL_ENABLED          = True
PRE_TP1_TRAIL_TRIGGER_R        = 0.5      # tighten when pnl_r ≥ +0.5
PRE_TP1_TRAIL_HOLD_MIN         = 10       # need to hold +0.5R for 10 min before tightening


# ── Whipsaw freeze (Phase 1.3) ────────────────────────────────────────────
# Validated 30-month finding: when NIFTY breaks BOTH its first-hour high AND
# its first-hour low (whipsaw signature), 70% of those days close flat ±0.5%.
# Block all new entries when this signature is detected on the index.
WHIPSAW_FREEZE_ENABLED         = True


# ── Conviction-engine sizing (replaces SCORE_SIZE_TIERS) ────────────────────
# Risk and target in ₹ per trade. Mapped to position size via stop distance.
# Tier S = STRONG_GREEN + FHH (100% historical accuracy, n=44)
# Tier A = GREEN + FHH        (97% historical accuracy, n=38)
# Tier B = YELLOW + FHH + A++  (88% historical accuracy, n=98) — half size
CONVICTION_RISK_INR = {
    "S": 1500.0,
    "A": 1500.0,
    "B":  750.0,
}
CONVICTION_TARGET_INR = {
    "S": 3000.0,
    "A": 2500.0,
    "B": 1500.0,
}


# ── Phase 0 feature flag ─────────────────────────────────────────────────────
# When True, the conviction-engine path is the entry decision authority.
# When False, the old _score_signals path runs (allows shadow-mode validation
# before fully cutting over).
USE_CONVICTION_ENGINE          = True


# ── Phase 2.1 — Discovery Engine (top-mover scanner) ─────────────────────────
# See docs/19_Discovery_Engine_Spec_2026-05-12.md.
# Spec evidence: 2026-05-12 JINDRILL +7.81%, OIL India +7.66%, CMSINFO +5.26%
# were the cleanest movers of the day — all OUTSIDE the 150-stock hardcoded
# universe. The agent was structurally blind to the highest-conviction longs.
#
# Defaults are conservative. SHADOW MODE (DISCOVERY_ALLOW_TRADES=False) keeps
# the engine running + logging without feeding discovered names to crew.py's
# trading pipeline. After 3-5 sessions of shadow logs look clean, flip the
# flag to True for live (still tier-capped at B- inside conviction_engine).
DISCOVERY_SCAN_INTERVAL_SEC      = 300      # 5 min between scans
DISCOVERY_FIRST_SCAN_DELAY_MIN   = 15       # skip 09:15-09:30 open auction noise
DISCOVERY_MIN_PCT_MOVE           = 2.5      # |pct_change| threshold to admit
DISCOVERY_MIN_VOLUME_RATIO       = 1.5      # today_vol / 20d_avg_vol
DISCOVERY_MIN_AVG_TURNOVER_INR   = 10e7     # ₹10 crore avg daily turnover
DISCOVERY_MAX_SPREAD_PCT         = 0.0015   # 0.15% (slightly looser than entry SPREAD_MAX_PCT)
DISCOVERY_MAX_NEW_ADDS_PER_SCAN  = 5
DISCOVERY_MAX_TOTAL              = 15       # max live-discovery names at once
DISCOVERY_MAX_PER_SESSION        = 40       # cumulative session cap
DISCOVERY_BLACKLIST_LOSS_THRESHOLD = 2      # losses before auto-blacklist
DISCOVERY_BLACKLIST_DAYS         = 7        # blacklist duration (trading days)
DISCOVERY_ALLOW_TRADES           = False    # SHADOW MODE — flip to True after validation


# ── Phase 2.3 — Stock-level decoupling rule ──────────────────────────────────
# See docs/21_Stock_Decoupling_Spec_2026-05-12.md and agents/stock_decoupling.py
#
# On a macro RED / STRONG_RED day, a single stock that is ALL OF:
#   - +STOCK_DECOUPLING_MIN_PCT (e.g. 4.0%) above prev close
#   - on STOCK_DECOUPLING_MIN_VOL_RATIO+ (e.g. 1.5x) avg volume
#   - within STOCK_DECOUPLING_MAX_PULL_FROM_HOD_PCT of intraday high
#   - whose sector index is NOT below STOCK_DECOUPLING_SECTOR_FLOOR_PCT
#   - with its own first-hour high cleanly broken
# may be admitted at tier B- (half-size of B). Catches the 2026-05-12 ONGC
# +5.93% case that the binary macro filter blocked.
STOCK_DECOUPLING_ENABLED               = False   # SHADOW MODE — log only until validated
STOCK_DECOUPLING_MIN_PCT               = 4.0     # stock %chg vs prev close
STOCK_DECOUPLING_MIN_VOL_RATIO         = 1.5     # today_vol / 20d_avg_vol
STOCK_DECOUPLING_MAX_PULL_FROM_HOD_PCT = 0.5     # LTP within X% of intraday high
STOCK_DECOUPLING_SECTOR_FLOOR_PCT      = -1.0    # sector chg ≥ this floor

# Symbol-sector → NIFTY sector-index name mapping. Symbols not in this map
# fall through with sector_quote=None which the rule treats as PASS (neutral).
# Keep the mapping conservative — only sectors that map cleanly to a NIFTY
# index get a sector check.
SYMBOL_SECTOR_TO_INDEX = {
    "IT":        "NIFTY IT",
    "BANKING":   "NIFTY BANK",
    "NBFC":      "NIFTY FIN SERVICE",
    "AUTO":      "NIFTY AUTO",
    "AUTO_ANC":  "NIFTY AUTO",
    "PHARMA":    "NIFTY PHARMA",
    "METALS":    "NIFTY METAL",
    "OIL_GAS":   "NIFTY ENERGY",
    "POWER":     "NIFTY ENERGY",
    "FMCG":      "NIFTY FMCG",
}

# ═══════════════════════════════════════════════════════════════════════════
# DEPRECATED — to be removed after conviction-engine forward-validation:
#   SCORE_SIZE_TIERS, HOUR_GATE_NUDGES, MIN_SCORE_*, CONFLUENCE_MULTIPLIER_*,
#   SETUP_DISARMED_LIST (becomes irrelevant — only momentum + fhh remain),
#   MOMENTUM_BO_REQUIRE_PRIORITY, all news-sentiment constants.
# Kept for now so crew.py keeps booting. Cleanup in Phase 0.5 / Phase 1.
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 PROBE-MODE OVERRIDES
# ═══════════════════════════════════════════════════════════════════════════
# See docs/23_Phase3_Live_Probe_Operations_2026-05-12.md
#
# When Phase 3 starts, BOTH of these conditions must hold:
#   - PAPER_TRADING = False   (real orders)
#   - PROBE_MODE_ENABLED = True (use scaled-down sizing below)
#
# Both flags default OFF. Flipping PAPER_TRADING without PROBE_MODE_ENABLED
# would route real orders at the paper-sized (₹15L) risk per trade — that's
# ₹1,500 risk per S/A trade vs the intended ₹500 for the ₹50k probe. To
# prevent this footgun, crew.py's _allocate must consult PROBE_MODE_ENABLED
# and apply the override table below when True.
#
# Set BOTH together via env-vars in deploy/.env when going live:
#   PAPER_TRADING=False
#   PROBE_MODE_ENABLED=True
# Override flow: any setting with a probe-mode entry below takes precedence
# when PROBE_MODE_ENABLED=True. Otherwise the original values apply.
PROBE_MODE_ENABLED              = False
PROBE_CAPITAL                   = 50_000
PROBE_MAX_POSITIONS             = 3
PROBE_CONVICTION_RISK_INR = {
    "S": 500.0,    # 1.0% of probe capital
    "A": 500.0,    # 1.0% of probe capital
    "B": 250.0,    # 0.5% of probe capital (B already half-size)
}
PROBE_CONVICTION_TARGET_INR = {
    "S": 1000.0,   # 2R target
    "A":  833.0,   # 1.67R target
    "B":  500.0,   # 2R on smaller risk
}


def get_active_capital() -> int:
    """Return the capital amount the system should size positions against."""
    return PROBE_CAPITAL if PROBE_MODE_ENABLED else CAPITAL


def get_active_max_positions() -> int:
    """Return the concurrent-position cap based on probe-mode state."""
    return PROBE_MAX_POSITIONS if PROBE_MODE_ENABLED else MAX_POSITIONS


def get_active_conviction_risk() -> dict:
    """Return the conviction-engine risk-INR table based on probe-mode state."""
    return PROBE_CONVICTION_RISK_INR if PROBE_MODE_ENABLED else CONVICTION_RISK_INR


def get_active_conviction_target() -> dict:
    """Return the conviction-engine target-INR table based on probe-mode state."""
    return PROBE_CONVICTION_TARGET_INR if PROBE_MODE_ENABLED else CONVICTION_TARGET_INR
