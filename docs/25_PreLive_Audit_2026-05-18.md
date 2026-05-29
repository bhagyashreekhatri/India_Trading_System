# Pre-Live Audit — India Trading System
**Date**: 2026-05-18
**Author**: Comprehensive code audit (post Fix #183)
**Scope**: Full codebase scan + cross-reference against PROJECT_MEMORY.md

---

## Executive summary

The system has **principled architecture** (conviction engine as decision authority, structural signals over discretionary nudges, comprehensive kill-switch coverage) but carries **non-trivial dead weight from the legacy scoring path** and has **six execution-path bugs** that will surface only when real broker rejects happen. Four heavyweight features were flipped live on 2026-05-18 without the doc-mandated multi-session shadow window. The 3-week paper-observation period before flipping to live (target: 2026-06-08) is now also the missing shadow validation window — provided the blocker list below is addressed and no live-execution path silently fails.

---

## 1. Architecture — component map

### Run loop
`main.py:311` `main()` — infinite while-loop, branches on IST clock each iteration:
- Kill switch poll (`system_controls.json::kill_switch`) → sleep 60s
- Pre-market gap analysis (09:00-09:15) → fires once per day
- Market-closed sleep
- EOD job (15:35-15:50)
- Live tick — the entire system

### Orchestrator
`agents/crew.py:163` `TradingCrew` — single class, ~2,400 lines. Constructs every agent in `__init__` (lines 169-310). Exposes `run_tick()` (line 314).

Boot sequence (`__init__`):
- `KiteDataClient` (broker wrapper)
- `NewsClient` (Groq+NewsAPI — dead-coded post Fix #183 but still imported)
- `TradeStateManager` (SQLite `./trade_state.db`)
- `ChromaMemory` (vector DB, 3 collections)
- `ScoringEngine` (legacy stub — telemetry only in conviction mode)
- `MarketStateAgent`, `FhhBreakDetector`, `DayTypeClassifier`, `VolatilityStateAgent`
- `ConvictionEngine` (injected with day_type, vol_state, state_mgr back-refs)
- `MidTradeReeval`, `DiscoveryEngine` (seeded with `core_universe = FULL_UNIVERSE`)
- Boot-time: `_paused_consec_losses` set if `get_consecutive_losing_days() ≥ 5`

### Per-tick order (`run_tick`, `crew.py:314-422`)
Every `SCAN_INTERVAL_MIN`=3 min:
1. Bump `_tick`, clear 4 per-tick caches (vwap, reject_counts, quote, tier_hist), clear FHH candle cache, reset entries_this_tick
2. `_manage_positions()` — open positions evaluated FIRST (sacred order)
3. Telemetry poke — drives one cached read each of market_state, day_type, vol_state, fhh_detector("NIFTY 50")
4. `discovery.run_scan(now)` — internally cadence-gated to 5 min
5. `_ok_to_trade()` time gate — 09:20 to 14:55 (RUNWAY_CHECK_ENABLED=True) or 14:45 (False)
6. `_detect_regime()` + `_detect_breadth()` — refreshed every tick (Phase 2.0)
7. `_scan_market()` — one batched `kite.get_quotes(universe ∪ discovery_set)`. Filters `abs(change_pct) ≥ 0.3%` AND `price × today_volume ≥ ₹50L`, keeps top 60
8. `_detect_setups(active)` — per symbol fetches `get_vwap_with_candles`, requires ≥8 today bars, calls `_detect_setups_multi` (only `MOMENTUM_BREAKOUT` fires in production)
9. `_score_signals` — runs stub `ScoringEngine.calculate()` for telemetry, applies legacy nudges (PDH/confluence/RAG-WR) BUT `will_enter` bypasses score thresholds in conviction mode (Fix #160 at line 1119-1126)
10. Pending-retest evaluator
11. `_allocate(scored)` — REAL decision authority. Per-symbol loop: conviction → blacklist → strikes → cooldown → sector cap → fresh LTP → spread → proximity → HTF → sizing → enter

### Sub-agents (`agents/`)
- `market_state.py:90` `MarketStateAgent.get_state()` — 10:15 IST NIFTY lock. Canonical path uses 5-min historical_data candle close (Fix #176); falls back to LTP if bar-time mismatch
- `fhh_break_detector.py:81` `FhhBreakDetector` — per-symbol first-hour-high/low + whipsaw tracker with tick-scoped candle cache (Fix #178)
- `conviction_engine.py:82` `ConvictionEngine.evaluate()` — universal filters → macro state → NIFTY FHH → stock FHH → day-type → runway → tier S/A/B/SKIP
- `discovery_engine.py:332` `DiscoveryEngine.run_scan()` — every 5 min, 150-symbol Kite chunks with 0.3s gap (Fix #169), time-adjusted volume (Fix #182), circuit veto ≥18% (Fix #164)
- `stock_decoupling.py:91` — 6-condition decoupling rule for RED days; admits at half-B
- `mid_trade_reeval.py:117` — 3-dim thesis check (macro/VWAP/HOD); 0-1=CONTINUE, 2=TIGHTEN_TO_BE, 3=CLOSE
- `runway_check.py:60` — `median_TTP1 × 1.5 ≤ remaining_min_to_14:45`; absolute 20-min floor

### Persistence
- SQLite `trade_state.db` — `positions`, `watchlist`, `session_stats`
- ChromaDB — `closed_trades`, `signals`, `news_events`
- JSONLs — `discovery_admits`, `rvol_ghost`, `reeval_shadow`, `decoupling_shadow`, `pending_retest`
- Disk caches — `news_cache.json`, `discovery_blacklist.json`, `discovery_daily_ctx.json`, `system_controls.json`, `system_status.json`

### EOD job (`jobs/eod_job.py:23`)
Fires daily 15:35-15:50 from `main.py:395`:
- Store closed-trade outcomes in ChromaDB
- Print summary + WR-by-setup
- Telegram report
- Groq self-critique batch
- Friday: weekly scorecard
- Month-end last trading day: monthly mean-R review

---

## 2. Strategy — the actual trading logic

### One complete cycle, from "listed on NSE" to "we have a position"

**Stage 1 — Universe formation**
- Core: 150 hardcoded names in `config/universe.py::FULL_UNIVERSE`
- Discovery: ~2,547 NSE EQ names post filter v5 (excludes -SM/-RR/-IV/-NG/-Y\d/-IT/-SF suffixes)

**Stage 2 — Active list per tick**
`_scan_market` (`crew.py:505`):
- Batched `kite.get_quotes(universe ∪ discovery_set)`
- Keep `abs(change_pct) ≥ 0.3%` AND `price × today_volume ≥ ₹50L`
- Top 60 sorted by absolute change
- Top-sector members promoted

**Stage 3 — Setup detection**
`_detect_setups_multi` in `tools/pattern_tools.py:547-614`. **Only `MOMENTUM_BREAKOUT` is wired to fire**. Conditions (line 576-602):
- Last bar closes above highest of prior 6 bars
- Last close > VWAP
- Body ratio ≥ 0.4
- Close position in candle ≥ 0.6
- Current bar range ≥ 1.0 × mean of prior 5 ranges (Fix #29/#38)
- Prior bar must be green (Fix #30)

Entry = round(last close); SL = `entry - max(ATR×0.8, entry×0.7%)` tick-aligned; TP1 = entry + 0.7R (Fix #48); TP2 = entry + 2.0R.

Six other detectors (`_detect_orb_breakout`, `_detect_failed_breakdown`, `_detect_trend_pullback`, `_detect_inside_bar_break`, plus VWAP_RECLAIM/VWAP_PULLBACK/RECOVERY_SETUP) are physically present but NOT called. `_detect_orb_breakout` still has hardcoded 09:30-10:30 clock gate (`pattern_tools.py:205`) — Three Laws Law-1 violation, dormant.

**Stage 4 — Scoring (telemetry only)**
Legacy `ScoringEngine.calculate()` runs but `will_enter` ignores score gate in conviction mode (`crew.py:1124`). RVOL veto (≥2.0 for MOMENTUM_BO, `crew.py:870`) and RAG proven-loser veto (`crew.py:1086`) still fire.

**Stage 5 — Conviction (THE entry brain)**
`ConvictionEngine.evaluate()`:
1. Universal filters: change_pct floor (-0.3%), HOD proximity (1.2%), spread (0.10%), 5-level depth ratio (1.5)
2. Macro state (10:15 NIFTY lock): STRONG_GREEN/GREEN/YELLOW/RED/STRONG_RED
3. NIFTY FHH break check
4. Stock FHH break check (when `REQUIRE_STOCK_FHH_BREAK=True`)
5. Day-type classifier (TREND/RANGE/BALANCED at 11:00 IST)
6. Runway check (median_TTP1 × 1.5)
7. Tier mapping:
   - STRONG_GREEN + FHH → Tier S (100% historical, n=44)
   - GREEN + FHH → Tier A (97% historical, n=38)
   - YELLOW + FHH + A++ stub-grade → Tier B half-size (88% historical, n=98)
   - RED with decoupling override → Tier B half-of-half
   - RED/STRONG_RED otherwise → SKIP

**Stage 6 — Sizing**
`_allocate` (`crew.py:1650-1670`):
```
risk_amount = active_capital
            × RISK_PER_TRADE_PCT (1%)
            × loser_streak_multiplier (1.0/0.85/0.70/0.50/0.30)
            × conviction_size_mult (S=1.0, A=1.0, B=0.5, decoupling=0.25)
            × vol_size_mult (NR7=1.2 / quiet=1.0 / normal=1.0 / expansion=0.7)
            × second_strike_dampener (1.0 first / 0.5 second)
```
Probe: `active_capital=₹50k`. Tier-S/A trade risks ₹500 max.
Position value capped at 10% capital (₹5k probe).
Floors: risk < 0.03% (₹15 probe) OR position value < 3% (₹1,500 probe) → watchlist not entry.
`qty = floor(risk / sl_dist)`.

**Stage 7 — Entry mechanics**
- Position written to DB
- Market order placed; return value checked (Fix #170)
- SL-M placed via `kite_client.py:388`; if fails → immediate market exit + Telegram (Fix #177)

**Stage 8 — Exit logic** (`_manage_positions`, `crew.py:1854-2136`)
- Overnight veto: entry_date ≠ today → close at LTP
- EOD force-close at 15:15
- SL hit: full exit (`sl_hit` vs `sl_trail_hit` distinction)
- TP1 first time: 50% exit, SL → entry (BE), broker SL-M cancel+replace
- TP2 after TP1: full exit
- Trailing SL post-TP1: 0.5×ATR default, 0.7 choppy regime, 0.4 RVOL≥2, 0.3 past +1.5R
- Pre-TP1 BE trail: +0.5R held 10min → SL → entry (Phase 1.2)
- Mid-trade reeval: 5-min cadence, 2/3 → tighten, 3/3 → close
- Stall: 25min (-0.5R to +0.3R) or 45min (±0.3R)

### What actually fires in production
**One setup**: MOMENTUM_BREAKOUT.
**One macro tier ladder**: S (rare, STRONG_GREEN+FHH), A (uncommon, GREEN+FHH), B (occasional, YELLOW+FHH).
**The conviction-engine path's S/A/B is the de-facto "setup taxonomy" today** — macro-state × FHH-break, not pattern shape.

---

## 3. Risk controls — every kill switch

In execution order inside `_allocate`:

| Control | File:line | Trigger |
|---|---|---|
| Pre-market kill switch | `main.py:350` | `system_controls.json::kill_switch=True` |
| Daily-profit lockout | `crew.py:1268` | `today_pnl ≥ 3% × active_capital` (₹1,500 probe) |
| +2R profit tightening | `crew.py:1400` | `today_pnl ≥ 2% × active_capital` — only Tier-S admits |
| Daily-loss kill | `crew.py:1294` | `today_pnl ≤ -2.5% × active_capital` (-₹1,250 probe) |
| Weekly drawdown kill | `crew.py:1328` | `week_pnl ≤ -7.5% × active_capital` (manual reset) |
| Consec losing days pause | `crew.py:283-289`, `1360` | `consecutive_losing_days ≥ 5` (manual reset) |
| Portfolio revenge cooldown | `crew.py:1377` | 20 min after any closed loss today (Fix #179) |
| Per-symbol cooldown | `crew.py:1518` | 45m after loss / 15m after win (Fix #45) |
| Max strikes/day per symbol | `crew.py:1514` | 2 trades; second × 0.5 size (Fix #26) |
| Max positions | `crew.py:1428` | 3 in probe (Fix #181) |
| Max sector exposure | `crew.py:1528` | 3 per sector |
| Symbol auto-blacklist | `crew.py:1509` | ≥3 trades AND WR < 30% (Fix #27) |
| Discovery auto-blacklist | `discovery_engine.py:432` | 2 losing trades → 7-day ban |
| Whipsaw freeze | `conviction_engine.py:289` | NIFTY breaks both FHH and FHL (Phase 1.3) |
| Macro RED/STRONG_RED block | `conviction_engine.py:179` | hard block unless decoupling override |
| Spread filter | `crew.py:1556`, `conviction_engine.py:152` | > 0.10% |
| RAG proven-loser veto | `crew.py:1077` | ≥10 history AND WR < 35% (Fix #44) |
| HTF down veto | `crew.py:1591` | 15-min HTF trend DOWN blocks longs |
| HOD-proximity gate | `conviction_engine.py:139` | LTP > 1.2% below day high |
| Stale-signal hard skip | `crew.py:1620` | age > 5 min in conviction mode |
| Runway check | `conviction_engine.py:361` | `median_TTP1 × 1.5 > remaining_min`; 20-min floor |
| Sizing floors | `crew.py:1694` | qty=1 OR position value < 3% → watchlist |
| Paper slippage simulation | `crew.py:117` | 12/22/8 bps entry/stop/target (Fix #180) |
| Overnight veto | `crew.py:1890` | entry_date ≠ today → close at LTP |
| EOD force-close | `crew.py:1911` | 15:15 IST (5min before MIS auto-square) |
| Time-stop | `crew.py:2125` | 25min (-0.5R..+0.3R) or 45min (±0.3R) |
| SL-M reject emergency exit | `crew.py:1767` | post-entry SL-M fail (Fix #177) |
| Discovery circuit veto | `discovery_engine.py:570` | abs(pct_change) ≥ 18% (Fix #164) |

---

## 4. Flaws — brutal, prioritized

### BLOCKERS (could lose real money on day one)

**B1. `ScoringEngine` stub can silently kill clean conviction-A admits.**
`scoring/engine.py:270` sets `is_valid = final >= 5.0`. `_score_signals` at `crew.py:1124` only adds to scored if `will_enter = is_valid AND ...`. A clean structural admit with poor body ratio or low news score can fall below 5.0 raw and get rejected before conviction runs. Even in conviction mode (Fix #160), this gate still fires.
**Fix**: in conviction mode, force `is_valid=True` for any candidate passing the structural detector.

**B2. TP1 partial-exit and full-exit don't check `place_order` return value.**
`crew.py:2166` (TP1 partial) and `crew.py:2308` (full exit) fire MARKET orders but ignore return. Mirror of Fix #170 for entry. If broker rejects TP1 sell, DB shows `tp1_hit=1, qty_remaining=half` while no shares sold, SL-M then placed for `qty_remaining` (half) covering the un-sold half on original SL.
**Fix**: apply Fix #170 pattern (check None, rollback DB row, alert).

**B3. Mid-trade SL-M failure paths incomplete.**
Fix #177 catches SL-M failure right after entry. Same code path during:
- Pre-TP1 BE trail (`crew.py:2002`) — only `pass`es exception
- Post-TP1 trail (`crew.py:2238`) — print + best-effort
- Reeval-tighten (`crew.py:2082`) — print + best-effort

Transient broker error mid-trade can leave position on OLD trigger or no trigger.
**Fix**: apply Fix #177 emergency-exit pattern to all three.

**B4. `market_state.py:248` bar-time guess fragile.**
Canonical 10:15 path checks `bar.time() in (10:10, 10:15)`. If Kite returns timestamp-at-close (10:09:59), silently falls through to LTP fallback — the exact behavior Fix #176 was meant to eliminate.
**Fix**: widen bar-time match to a 30-second window OR explicitly check the 5-min candle whose `bar_end ≤ 10:15:30`.

**B5. Conviction HOD-proximity uses session high.**
`conviction_engine.py:139` reads `stock_quote.get("high", 0.0)` — Kite's `ohlc.high` is the SESSION high. Breakout above a fresh 11:00 swing high will be 0.5-2% below the morning peak and gets killed by 1.2% gate. Mismatch with how a tape reader defines "at HOD" on a multi-leg day.
**Fix**: track rolling intraday high from VWAP candle stream; use whichever is lower of session-high or (last-30-min-high + 0.5%).

**B6. `kite.get_quotes` silently swallows errors.**
`data/kite_client.py:54` — returns `{}` on any exception. Downstream `_quote_cache` stays empty, consumers fall back to single-symbol fetches one-by-one, page-attacking the API with no Telegram alert.
**Fix**: surface error via Telegram alert if `get_quotes` returns `{}` for a non-empty input list.

### HIGH (will materially degrade live performance)

**H1. One setup, period.** Six detectors dormant. Flat/yellow tape → 0-2 admits/day. RVOL≥2 + HOD-proximity + runway compound to thin admission. Concentration of edge in one pattern means one regime shift kills the system.

**H2. Four shadow flags flipped LIVE same day.** 2026-05-18: `DISCOVERY_ALLOW_TRADES`, `STOCK_DECOUPLING_ENABLED`, `RUNWAY_CHECK_ENABLED`, `MID_TRADE_REEVAL_ENABLED` all True. PROJECT_MEMORY.md line 446-450 says all default False; doc is out of sync. CLOSE-ENABLED in mid-trade reeval has never observed a production fire.

**H3. NewsAPI/Groq path still firing per tick.** Fix #183 removed Discovery enrichment, but `_get_news` (`crew.py:767`) called per candidate per tick from `_score_signals`. Result feeds nothing actionable; burns Groq quota.
**Fix**: Remove `_get_news` and the NewsClient import from crew.py entirely.

**H4. HTF trend and spread fetches uncached.** `crew.py:1591` and `1550` — per-symbol Kite calls per tick. Per-tick `_quote_cache` (Fix #168) helps OHLC but not these. Tens of round-trips/tick still.

**H5. RAG keys on legacy regime taxonomy.** `crew.py:1067` — historical wins binned by CHOPPY/TRENDING/RECOVERING. Conviction drives entries off macro state. WR-nudge samples wrong stratification.

**H6. Tier-B path effectively dead.** YELLOW + FHH + A++ stub-grade returns Tier B. Stub-grade ≥ 8.0 almost never happens in conviction mode. YELLOW days produce few/no admits.

**H7. `place_sl_order` failure during pre-TP1 trail silently passes** (`crew.py:2002`).

### MEDIUM

**M1. Probe sizing awkward for mid-priced stocks.** ₹500 stock with SL distance ₹3.50 → risk ₹500 → 142 shares (₹71k) → MAX_POSITION_VALUE_PCT=10% caps at ₹5k → 10 shares → actual risk ₹35. Position-value floor 3% sometimes triggers and watchlists.

**M2. Stock decoupling structurally dead in probe.** Net multiplier = 0.25 × B-tier (₹62.50 risk). Qty=1 on most mid-caps.

**M3. Discovery and Conviction don't share liquidity verification.** Discovery filters avg turnover ₹10cr; Conviction has no turnover gate.

**M4. ChromaDB RAG inside scoring loop.** 60 ChromaDB hits per tick, no caching, no batch.

**M5. Breadth dead computation.** `_detect_breadth` fires 50+ quote calls but result is informational (Fix #40 zeroed the penalty).

**M6. EOD job no catch-up.** Restart between 15:30-15:35 → daily summary skipped silently.

**M7. Persisted `regime` column uses legacy CHOPPY/TRENDING.** RAG queries key on wrong regime.

**M8. Watchlist write-amplification.** Every tick, ~20 names rewritten via delete-then-insert.

### LOW (tech debt)

- Dead constants: `MIN_SCORE_ENTRY_CONSERVATIVE`, `CONFLUENCE_MULTIPLIER_2/3`, `SCORE_SIZE_TIERS`, `BREADTH_BULLISH/BEARISH`, `MIDDAY_AVOID_*`, `NO_NEW_ENTRY_AFTER`
- `_detect_orb_breakout` still contains 09:30-10:30 clock gate (dormant)
- Inconsistent log prefixes
- No structured logging
- No integration tests against recorded sessions

---

## 5. Go-live readiness

### Current shadow-mode state (settings.py)
| Flag | Value | Note |
|---|---|---|
| `PAPER_TRADING` | True | line 26 |
| `PROBE_MODE_ENABLED` | False | line 558 |
| `USE_CONVICTION_ENGINE` | True | line 427 |
| `DISCOVERY_ALLOW_TRADES` | True | flipped 2026-05-18 (Fix #171) |
| `STOCK_DECOUPLING_ENABLED` | True | flipped 2026-05-18 (Fix #171) |
| `RUNWAY_CHECK_ENABLED` | True | flipped 2026-05-18 (Fix #171) |
| `MID_TRADE_REEVAL_ENABLED` | True | flipped 2026-05-18 (Fix #171) |
| `REQUIRE_STOCK_FHH_BREAK` | True | |
| `WHIPSAW_FREEZE_ENABLED` | True | |
| `PRE_TP1_TRAIL_ENABLED` | True | |
| `PENDING_RETEST_ENABLED` | True | |
| `TRAILING_SL_ENABLED` | True | |

### Owner's stated procedure (PROJECT_MEMORY line 450)
"PAPER_TRADING=True + PROBE_MODE_ENABLED=False — flip both simultaneously at Phase 3 start (target: ~3 weeks out)." Goal: ₹50k live probe.

### Doc/code drift
PROJECT_MEMORY.md "Shadow flags" section (line 446-450) says four flags above are default False — code shows all four flipped True 2026-05-18. Operator's own multi-session-shadow-window rule was violated by Fix #171.

### Realistic earliest live date
Per the doc's own rule of "3-5 sessions of clean shadow logs before flipping," the four flags need a retroactive observation window. 3 weeks of paper running gives:
- Real data on Mid-Trade Reeval CLOSE actually catching its target loss class
- `rvol_ghost.jsonl` accumulation for `scripts/rvol_backtest.py` to validate RVOL=2.0 floor
- More Discovery admits under varied circuit/macro conditions
- Validation that Runway Check doesn't strangle late-day admits

Earliest responsible date: **2026-06-08** IFF no degraded behavior observed AND blockers B1-B6 fixed.

### Pre-live checklist (not in code, must be done)
1. **Add pre-flight assertion** in `main.py` health_check: `assert not (PAPER_TRADING == False and PROBE_MODE_ENABLED == False)`. Closes the 30× risk footgun.
2. **Fix B1**: ScoringEngine bypass for conviction admits.
3. **Fix B2**: TP1 + full_exit return-value checks (mirror Fix #170).
4. **Fix B3**: SL-M failure handling in pre-TP1 trail, post-TP1 trail, reeval-tighten (mirror Fix #177).
5. **Fix B4**: market_state bar-time matching widened.
6. **Fix B5**: Conviction HOD redefinition (rolling intraday high).
7. **Fix B6**: get_quotes empty-result Telegram alert.
8. **Force one full session in `PAPER_TRADING=False` mode** with `PROBE_MODE_ENABLED=False` BLOCKED at boot — full reconciliation of every position row vs Kite order book at session end.
9. **PROJECT_MEMORY.md updated** to reflect actual flag state.
10. **Confirm `EOD_PARTIAL_UNWIND_TIME = "14:45"` semantics** — runway math gates against 14:45 even though force-close is 15:15. 30 min "runway" beyond what runway_check measures is intentional or bug?

### Actual go-live procedure when ready
Single deployment, both flags flipped together:
```python
# settings.py
PAPER_TRADING = False
PROBE_MODE_ENABLED = True
```
Then:
```bash
git commit -am "Go live — flip PAPER_TRADING + PROBE_MODE_ENABLED"
git push
ssh us-trading-agent
cd /root/india_trading && git pull
sudo systemctl restart trading-system
sudo journalctl -u trading-system -f
# Watch first 30 min carefully for first live admit
```

Both flags are read at module-import time. **They must be co-flipped.** Without the pre-flight assertion (item 1 above), nothing stops a partial flip.

---

## Summary verdict

**Architecture**: Principled. Conviction engine as single decision authority, comprehensive kill-switch coverage, observability via JSONL audit logs and shadow tabs.

**Strategy**: Narrow. One pattern (MOMENTUM_BREAKOUT) × macro tier (S/A/B). 30-month backtest validates the macro+FHH edge but doesn't validate the pattern × macro stack live. Effective in trending/expansion conditions; will produce 0-2 admits/day in choppy/YELLOW tape.

**Execution path**: Six bugs that surface only on real broker rejects. Three of those (B2, B3) can leave positions in inconsistent states between DB and broker. These are the highest-risk pre-live issues.

**Operator discipline**: Compromised by Fix #171's four-flag simultaneous flip on 2026-05-18 without shadow validation. The 3-week paper window now does double duty.

**Earliest responsible live date**: 2026-06-08, contingent on B1-B6 fixed and 12-15 clean paper sessions observed.
