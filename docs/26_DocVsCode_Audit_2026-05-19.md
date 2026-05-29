# Doc vs Code Audit — Where Are We Really?
**Date**: 2026-05-19 (8 days after Phase 0 rebuild)
**Scope**: All `docs/*.md` (1-25) + `PROJECT_MEMORY.md` cross-checked against `agents/`, `tools/`, `config/`, `memory/`, `data/`, `main.py`
**Purpose**: Honest answer to "what's implemented per the research, what's pending, what stage are we at"

---

## TL;DR

**Code build**: 5 weeks AHEAD of plan. Phase 0+1+2+3.0.1 all shipped in 8 days against an 8-week budget.

**Forward validation**: Week 0. None of the new code has been observed in shadow long enough to satisfy doc-17 Phase 1 acceptance gates. The 20-session paper-validation window the plan called for before Phase 2 was skipped.

**Pre-live blockers**: 6 originally. 2 fixed today (B1, B4). 4 remain (B2, B3, B5, B6).

**Earliest defensible Phase 3 (₹50k live probe) go-live**: 2026-06-08, contingent on (a) B2/B3/B5/B6 fixed, (b) 12-15 clean paper sessions observed, (c) doc 23 §2 12-gate pre-flight executed.

---

## Section 1 — Research → Code mapping

Every Tier S finding from the 30-month research is implemented:

| Research finding | n | Doc | Code | Status |
|---|---:|---|---|---|
| 10:15 IST macro filter (5 states) | 584 | 13, 14, 16 | `agents/market_state.py:90-188` + `settings.py:345-349` | DONE |
| STRONG_GREEN + FHH = 100% | 44 | 16 | `agents/conviction_engine.py:273-302` + `fhh_break_detector.py:81-256` | DONE |
| GREEN + FHH = 97.4% | 38 | 16 | Same | DONE |
| YELLOW + FHH = 87.8% at half-size | 98 | 16 | `conviction_engine.py:430+` | DONE |
| STRONG_RED + FHH = TRAP (skip) | 22 | 16 | Hard-block in conviction | DONE |
| Whipsaw freeze (70% chop) | 71 | 15 | `conviction_engine.py:289-294` + `WHIPSAW_FREEZE_ENABLED=True` | DONE |
| Day-type classifier | 335 | 15 | `agents/day_type_classifier.py` | DONE |
| NR7 expansion bias | 50 | 15 | `tools/volatility_state.py` | DONE |
| Pre-TP1 trail SL | — | 17 | `crew.py` PreTP1Trail | DONE |
| Stock decoupling on RED days | — | 21 | `agents/stock_decoupling.py:91-205` | DONE |
| Runway check | — | 22 | `agents/runway_check.py:60-158` | DONE |
| Mid-trade reeval (3-dim, ladder) | — | 24 | `agents/mid_trade_reeval.py:82-198` | DONE |
| Discovery Engine | — | 19 | `agents/discovery_engine.py:151-840` | DONE |
| Sector-aware macro | — | 20 | (correctly REJECTED) | NOT BUILT |

**Sizing math from doc 16 §3.1** — `risk × loser_streak × conviction × vol × second_strike` — wired in `crew.py:1650-1670`.

**Doc 16 "Six Brutal Rules"** — all hardcoded as kill switches in `_allocate`:
1. SL before trade — broker-side SL-M (Fix #6)
2. Daily loss cap 2.5% — `crew.py:1294`
3. Per-trade risk 0.5-1% — `crew.py:1650`
4. Asymmetric cooldown 45m/15m — `crew.py:1518` (Fix #45)
5. Size on edge — `crew.py:1665` (tier × loser-streak)
6. Be smaller than you think — `MAX_POSITIONS=3` in probe (Fix #181)

---

## Section 2 — Phase progress map

### Phase 0 — Surgery (Week 1 per doc 17)

| Item | Plan | Reality |
|---|---|---|
| Delete 8 CrewAI legacy agents | DELETE | DONE |
| Delete `tools/score_tools.py` | DELETE | DONE |
| Delete `tools/news_tools.py` | DELETE | DONE |
| Strip `scoring/engine.py` to types only | DELETE class | PARTIAL — stub class retained, but `USE_CONVICTION_ENGINE=True` bypasses its decision gate (Fix #160) and Fix #184 bypasses `is_valid` gate |
| `settings.py` ~107 lines target | -150 LOC | NOT DONE — 591 lines actual (5.5× over) |
| Build `market_state.py` | NEW ~120 LOC | DONE — 317 lines |
| Build `fhh_break_detector.py` | NEW ~150 LOC | DONE — 256 lines |
| Build `conviction_engine.py` | NEW ~120 LOC | DONE — 502 lines |
| Collapse `pattern_tools.py` to 2 detectors | -350 LOC | PARTIAL — only MOMENTUM_BREAKOUT fires; 6 others dormant with "DO NOT CALL" banner (Fix #165) |

**Verdict**: Behaviorally shipped. Cosmetic cleanup deferred. Phase 1.8 (deprecated constants cleanup) was promised but not executed.

### Phase 1 — Forward validation (Week 2-5 per doc 17)

All 6 sub-phases code-shipped on 2026-05-11 (pulled forward from Week 2-5):

| Phase | Status |
|---|---|
| 1.1 Stock-level FHH + HOD proximity | DONE (HOD threshold relaxed 0.5%→1.2% in Fix #162) |
| 1.2 Pre-TP1 trail SL | DONE (Fix #159 corrected kwargs mismatch) |
| 1.3 Whipsaw freeze | DONE |
| 1.5 Day-type classifier | DONE |
| 1.6 NR7 detector | DONE |
| 1.7 Volatility-adaptive sizing | DONE |
| 1.8 Cosmetic cleanup | NOT DONE |
| **20 paper sessions @ ≥70% precision** | **NOT MEASURED** — no rolling forward-precision number reported anywhere |

**Verdict**: Code shipped 5 weeks early. Acceptance gates (20-session validation) skipped entirely.

### Phase 2 — Coverage (Week 6-8 per doc 17)

| Phase | Status |
|---|---|
| 2.0 Telemetry patch | DONE (Fix #67) |
| 2.1 Discovery Engine + hardening (v3-v5) | DONE — news enrichment subsequently REMOVED (Fix #183) |
| 2.2 Sector-aware macro | CORRECTLY REJECTED |
| 2.3 Stock decoupling | DONE, flag flipped LIVE 2026-05-18 |
| 2.5 Hygiene (delete midday spam, retag regime) | DONE |
| 2.6 Runway check | DONE, flag flipped LIVE 2026-05-18 |
| 2.7 Mid-trade reeval | DONE, flag flipped LIVE 2026-05-18 |
| 2.8 RVOL ghost telemetry + backtest analyzer | DONE |
| 2.9 Shadow Mode dashboard tab | DONE |

**Verdict**: All shipped. But the flag flips on 2026-05-18 violated doc-mandated "3-5 sessions of shadow logs before flip" rule for 4 features simultaneously.

### Phase 3 — Live probe (Week 9-12 per doc 17)

| Item | Status |
|---|---|
| 3.0.1 weekly DD / consec-loss / monthly-R kill switches | DONE |
| Probe-mode settings + helpers | DONE (Fix #161) |
| Pre-flight assertion (refuse boot if PAPER=False AND PROBE=False) | DONE (Fix #187 today) |
| 12-gate pre-flight checklist (doc 23 §2) | NOT EXECUTED |
| Flag flip `PAPER_TRADING=False` + `PROBE_MODE_ENABLED=True` | NOT DONE |

**Verdict**: Infrastructure ready. Gates not met. Flip not done.

---

## Section 3 — Spec docs check (19-24)

### Doc 19 — Discovery Engine

| Spec | Code | Status |
|---|---|---|
| Seed pool from `kite.instruments(NSE)` EQ | `discovery_engine.py:219-328` | DONE |
| Scan every 5 min | `:340-353` | DONE |
| Hard filters: \|%chg\|≥2.5%, vol≥1.5×, turnover≥₹10cr, spread≤0.15% | filter chain | DONE |
| Caps: 5/scan, 15 live, 40/session | `settings.py:452-454` | DONE |
| Auto-blacklist 2-loss → 7-day ban | `:432` + JSON | DONE |
| Telemetry JSONL audit | `_log_admit` (`:832`) | DONE |
| Default OFF `DISCOVERY_ALLOW_TRADES=False` | TRUE since 2026-05-18 | **DRIFT** |
| News catalyst attribution | Built (Fix #77), then REMOVED (Fix #183) | RESOLVED (out of scope) |

### Doc 20 — Sector-Aware Macro
**Status**: REJECTED. No code. Verified — `Grep "DECOUPLED_STRONG"` returns nothing in production code. Replaced by stock-decoupling (doc 21).

### Doc 21 — Stock Decoupling

| Spec | Code | Status |
|---|---|---|
| 6 conditions enforced | `stock_decoupling.py:91-204` | DONE |
| Tier B-, size 0.5× | `:191-204`; `conviction_engine.py:228-245` (Fix #166 corrected math) | DONE |
| Sector lookup | `settings.py:516-527` | DONE |
| Default OFF `STOCK_DECOUPLING_ENABLED=False` | TRUE since 2026-05-18 | **DRIFT** |
| Shadow ADMIT logging | `conviction_engine.py:208-227` | DONE |

### Doc 22 — Runway Check

| Spec | Code | Status |
|---|---|---|
| `median_TTP1 × 1.5 ≤ remaining_min` | `runway_check.py:127-143` | DONE |
| 20-min absolute floor | `:111-124` | DONE |
| Bootstrap defaults (45min global + per-setup) | `settings.py:196` + `:201-210` | DONE |
| `state.get_median_ttp1_minutes()` | `trade_state.py:367-424` | DONE |
| Default OFF `RUNWAY_CHECK_ENABLED=False` | TRUE since 2026-05-18 | **DRIFT** |
| §12 After 5 validated sessions, set `NO_NEW_ENTRY_AFTER="15:25"` | still "14:45" | NOT DONE |

### Doc 23 — Phase 3 Live Probe Operations

| Spec | Code | Status |
|---|---|---|
| §3 Capital recalibration | `settings.py:559-590` | DONE |
| §5 New kill switches | DONE | DONE |
| §2 12-gate pre-flight checklist | Manual operator checklist | NOT EXECUTED |
| §10 Co-flip procedure with assertion | Fix #187 boot assertion | DONE (infra) |

### Doc 24 — Mid-Trade Reeval

| Spec | Code | Status |
|---|---|---|
| 3-dim check (macro, VWAP, HOD-1.5%) | `mid_trade_reeval.py:141-163` | DONE |
| Action ladder 0-1=CONTINUE, 2=TIGHTEN, 3=CLOSE | `:164-180` | DONE |
| Per-position 5-min interval | `should_check()` `:109-115` | DONE |
| Default OFF `MID_TRADE_REEVAL_ENABLED=False` | TRUE since 2026-05-18 | **DRIFT** |
| 10/10 acceptance tests | per doc 24 | UNVERIFIED |

---

## Section 4 — Master ship-list (what's pending)

### Overdue (was supposed to ship, hasn't)

1. Continuous sector strength score (P1.1 doc 11) — still hardcoded top-3
2. Trend quality classifier per stock — not built
3. Focus list state machine (Phase C) — not built
4. Premarket brief (Phase H) — not built
5. Weekly threshold review job (Phase G) — not built
6. Sector rotation handoff detector (P2.4) — not built
7. **Phase 1.8 cosmetic cleanup**: `MIN_SCORE_ENTRY_CONSERVATIVE`, `CONFLUENCE_MULTIPLIER_2/3`, `SCORE_SIZE_TIERS`, `BREADTH_BULLISH/BEARISH`, `MIDDAY_AVOID_*`, `NO_NEW_ENTRY_AFTER`, `SETUP_DISARMED_LIST`, `MOMENTUM_BO_REQUIRE_PRIORITY` — all dead constants in `settings.py`
8. **Doc 22 §12** — set `NO_NEW_ENTRY_AFTER="15:25"` after runway-check validates
9. **Delete legacy `_score_signals` body** — still running as "telemetry" but conviction is authority
10. **Tests for new architecture** — `tests/test_engine.py` tests deleted ScoringEngine

### Pre-live blockers (doc 25)

| # | Item | Status |
|---|---|---|
| B1 | ScoringEngine `is_valid` gate bypass for conviction admits | **FIXED 2026-05-19** (Fix #184) |
| B2 | TP1 + full_exit `place_order` return-value checks | OPEN |
| B3 | Mid-trade SL-M failure paths (pre-TP1, post-TP1, reeval-tighten) | OPEN |
| B4 | market_state bar-time matching widened | **FIXED 2026-05-19** (Fix #186) |
| B5 | Conviction HOD redefinition (rolling intraday high vs session) | OPEN |
| B6 | `get_quotes` empty-result Telegram alert | OPEN |

### Pending forward validation

1. **20-session forward macro precision ≥70%** (doc 17 Phase 1 acceptance) — NOT MEASURED
2. **RVOL 2.0 threshold validation** — `rvol_ghost.jsonl` accumulating; ~2 weeks more
3. **Mid-trade reeval CLOSE actually firing** in production
4. **Decoupling actually firing** — needs a STRONG_RED day
5. **Runway check not strangling late-day admits** — needs observation

### Future phase

1. Phase 4 — ₹3L scaled capital (months 4-5)
2. Phase 5 — ₹20L full deployment (months 8-12)
3. Short-side decoupling rule (not designed)
4. Per-regime median TTP1 (needs 200+ trades)

---

## Section 5 — Current stage

**Doc 17 projected timeline (2026-05-11):**
- Phase 0 (Week 1) → ~2026-05-18
- Phase 1 (Week 2-5) → ~2026-06-08
- Phase 2 (Week 6-8) → ~2026-06-29
- Phase 3 (Week 9-12) → ~2026-07-20

**Today: 2026-05-19. Days since rebuild: 8.**

| Dimension | Reality |
|---|---|
| Code shipped | ~5 weeks ahead |
| Forward-validated edge | Week 0 (essentially no shadow data collected before flag flips) |
| Phase 3 infrastructure | Ready |
| Phase 3 gates | NOT MET (12-gate pre-flight not executed) |
| Phase 3 flag flip | NOT DONE |

**Bottom line**: Built 8 weeks of code in 1 week. Now hitting the wall that no amount of coding can climb — **time on tape**. The plan said 20 paper sessions before Phase 2 acceptance. We have ~5 sessions of paper data on the four flipped-live features.

---

## Section 6 — Drift / trust audit

### Critical: PROJECT_MEMORY.md doc-vs-code drift

`PROJECT_MEMORY.md` lines 446-450 ("Open / pending") claim:
- `DISCOVERY_ALLOW_TRADES = False`
- `STOCK_DECOUPLING_ENABLED = False`
- `RUNWAY_CHECK_ENABLED = False`
- `MID_TRADE_REEVAL_ENABLED = False`

`config/settings.py` actual values (post-Fix #171, 2026-05-18):
- All 4 are `True`

**The memory file is out of date and gives wrong information about system state.** This is the #1 trust audit finding. Anyone reading the memory file today (including me, in a future session) gets a misleading picture.

### Code-size drift vs doc 17 targets

| File | Target | Actual |
|---|---:|---:|
| `crew.py` | 1466 LOC | ~2400 LOC |
| `settings.py` | 107 LOC | 591 LOC |
| `pattern_tools.py` | 400 LOC | 692 LOC |

Reason: features were ADDED on top of legacy paths rather than replacing them.

### Three Laws Law-1 violation (dormant)

`tools/pattern_tools.py:205` `_detect_orb_breakout` still contains a hardcoded 09:30-10:30 clock gate. Dormant (banner says DO NOT CALL FROM PRODUCTION PATHS) but violates the rule.

### Scoring engine `is_valid` gate kill-path (NOW FIXED)

`scoring/engine.py:270` `is_valid = final >= 5.0` was silently killing clean conviction admits via `crew.py:1142-1148` `will_enter = result.is_valid AND ...` until Fix #184 today.

This was unfixed for the entire 7-day period the conviction engine was nominally "the sole decision authority." The fix at line 1146 today changes `will_enter = result.proximity_ok` for conviction mode, bypassing `is_valid`.

### `NO_NEW_ENTRY_AFTER` clock rule coexists with runway check

`settings.py:298` `NO_NEW_ENTRY_AFTER = "14:45"` is still active alongside the runway check. Doc 22 §12 says "after 5 runway-validated sessions, set to '15:25'." Both rules currently fire (functionally redundant; runway is meant to replace the clock).

### `EOD_PARTIAL_UNWIND_TIME=14:45` vs `EOD_CLOSE_TIME=15:15`

Runway floor is 30 minutes tighter than force-close. Doc 25 §5 item 10 questions whether this is intentional. Not bugged but undocumented.

### Probe sizing footgun (now fixed)

Without Fix #187 (today's commit), flipping just `PAPER_TRADING=False` would route real orders sized against `CAPITAL=₹15L` rather than `PROBE_CAPITAL=₹50k` — 30× intended risk. Existed for the full rebuild week.

### Sizing math bug in conviction engine (fixed by Fix #166)

`conviction_engine.py:230` was `0.5 * dec_res.size_multiplier * 2` — coincidentally correct, but the multiplication-by-2 was nonsense. Fixed in Fix #166. Doc 21 never specified the math, so the drift was self-inflicted.

### Tests integrity unverified

Doc 21 §9 says "see `/tests/test_decoupling.py` (or dev-time `outputs/test_decoupling.py`)." Doc 18 §4.1 says `tests/test_engine.py` needs rewrite. Test coverage for the new architecture is unverified.

---

## What to do this week (priority order)

1. **Update PROJECT_MEMORY.md lines 446-450** to reflect 2026-05-18 flag flips — 15 minutes
2. **Fix B2 + B3 + B5 + B6** — 4 remaining doc-25 blockers — ~3 hours
3. **Add rolling forward-precision metric** for macro filter (daily EOD log) — 1 hour
4. **Phase 1.8 cosmetic cleanup** of dead constants in `settings.py` — 30 min
5. **Run the 12-gate pre-flight checklist** from doc 23 §2 across 3 paper sessions
6. **Verify or rewrite `tests/test_engine.py`** to test the conviction engine
7. **Doc 22 §12 transition**: after 5 clean runway sessions, set `NO_NEW_ENTRY_AFTER="15:25"`

---

*The build is solid. The validation is the gate. We are not as far along as the commit log suggests — but we are not nearly as behind as the gap might first appear. Eight days of code shipped, eight days of paper data needed, six pre-live bugs to close, then a flag flip and we're live with ₹50k.*
