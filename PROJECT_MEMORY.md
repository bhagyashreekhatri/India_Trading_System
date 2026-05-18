# NSE Trading System — Project Memory
*Last updated: 2026-05-18 ~15:30 IST | Operator: Bhagya*
*Recent activity: Discovery filter v3→v5 (CF mitigation) + scalper-lens audit fixes #159-162. Conviction engine is now sole decision authority — was being silently nuked by stub-scorer's MIN_SCORE_ENTRY=7.0 gate. HOD proximity relaxed 0.5%→1.2% to allow pullback-to-FHH-retest entries. PROBE_MODE wired through allocator (closed 30× risk footgun for live probe). First live Discovery admit: FCL +19.97% on 2026-05-18.*

---

# ⛔ READ THIS FIRST — EVERY SESSION, EVERY RESPONSE ⛔

## THE THREE LAWS OF THIS PROJECT (locked permanent by operator, 2026-05-11)

**Before writing one line of code. Before suggesting one fix. Before reading any log. Before answering any question. Internalise these three laws.**

### LAW 1 — THINK LIKE A PRO TAPE-READING SCALPER, NOT LIKE A CODER WITH RULES

A pro scalper does NOT think in categories like:
- ❌ "Morning setups vs afternoon setups"
- ❌ "Pre-lunch behavior vs post-lunch behavior"
- ❌ "This sector works on Mondays"
- ❌ "MOMENTUM_BREAKOUT peaks at 09:30-11:00"
- ❌ "Filter X works better in afternoon"

A pro scalper reads **three things, every moment, regardless of clock or calendar:**
1. **Order flow** — is bid absorbing supply, or is supply hitting bids?
2. **Structure** — higher highs / higher lows / fresh breakouts / failed breakouts / consolidation geometry
3. **Execution physics** — spread, depth, RVOL relative to the stock's own history

The clock is not a feature. The day-of-week is not a feature. The "lunch hour" is not a thing. Every minute the market is open, the only question is: **what is the tape telling me about this specific stock right now?**

### LAW 2 — NO HARDCODING. EVER. ANYWHERE.

**Forbidden in code AND in reasoning:**

| Category | Forbidden | Required |
|---|---|---|
| Symbols | `if symbol == "IDEA"` | `for symbol in FULL_UNIVERSE` |
| Sectors | `top_sectors = ["IT","PHARMA","METAL"]` | Dynamic ranking from live data |
| Time gates | `if time(12,0) <= now <= time(13,30)` | No time gate; structural conditions only |
| Time weights | `SETUP_TIME_WEIGHTS = {"MB":{"09-11":1.2}}` | Data-driven function over rolling history |
| Detector names | `LUNCH_LULL_STEALTH`, `MORNING_BREAKOUT` | Structural: `TIGHT_BASE_ABSORPTION` |
| Magic numbers | `if range > 0.015` (buried in code) | All thresholds in `config/settings.py` |
| Day-of-week | `if today.weekday() == 4` | None — markets don't care |
| Regime labels | `if regime == "PHARMA_LEADING_IT_FADING"` | Measure sector strength dynamically per-bar |

**The test:** *"Would this rule work the same way if every symbol, sector, hour, and weekday were completely different from today's?"* If no → it's hardcoded → it's wrong → it goes in the trash.

### LAW 3 — STRUCTURE IS THE RULE; TIME IS A CO-FEATURE WHOSE WEIGHT IS LEARNED, NEVER DECLARED

If results appear to vary by time-of-day, the right question is **NOT** "should we add a time gate?" The right question is **"what structural feature varied that happens to correlate with time?"**

Examples of correct re-framing:
- Spread widens around 12:00-13:30 → build a **spread filter** (measures spread directly), not a "lunch filter"
- Volume bursts in first 15 min → build an **RVOL filter** (measures volume directly), not an "opening filter"
- Force-close at 15:15 is mechanical → build a **time-to-target check** at entry ("will this trade have runway?"), not a "no entries after 14:45 rule"
- Specific setups underperform during low-volatility windows → build an **ATR/volatility filter** (measures volatility directly), not a "midday gate"

The system never says "it's 12:30, change behavior." The system says "spread widened to 0.18%, change behavior" — and that happens to be true at 12:30 today and at 11:00 tomorrow during an unexpected news lull.

---

## 🚨 SELF-CHECK BEFORE EVERY RESPONSE

Before sending any answer about this project, Claude must internally answer:

1. **Did I use any phrase that references a clock category?** ("morning," "afternoon," "lunch," "pre-/post-lunch," "EOD as a setup type," etc.) → STOP, rewrite the reasoning structurally.

2. **Did I propose any rule, detector, threshold, or filter that names a specific symbol, sector, or time window?** → STOP, generalise it.

3. **Did I explain a result by referencing a time-of-day category?** ("it works at 10am because…", "it failed because it's afternoon…") → STOP. The real explanation is structural — find it.

4. **Would a real desk scalper say what I just said, or would they look at me confused?** → If confused, rewrite.

This isn't optional. This is the entry condition for every response.

---

## 🎯 NORTH STAR — DO NOT FORGET (re-stated 2026-05-08)

**Goal: ₹1,000–₹5,000 per TRADE — scalper-pro mindset, NOT institutional hedge fund.**

- Per-trade target, NOT per-day. Each trade stands alone.
- Quality of trade > volume of trades. Idle is a valid state.
- Think like a desk scalper watching the tape — not a quant optimising Sharpe.
- Don't chase runaway names (proximity gate is correct). Wait for retest instead.
- Size for the ₹ target, not for % of capital theory.
- Filters protect from bad trades, they don't manufacture trades.
- Stay paper for ~2 weeks; move to live with real money once metrics hold.
- All code is production-grade — will handle real money soon.

**When in doubt, ask: "Would a pro scalper take this trade?"** Not: "Does the model say take this trade?"

---

## 🧬 GENERIC-FIRST DESIGN PRINCIPLE (mandated 2026-05-11 by operator)

**NEVER HARDCODE. Every rule, detector, filter, threshold must be GENERIC and work on ANY symbol/sector/regime.**

### Forbidden patterns (these are bugs even if they "work" today):

❌ `if symbol == "IDEA": ...`
❌ `if sector == "PHARMA": ...`
❌ `if PHARMA_fading and IT_emerging: ...`
❌ `top_sectors = ["IT", "PHARMA", "METAL"]` (anywhere in code that's not output of a function)
❌ Magic numbers buried in detectors (`if range > 0.015`)
❌ Day-specific rules (`if today == "expiry_day"`)
❌ Hand-picked symbol lists in pattern detection logic
❌ **Time-of-day gates on detectors** (`if not (time(12,0) <= now <= time(13,30)): return None`)
❌ **Detectors named after times of day** (`LUNCH_LULL_STEALTH`, `MORNING_BREAKOUT`, `AFTERNOON_REVERSAL`)
❌ **Hardcoded `setup_type → time_bucket → weight` tables** (`SETUP_TIME_WEIGHTS = {"MOMENTUM_BREAKOUT": {"09:30-11:00": 1.2}}`)
❌ **Time-window "best setup / worst setup" playbooks** (any human-authored table of "this pattern works at this hour")

### Required patterns:

✅ `for symbol in FULL_UNIVERSE: ...` (iterate all)
✅ `for sector in SECTOR_MAP.unique_values(): ...` (dynamic sector lookup)
✅ Thresholds imported from `config/settings.py` or `config/thresholds.py`
✅ Pattern-structure detection (count pushes, measure ranges, check ratios — never name-match)
✅ Sector-size-adaptive thresholds (e.g. `threshold = max(3, len(stocks) // 4)`)

### Application to all 5 new patterns being designed for EOD:

| Pattern | Generic core |
|---|---|
| #70 STAIRCASE | "≥N upward pushes + higher consolidations + sustained vol" — works on any stock |
| #71 Pre-TP1 trail | "+X.X R favorable + held Y min → move SL to BE+Z" — works on any trade |
| #72 SECTOR_ROTATION_HANDOFF | "iterate SECTOR_MAP, count new-HODs and fades per sector" — any sector pair |
| #73 PERSISTENT_LEADER | "stock making new HOD while ≥X% of its sector peers fade" — any sector |
| #74 NEGATIVE_DAY_RECOVERY | "day_pct < 0 AND new HOD AND bounce > X% from low" — any stock |

### Why this matters:

Hardcoded rules look smart in backtest but **fail in live trading** because markets don't repeat the same patterns:
- Today's PHARMA-IT rotation will be METALS-FMCG next week
- Today's IDEA staircase will be DEVYANI staircase next month
- Today's banking fakeout will be auto fakeout next session

Generic rules survive regime changes. Hardcoded rules die.

**Operator instruction (verbatim, 2026-05-11):**
> "i dint want anything any bug to be hard coded..just make ur minset in a generic dynamic approach"

This is a permanent design constraint. Every code change, every fix, every detector, every filter must pass the test:

> **"Would this work the same way if the symbols/sectors involved were completely different?"**

If the answer requires knowing today's specific names → it's hardcoded → it's wrong.

### AMENDMENT 2026-05-11 (12:25 IST) — Time-of-day is NOT exempt

Operator caught a same-day violation: Claude proposed a `LUNCH_LULL_STEALTH_BREAKOUT` detector gated to 12:00-13:30 IST and a `SETUP_TIME_WEIGHTS` dict mapping setups to time windows. Both were classic temporal overfit.

**Operator instruction (verbatim, 2026-05-11):**
> "this hard coding as per time zone are u sure its generic? we already discussed right? when ever u fix bugs or write code or design architectire it should be generic. example 12:00 - 13:30 BID_ASK_ABSORPTION, LUNCH_LULL_STEALTH, STAIRCASE not necessary every day.. some times BID_ASK_ABSORPTION, LUNCH_LULL_STEALTH, STAIRCASE this setups also can trugger ate 11:00 or 2:00"

**Permanent rules added:**

1. **No detector may be named after a time of day.** The pattern definition lives in its structure (e.g. "tight base + fresh HOD + bid absorption"), not in its hour.

2. **No detector may be gated by clock time.** A pattern fires whenever its structural conditions occur — at 09:45, 11:00, 12:15, or 14:30 — equally.

3. **No human writes a `setup → time_bucket → weight` table.** Time-of-day weighting comes from data: a function reads each setup's rolling-N-day historical expectancy in the current time bucket and returns `expectancy_bucket / expectancy_global`. Cold-start default = 1.0 (neutral).

4. **Same-day clusters are evidence, not rules.** If a pattern happens 3 times in one hour on one day, that is a coincidence of the tape. The rule is the structural mechanism, not the clock.

5. **The renaming convention is enforced:** if a proposed detector name contains "LUNCH", "MORNING", "AFTERNOON", "CLOSING", or any other temporal word, rename it to describe the structural mechanic instead.

**Concrete corrections made today:**
- `LUNCH_LULL_STEALTH_BREAKOUT` → `TIGHT_BASE_ABSORPTION_BREAKOUT`
- `SETUP_TIME_WEIGHTS` hardcoded dict → `get_setup_context_weight(setup_type, context)` data-driven function reading from `trade_state.db`
- "Time-window playbook" table → DELETED

**The meta-principle:** Time is a feature, not a gate. Structure is the rule, time is a co-feature whose weight is learned, not declared.

### DEEPER AMENDMENT 2026-05-11 (13:50 IST) — Drop clock categories from REASONING, not just from code

Operator caught Claude reverting to clock-shaped reasoning **even after locking the no-clock-gates rule into the code design**. The phrase Claude used: *"if these picks fail, the filter doesn't work in afternoon conditions."*

**Operator instruction (verbatim, 2026-05-11):**
> "one thing can u explain me when real human scalper do trading ...does he even look at what is working in morning, afternoon, even, post lunch, pre lunch etc etc..its market..any time any ticker at any momet will go up n come down. filter doesn't work in afternoon conditions,? what is this?"

**The deeper principle (locked permanent):**

A pro tape-reader does not maintain mental categories of "morning behavior" vs "afternoon behavior." They read three structural things at every moment:
1. Order flow — is bid absorbing supply or is supply hitting bids?
2. Structure — higher-highs / higher-lows / fresh breakouts / failed breakouts / consolidation geometry
3. Execution physics — spread, depth, RVOL relative to history

**These three reads have NO clock dependence.** Saying "bid/sell ≥ 1.5 represents buyer absorption" is a true statement about market microstructure at any instant. It is equally true at 09:45, 11:17, 14:45, and on options-expiry Thursdays.

**The only things that legitimately vary through the day:**
- Liquidity profile (measure spread + depth, not the clock)
- Time-to-force-close (a physical constraint on position runway, not a market truth)

**Forbidden in REASONING (not just code):**
- ❌ "This rule works better in the morning"
- ❌ "Setups change after lunch"
- ❌ "Filter fails in afternoon conditions"
- ❌ Any sentence where the explanation for a result references a time-of-day category

**Required in REASONING:**
- ✅ "The filter passed/failed because of [structural property X]"
- ✅ "The threshold is wrong because [order-flow measurement Y]"
- ✅ "Liquidity at the entry moment was [N basis points spread + M lots depth]" (measurement, not clock)

If a result varies by time-of-day, the right question is: **what structural feature varied that correlates with time-of-day?** Then build the filter on that feature, not on time.

Examples:
- Spread widens 12:00-13:30 → build a spread filter, not a "lunch filter"
- Volume bursts at open → build an RVOL filter, not an "open filter"
- Force-close at 15:15 → build a "time-to-target" check on the entry, not a "no entries after 14:45" rule

**This principle applies retroactively to existing fixes:**
- Fix #46 ("ORB only fires 09:30-10:30 IST") — needs re-examination. The real rule is probably "ORB only fires when the opening range is structurally complete AND no fresh data has invalidated it." That should auto-fire at the right moment without a clock gate.
- Fix #34 ("EOD partial unwind at 14:45") — needs to be re-thought as "begin position-runway evaluation when time-to-force-close < expected-time-to-target."
- Fix #35 ("Dynamic lunch-window gate") — needs to be re-thought as "raise threshold when measured per-trade slippage exceeds N basis points," not when the clock says 12-13.

This rewrite work isn't urgent (none of these are currently losing money structurally) but goes on the principle-cleanup queue.

---

## 🛑 INTENTIONAL BEHAVIORS — DO NOT "FIX" THESE (added 2026-05-11)

These look like bugs but are real scalper-pro features. Future Claude should NOT propose to "fix" them.

**First 30-40 min blindness (09:15-09:55 IST):**
- Setup detection requires VWAP-with-candles which uses 5-min bars, needs ≥ 8 today bars
- Math: 8 × 5 min = 40 min after open → first setup detection 09:55 IST
- WHY THIS IS CORRECT: Opening 15-30 min is fakeout central — gap-up exhaustion, operator stop-runs, retail panic. Validated 2026-05-11 when THERMAX spiked +3% at 09:30 then crashed back to flat by 09:35. Any chase at the breakout would have been stopped out immediately.
- The system intentionally lets the tape settle before acting. Pro scalpers avoid the open for the same reason.
- See also: Fix #46 (ORB time-window enforcement 09:30-10:30) — same wisdom encoded explicitly.
- **If a future analysis says "we're missing the first hour, let's fix it" — STOP. Read this note. Validate against actual fakeout rate on first-30-min trades before changing anything.**

---

## 🧠 MINDSET HIERARCHY — DO NOT VIOLATE (re-stated 2026-05-08)

**Scalper decides WHAT. Engineer decides HOW. Data decides WHO WAS RIGHT.**

- Scalper-first philosophy, engineer-quality implementation underneath.
- Trader-designed behavior, engineer-built implementation, data-validated evolution.
- Architecture exists to SERVE execution quality — not the other way around.

**Where they conflict, scalper wins, engineer adapts:**
- Elegant abstraction that slows hot path > 100ms → engineer rebuilds ugly + fast.
- "I want one rule, no boosters" → engineer does NOT sneak in weighted-pass logic.
- "Skip if anything smells off" → engineer implements fail-closed defaults (skipped trade = safe; wrong trade = expensive).
- Abstraction layers "for testability" that obscure setup/level/trigger/stop/invalidation → not built. Trade logic must remain readable in code.

**Where engineer wins quietly (scalper doesn't think about these, but they keep us alive):**
- Persistence + replay safety on crash mid-session.
- Idempotent order placement (no double-fills on broker hiccups).
- Atomic state transitions (no half-promoted focus names, no half-placed brackets).
- Bounded retry with backoff on broker/data APIs.
- Every reject logged with which rule failed; every state transition timestamped.

**The product is: a scalper's brain in production-grade implementation.**
NOT a scalper's chaos. NOT an engineer's abstraction.

**When in doubt about a code decision, ask in order:**
1. "Would a pro scalper take/skip this trade BECAUSE of this code?" (scalper test)
2. "If this code crashes / fails / gets a stale value, does the system fail SAFE?" (engineer test)
3. "Can we measure whether this decision was right at EOD?" (data test)

If any of those three is "no" — the code isn't ready.

---

## ✅ Fixes deployed 2026-04-28 (read before writing code)

| # | Fix | Files | Verified by |
|---|---|---|---|
| 1 | **Stall-bug TZ correction** — `_entry_dt_aware` auto-detects host TZ; `entry_time` now written IST-aware via `_now_iso_ist()`; `is_in_cooldown` + `get_win_rate_by_hour` IST-corrected | `agents/crew.py`, `memory/trade_state.py` | sandbox UTC sim: 5-min entry reads as 5 min (was 335) |
| 2 | **Score calibration** — news baseline 0.5 → 0.0; RECOVERING regime mults: recovery_setup 1.3→1.0, momentum_breakout 1.0→1.1, failed_breakdown 1.1→0.8 | `scoring/engine.py` | replay on 151 trades: A WR 70%, A+ WR 76.5%, calibration monotonic |
| 3 | **Operational guards** — overnight veto (force-close any prior-session position), daily-loss kill switch (-2.5% of CAPITAL → freeze entries), `sl_hit` vs `sl_trail_hit` distinction | `agents/crew.py`, `config/settings.py` | targeted sim of all three guards |
| 4 | **Groq hardening** — typed retries (RateLimitError honours Retry-After, APITimeout/Connection backoff), `response_format=json_object`, `timeout=10s`, persistent disk cache `news_cache.json`, telemetry counters | `data/news_client.py` | mocked 6-path test (success/429-retry/4×429/JSONErr/BadReq/cache-restart) |
| 5 | **Multi-setup + confluence + turnover scanner** — `_detect_setups_multi` returns all matches; `confluence_count` tagged; multipliers x1.15/x1.25; scanner uses `turnover ≥ ₹50L` not raw shares | `tools/pattern_tools.py`, `agents/crew.py`, `config/settings.py` | 3 setups fired together on synthetic strong breakout |
| 6 | **Broker-side SL-M orders** — placed on entry, cancelled+replaced on TP1 / trail, cancelled before full exit; `sl_order_id` column on Position | `data/kite_client.py`, `memory/trade_state.py`, `agents/crew.py` | syntax + 10/10 engine tests |
| 7 | **Tick-size rounding (₹0.05)** — `_round_to_tick`/`_round_down_tick`/`_round_up_tick` in engine; applied in `_make_signal` (entry/SL/TP1/TP2), `_calc_tp` (both), trail SL | `scoring/engine.py`, `tools/pattern_tools.py`, `tools/score_tools.py`, `agents/crew.py`, `config/settings.py` | rounding cases verified |
| 8 | **Real-VWAP breadth** — per-tick `_vwap_cache` populated by setup detection; breadth + sector strength use real VWAP (fallback `last>open`) | `tools/volume_tools.py`, `agents/crew.py` | both bias directions fixed in mock test |
| 9 | **Sizing floor** — per-position cap 20%→10% (10 pos × ₹1.5L = ₹15L exact); risk floor 0.03% (₹450); position floor 3% (₹45k); below floor → watchlist | `config/settings.py`, `agents/crew.py` | DIVISLAB/ONGC/NMDC qty=1 trades blocked, legitimate trades enter |
| 10 | **TREND_PULLBACK setup** — strong-mover (≥3% day) second-leg pullback entry; mother-bar trend + pullback + resumption green bar | `scoring/engine.py`, `tools/pattern_tools.py`, `tests/test_engine.py` | 6 scenarios; SAPPHIRE-class detected with tick-aligned prices |
| 11 | **Daily-profit lockout** — +3% capital P&L → freeze new entries; +2% → tighten gate to 8.0 (A+/A++ only). Mirror of Fix #3 kill switch on the upside | `config/settings.py`, `agents/crew.py` | thresholds verified at all PnL levels |
| 12 | **INSIDE_BAR_BREAK setup** — 3-bar pattern: mother + inside + breakout above mother high; VWAP bias filter; tick-aligned | `scoring/engine.py`, `tools/pattern_tools.py` | 5 scenarios incl. defensive bounds |
| Dash | **Dashboard learning_tab TZ fix** — `pd.to_datetime(format='ISO8601')` handles mix of naive (legacy) + IST-aware (Fix #1) timestamps | `dashboard/learning_tab.py` | mixed-format parse verified |
| 13 | **Honest fill prices** — refetch live LTP at order time (`_allocate`); refetch at TP1 / full-exit. Stops paper P&L being inflated by 20–25 min stale signal-bar prices | `agents/crew.py` | M&MFIN class bug — entry now matches live LTP |
| 14 | **Persist regime as a column** on `positions`. ChromaDB write + EOD job both prefer the persisted regime; substring parser is fallback only for legacy rows | `memory/trade_state.py`, `agents/crew.py`, `jobs/eod_job.py` | schema migrated; new entries write regime |
| 15 | **Sector flow gating** — top-3 sectors get +0.3 score boost; weak-3 get -0.5 penalty. Trade with the flow, not against it | `agents/crew.py` | uses breadth_cache top/weak sectors; saved in score_breakdown |
| 16 | **Paper-mode slippage simulation** — 5bps entry / 10bps stop / 3bps target worsens paper fills to model live broker reality. Auto-skipped in live mode | `config/settings.py`, `agents/crew.py` | helper `_apply_paper_slippage`; applied in `_allocate`, `_partial_exit_tp1`, `_full_exit` |
| 17 | **PDH/PDL scoring boost** — entry > previous day's high earns +0.3 score nudge. Cached per-day per-symbol so only one Kite call per stock per session | `data/kite_client.py`, `agents/crew.py` | `get_pdh_pdl()`; saved as `pdh_nudge` in score_breakdown |
| 18 | **NewsAPI company-name aliases** — `COMPANY_NAMES` dict (~80 names) + `get_company_name()`; query NewsAPI with `"<company>" OR <symbol>` instead of bare ticker. Doubles news hit-rate | `config/universe.py`, `data/news_client.py` | "RELIANCE" now matches "Reliance Industries" headlines |
| 19 | **Leaders watchlist — relaxed proximity** — stocks up ≥3% with RS≥1.5% get 1.5% proximity ceiling (vs 0.7%). Catches trending entries that strict proximity rejects | `config/settings.py`, `agents/crew.py` | 6 threshold cases verified |
| 20 | **15-min HTF trend filter** — `get_htf_trend()` classifies last 4 fifteen-min bars as up/down/neutral via HH-HL count. LONG entries vetoed when HTF is DOWN. Defensive `neutral` default on any data shortage | `data/kite_client.py`, `agents/crew.py` | up/down/neutral/short cases verified |
| 21 | **Today-only VWAP/df after weekends** — `days=1` returned 0 bars on Mondays after weekends/holidays (Sun has no market data) → ALL stocks failed `len(df) ≥ 8` check → 0 setups. Now `days=3` + `_filter_to_today()` filter. Also fixes VWAP polluted by prior-session volume | `data/kite_client.py` | engine tests pass; observed log root cause was `few_candles=60/60` after weekend |
| 22 | **A1 — Volume veto for momentum_breakout** — RVOL < 2.0 → reject. Real breakouts come on volume; 60% of low-volume "breakouts" fade. New constant `MOMENTUM_BO_MIN_RVOL=2.0` | `config/settings.py`, `agents/crew.py` | engine tests pass |
| 23 | **A6 — Score-based sizing tiers** — risk scaled by grade: A++ ₹15k, A+ ₹11.25k, A ₹7.5k, B ₹3.75k. Concentrates capital in highest-conviction trades; combines multiplicatively with conservative-mode dampener | `config/settings.py`, `agents/crew.py` | size scaling verified |
| 24 | **A5 — Time-of-day score-gate nudges** — 9 IST +0.5, 10 IST +0.3, 12 IST -0.2 (best hour per file 04). Raises bar in noisy/losing hours, lowers in proven hour | `config/settings.py`, `agents/crew.py` | engine tests pass |
| 25 | **B2 — Volatility-adaptive trail** — `_try_trail_sl` multiplier now context-aware: 0.7×ATR in CHOPPY regime (tighter), 0.4×ATR when RVOL≥2 (looser, let hot trades run), else 0.5×ATR | `agents/crew.py` | engine tests pass |
| 26 | **C1 — Smart re-entry rule** — after 30-min cooldown, allow 2nd entry on same stock at 50% size; hard cap 2/day. New `count_today_trades_on()` in trade_state | `memory/trade_state.py`, `agents/crew.py` | engine tests pass |
| 27 | **D2 — Symbol auto-blacklist** — skip any symbol with ≥3 closed trades AND <30% WR in rolling 30. Kills proven losers (CESC, CEATLTD, JINDALSTEL et al from file 04). New `is_symbol_blacklisted()` in trade_state | `memory/trade_state.py`, `agents/crew.py` | engine tests pass |
| 28 | **B3 — Aggressive trail past +1.5R** — once unrealised pnl_r ≥ 1.5, mult overrides to 0.3×ATR (tightest). Locks more of big winners | `agents/crew.py` | engine tests pass |
| 29 | **A4 — Range expansion check on momentum BO** — trigger bar's range must be ≥ 1.3× mean of prior 5 bars' ranges. Filters fading "breakouts" where momentum is contracting | `tools/pattern_tools.py` | engine tests pass; fail-open on math errors |
| 30 | **A3 — Two-bar confirmation on momentum BO** — prior bar must also be green (close > open). Filters single-bar pops after red-bar sequences (bear traps) | `tools/pattern_tools.py` | engine tests pass |
| 31 | **C2 — Loser-streak gradient dampener** — sizing tier by consec losses: 0→1.0, 1→0.85, 2→0.70, 3→0.50, 4+→0.30. Smooth de-risk replacing the binary cliff at 3 losses | `config/settings.py`, `agents/crew.py` | engine tests pass |
| 32 | **B5 — Time-stop tiers** — Tier 1: 25 min + pnl_r ∈ [-0.5, +0.3] → exit (no-momentum); Tier 2: 45 min + \|pnl_r\| ≤ 0.3 → exit (severe stall, loosened from 0.15). Catches more stuck trades earlier | `agents/crew.py` | engine tests pass |
| 33 | **C3 — Winner-streak gate shift** — after 3 wins in a row today, score gate raised +0.3. Counters regression-to-mean. New `get_consecutive_wins()` in trade_state | `memory/trade_state.py`, `agents/crew.py` | engine tests pass |
| 34 | **B9 — EOD partial unwind** — after 14:45 (NO_NEW_ENTRY_AFTER), force-exit any position still on initial SL (no TP1 hit). TP1-hit positions keep running to 15:00. Frees capital and avoids the 15:00 dump on dead trades | `agents/crew.py` | engine tests pass; new exit reason `eod_partial_unwind` |
| 35 | **A9 — Dynamic lunch-window gate** — midday gate raised to 8.5 (from 8.0) if today_pnl < 0 by 13:00. Adapts risk to morning's tape | `agents/crew.py` | engine tests pass |
| 36 | **A2 — Score decay on aging signals** — `_make_signal` stamps `detected_at` IST. In `_allocate`, if age > 5 min → final_score −0.5 and re-check gate. Defensive against signal queueing across ticks | `tools/pattern_tools.py`, `agents/crew.py` | engine tests pass |
| 37 | **Filter-stack relaxation** — observed full session w/ ZERO entries; the cumulative filters were choking. Relaxed: MOMENTUM_BO_MIN_RVOL 2.0→1.7, hour 9 IST nudge +0.5→+0.3, hour 10 +0.3→+0.2, A4 range expansion 1.3×→1.2×, A9 midday gate 8.5→8.3 | `config/settings.py`, `tools/pattern_tools.py`, `agents/crew.py` | engine tests pass |
| 38 | **Catch smooth grinders (COFORGE/IDEA class)** — agent missed COFORGE +8% / IDEA +5% smooth runs. Two fixes: (a) range_expanded threshold 1.2→1.0 (only rejects truly shrinking, not similar-size bars); (b) TREND_PULLBACK accepts small-body bar (body_ratio<0.35) as pullback marker, not only red bars | `tools/pattern_tools.py` | engine tests pass |
| 39 | **Per-stage rejection counters (diagnostic)** — `self._reject_counts` cleared each tick, incremented at every reject point in `_score_signals` and `_allocate`. Printed at end of tick: `Rejections: htf_down=12, score_below_gate_to_watchlist=8, ...`. **Lets us SEE which gate kills trades instead of guessing.** | `agents/crew.py` | engine tests pass |
| 40 | **Breadth-bearish ≠ kill the tick** — was an EARLY RETURN (`return self._tick_summary(0,0,0)`) on any breadth ≤ 40% → 0 setups even on Nifty −0.07% days w/ strong individual movers. Now: scanner + setups + scoring all run; bearish breadth applies a −0.7 score penalty in `_score_signals` so only A+/A++ fire. **Critical fix — agent had been completely idle on any down-tilt market day.** | `agents/crew.py` | engine tests pass; saved as `breadth_pen` in score_breakdown |
| 41 | **D1 — RAG read activated** — `_score_signals` now queries ChromaDB `signal_patterns` per (setup_type, regime). With ≥5 historical trades: WR≥65% → +0.3 nudge; WR<40% → −0.5; else 0. **Closes the learning loop** — agent had been writing outcomes for weeks but never reading them. Stored as `hist_nudge`/`hist_found`/`hist_wr` in score_breakdown | `agents/crew.py` | engine tests pass |
| 42 | **D4 — EOD self-critique** — single batched Groq call grades each closed trade's PROCESS independent of outcome. 2×2 tag (good/bad-process × good/bad-outcome) is the highest-information learning artefact. New `trade_critiques` Chroma collection + `store_trade_critique` + `get_critique_tag_counts`. Failure is non-fatal | `jobs/eod_job.py`, `memory/chroma_client.py` | engine tests pass |
| 43 | **P1 — Spread filter at entry** — hard reject if `kite.get_spread_pct(sym) > 0.10%`. Wide spreads silently destroy scalp R:R (a 0.10% spread on a 0.7% stop eats 28% of TP1). spread=999 (no depth) → defer, not fail-open. New `ENTRY_MAX_SPREAD_PCT=0.10` | `config/settings.py`, `agents/crew.py` | engine tests pass; new rejects: `spread_too_wide`, `spread_no_depth` |
| 44 | **P2 — RAG proven-loser veto** — stronger than the -0.5 nudge in Fix #41: if (setup × regime) has ≥10 historical trades AND WR < 35%, hard skip. Doesn't take known-loser combos at all. New `RAG_VETO_MIN_TRADES=10`, `RAG_VETO_MAX_WINRATE=35.0` | `config/settings.py`, `agents/crew.py` | engine tests pass; new reject: `rag_proven_loser` |
| 45 | **P10 — Asymmetric cooldown** — last exit was a LOSS → 45-min cooldown (anti-revenge). Last exit was a WIN → 15-min cooldown (let continuation trade fire). `is_in_cooldown` extended w/ `after_loss_minutes` / `after_win_minutes` kwargs (back-compat) | `memory/trade_state.py`, `agents/crew.py`, `config/settings.py` | engine tests pass |
| 46 | **P3 — ORB time-window enforcement** — `_detect_orb_breakout` now only fires between 09:30–10:30 IST. Late ORB breakouts (post-10:30) have ~40% WR vs 65–70% in the proper window | `tools/pattern_tools.py` | engine tests pass |
| 47 | **NO_NEW_ENTRY_AFTER 14:45 → 13:30** — observed pattern: morning idle (filters too tight) → late-afternoon entries → EOD eats them → losses. Late entries had zero physical runway to reach TP1 before EOD partial-unwind (14:45) + 15:00 close. New cutoff gives every trade ≥75 min before exit pressure | `config/settings.py` | engine tests pass |
| 48 | **B1-surgical — TP1 1.0R → 0.7R** — file 04 showed 71% of trades stalled without ever hitting 1R. Lowering TP1 to 0.7R lets partial-profit fire on +0.5% moves (frequent) instead of +1% (rare). Half booked at TP1, SL→BE on the rest, TP2 stays at 2R for the runners. Single-config change, no new filters | `config/settings.py` | engine tests pass |
| 49 | **Rejection telemetry always visible** — Fix #39's `[Crew] Rejections this tick:` line was conditional on non-empty counter. Now prints every tick with diagnostic context ("NONE — no setups detected" / "all candidates passed" / "all setups dropped before scoring"). Always-on operator visibility | `agents/crew.py` | engine tests pass |
| 50 | **Live tab — Realised + Unrealised columns** — was a single P&L column that silently fell back to entry_price on Kite-fetch failure (showed fake +0.00% / ₹+0). Now: split into Realised (booked TP1 partials) + Unrealised (open portion vs live LTP). Failed LTP fetches show "—" not 0, and a warning banner names the affected count | `dashboard/live_tab.py` | engine tests pass |
| 51 | **Dashboard Kite token staleness** — `_get_kite()` was `@st.cache_resource` so the client was built ONCE at dashboard start, holding yesterday's KITE_ACCESS_TOKEN. Engine restarts on `kite_login.py --push` but dashboard does not — so "Live LTP fetch failed N/N" every morning. Fix: drop the cache and reload `.env` per render. State/Chroma caches kept (no token dependency) | `dashboard/live_tab.py` | engine tests pass |
| 52 | **Proximity-failed bucket split (NBCC-class)** — when score≥effective_min but `proximity_ok=False` (price ran past entry trigger), the rejection landed in `score_below_gate_to_watchlist` — same bucket as genuinely-weak signals. Now emits `proximity_failed_to_watchlist` and the per-symbol scorer line tags `⚠ skip-proximity`. Lets us measure how many high-score signals (often A++ momentum names) the 0.7% drift cap is killing. **Diagnostic only — no behavioural change yet. Run 2 days, then decide on late-entry path.** | `agents/crew.py` | engine tests pass |
| 53 | **Dashboard token bug — root cause** — Fix #51 dropped the cache and reloaded .env, but `KiteDataClient.__init__` was reading `KITE_ACCESS_TOKEN` from `config.settings`, which is a Python module constant frozen at the dashboard process's first import. `load_dotenv(override=True)` updates `os.environ` but cannot mutate the cached `config.settings.KITE_ACCESS_TOKEN`. Fix: `KiteDataClient.__init__(access_token=None)` — dashboard now passes the fresh token from `os.environ` explicitly. Engine path unchanged. Dashboard banner now shows the actual exception text instead of swallowing it | `data/kite_client.py`, `dashboard/live_tab.py` | engine tests pass |
| 54 | **Watchlist UX — dedup + LTP + Drift %** — three-part fix triggered by user seeing same NBCC twice in watchlist (scores 9.8 AND 9.1) with stale entry price 97.95 from 40 min earlier. (a) `add_to_watchlist` is now an upsert — DELETE today's row for the same symbol before INSERT, so latest state per symbol only. (b) Dashboard derives Grade from score (DB has no grade column) so A++ score 9.8 no longer reads as "B-grade waiting". (c) New `LTP ₹` + `Drift %` columns: live price for each watchlist symbol so the user instantly sees the gap that triggered proximity-skip. Header rewritten to "proximity-failed (high score, ran past entry) + B-grade waiting" with caption explaining 0.7% drift = proximity gate | `memory/trade_state.py`, `dashboard/live_tab.py` | parse clean |
| 55 | **Dashboard token — defensive override** — Fix #53 added `KiteDataClient(access_token=...)` keyword arg, but a partial deploy (or stale `__pycache__`) on the server caused `TypeError: KiteDataClient.__init__() got an unexpected keyword argument 'access_token'`. Hardened: `_get_kite()` now constructs the client with no args, then calls `client.kite.set_access_token(fresh_token)` on the underlying KiteConnect object. Works against any KiteDataClient version, no signature dependency | `dashboard/live_tab.py` | parse clean |
| 56 | **PHASE A — kill 6 setups, tighten momentum** — 280-trade audit (`docs/08_Findings_From_280_Trades.md`) showed: gross +₹1.72L, net **-₹40k after costs**, mean R per trade only +0.075R gross, 71% stalled-no-movement (unchanged from Doc 04), TP1 hit rate 17%. Only momentum_breakout (n=147, WR 66.7%, +0.159R gross) is viable; other 6 setups bleed. Migration plan revised: instead of Phase A = sizing rewrite, **Phase A = take fewer better trades**. Disabled 6 setups via `SETUP_DISARMED_LIST` (detection still runs for confluence count, but no entries). Tightened momentum: RVOL 1.7→2.0; new requirement confluence ≥ 2 OR top-3 sector via `MOMENTUM_BO_MIN_CONFLUENCE` + `MOMENTUM_BO_REQUIRE_PRIORITY`. Goal: lift mean R to +0.30+, drop trade rate from 14/day to 3-5/day. Partials KEPT (data showed single-target sims all worse). Sizing rewrite deferred to Phase E (after edge is proven) | `config/settings.py`, `agents/crew.py`, `docs/08_Findings_From_280_Trades.md` | syntax + flag-load verified; reversible via 3 config flags |
| 57 | **PHASE D — pending-pullback retest** — Phase A smoke test (`docs/09_Phase_A_Smoke_Test.md`) showed filters alone only lift mean R 0.075→0.114 (insufficient). Real problem: 71% stall = entries land at exhaustion points after the move. Phase D fix: when high-score signal fires but proximity_failed (drift > 0.7%), don't skip — mark `PENDING_RETEST` and watch for price to come back to trigger ± 0.3% within 10 min. On retest, fire entry. Catches NBCC-class moves cleanly. State machine: PENDING_RETEST → READY (fire) / DEAD (timeout / drift > 2% / broke SL). New module `tools/pending_pullback.py` with `PendingPullbackRegistry`. Integrates into crew via 2 hooks: (a) proximity-failed branch in `_score_signals` adds to registry; (b) tick-loop step 6b evaluates registry, READY entries injected into scored list and flow through standard `_allocate` gates (kill switch / cooldown / spread / sector cap / RAG veto / live LTP refetch all preserved). In-memory state for v1; restart loses pending entries (acceptable — entries are < 10min old, next tick reseeds). Audit log to `logs/pending_retest.jsonl`. Telemetry counters: `pending_retest_added`, `pending_retest_fired`. Reversible via `PENDING_RETEST_ENABLED=False` | `config/settings.py`, `agents/crew.py`, `tools/pending_pullback.py` | state-machine unit tests pass (5/5: add, no-false-retest, retest-fires, drift-too-far, broke-SL) |
| 58 | **Watchlist 30-day retention for analytics** — `clear_old_watchlist()` was wiping everything except today, destroying the historical proximity-failed signal data needed for Phase D smoke tests. Now retains 30 days. Dashboard's `get_watchlist()` still filters to today-only (UI unchanged). New method `get_watchlist_history(days_back=30)` for analytics scripts. Enables proper Phase D candidate-rate measurement after 5+ trading sessions | `memory/trade_state.py` | imports + methods verified |
| 59 | **EOD timing rewrite — capture closing momentum** — operator-flagged 2026-05-10: NSE last 30 min (15:00-15:30) has institutional rebalancing + expiry hedging + closing-print activity; we were giving it up. **Two bugs found:** (a) Fix #34 "EOD partial unwind at 14:45" was tied to `NO_NEW_ENTRY_AFTER` constant; when Fix #47 changed that to 13:30, partial unwind started firing at 13:30 — closing non-TP1 positions 105 minutes before market close. (b) `EOD_CLOSE_TIME` was 15:00 — gave up the final 30 min entirely. **Fix:** delete the partial unwind block (let SL/TP/trail handle individual exits through the natural session); move `EOD_CLOSE_TIME` to 15:15 (5 min control buffer before Zerodha MIS auto-square at 15:20). Each position now rides its own exit logic through the highest-momentum window of the day, then force-closes 15 min before market close | `config/settings.py`, `agents/crew.py` | syntax + flag-load verified; pre-flight passes |
| 60 | **Entry cutoff rolled back 13:30 → 14:45** — paired with Fix #59. The 13:30 cutoff (Fix #47) existed only because the buggy partial-unwind at 14:45 would have killed 13:30-14:45 entries with 15 min runway. Fix #59 deleted that bug — now 14:45 entries get 30 min runway to the 15:15 force-close, fully through the closing-momentum window. Recovers the 13:30-14:45 trading hour we were forfeiting. Note: full session timing is now (a) 09:20 first entry → (b) 14:45 last entry → (c) 15:15 force-close → (d) Zerodha auto-square 15:20. Operator-flagged scalper insight: pro scalpers trade through closing momentum, not before it | `config/settings.py`, `docs/01_Project_Overview_and_Goal.md` | flag-load verified; pre-flight passes |

**Constants added to `config/settings.py`:**
`DAILY_LOSS_KILL_PCT=0.025`, `DAILY_PROFIT_LOCKOUT_PCT=0.030`, `DAILY_PROFIT_TIGHTEN_PCT=0.020`, `CONFLUENCE_MULTIPLIER_2=1.15`, `CONFLUENCE_MULTIPLIER_3=1.25`, `SCAN_MIN_TURNOVER=5_000_000`, `TICK_SIZE=0.05`, `MIN_RISK_PER_TRADE_PCT=0.0003`, `MIN_POSITION_VALUE_PCT=0.03`, `MAX_POSITION_VALUE_PCT=0.10` (was 0.20).

**Schema additions on `positions`:** `sl_order_id TEXT DEFAULT ''`, `regime TEXT DEFAULT ''`.

**SetupType enum now (8 setups):** MOMENTUM_BREAKOUT, VWAP_PULLBACK, VWAP_RECLAIM, FAILED_BREAKDOWN, RANGE_BREAKOUT, RECOVERY_SETUP, **TREND_PULLBACK** (Fix #10), **INSIDE_BAR_BREAK** (Fix #12). All have multipliers across all 4 regimes.

**New runtime files:** `news_cache.json` (persistent Groq cache; in `.gitignore`).

**Helpers in `agents/crew.py`:** `_entry_dt_aware`, kill-switch block at top of `_allocate`, overnight-veto block at top of `_manage_positions`, multi-setup integration in `_detect_setups`, confluence multiplier in `_score_signals`, SL-M place/cancel/replace plumbing throughout.

**Helpers in `memory/trade_state.py`:** `_now_iso_ist`, `_to_ist`, `update_sl_order_id`. `Position` dataclass has `sl_order_id` field.

**Behaviour to expect post-deploy:**
- `stalled_no_movement` exits should drop from 71 % → < 25 %.
- A++ count should fall sharply (calibration tightened); A WR should hold ~70 %.
- Logs show `⚡ CONFLUENCE x{n}` lines, `🛑 SL-M placed`, `🛑 DAILY-LOSS KILL SWITCH`, `⚠ OVERNIGHT VETO`.
- `news_cache.json` present after first session; reload logged on restart.
- All generated prices are multiples of ₹0.05.

---

## 🏗️ PHASE 0 → 3.0.1 REBUILD (2026-05-11 → 2026-05-12)

**Context:** The 30-month NIFTY analysis (docs 13-16, n=584 sessions) showed the old 0-10 scoring engine with regime-multiplier nudges was *anti-predictive* — A++ trades returned -0.095R while A trades returned +0.092R across 280 audited trades. Complete teardown + rebuild against empirically-validated structural rules. New code is feature-flagged; the old `_score_signals` path is preserved for fallback during shadow validation.

### Phase 0 — Foundation (shipped 2026-05-11)

| # | Phase | What changed | Files | Validation |
|---|---|---|---|---|
| 61 | **Phase 0** — Macro+FHH+Conviction stack | New `market_state.py` (10:15 IST 5-state filter STRONG_GREEN/GREEN/YELLOW/RED/STRONG_RED, validated 98%/72%/coin/74%/89% close-precision n=584); new `fhh_break_detector.py` (first-hour-high break per-symbol, validated 97-100% close-positive when combined with macro); new `conviction_engine.py` returns tier S/A/B/SKIP replacing the 0-10 score. Old `ScoringEngine` deleted; minimal neutral stub retained for crew.py import compat | `agents/market_state.py`, `agents/fhh_break_detector.py`, `agents/conviction_engine.py`, `scoring/engine.py` | 30-month backtest + sandbox unit tests |
| 62 | **Phase 0.5/0.6** — Strip legacy nudges + trim setups | Removed empirically-wrong: HOUR_GATE_NUDGES application, midday lunch gate, sector_nudge, breadth_pen, winner-streak gate raise. Trimmed `_detect_setups_multi` to ONLY produce MOMENTUM_BREAKOUT (6 other detectors dormant). Extracted tick-rounding helpers to `tools/tick_utils.py` | `agents/crew.py`, `tools/pattern_tools.py`, `tools/tick_utils.py` | pre-flight script + 7-test suite |
| 63 | **Phase 1.1** — Stock-level FHH + HOD proximity | Conviction engine now requires the STOCK's own first-hour-high to be cleanly broken (not just NIFTY's). HOD-proximity gate rejects entries > 0.5% below intraday high (don't chase extended moves) | `agents/conviction_engine.py`, `config/settings.py` (STOCK_HOD_PROXIMITY_PCT=0.005) | engine tests pass |
| 64 | **Phase 1.2** — Pre-TP1 trail SL | Move SL to break-even after +0.5R held 10 min. Uses cancel_order + place_sl_order (NOT modify_order which doesn't exist on KiteDataClient — caught in pre-flight) | `agents/crew.py`, `config/settings.py` (PRE_TP1_TRAIL_ENABLED, PRE_TP1_TRAIL_TRIGGER_R=0.5, PRE_TP1_TRAIL_HOLD_MIN=10) | targeted unit test |
| 65 | **Phase 1.3** — Whipsaw freeze | When NIFTY breaks BOTH first-hour-high AND first-hour-low (whipsaw signature, 70% historical chop), block all new entries | `agents/conviction_engine.py`, `config/settings.py` (WHIPSAW_FREEZE_ENABLED=True) | engine tests pass |
| 66 | **Phase 1.5/1.6/1.7** — Day-type + NR7 + Volatility sizing | `agents/day_type_classifier.py` classifies at 11:00 IST (TREND_FORMING_UP/DN, RANGE_FORMING, BALANCED) — conviction skips TREND_FORMING_DN and RANGE_FORMING. `tools/volatility_state.py` detects NR7 day-after expansion (66% follow-through) + COMPRESSED/NORMAL/EXPANDED/EXTREME regime → size multiplier 0.7-1.2× | `agents/day_type_classifier.py`, `tools/volatility_state.py`, `agents/conviction_engine.py` | engine tests pass |

### Phase 2 — Visibility, capacity, override (shipped 2026-05-12)

| # | Phase | What changed | Files | Validation |
|---|---|---|---|---|
| 67 | **Phase 2.0** — Telemetry patch | Added `[MarketState]`, `[FHH]`, `[Day-Type]`, `[Vol-State]` log lines so the new Phase 1 modules are visible in journalctl. Refresh regime every tick (was every 5 ticks → went stale on adversarial days). Fixed misleading "1 entries" counter (now counts post-conviction admits, not scorer passes). Removed stale "-0.7 penalty" breadth log message (penalty was already zeroed in Phase 0.5) | `agents/market_state.py`, `agents/fhh_break_detector.py`, `agents/day_type_classifier.py`, `tools/volatility_state.py`, `agents/crew.py`, `main.py` | live observation 2026-05-12 |
| 68 | **Phase 2.1** — Discovery Engine | New `agents/discovery_engine.py`. Seeds candidate pool from `kite.instruments(NSE)` at boot (~600-900 names), scans every 5 min, admits names crossing ±2.5% on >1.5× volume with ≥₹10cr turnover + ≤0.15% spread. Bounded: 5 new/scan, 15 total live, 40/session. Auto-blacklist after 2 losses (persisted to `discovery_blacklist.json`). **Shadow mode default** via `DISCOVERY_ALLOW_TRADES=False`. Catches the 2026-05-12 JINDRILL +7.81% / OIL India +7.66% class of names that were structurally invisible to the 150-stock hardcoded universe | `agents/discovery_engine.py`, `agents/crew.py`, `config/settings.py` | 13/13 acceptance tests on today's tape |
| 69 | **Phase 2.2** — Sector-aware macro | **REJECTED** based on same-day evidence. Original spec (doc 20): admit longs in sectors that are DECOUPLED_STRONG at 10:15 even on STRONG_RED days. 2026-05-12 tape: METAL +0.52% morning → -0.35% close. Sector decoupling collapsed entirely; relief admits would have lost money. Replaced by Phase 2.3 stock-level rule instead | — (spec only at `docs/20_*.md`) | counterfactual replay against 2026-05-12 tape |
| 70 | **Phase 2.3** — Stock decoupling override | New `agents/stock_decoupling.py`. On macro RED/STRONG_RED days, admits longs at tier B- (half-size) when ALL 6 conditions hold: stock %chg ≥ +4%, vol ratio ≥ 1.5×, LTP within 0.5% of HOD, sector index ≥ -1.0%, stock's own FHH cleanly broken, ≥ 11:00 IST. Catches ONGC +5.93% case from 2026-05-12 that pure macro filter blocked. **Shadow mode default** via `STOCK_DECOUPLING_ENABLED=False` | `agents/stock_decoupling.py`, `agents/conviction_engine.py`, `config/settings.py` (6 thresholds + SYMBOL_SECTOR_TO_INDEX mapping) | 10/10 acceptance tests |
| 71 | **Phase 2.5** — Hygiene | Removed midday-lull `[Crew] Midday lull (13:00–14:00) — selective only` print spam (gate is informational only — no behavior). Retagged legacy regime detector as `[LegacyRegime] RECOVERING|EVENT|TRENDING|CHOPPY ... (informational only; [MarketState] gates entries)` to distinguish from Phase 0 conviction state. NO_NEW_ENTRY_AFTER stayed at 14:45 (Fix #60 rollback was correct — 13:30 was too aggressive) | `agents/crew.py` | live in next deploy |
| 72 | **Phase 2.6** — Runway check (shadow) | New `agents/runway_check.py` replaces the blunt `NO_NEW_ENTRY_AFTER` clock with empirical setup-aware: `median_TTP1 × 1.5 ≤ remaining_minutes_to_14:45`. Reads median time-to-TP1 per setup from `trade_state.db` (last 50 wins). Bootstrap fallback ladder (setup-specific → global 45m) for cold start. Absolute floor: never enter < 20 min before EOD. **Shadow mode default** via `RUNWAY_CHECK_ENABLED=False` + `RUNWAY_CHECK_LOG_SHADOW=True`. Final removal of clock categories from entry path | `agents/runway_check.py`, `memory/trade_state.py` (new `get_median_ttp1_minutes()`), `agents/conviction_engine.py`, `config/settings.py` (7 constants + setup defaults) | 8/8 acceptance tests |

### Phase 3.0.1 — Live-probe safety nets (shipped 2026-05-12)

| # | What changed | Files | Validation |
|---|---|---|---|
| 73 | **Weekly drawdown kill** (-7.5% of CAPITAL → block entries + Telegram alert) + **Boot-time consecutive-losing-days pause** (5 losing days → block until manual reset) + **Monthly negative-R review** (last trading day → flag for retrospective, no auto-pause). Three new queries on TradeStateManager: `get_week_pnl()`, `get_consecutive_losing_days()`, `get_month_avg_r()` | `memory/trade_state.py`, `agents/crew.py`, `jobs/eod_job.py`, `config/settings.py` (WEEKLY_LOSS_KILL_PCT=0.075, CONSECUTIVE_LOSING_DAYS_PAUSE=5, MONTHLY_NEG_R_REVIEW=True) | 10/10 acceptance tests |
| 74 | **Probe-mode settings + helpers** (Phase 3 go-live prep). `PROBE_MODE_ENABLED` flag (default False) + `PROBE_CAPITAL=50_000` + scaled risk table (S/A=₹500, B=₹250) + helper functions `get_active_capital()` / `get_active_max_positions()` / `get_active_conviction_risk()` / `get_active_conviction_target()`. Footgun-prevention: flipping `PAPER_TRADING=False` alone would route real orders at paper-sized (₹15L) risk — must also flip `PROBE_MODE_ENABLED=True` | `config/settings.py` | settings constant verification |

### Phase 2.1 hardening + Phase 2.7-2.9 (shipped 2026-05-18)

Live-day observation surfaced a critical Discovery bug + opportunities for the next layer of validation infrastructure.

| # | What changed | Files | Validation |
|---|---|---|---|
| 75 | **Discovery field-name bug fix** — boot log showed `seeded candidate pool — 0 NSE EQ names` despite 9,780 instruments loading. Root cause: filter checked `series == "EQ"` but Kite's bulk `instruments(exchange)` SDK call returns `instrument_type` (EQ/FUT/CE/PE), NOT `series` (which is only in `search_instruments` responses). Swapped to correct field name. Pool now seeds ~1,500 NSE EQ names | `agents/discovery_engine.py`, test mock updated | 13/13 acceptance tests still pass; diagnostic counter `non-EQ-type=9780→~8200` confirms fix |
| 76 | **Discovery persistent daily-context + per-scan rate-limit budget** — three rate-limit hazards fixed: (a) `_daily_context` cache was per-session in-memory, wiped on restart → re-fetched 100+ daily-history endpoints on every boot; (b) failed Kite fetches were cached as empty `_DailyContext()`, permanently rejecting the symbol for the session; (c) no per-scan call budget → cold boot could fire 100+ calls in seconds, tripping Kite's 10 req/s limit. New: persist to `discovery_daily_ctx.json` keyed by symbol+date, never cache empty results, `DISCOVERY_MAX_NEW_CONTEXT_FETCHES_PER_SCAN=10` setting | `agents/discovery_engine.py`, `config/settings.py` | acceptance tests pass; sample log line confirms `daily context cache: N symbols loaded (today)` at boot |
| 77 | **Discovery news catalyst attribution** — when DiscoveryEngine admits a name, fire `NewsClient.get_news_for_symbol()` on a cold path (best-effort, never blocks scan). Logs `[DiscoveryNews] SYMBOL: "headline" sentiment=X catalyst=Y` second line + appends full admit + news to `discovery_admits.jsonl`. Builds the recurring-catalyst dataset (e.g. JINDRILL ran +7.81% on 2026-05-12 and +8.59% on 2026-05-18 — likely same crude/oil-services catalyst). Failure modes handled: Groq 429, NewsAPI timeout, etc. | `agents/discovery_engine.py`, `agents/crew.py` | E2E stub test verified [DiscoveryNews] emits + JSONL appends correctly |
| 78 | **Phase 2.7 — Mid-Trade Structural Re-evaluation** — new `agents/mid_trade_reeval.py`. Every `MID_TRADE_REEVAL_INTERVAL_MIN` (default 5) per open position, re-checks 3 thesis dimensions: macro state (allows long?), VWAP (LTP ≥ today's VWAP?), HOD-proximity (LTP within 1.5% of intraday high?). Action ladder: 0-1 broken=CONTINUE, 2=TIGHTEN_TO_BE (move SL to entry), 3=CLOSE at market. Catches the "got in clean, market changed under me" loss class. **Shadow mode default** via `MID_TRADE_REEVAL_ENABLED=False`. See doc 24 | `agents/mid_trade_reeval.py`, `agents/crew.py`, `config/settings.py` (6 constants) | 10/10 acceptance tests pass |
| 79 | **Phase 2.8 — RVOL ghost-trade telemetry** — new `tools/rvol_ghost.py`. When the scorer rejects a `momentum_breakout` setup for RVOL < 2.0 (Fix #22/Fix #56), append a structured record to `rvol_ghost.jsonl` with symbol, RVOL, would-be entry/SL/TP1, direction, macro state. Best-effort writes — never breaks rejection flow. Anecdotally the 2.0 floor saves more losses than it misses wins (ABB@1.96 closed -0.92%, ONGC@1.93 closed +5.93% on 2026-05-12), but no structured dataset existed. Now we get one | `tools/rvol_ghost.py`, `agents/crew.py` | unit test: 2 records written + read back correctly; bucket distribution test passes |
| 80 | **Phase 2.8 — RVOL backtest analyzer** — new `scripts/rvol_backtest.py`. Reads `rvol_ghost.jsonl`, for each rejection pulls 5-min candles from Kite, walks forward bar-by-bar to determine outcome (TP1 hit / SL hit / EOD pnl_r), buckets by RVOL (`[0.5-1.0)`, `[1.0-1.5)`, `[1.5-1.7)`, `[1.7-2.0)`, `[2.0-2.5)`, `[2.5+]`), produces win-rate + mean R per bucket, recommends `MOMENTUM_BO_MIN_RVOL` threshold based on lowest bucket with n≥5 AND positive mean-R. After 2-3 weeks of accumulated data, this replaces "we think 2.0 might be too tight" with empirical evidence | `scripts/rvol_backtest.py` | bucket-labeling tests pass; analyzer ready to run once data accumulates |
| 81 | **Phase 2.9 — `tools/shadow_log.py` helper** — single `record_shadow_event(event_type, data, path)` function. Used by `agents/crew.py` (Reeval TIGHTEN-SHADOW / CLOSE-SHADOW events → `reeval_shadow.jsonl`) and `agents/conviction_engine.py` (Decoupling ADMIT-SHADOW events → `decoupling_shadow.jsonl`). Same JSONL pattern as `discovery_admits.jsonl` and `rvol_ghost.jsonl`. Best-effort writes — never breaks the caller | `tools/shadow_log.py`, `agents/crew.py`, `agents/conviction_engine.py` | unit test confirms structured records write correctly |
| 82 | **Phase 2.9 — Shadow Mode dashboard tab** — new 4th tab in Streamlit dashboard. Reads all 4 shadow JSONL files and renders: (1) 🔍 Discovery Admits table with catalyst headlines, (2) 🎯 Decoupling would-admit table, (3) 🔄 Re-eval TIGHTEN/CLOSE events table, (4) 📉 RVOL Ghost Rejections with bucket histogram + table. Top metrics row shows count-per-file. "Show today only" checkbox to filter. Lets us scan "what did the agent NEARLY do today?" without grepping journalctl | `dashboard/shadow_tab.py`, `dashboard/app.py` | AST clean; sample JSONL data renders correctly |

### Live-day hardening (shipped 2026-05-18 PM)

After Phase 2.9 deployed, a live-day session surfaced two classes of issues:
(a) Discovery seed-pool filter was too permissive (CF-blocked + over-seeded);
(b) A scalper-lens code audit found 4 critical bugs / hostile-defaults in the
crew.py tick path that were silently nuking conviction-engine admits.

**Discovery filter + chunking hardening (v3 → v5):**

| # | What changed | Files | Validation |
|---|---|---|---|
| Dv3 | **Filter v3 — suffix regex expanded** — added `-SM` (SME), `-RR` (REIT/Rights Renounce), `-IV` (InvIT), `-NG` (debt notes), `-Y\d` (debt), `-IT` (trust) to `_NON_EQ_SUFFIX_RE`. Also added 0.6s sleep between Kite quote chunks + 2-consecutive-empty abort to defuse Cloudflare burst-detection. Pool dropped from 9,538 → 2,547. **First live Discovery admit ever**: FCL +19.97% on 2026-05-18 14:30 IST (but stock at upper circuit — see Fix #164 below) | `agents/discovery_engine.py` | 36/36 then 85/85 filter regression tests |
| Dv4 | **Filter v4 — `-SF` suffix + per-chunk retry-with-backoff** — caught `QSIFAARG-SF`/`QSIFAARR-SF` leaks. Added 2.5s retry on empty CF-blocked chunks. FAILED in production: identical 30KB URL on retry hits identical CF fingerprint block. Retry approach abandoned | `agents/discovery_engine.py` | retry didn't help; CF blocks on URL signature, not transient state |
| Dv5 | **Chunk size 500 → 150** — root cause of CF blocks was URL length (30KB with 500 instrument tokens). 150-symbol chunks give ~10KB URLs, well under bot-pattern thresholds. 17 chunks × 0.6s sleep ≈ 18s total scan latency, well inside 3-min tick interval | `agents/discovery_engine.py` | syntax clean; live verification on next boot |

**Scalper-lens audit fixes (Fix #159-162):**

| # | What changed | Files | Validation |
|---|---|---|---|
| 159 | **`place_sl_order` kwargs mismatch** — `crew.py:1686-1691` (PreTP1Trail) and `1764-1769` (Reeval-Tighten) called `place_sl_order(symbol=, quantity=, trigger_price=, direction=)` but the actual signature is `(symbol, transaction, quantity, trigger, price)`. Would TypeError on every live SL tighten. Broad `except Exception` was hiding it in paper mode. Live mode flip would silently leave SL at the original stop — exactly the loss class Phase 1.2 was added to prevent | `agents/crew.py` | both call sites fixed; syntax clean |
| 160 | **Bypass `_score_signals` gates when conviction is authority** — `_score_signals` was running BEFORE conviction every tick, applying `MIN_SCORE_ENTRY=7.0` + RVOL veto + score decay + per-setup gates. The stub scorer returns ~3-6 for most clean structural admits → conviction admits died at the score gate before `_allocate` ever saw them. 4 surgical edits: (a) `_score_signals` `will_enter` gate now bypasses score check when `USE_CONVICTION_ENGINE=True`; (b) `+2R tighten` filter replaced with conviction-tier filter (S-only instead of score ≥ 8.0); (c) signal-age >5min now hard-skips in conviction mode instead of score-decay-and-re-gate; (d) sizing uses `conviction_size_mult` instead of double-scaling with `SCORE_SIZE_TIERS`. Conviction engine is now the sole decision authority — old path preserved for fallback | `agents/crew.py` | syntax clean; behavior gated on existing flag |
| 161 | **Wire `PROBE_MODE_ENABLED` through `_allocate`** — `config/settings.py` had `get_active_capital()`/`get_active_max_positions()`/`get_active_conviction_risk()`/`get_active_conviction_target()` helpers ready, but `crew.py` was using bare `CAPITAL` (₹15L) and `MAX_POSITIONS` in 6 places. Flipping `PROBE_MODE_ENABLED=True` + `PAPER_TRADING=False` for the ₹50k live probe would size against ₹15L — **30× intended risk**. Now `_allocate` reads `active_capital`/`active_max_positions` once at top, used consistently throughout (kill-floor, lockout-ceiling, week-floor, max-pos check, risk-amount, max-pos-val, min-risk, min-pos) | `agents/crew.py` | syntax clean; helper returns verified |
| 162 | **HOD proximity 0.5%→1.2%, change_pct floor -0.3%** — conviction engine was rejecting any stock with `change_pct < 0` AND requiring LTP within 0.5% of day high. Together: stock must be POSITIVE on the day AND within 0.5% of HOD. That eliminated every clean pullback-to-FHH-retest entry (the canonical scalper setup — stock is up structurally, just pulled to test the breakout level). New: `STOCK_HOD_PROXIMITY_PCT=0.012` (1.2%) + new `STOCK_CHANGE_PCT_FLOOR=-0.003` setting (-0.3%). Captures "flat with bullish structure" while still rejecting clearly-bearish bouncing-from-low names | `config/settings.py`, `agents/conviction_engine.py` | settings load verified; conviction_engine imports clean |

**Audit findings deferred to next pass (logged for visibility):**

- 🟡 `_score_signals` does 4-7 Kite quote calls per candidate per tick — race-prone, slow. Should cache `self._quote_cache` for the duration of a tick.
- 🟡 `conviction_engine.py:220` sizing math `0.5 * dec_res.size_multiplier * 2` cancels itself; works by coincidence. Should be `0.5 * dec_res.size_multiplier`.
- 🟡 `place_order` returns `None` on broker reject without exit-path recheck → state can write "closed" when order didn't actually exit.
- 🟢 `_is_midday()` still survives; leaks `"midday_mode"` to dashboard status JSON (Three-Laws Law-3 violation).
- 🟢 14 stale constants in `settings.py` from Phase 0.5 (HOUR_GATE_NUDGES, MIN_SCORE_ENTRY_CONSERVATIVE, CONFLUENCE_MULTIPLIER_2/3, etc.) — defined but never read.
- 🟢 `tools/pattern_tools.py` still has 1500+ LOC of unused detectors with `_detect_orb_breakout`'s hardcoded 09:30-10:30 IST gate — dead-code Three-Laws violation surface.

### Open / pending after this work

Shadow flags (all default False — flip after observed data validates):
- **DISCOVERY_ALLOW_TRADES = False** — flip after 3-5 sessions of clean shadow logs in the Shadow tab
- **STOCK_DECOUPLING_ENABLED = False** — flip after 3-5 sessions
- **RUNWAY_CHECK_ENABLED = False** (logs admit-shadow / would-skip lines) — flip after 2 sessions
- **MID_TRADE_REEVAL_ENABLED = False** — flip after 3-5 sessions of `[Reeval]` shadow logs (only fires when positions exist)
- **PAPER_TRADING = True** + **PROBE_MODE_ENABLED = False** — flip both simultaneously at Phase 3 start (target: ~3 weeks out)

Empirical questions waiting on data:
- **B1 (hardcoded sector-priority filter)** — KEEP for now; needs 30-month back-test using existing trade_state schema
- **B7 (RVOL 2.0 threshold)** — KEEP for now; **`scripts/rvol_backtest.py` will give a data-driven answer** after 2-3 weeks of `rvol_ghost.jsonl` accumulation

Cleanup deferrals (cosmetic):
- **Phase 1.8 (deprecated constants cleanup)** — DEFERRED, cosmetic only
- **PROJECT_MEMORY Fix #75-#82** — ✅ ADDED above (this entry self-completes)
- **Move Discovery scan to jobs/discovery_cron.py** — would clean up inline-in-crew.py structure but no behavior change

### Doc index after this work

- doc 01-04: original architecture + historical analysis (unchanged)
- doc 05-12: setup audits, validation reports (auto-generated where applicable)
- doc 13: 6-month scalper research (10:15 macro discovery)
- doc 14: 18-month OOS validation
- doc 15: setup pattern library (FHH break + day-type + NR7 + vol regime)
- doc 16: 30-month final analysis (584 sessions — the empirical foundation)
- doc 17: full rebuild plan
- doc 18: rebuild status (Phase 0+1)
- **doc 19: Discovery Engine spec (Phase 2.1)**
- **doc 20: Sector-aware macro spec — REJECTED**
- **doc 21: Stock decoupling spec (Phase 2.3)**
- **doc 22: Runway check spec (Phase 2.6)**
- **doc 23: Phase 3 live probe operations playbook**
- **doc 24: Mid-trade re-evaluation spec (Phase 2.7)**

### JSONL audit files generated at runtime

These accumulate across sessions and feed the dashboard Shadow tab + offline analyzers:
- `discovery_admits.jsonl` — one row per Discovery admit, with catalyst headline (Phase 2.1.2)
- `discovery_daily_ctx.json` — per-symbol 20-day avg volume / turnover cache (Phase 2.1.1)
- `discovery_blacklist.json` — auto-blacklisted Discovery names (Phase 2.1)
- `rvol_ghost.jsonl` — one row per RVOL rejection (Phase 2.8)
- `reeval_shadow.jsonl` — one row per Reeval TIGHTEN/CLOSE event (Phase 2.9)
- `decoupling_shadow.jsonl` — one row per Decoupling ADMIT-SHADOW event (Phase 2.9)

---

## ✅ RESOLVED — paper-trade fill-price mismatch (flagged 2026-04-29, fixed via Fix #13)
```
Symptom (Bhagya, live observation 2026-04-29):
  Telegram entry alert says M&MFIN bought @ ₹320.55.
  Dashboard shows entry ₹320.55.
  Within seconds, actual LTP on Kite is ₹322.05 — a ₹1.50 (~0.47%) gap.

Likely cause:
  state.open_position() stores entry_price = signal["entry_price"], which is
  the CLOSE of the trigger bar (from _detect_setups, possibly 1-3 minutes old).
  Then kite.place_order() runs — in paper mode it just stamps a fake order id,
  it does NOT refresh the actual fill price.
  → Paper P&L is computed against an optimistic entry that wouldn't be
    achievable live. All "wins" today are inflated by this slippage gap.

Where the fix likely belongs:
  - agents/crew.py::_allocate — after place_order returns, refetch quotes,
    overwrite Position.entry_price with the actual LTP.
  - OR: don't call open_position until AFTER fetching the live LTP at order time.
  - Same fix needed for partial_exit_tp1 and full_exit (exit price should be
    actual fill, not signal-bar close).

Implications for the production go-live (2-3 weeks out):
  - Live mode will reveal the true edge (with real slippage). Today's
    paper P&L is overstated by roughly the size of this gap × number of trades.
  - Real round-trip slippage on a tight scalp could be 0.3-0.6%, which
    eats much of the targeted ₹1500-3000 net per trade.

Status: ✅ FIXED 2026-04-29 as Fix #13.
  - _allocate now fetches FRESH LTP, validates proximity vs live, uses live LTP as fill
  - _partial_exit_tp1 refetches LTP at TP1 fire
  - _full_exit refetches LTP at exit
  - All paths fall back gracefully on quote failure
```

## 🚨 PRODUCTION MANDATE (Bhagya's rule, 2026-04-28)
```
This agent will move to LIVE TRADING with REAL MONEY in 2–3 weeks.
Before suggesting or writing ANY code:
  - Treat every line as production code that will handle real INR.
  - No hallucinated function names, classes, or imports — verify against the repo.
  - No vague pseudocode — every fix must be concrete, testable, and deterministic.
  - Defensive bounds (None checks, div-by-zero, empty df) on every new function.
  - All new prices must go through tick-rounding (Fix #7 helpers).
  - All new timestamps must be IST-aware (Fix #1 helpers).
  - All new scoring inputs must integrate with the regime-multiplier table.
  - When adding a SetupType: enum + REGIME_MULTIPLIERS row + tests, ALL three.
  - Verify with python -c "import ast; ast.parse(...)" + run tests/test_engine.py
    after every code change.
  - If unsure about behaviour → ask. Never guess on production code.
```

## ⚡ TOKEN DISCIPLINE — STRICT (Bhagya's rule)
```
Opus 4.7 burns tokens fast. Every Claude session must:
- Be concise. No preamble. No "Here's what I'll do" intros.
- Use Edit (not Write) when modifying files. Read only the lines needed.
- Batch related tool calls in one message — avoid round-trip confirmations.
- Short prose in chat replies. No verbose markdown unless creating a deliverable doc.
- Never re-read files already read in the same session.
- Status updates: 1–2 sentences max.
- Long deliverables (.md docs, full code files): full content is fine — that's the work product.
```

## ⚡ Claude rules for every code change session
```
AFTER EVERY BUG FIX OR CODE CHANGE — always do these 3 things automatically:

1. Commit + push (tell Bhagya to run from Mac terminal):
   cd ~/Desktop/India_Trading_System
   rm -f .git/HEAD.lock .git/index.lock   # clear locks if needed
   git add <changed files>
   git commit -m "fix: description"
   git push origin main

2. Deploy to server:
   ssh root@168.144.101.223 "cd /root/india_trading && git reset --hard HEAD && git pull && systemctl restart trading-system && echo Done"

3. Check live logs:
   ssh root@168.144.101.223 "journalctl -u trading-system -f"

Never just say "fix is done" — always provide all 3 commands at the end.
```

---

## Project identity
- **Owner:** Bhagya (Bhagyashree Khatri)
- **Project:** India_Trading_System
- **Location:** ~/Desktop/India_Trading_System (Mac)
- **Server:** DigitalOcean 168.144.101.223 (systemd service: trading-system)
- **Dashboard:** http://168.144.101.223:8501 (3 tabs working)
- **Type:** NSE intraday paper trading → live later

---

## Tech stack
```
Python 3.x
Pure Python orchestration — TradingCrew class (NOT CrewAI — removed)
Groq llama-3.3-70b  — news sentiment ONLY (not scoring)
ChromaDB 0.4.22     — vector memory (3 collections)
Kite Connect 5.0.1  — Zerodha (data + orders)
NewsAPI             — Bhagya has API key
Streamlit 1.31.1    — read-only dashboard (3 tabs)
SQLite              — trade state DB
python-dotenv       — .env management
Telegram Bot API    — real-time alerts
```

---

## Architecture: Pure Python TradingCrew (no CrewAI)

`agents/crew.py` → one `TradingCrew` class with 8 internal methods:
```
_scan_market()        150 stocks → batch quotes → top active
_detect_regime()      Nifty+BankNifty VWAP → TRENDING/CHOPPY/RECOVERING/EVENT
_detect_breadth()     50-stock sample vs VWAP → breadth_pct + top sectors
_detect_setups()      calls _detect_all_setups() per stock (pattern_tools)
_score_signals()      ScoringEngine + time filter + consecutive loss guard
_allocate()           position sizing + sector cap + proximity check + all gates
_manage_positions()   TP1 partial exit + trailing SL + full exit + EOD close
run_tick()            calls all above → returns summary dict
```

---

## 7 Setup types
```
1. momentum_breakout    — breaks above 20-bar high, volume 1.5× avg
2. vwap_pullback        — pullback to VWAP in uptrend, bullish candle
3. vwap_reclaim         — price reclaims VWAP after being below
4. failed_breakdown     — breaks below support, immediately reverses
5. range_breakout       — 10-bar range ≤2%, breaks with volume
6. recovery_setup       — fell >3% from open, recovering above VWAP
7. orb                  — Opening Range Breakout (9:15–9:30 range)
```

---

## Scoring formula
```
Raw Score = setup_quality(0-3) + volume(0-2) + market_alignment(0-2)
          + relative_strength(0-2) + news(0-1, penalty -0.5)
Final = Raw × Regime Multiplier (capped 10)

Regime multipliers:
                    TRENDING  CHOPPY  RECOVERING  EVENT
momentum_breakout     1.2     0.6      1.0        0.7
vwap_pullback         1.0     1.2      1.0        0.7
vwap_reclaim          1.0     1.1      1.4        0.7
failed_breakdown      1.0     1.1      1.1        0.7
range_breakout        1.1     0.7      0.9        0.7
recovery_setup        0.8     0.8      1.3        0.7
orb                   1.1     0.8      1.0        0.7

Grades:
A++ 9-10  → full size immediately
A+  8-9   → full size
A   7-8   → standard size
B   5-7   → half size, capital idle only
C   <5    → ignore
```

---

## Trading rules
```
PAPER_TRADING = True
Capital ₹2,00,000 | Max 10 positions | Max 30% per sector
Risk 1% = ₹2,000 per trade | qty = floor(2000 / sl_distance)
TP1 = 1R (50% exit) | TP2 = 2R (remaining 50%)
Trailing SL: after TP1 → trail by 0.5×ATR per tick
Price >0.7% from signal = skip
30-min cooldown per stock after exit
No entry before 9:20 | No entry after 14:45
Midday 13:00–14:00: score threshold +0.5
Breadth gate: <40% stocks above VWAP → no new entries
3 consecutive losses → conservative mode (score=8.0, size=50%)
EOD force-close at 15:00
3 human controls: kill switch | score threshold | max positions
```

---

## Key Position fields (do NOT use old names)
```python
# USE THESE:
tp1_price, tp2_price    # NOT target_price
entry_reason            # NOT reason
initial_sl              # original stop loss for R calculation
tp1_hit: bool           # True after partial exit
quantity_remaining      # after TP1 partial exit
```

---

## ChromaDB status
```
3 collections: signal_patterns, news_signals, regime_context
STATUS: Storing data ✅ | RAG loop NOT wired ❌

⚠️ DO NOT wire RAG into scoring yet
Need 50+ closed trades first (~2-3 weeks paper trading)
Empty DB = 0% win rate = incorrectly blocks all entries
Phase 3 ETA: mid-May 2026
```

---

## Files — ALL BUILT (Phase 1 + 2 complete)
```
config/settings.py       ✅ all params incl. TP1/TP2/trailing/breadth
config/universe.py       ✅ 150 stocks + SECTOR_MAP + SECTOR_LEADERS
data/kite_client.py      ✅ KiteDataClient
data/news_client.py      ✅ NewsClient + Groq sentiment
scoring/engine.py        ✅ ScoringEngine — 10/10 tests passing
tests/test_engine.py     ✅ full test suite
memory/trade_state.py    ✅ TradeStateManager (SQLite)
memory/chroma_client.py  ✅ ChromaMemory (3 collections)
tools/kite_tools.py      ✅
tools/volume_tools.py    ✅ breadth + sector strength
tools/pattern_tools.py   ✅ 7 setups + ORB + gap analysis
tools/news_tools.py      ✅
tools/chroma_tools.py    ✅
tools/score_tools.py     ✅ partial_exit_tp1(), close_position()
tools/telegram_tools.py  ✅ 9 alert functions
agents/crew.py           ✅ TradingCrew (pure Python)
dashboard/app.py         ✅ 3-tab Streamlit
dashboard/live_tab.py    ✅ breadth + TP1 badge + score breakdown
dashboard/analytics_tab.py ✅
dashboard/learning_tab.py  ✅ Tab 3
jobs/eod_job.py          ✅ Chroma + Telegram + weekly scorecard
main.py                  ✅ 3-min loop + premarket at 9:00
```

---

## ✅ ~~Pending bug fixes~~ — DEPLOYED 2026-04-28 (kept for history)

### Fix 1: Kite historical data retry logic — CODE ALREADY WRITTEN, NOT DEPLOYED
```
File: data/kite_client.py → get_candles()
Problem: "Request failed (kt-common)" — Kite API overload, skips stock entirely
Fix: Retry up to 3 times with 1s, 2s backoff — code already in local kite_client.py
Status: NOT pushed to server yet (server was running during market hours)
```

### Fix 2: ORB + Gap analysis broken — get_historical_data() doesn't exist — CODE FIXED LOCALLY
```
File: tools/pattern_tools.py
Problem: _get_orb_levels() and _gap_analysis() both call kite.get_historical_data()
         which does NOT exist on KiteDataClient — actual method is get_candles()
         Both fail silently (try/except returns None) → ORB never fires, premarket gaps always empty
Fix: Already applied locally:
  _get_orb_levels  line 118: get_historical_data(symbol, interval="minute", lookback_days=1)
                           → get_candles(symbol, interval="minute", days=1)
  _gap_analysis    line 251: get_historical_data(symbol, interval="day", lookback_days=3)
                           → get_candles(symbol, interval="day", days=3)
Status: Fixed in local tools/pattern_tools.py — NOT pushed to server yet
```

### Fix 3: HDFC delisted in SECTOR_LEADERS — CODE FIXED LOCALLY
```
File: config/settings.py
Problem: SECTOR_LEADERS["FINANCIAL"] had "HDFC" — merged with HDFCBANK in July 2023, delisted.
         Kite can't find instrument token → sector strength for FINANCIAL always silently fails.
Fix: Replaced "HDFC" with "HDFCAMC" (HDFC Asset Management — active & liquid)
Status: Fixed in local config/settings.py — NOT pushed to server yet
```

### EOD deploy command (all 3 fixes together):
```bash
cd ~/Desktop/India_Trading_System
rm -f .git/HEAD.lock .git/index.lock
git add data/kite_client.py tools/pattern_tools.py config/settings.py
git commit -m "fix: kite retry logic + fix get_historical_data method name + replace delisted HDFC in sector leaders"
git push origin main
ssh root@168.144.101.223 "cd /root/india_trading && git reset --hard HEAD && git pull && systemctl restart trading-system && echo Done"
```

---

## Next week priorities 🔲

### #1 — Multi-setup confluence scoring ⭐ (Bhagya's idea)
```
When stock triggers 2+ setups simultaneously:
  2 setups → Raw Score × 1.15
  3 setups → Raw Score × 1.25

Show "⚡ CONFLUENCE" badge on dashboard signals table
Log in entry_reason: "VWAP Pullback + Momentum BO (confluence x2)"

How to build:
  1. agents/crew.py → _score_signals():
     setups = _detect_all_setups(sym)  # already returns all matches
     confluence_multiplier = 1.0 + (0.15 if len(setups)==2 else 0.25 if len(setups)>=3 else 0)
     raw_score = raw_score * confluence_multiplier
  2. scoring/engine.py → add confluence_bonus kwarg to .score()
  3. dashboard/live_tab.py → show ⚡ badge if len(setups) >= 2
```

### #2 — PDH/PDL levels
```
Previous day high/low as key levels
Break above PDH: +0.3 to setup_quality
Hold above PDH on pullback: +0.2 bonus
Add to pattern_tools.py detection
```

### #3 — Multi-timeframe (15-min confirmation)
```
Currently: 5-min candles only
Add: 15-min trend must agree with setup direction
Reduces false signals in choppy market
```

### #4 — Inside bar setup (8th setup type)
```
inside_bar: tight range compression → energy coiling
High win rate on confirmed breakout
Add to pattern_tools.py → _detect_all_setups()
```

### #5 — Nifty PCR data
```
PCR > 1.2 → bullish → raise regime towards TRENDING
PCR < 0.8 → bearish → extra caution
Wire into _detect_regime() in crew.py
```

---

## Phase 3: RAG loop (wait ~mid-May 2026)
```
After 50+ closed trades:
  historical_edge = chroma.query_similar_signals(setup_type, regime)
  Add as 6th scoring component: weight 0–0.5 bonus
  Wire: crew.py _score_signals() → engine.score(historical_edge=...)
```

---

## Server deploy commands
```bash
# Server: DigitalOcean 168.144.101.223 (root, password auth)
# Project path on server: /root/india_trading   ← lowercase, NOT India_Trading_System
# Venv: /root/india_trading/venv/bin/python
# GitHub repo: https://github.com/bhagyashreekhatri/India_Trading_System

# Full one-liner deploy from Mac terminal:
ssh root@168.144.101.223 "cd /root/india_trading && git reset --hard HEAD && git pull && systemctl restart trading-system && echo Done"

# Check service:
ssh root@168.144.101.223 "systemctl status trading-system"

# Live logs:
ssh root@168.144.101.223 "journalctl -u trading-system -f"
```

---

## Day 1 observation checklist (tomorrow)
Things to watch and decide after first live day:
- How many trades does the agent take? (expect 5-15/day)
- Which setups fire most often?
- Are scores reasonable? Any setups consistently <5 (never firing)?
- Any false entries? (price moved, R:R broken)
- Breadth gate triggering? (good or too restrictive?)
- Consecutive loss protection activating?
- Telegram alerts arriving correctly?
- EOD report at 15:35 — did it run?
