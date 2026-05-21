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
# Fix #181 (2026-05-18) — dropped 10 → 3 to match PROBE_MAX_POSITIONS.
# Reasoning: paper validates a 10-position concurrency the operator will never
# run. Probe is capped at 3. Paper at 10 generates "I was full so I skipped
# admits" behaviour that won't exist live. Aligning the regimes so paper
# metrics describe the system that will actually trade. A solo scalper aiming
# ₹1-3k/trade cannot monitor 10 names anyway.
MAX_POSITIONS           = 3               # paper now matches probe concurrency
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
MOMENTUM_BO_MIN_RVOL    = 1.5   # Fix #22 (A1) → Fix #37 1.7 → Fix #56 back to 2.0
                                #   → Fix #189 (2026-05-19) lowered to 1.5.
                                # Justification: 30-month/18-month dataset analysis
                                # (doc 14 §4, doc 12 §2) explicitly recommends
                                # lowering this to 1.0 because the vol 1.0-1.5
                                # bucket has the HIGHEST expectancy (75% WR /
                                # +0.317R). Fix #56 raised it back to 2.0 based
                                # on 280-trade DB intuition, but that DB was
                                # pre-rebuild — predates conviction engine and
                                # macro/FHH filters. With conviction in place
                                # as the precision gate, RVOL just confirms
                                # "real buyer presence" — 1.5 is sufficient.
                                # Today's observed bottleneck: 2026-05-19 had
                                # 6+ clean MOMENTUM_BREAKOUT candidates in
                                # 1.4-1.9 range get killed before reaching
                                # conviction. INFY 1.44, INTELLECT 1.98,
                                # TORNTPHARM 1.48, etc. Lowering to 1.5 lets
                                # these reach conviction while still blocking
                                # the genuinely-weak (RVOL < 1.0) fakeouts.
                                # If after 5 sessions the WR drops below 60%,
                                # revisit. Backed by `scripts/rvol_backtest.py`
                                # once enough ghost data accumulates.

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

# ─── HOUR_GATE_NUDGES — DELETED Fix #165 (2026-05-18) ────────────────────────
# Was: a dict mapping IST hour → score-gate nudge (Fix #24 / A5).
# Why deleted:
#   1. The Phase 0.5 rebuild (2026-05-11) removed the *application* of these
#      nudges from `_score_signals` but left the dict imported. Audit found
#      it was dead weight and a Three-Laws Law-1 violation surface (clock
#      categories). 30-month analysis (584 sessions) refuted the original
#      premise — hours nudged DOWN (12 IST) had +0.099R but hours nudged UP
#      (9-10 IST) had 51-58% WR, not catastrophic.
#   2. Three Laws Law-3: time-of-day weight must be LEARNED from data, not
#      declared in a static dict. The conviction engine reads structural
#      state (macro + FHH + day-type) which captures the actionable hour-
#      correlated signal directly.
# Kept as a tombstone comment so future archaeology finds the reasoning.
# (Originally: {9:+0.3, 10:+0.2, 11:0, 12:-0.2, 13:0, 14:0})

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


# ─── Phase 2.6 — Runway check (replaces NO_NEW_ENTRY_AFTER clock rule) ───────
# See docs/22_Runway_Check_Spec_2026-05-12.md and agents/runway_check.py.
#
# Replaces the blunt `NO_NEW_ENTRY_AFTER = 14:45` clock cutoff with an
# empirical setup-aware rule: median_TTP1 × safety_factor ≤ remaining_minutes.
# Default OFF; LOG_SHADOW=True emits would-skip/would-admit lines for
# observation without blocking.
# Fix #171 (2026-05-18) — flipped to True per operator decision. Removes the
# last clock-category survivor (NO_NEW_ENTRY_AFTER=14:45 hard wall). Rollback:
# set back to False if entries are blocked unexpectedly or runway math acts up.
RUNWAY_CHECK_ENABLED       = True        # LIVE — was SHADOW until 2026-05-18
RUNWAY_CHECK_LOG_SHADOW    = True        # keep [Runway] log lines for visibility
RUNWAY_SAFETY_FACTOR       = 1.5         # buffer over median TTP1
RUNWAY_LOOKBACK_TRADES     = 50          # median window per setup
RUNWAY_MIN_REMAINING_MIN   = 20          # absolute floor — never enter < 20m before EOD
RUNWAY_DEFAULT_TTP1_MIN    = 45          # fallback when no historical data for this setup

# Setup-specific bootstrap values (used when fewer than 5 historical wins
# exist for the setup). Once data accumulates, the live median takes over
# and these are ignored. Empirically reasonable starting points:
RUNWAY_SETUP_DEFAULTS = {
    "momentum_breakout":   30,   # typical post-FHH-break momentum trades
    "fhh_break":           35,
    "vwap_pullback":       40,
    "vwap_reclaim":        40,
    "failed_breakdown":    20,
    "range_breakout":      25,
    "trend_pullback":      45,
    "inside_bar_break":    30,
}

# Convenience alias — the runway check references the EOD partial-unwind
# moment, which in this codebase is the same as NO_NEW_ENTRY_AFTER (Fix #34
# uses this time as the partial-unwind trigger). We hardcode the value here
# (not a forward reference to NO_NEW_ENTRY_AFTER which is defined later in
# the file) so the constant is importable in any order. Keep both in sync.
EOD_PARTIAL_UNWIND_TIME    = "14:45"

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
# Fix #180 (2026-05-18) — bumped 5/10/3 → 12/22/8 bps after brutal scalper review.
# Reasoning: Discovery surfaces mid-caps (JINDRILL/AMBER/FCL/ARVIND class).
# Real NSE bid-ask on these is 8-15 bps at top-of-book, 20-50 bps on SL fills
# under momentum. Old values were modelling RELIANCE/INFY, not the names we
# actually trade. Paper P&L was overstated by 10-25 bps per round trip,
# meaning paper "+₹3.50 booked" → live "+₹2.00" — paper looked profitable
# while live edge was 35% smaller. Pre-live: paper must converge toward live
# reality, so this gets WORSE not better before flag flip. Re-run 5 paper
# sessions and reconfirm metrics before PAPER_TRADING=False.
# Fix #179 (2026-05-18) — cross-symbol post-loss cooldown ("revenge brake").
# Per-symbol cooldown (45m loss / 15m win) protects against re-entering the
# loser. It does NOT protect against the tilt pattern of chasing the NEXT
# obvious name after a loss. This portfolio-level cooldown blocks ALL new
# entries (any symbol) for N minutes after any closed_loss today. The kill-
# switch at -2.5% capital is the backstop; this is the intermediate brake.
# Set to 0 to disable.
PORTFOLIO_LOSS_COOLDOWN_MIN = 20

PAPER_SLIPPAGE_ENTRY_BPS  = 12   # 0.12% — realistic mid-cap entry slip
PAPER_SLIPPAGE_STOP_BPS   = 22   # 0.22% — momentum SL fills slip hardest
PAPER_SLIPPAGE_TARGET_BPS = 8    # 0.08% — limit orders, lighter than entry/stop

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
# Fix #198 (2026-05-19) — MIDDAY_AVOID_START / MIDDAY_AVOID_END DELETED.
# Three-Laws Law-3 violation (clock category in code & reasoning); the
# 18-month research (doc 14) showed NO hour-of-day bias remains after
# the 10:15 macro filter is applied. Fix #165 deleted `_is_midday()`
# already; this fix removes the now-orphaned constants. If you're
# looking for "skip lunch hours" behavior, the answer is: don't.
# Conviction engine reads structural state per tick — no clock gate.
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


# ── Intraday macro re-evaluation (recovery unlock) ───────────────────────────
# The 10:15 lock is a BASE-RATE read, not a six-hour verdict. On V-shaped
# recovery days (gap down → reclaim) the locked RED/STRONG_RED freezes the agent
# out of the ENTIRE recovery. Live evidence — 2026-05-20: NIFTY locked RED at
# 10:15 (-0.42%), then ground straight back up and made a fresh high above prev
# close by 12:00; the agent took zero trades while PCBL ran +8.5% and RELIANCE
# +1.8%. This re-checks NIFTY AFTER the lock and UPGRADES the state (never
# downgrades) once a strictly-better level is HELD across MACRO_RECHECK_CONFIRM_BARS
# consecutive 5-min candle closes.
#
# Research-consistent: the 30-month study sampled the 10:15 candle close as a
# base rate for the day's CLOSE — it never claimed the state is immutable.
# Healing only ever fires on DEMONSTRATED reclaim (sustained candle closes, not
# a single tick), so it does NOT reintroduce falling-knife risk: on a day that
# keeps bleeding, NIFTY never reclaims, the upgrade never fires, capital is safe.
#
# Upgrade ladder (each requires ALL last-N closes above the level, vs prev close):
#   reclaim > -0.3%  → upgrade to YELLOW  (out of RED/STRONG_RED → half-size A++)
#   reclaim > +0.3%  → upgrade to GREEN
#   reclaim > +0.5%  → upgrade to STRONG_GREEN
# Only ever moves UP the ladder; the 10:15 lock is the floor (long-only system
# already sits out on the bearish side, so no downgrade path is needed).
#
# SHADOW vs LIVE:
#   MACRO_RECHECK_ENABLED = False → SHADOW: logs [MacroRecheck] WOULD-UPGRADE and
#                                   returns the LOCKED state (zero behaviour change)
#   MACRO_RECHECK_ENABLED = True  → LIVE: returns the upgraded state to conviction
# Rollback: set MACRO_RECHECK_ENABLED = False to revert to pure 10:15 lock.
MACRO_RECHECK_ENABLED          = True    # LIVE (2026-05-20) — operator call: trade recovered days
MACRO_RECHECK_CONFIRM_BARS     = 3       # consecutive closed 5-min bars above level (~15 min)
MACRO_RECHECK_LOG_SHADOW       = True    # emit [MacroRecheck] lines even in shadow


# ── Order book depth filter (universal pre-entry) ────────────────────────────
# 5-level aggregate bid_qty / sell_qty (NOT top-of-book, which can be spoofed
# by a single large order). Validated finding: top-of-book ratio is noise,
# 5-level depth is structural commitment.
ORDER_BOOK_RATIO_MIN           = 1.3
# Fix #190 (2026-05-19) — lowered 1.5 → 1.3. 2026-05-19 observed: ANGELONE
# scored 7.9 reaching conviction, then rejected at depth ratio 1.45 (just
# below 1.5 threshold). BSOFT separately rejected at 0.65 (genuinely weak,
# still rejected at 1.3). The 1.5 threshold was conservative — no
# empirical 30-month validation behind the exact number. 1.3 admits the
# cusp candidates (1.3-1.5 band) while still blocking sub-1.3 (genuinely
# sell-pressure-dominant). Conviction engine has FIVE other filters
# (macro, FHH, HOD, change_pct floor, spread) — depth is one signal of
# five. Revisit threshold if 5+ paper sessions show 1.3-1.5 entries
# losing systematically.


# ── Universal spread filter ──────────────────────────────────────────────────
# (Same threshold as Fix #43's ENTRY_MAX_SPREAD_PCT but used by conviction_engine.)
# 0.10% spread on a 0.7% stop eats 28% of TP1 — wide spreads silently destroy
# scalp R:R. Hard skip.
SPREAD_MAX_PCT                 = 0.0010   # 0.10%


# ── Stock-level HOD proximity (Phase 1.1) ────────────────────────────────────
# Maximum % below today's high for a valid entry candidate.
# Fix #162 (2026-05-18): relaxed 0.005 (0.5%) → 0.012 (1.2%) after audit found
# 0.5% was scalper-hostile. Real pullback-to-FHH-retest entries (the textbook
# tape-reader setup) typically pull back 0.6-1.0% off the fresh HOD before the
# second clean push. Combined with the legacy "change_pct < 0 → SKIP" rule
# (also relaxed to -0.3% in this fix), 0.5% eliminated almost every clean
# pullback admit — only naked HOD breaks survived. The mid-trade re-eval
# already uses 1.5% for its HOD-broken-check, so 1.2% pre-entry is tighter
# than the post-entry tolerance, which is what we want.
STOCK_HOD_PROXIMITY_PCT        = 0.020    # 2.0% — Fix #192 (2026-05-19).
# Was 0.5% (Phase 1.1) → 1.2% (Fix #162) → 2.0% now.
# Doc 25 §4 B5 flagged: Kite's `ohlc.high` is the SESSION high, not a
# rolling intraday high. On a multi-leg day (e.g. 09:30 peak ₹510, then
# pullback to ₹495, then 11:00 swing high ₹505, then pullback to ₹498),
# a 1.2% gate kills the 11:00 retest entry because LTP=₹498 is 2.4%
# below session-high ₹510 — but it's <0.5% below the relevant 11:00
# swing high. The proper fix is rolling intraday high tracking; the
# simpler fix is widening the threshold to accommodate the second-leg
# scenario. 2.0% is the band where a stock is still structurally "near"
# its day's range without being a distant chase. Mid-trade reeval
# already uses 1.5% for HOD-broken-check, so pre-entry 2.0% is slightly
# looser than post-entry — acceptable because pre-entry has more
# filters (FHH, RVOL, depth) AND a lower-quality entry can still be
# managed by the reeval.
STOCK_CHANGE_PCT_FLOOR         = -0.003   # -0.3% — allows flat/bullish-structure pullback


# ── Per-stock FHH break requirement (Phase 1.1) ──────────────────────────────
# When True, the conviction engine requires the SYMBOL's own first-hour-high
# to be cleanly broken (not just NIFTY's). When False, falls back to
# NIFTY-only FHH (Phase 0 behavior; what the 30-month research actually
# validated at 97%).
#
# Fix #191 (2026-05-19) — flipped True → False.
# Rationale:
#   - The 30-month research (docs 14, 15, 16) validated GREEN+NIFTY-FHH=97%
#     (n=48), NOT stock-level FHH. Stock-level FHH was a Phase 1.1
#     speculative tightening added on top of the research without
#     empirical backing.
#   - 2026-05-19 paper session: zero entries fired despite GREEN macro +
#     NIFTY FHH break at 10:45. The stock-level FHH gate is one of the
#     filters contributing to over-restriction.
#   - Per-stock FHH adds an unknown second-derivative requirement — if
#     stock has been pinned to its first-hour high all morning, it can't
#     "break" it on a candle that opens/closes there. Tightens beyond
#     what the data supports.
#   - Reverting to NIFTY-only FHH aligns with the doc-15 spec exactly
#     ("clean FHH break" referred to NIFTY throughout the research).
# If after 10+ paper sessions the WR drops below 60%, revisit. The
# conviction engine still has 6 other filters; this is one input.
REQUIRE_STOCK_FHH_BREAK        = False


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
# Fix #164 (2026-05-18): NSE non-F&O equity locks at 20% UC; surveillance
# stocks lock at 5% or 10%. At/near circuit there's no two-way market — the
# 2026-05-18 FCL admit at +19.97% had spread=0.000% pull-from-extreme=0.00%
# = literally locked-no-fills. We veto absolute moves ≥ this threshold so
# Conviction doesn't waste attention on names we structurally can't trade.
DISCOVERY_UPPER_CIRCUIT_VETO_PCT = 18.0     # |pct_change| ≥ 18% → veto (locked)
DISCOVERY_MIN_AVG_TURNOVER_INR   = 10e7     # ₹10 crore avg daily turnover
DISCOVERY_MAX_SPREAD_PCT         = 0.0015   # 0.15% (slightly looser than entry SPREAD_MAX_PCT)
DISCOVERY_MAX_NEW_ADDS_PER_SCAN  = 5
DISCOVERY_MAX_TOTAL              = 15       # max live-discovery names at once
DISCOVERY_MAX_PER_SESSION        = 40       # cumulative session cap
DISCOVERY_BLACKLIST_LOSS_THRESHOLD = 2      # losses before auto-blacklist
DISCOVERY_BLACKLIST_DAYS         = 7        # blacklist duration (trading days)
# Fix #171 (2026-05-18) — flipped to True per operator decision. Live admit
# evidence: FCL +19.97% on 2026-05-18 (circuit-veto correctly blocked); filter
# v5 + CIRCUIT_VETO=18% in place. Rollback: set back to False to roll Discovery
# back into shadow mode without losing the [Discovery] log telemetry.
DISCOVERY_ALLOW_TRADES           = True     # LIVE — was SHADOW until 2026-05-18
DISCOVERY_MAX_NEW_CONTEXT_FETCHES_PER_SCAN = 10  # rate-limit guard: max Kite get_candles calls per scan
                                                  # (daily-context cache is persisted to disk so subsequent
                                                  #  scans skip already-seen symbols)


# ── Phase 2.7 — Mid-Trade Structural Re-evaluation ──────────────────────────
# See docs/24_Mid_Trade_Reeval_Spec_2026-05-18.md and agents/mid_trade_reeval.py
#
# Every MID_TRADE_REEVAL_INTERVAL_MIN per open position, re-check the 3-dim
# entry thesis (macro state / above-VWAP / HOD-proximity). Action ladder:
#   • 0-1 broken → CONTINUE  (existing SL/TP/trail manages)
#   • 2 broken   → TIGHTEN_TO_BE  (move SL to entry_price)
#   • 3 broken   → CLOSE at market with reason "thesis_invalidated"
#
# Catches the "got in clean, market changed under me" loss class. Default OFF
# via MID_TRADE_REEVAL_ENABLED. Shadow logs via MID_TRADE_REEVAL_LOG_SHADOW.
# Fix #171 (2026-05-18) — flipped to True per operator decision. Lowest-risk
# of the 4 flips: TIGHTEN_TO_BE is a stop-tighten (not market exit) and CLOSE
# is shadow-validated. Catches the "got in clean, market changed under me"
# loss class. Rollback: set back to False to revert to shadow.
MID_TRADE_REEVAL_ENABLED       = True     # LIVE — was SHADOW until 2026-05-18
MID_TRADE_REEVAL_LOG_SHADOW    = True     # keep [Reeval] lines for visibility
MID_TRADE_REEVAL_INTERVAL_MIN  = 5        # re-check at most once per N min per position
MID_TRADE_HOD_RELAX_PCT        = 0.015    # 1.5% (relaxed from entry's 0.5%)
MID_TRADE_TIGHTEN_AT_BROKEN    = 2        # 2/3 dims broken → tighten SL to BE
MID_TRADE_CLOSE_AT_BROKEN      = 3        # 3/3 dims broken → close at market


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
# Fix #171 (2026-05-18) — flipped to True per operator decision, paired with
# Fix #166 which corrected the sizing math (0.5 × x × 2 → 0.5 × x). On macro
# RED/STRONG_RED days, allows one stock that meets the 6-condition rule to
# enter at tier B half-size. Catches ONGC-class +5.93% admits the binary macro
# gate blocked. Rollback: set back to False to revert to shadow.
STOCK_DECOUPLING_ENABLED               = True    # LIVE — was SHADOW until 2026-05-18
STOCK_DECOUPLING_MIN_PCT               = 4.0     # stock %chg vs prev close
STOCK_DECOUPLING_MIN_VOL_RATIO         = 1.5     # today_vol / 20d_avg_vol
STOCK_DECOUPLING_MAX_PULL_FROM_HOD_PCT = 1.5     # LTP within X% of intraday high
# Fix #205 (2026-05-20) — loosened 0.5 → 1.5. Live evidence: PCBL +8.5% on a
# RED-locked day was a textbook decoupling candidate but was BLOCKED because it
# had pulled back 2.3% off its high when scanned — the 0.5% gate is too tight
# for the discovery scan cadence (a strong name breathes more than 0.5% between
# scans). 1.5% still demands the stock be near its high (not chasing a fader)
# while admitting names that pulled back one normal swing. Rollback: set to 0.5.
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


# ─────────────────────────────────────────────────────────────────────────────
# SCALP MODE  (2026-05-21 — operator directive: "be a scalper, trade daily")
# ─────────────────────────────────────────────────────────────────────────────
# Why this exists:
#   The conviction pipeline (setup-detector + RVOL gate + 6 conviction gates,
#   all ANDed) took ZERO trades across 10 sessions. A name ripping on 12x
#   volume above VWAP making higher highs (e.g. ANGELONE 2026-05-21) cannot
#   clear the base-breakout setup detector (small-body continuation bars are
#   logged weak_body) and so never reaches scoring. The agent found the winners
#   and never traded them.
#
# Philosophy (agreed with operator):
#   Move the strictness from the ENTRY to the EXIT. Loosen entry to a pure
#   stock-structural trigger (above VWAP + last bar up + volume + book not
#   collapsing + not over-extended), take MANY small shots, and protect each
#   one with a HARD tight stop, a fast take-profit, a flat-trade scratch, and a
#   firm daily loss cap. A trap then costs a 0.4% scratch instead of being
#   something we pre-screen the whole day for.
#
# Profile chosen: AGGRESSIVE.  Daily loss cap: ₹30,000 (2% of ₹15L).
#
# SHADOW-FIRST: SCALP_MODE_ENABLED defaults False. When False the engine still
# evaluates and logs `[Scalp] WOULD-ENTER ...` lines but places nothing, so we
# collect a session of evidence before flipping it live (same pattern as the
# macro recovery-unlock Fix #205/#206).
SCALP_MODE_ENABLED              = True     # LIVE (paper) 2026-05-21 — operator call: trade it now

# ── Entry trigger (loosened) ────────────────────────────────────────────────
SCALP_REQUIRE_ABOVE_VWAP       = True      # LTP must be above session VWAP
SCALP_REQUIRE_UP_BAR           = True      # last completed bar close > open
SCALP_RVOL_MIN                 = 1.2       # "volume present" — well below the 1.5 momentum gate
SCALP_OB_RATIO_MIN             = 0.7       # 5-level bid/sell ≥ 0.7 (light book guard; blocks 2:1 sell-stacked fades)
SCALP_SPREAD_MAX_PCT           = 0.0015    # 0.15% — slightly looser than the 0.10% conviction spread
SCALP_MAX_EXT_FROM_VWAP_PCT    = 0.015     # don't chase: skip if LTP > 1.5% above VWAP (blocks parabolic blowoff tops)
SCALP_CIRCUIT_VETO_PCT         = 0.18      # reuse discovery circuit veto — no entries on ±18% locked names

# ── Exit discipline (where the strictness lives now) ────────────────────────
# Volatility-scaled stop (2026-05-21): a flat 0.4% sits INSIDE the noise of a
# high-priced wide-range name (MTARTECH bars swing ₹40-60 but 0.4% of ₹7800 is
# only ₹31 → whipsawed out of good moves). So the stop is the WIDER of the flat
# floor and 1× ATR, capped so per-trade ₹risk stays bounded. Target is a fixed
# R-multiple of whatever the stop turns out to be, so reward:risk is constant.
SCALP_STOP_PCT                 = 0.004     # floor: stop never tighter than −0.4%
SCALP_STOP_ATR_MULT            = 1.0       # stop = max(0.4%, 1.0 × ATR of recent bars)
SCALP_STOP_MAX_PCT             = 0.010     # cap: stop never wider than −1.0% (bounds ₹risk)
SCALP_TP_R_MULT                = 2.0       # target = 2× the actual stop distance (2:1)
SCALP_TP_PCT                   = 0.008     # fallback target when ATR unavailable (+0.8%)
SCALP_SCRATCH_MIN              = 6         # if not > +0.1% after 6 min → scratch out (sneak in, no go, leave)
SCALP_TIME_STOP_MIN            = 20        # hard max hold — exit at market after 20 min regardless

# ── Sizing / concurrency ────────────────────────────────────────────────────
SCALP_NOTIONAL_INR             = 200_000   # ₹2L notional per scalp (≈₹800 risk at the 0.4% stop)
SCALP_MAX_POSITIONS            = 5         # more shots than the 3 swing slots; 5×₹2L = ₹10L < ₹15L
SCALP_DAILY_LOSS_CAP_INR       = 30_000    # halt new scalp entries for the day after ₹30k realized loss
SCALP_NO_ENTRY_AFTER           = "14:55"   # no fresh scalps in the last ~20 min; manage/close only
