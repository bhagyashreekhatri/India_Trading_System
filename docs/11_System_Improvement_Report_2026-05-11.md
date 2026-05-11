# NSE Trading System — Brutal Improvement Report

*Authored 2026-05-11 EOD, after live-session analysis, paper-vs-agent comparison, and full doc review*
*Audience: operator (Bhagya). Honest read from a scalper / prop / microstructure perspective. No filler.*

---

## 0. The one paragraph

The system is a well-engineered orchestration shell wrapped around a strategy with **near-zero net edge** (280 trades, −₹40k net after costs, 71% stalled exits). 60 fixes deployed across two weeks corrected infrastructure but did not produce edge. Today's live session validated the diagnosis: the agent's "boring caution" (a coincidentally-active lunch gate) beat a 5-pick structural-filter paper plan by ~₹2,000 because the broader index closed −1.5%. The structural rules identified the right stocks. They did not have a way to read **what the index was doing to those stocks**. The path forward is not more filters — it is **a real market-context engine** that measures order flow, structure, and execution physics continuously, with no clock categories, no hardcoded sectors, and no per-symbol special cases.

---

## 1. Executive Summary

### 1.1 Current system maturity

| Layer | Maturity | Note |
|-------|---------|------|
| **Infrastructure** | ✅ Production-grade | TZ-aware, persisted state, idempotent orders, dashboards, kill switches, RAG memory, paper-slippage sim |
| **Orchestration** | ✅ Solid | Single-process loop, 3-min ticks, sub-100ms hot path, no LLM in scoring |
| **Strategy edge** | ❌ Near-zero | 280-trade audit shows −₹40k net; only momentum_breakout is gross-positive (147 trades, +0.159R gross, −0.01R net) |
| **Adaptive intelligence** | ❌ Mostly absent | System has lots of rules but no continuous market-state read |
| **Live readiness** | 🟡 Mechanically yes, edge-wise no | Could ship to live trading tomorrow; would lose money slowly |

### 1.2 Three biggest strengths

1. **Discipline infrastructure is real.** Kill switches, cooldowns, RAG proven-loser veto, spread filter, broker-side SL-M, tick-size rounding, live-LTP refetch — these are the boring saves that make the difference between losing slowly and losing fast. Today the agent caught one TORNTPHARM trade (+₹92) and then sat in cash through a market that closed −1.5%. That's worth more than it looks.

2. **The data pipeline is honest.** Paper-slippage simulation, real-VWAP breadth, IST-aware timestamps, cost-stack modeling. The system tells the truth about its performance — that's why we know it's −₹40k net, not the +₹172k gross that a sloppier system would report.

3. **The setup pruning instinct is right.** Killing 6 of 7 setups (Phase A) cut noise. The remaining momentum_breakout is the only setup with credible gross edge in the data.

### 1.3 Three biggest weaknesses

1. **No market-context intelligence.** The agent sees "Nifty −1%" as a breadth penalty (−0.7 score nudge) but cannot tell whether the index is **trending down linearly** (longs are doomed), **chopping with no direction** (random outcomes), **finding a base** (longs may work), or **capitulating** (very short-term reversal coming). All four are the same "breadth=40%, nifty=-1%" reading. Without this, the system either over-trades or under-trades the same external state.

2. **Static rule stack masquerading as adaptive intelligence.** The system has dozens of constants in `config/settings.py` and treats each as universal. Real markets reward filters that adapt their thresholds based on measured state (volatility, liquidity, recent volatility-of-volatility, recent participation profile). The current system has no feedback from "what worked yesterday" to "what threshold to use today."

3. **Order flow understanding is shallow.** The system reads top-of-book bid_qty vs sell_qty as a snapshot. It does not read flow direction (`avg_price` vs `LTP` drift), depth-tier growth (institutional layering), aggression footprint (trades hitting bid vs lift), or **change in order book over time** (bid stack growing vs evaporating). Today's live trades validated that single-snapshot depth-flip is too noisy as an exit signal.

### 1.4 Live readiness assessment

**Can it run on real money tomorrow?** Mechanically yes. Will it lose money? Almost certainly, because:

- Gross edge is too thin to clear the cost stack (₹760/trade) reliably
- No macro-context filter means weak-market days produce loss clusters
- Stall rate 71% means most "trades" never test the actual exit thesis
- Win-rate inversion (best scores have worst outcomes per file 04) is partially corrected but not eliminated

**Recommended state before live money:** ship the 5 P0 changes below, paper-trade for 10 sessions, verify net P&L positive across 3 different market regimes (trending up, range, trending down). Only then.

---

## 2. What Was Actually Achieved

### 2.1 Completed phases (real)

| Phase | Status | What it did | What it didn't do |
|-------|--------|-------------|-------------------|
| Phase 1 (setup) | ✅ done | Built 7 detectors, scoring engine, kite client | n/a |
| Phase 2 (operationalize) | ✅ done | TZ fixes, kill switches, cooldowns, dashboard | n/a |
| Phase 2.5 (audit) | ✅ done | 280-trade analysis, exit distribution, setup audit | Revealed near-zero edge |
| Phase A (kill 6 setups) | ✅ shipped 2026-05-10 | Disarmed 6 setups; tightened momentum_breakout (RVOL≥2.0, confluence≥2 OR top-3 sector) | Did not add what to do instead |
| Phase D (pending-pullback retest) | ✅ shipped 2026-05-10 | Captures proximity-failed signals; retest within 10 min within ±0.3% fires entry | Not yet validated in live data |

### 2.2 Functional components (production-critical, keep)

- **TZ-aware timestamps** (Fix #1) — every datetime is IST-aware
- **Kill switch + profit lockout** (Fix #3, #11) — capital preservation infrastructure
- **Asymmetric cooldown** (Fix #45) — 45min after loss, 15min after win (anti-revenge)
- **Spread filter** (Fix #43) — hard reject if spread > 0.10%
- **RAG proven-loser veto** (Fix #44) — wipes out demonstrably-losing setup×regime combos
- **Live LTP refetch** (Fix #13) — never trust stale signal price
- **Broker-side SL-M** (Fix #6) — stop lives on exchange
- **Tick-size rounding** (Fix #7) — production NSE requirement
- **Paper slippage simulation** (Fix #16) — paper P&L reflects live execution friction
- **Rejection telemetry** (Fix #39, #49) — operator sees why trades didn't happen
- **EOD self-critique loop** (Fix #42) — RAG learning continues
- **Phase D pending-retest** (Fix #57) — structural fix for proximity-failed signals

### 2.3 Working adaptive behaviors (real, but limited)

- **Per-day loser-streak gradient sizing** (Fix #31) — 0→1.0, 1→0.85, 2→0.70, 3→0.50, 4+→0.30
- **Per-day winner-streak gate raise** (Fix #33) — after 3 wins, gate raised +0.3
- **Volatility-adaptive trail multiplier** (Fix #25) — 0.7×ATR in CHOPPY, 0.4×ATR when RVOL≥2, else 0.5×ATR
- **Aggressive trail past +1.5R** (Fix #28) — locks more profit on big winners
- **Symbol auto-blacklist on rolling WR** (Fix #27) — ≥3 trades AND <30% WR = skip
- **Score-based sizing tiers** (Fix #23) — concentrates capital in highest-conviction trades

These adapt to **per-stock history** and **per-day P&L state** — that is real adaptation. But they adapt to historical/internal state, not to **current market-context state**. That is the gap.

---

## 3. What Is Still Missing

### 3.1 Critical missing intelligence

**3.1.1 — Macro context engine (the #1 missing piece)**

The system does not measure or react to:

- **Index slope structure** (linear up / linear down / choppy with no direction / coiling / breakout / breakdown)
- **Index participation type** (broad rally vs narrow leadership vs defensive rotation vs index-led-by-mega-caps)
- **Breadth dynamics** (improving / deteriorating, not just absolute level)
- **Volatility regime** (compression / expansion / extreme / mean-reverting)
- **Sector flow direction** (where is money moving INTO right now — discovered, not declared)
- **Index lower-low geometry** (each new low confirms downtrend; failure to make new low = base attempt)
- **Distance from intraday VWAP for index** (Nifty trading 0.5%+ below its VWAP = institutional offer side)

The current breadth signal is binary: `>40%` or `<40%`. That throws away 95% of the information.

**3.1.2 — Real-time trend quality classifier**

Every name in the universe has one of these states at any moment:

- **Building** — base forming, range tightening, accumulation
- **Linear up** — clean higher highs / higher lows on rising volume
- **Parabolic / exhausting** — accelerating but RVOL declining (climax pattern)
- **Distributing** — stalling at highs, volume on down-bars, depth thinning on bids
- **Breaking down** — lower lows confirmed, sellers in control
- **Bouncing weakly** — dead-cat off lows, no real demand
- **Reclaiming** — recovering above key level, bid showing up

The system does NOT classify these. It just looks at the latest bar against a 20-bar window. **A pro scalper reads this in 2 seconds; the system has no way to express it.**

**3.1.3 — Continuous order flow analysis**

The system reads the order book as a single snapshot per tick. A pro tape reader watches:

- **Bid stack growth/decay** over multiple snapshots (institutional layering vs flight)
- **Trade-through-offer** signature (last_price hitting ask repeatedly = aggressive buying)
- **Average trade size trend** (rising = institutional, falling = retail froth)
- **Depth refilling speed** (after a sweep, bids reappearing fast = real demand)
- **Bid/ask quantity asymmetry over time** (not just current ratio)

Today's ZYDUSLIFE call (cut at 953.5 based on a single 519-lot sell wall) was wrong because the wall was absorbed in the next minute. A continuous monitor would have seen the wall vanish and price grind up.

**3.1.4 — Adaptive entry timing**

The system has one entry path: setup fires → score → check gates → enter at LTP. Real scalpers have multiple paths:

- **Confirmed break + retest** (the higher-quality entry — what Phase D pending-retest attempts)
- **Continuation break after consolidation** (mid-session re-entry; not currently a setup)
- **Pullback to mean in established trend** (the safest scalp pattern; partially via VWAP_PULLBACK but disarmed)
- **Failed continuation** (the reversal scalp; partially via FAILED_BREAKDOWN but disarmed)
- **Range explosion** (compression → release; partially via RANGE_BREAKOUT but disarmed)

By disarming 6 of 7 setups (Phase A), the system collapsed to one entry style. That was the right move at the time (each setup was bleeding), but it leaves **most of the day's actual opportunity uncovered**. The fix isn't to re-arm the disarmed setups blindly — it's to rebuild them with **structural quality gates** so they earn their re-arming.

**3.1.5 — Fakeout detection**

The system has Fix #29 (range expansion ≥1.2×) and Fix #30 (two-bar confirmation green) as fakeout filters. These help but miss the real fakeout signature: **price breaks out, fails to attract follow-through volume, drifts back into the prior range with deteriorating depth**. That requires watching the 3-5 bars after the trigger, which the current logic doesn't do.

### 3.2 Scalping-specific missing logic

**3.2.1 — Time-to-target check** (NOT a clock rule)

A pro scalper asks at every entry: *"Will this trade have enough remaining session-runway to reach target?"* If the answer is "no, the move needs 60 min and force-close is in 35 min" — skip the entry. The current system has `NO_NEW_ENTRY_AFTER = "14:45"` which is a blunt clock rule. The real rule is: `expected_time_to_TP1 < remaining_session_runway`. Generic, no clock category.

**3.2.2 — Position-runway re-evaluation**

For an open position: *"This trade has held for 25 minutes and is at +0.3R. Median time-to-TP1 for this setup historically was 38 min. Do I expect the next 13 min to deliver the remaining 0.7R?"* That requires combining setup-historical-time-to-TP1 with current move quality. Not built.

**3.2.3 — Aggression footprint**

When a stock is breaking out, are buyers paying up (hitting offers, climbing the ladder) or are sellers stepping aside (offers being lifted but bids barely refilling)? Both look the same in OHLC. They look different in the trade tape. Without trade-level data, the system can only approximate: `LTP > avg_price` (drift up) — but doesn't use even this. Today's scan was the first time I used it.

**3.2.4 — Liquidity-aware sizing**

Position size today is determined by score tier + risk budget. It does not consider: *"Can I exit this 5000-share position cleanly?"* For thin names, even a ₹3L position can move the market against you on exit. A real scalper sizes down on thin liquidity even if conviction is high.

**3.2.5 — Multi-snapshot signal confirmation**

The current system reacts to single-snapshot readings. Today's lessons:
- Single-snapshot order-book ratio works for entry-filter (clear signal at the moment of trigger)
- Single-snapshot depth-flip does NOT work for exit (519-lot sell wall was absorbed in the next minute)
- Mid-trade exit signals need **persistence**: 2+ consecutive snapshots showing the same degradation + price weakness + reducing volume

### 3.3 Real-world trading gaps

- **No event awareness** — Fed meetings, RBI policy, results-day stocks, ex-dividend, expiry-day idiosyncrasies, government data releases. Today the agent had no idea what was driving the −1.5% close.
- **No correlated-asset checks** — INR/USD, crude, gold, US futures, key sector ETFs. A stock might look strong in isolation but its sector ETF could be breaking down.
- **No options-derived information** — PCR, max-pain levels, IV percentile. Even basic Nifty PCR could discriminate "trend continuation" from "reversal probable."
- **No after-hours / pre-market gap awareness** — gap fills, gap-and-go, vs failed-gap pattern.
- **No proper close-of-session strategy** — last 15 min of NSE has its own structure (rebalancing, expiry hedging, closing-print arbitrage) but the system treats it as just "force-close at 15:15."

---

## 4. Live Market Findings From Today (Detailed)

### 4.1 What the agent actually did

- **Boot to 09:55 IST:** correctly idle (first 30-min blindness is intentional, validated).
- **10:15 IST:** entered TORNTPHARM via momentum_breakout setup, score ≥7.0. Exited 10:42 at +₹92 (stall exit).
- **10:45 – 13:30 IST:** detected dozens of setups but every one was either disarmed (FAILED_BREAKDOWN, VWAP_PULLBACK, etc.) or below score threshold. **Zero entries** for 2 hours 45 minutes.
- **13:00 IST onward:** lunch midday gate raised threshold to 8.3 because morning P&L was −₹422. **Nothing scored above 8.3 for the rest of session.**
- **13:30 IST:** stale-config bug — `NO_NEW_ENTRY_AFTER=13:30` was still in running memory despite file change to 14:45. Service restarted at 13:37.
- **13:37 – 15:30 IST:** service running fresh config but the 8.3 lunch gate still blocked all entries. Detected several x4-confluence clusters (SBIN, RBLBANK, MANAPPURAM at tick #1 post-restart) but none scored 8.3, and structurally those were dead-cat bounces anyway (all DOWN on day).
- **Final P&L:** +₹92 from one TORNTPHARM trade.

### 4.2 Setups it detected vs missed

**Detected and entered:** TORNTPHARM momentum_breakout (single trade)

**Detected but rejected by disarmed-list:** dozens (FAILED_BREAKDOWN dominating)

**Detected and rejected by RVOL/priority:**
- **LICHSGFIN tick #74 (12:54):** RVOL 14.04× — strongest momentum signal of the session — rejected because sector NBFC wasn't in top-3 (`['IT','METAL','PHARMA']`). **Confirmed missed opportunity.**
- **MARICO tick #77 (13:03):** Confluence x2 with momentum_breakout — rejected because RVOL 1.29 < 2.0 floor. **Pattern was tight-base-absorption (sustained, not spike volume) — confirmed missed.**

**Never detected (structural gap):**
- **SUNPHARMA continuation breakout after 30-min base** — agent's MB detector requires 20-bar high, and SUNPHARMA's morning high was older than 20 5-min bars; no setup fired.
- **WELCORP second breakout from mid-day consolidation** — only detected as FAILED_BREAKDOWN/VWAP_PULLBACK (both disarmed); pure-momentum continuation isn't a current setup type.

### 4.3 False positives the agent generated (tick #1 post-restart)

Six "confluence" setups in BANKING/NBFC stocks (SBIN, RBLBANK, MANAPPURAM, BANDHANBNK, NATCOPHARM, RVNL) all flagged MOMENTUM_BREAKOUT — but live data showed **6 of 7 were DOWN on the day** with sell-dominant order books. The MOMENTUM_BREAKOUT detector fired on 5-min-bar breaks of intermediate highs while the stocks were in downtrends. This is exactly the **Fix #7 (`day_pct > 0` + fresh-day-high required)** problem caught live. The 8.3 lunch gate accidentally protected the agent from entering them — but that's defence by coincidence.

### 4.4 Hesitation / over-filter behavior

The agent's behavior 11:00 – 15:15 was effectively **paralysis**:
- 6 of 7 setups disarmed
- The 1 remaining setup either didn't fire (no 20-bar-high break) or got rejected (RVOL < 2.0)
- After morning loss, lunch gate raised threshold to 8.3 (mathematically near-unreachable for current scoring)

**This is structurally a system that has lost the ability to trade.** It's not under-filtering — it's under-engaged. The filters are doing the wrong job: they're preventing all action, including good action.

The right filter design isn't "block more trades when down." It's "**read the market state and adjust position-runway expectations**." On a −1.5% Nifty close day, the right reaction is: smaller size, only highest-conviction structural pickups, very tight stops, very short hold times. The current "raise threshold" reaction yields zero trades, which can never recover the morning's loss.

### 4.5 What it understood correctly (the wins to keep)

- **Skipped THERMAX fakeout at 09:30** — correctly avoided the first-30-min gap-up exhaustion (validated in PROJECT_MEMORY as intentional behavior).
- **Did not chase IDEA at 12.27 after +9% move** — correct, chasing a runaway is a known losing pattern.
- **Cooldown after TORNTPHARM exit** — held to discipline.
- **Sat in cash through −1.5% Nifty close** — accidentally correct. A long-only system shouldn't fight broad selling.

### 4.6 What it understood wrong (the misses to fix)

- **Treated negative-day stocks (SBIN, RBL, MANAPPURAM bouncing from session lows) as MOMENTUM_BREAKOUTs** — should require day_pct > 0 + fresh-day-high
- **Treated NBFC sector as ineligible because not in hardcoded top-3** — should compute live sector strength dynamically; LICHSGFIN with RVOL 14 was the trade of the day
- **Treated sustained-absorption volume (RVOL 1.29) as fakeout-risk** — structural pattern needs different threshold, MARICO was a clean tight-base-absorption
- **Lunch gate fired on absolute ₹422 loss** — should fire on % of capital drawn, not absolute

### 4.7 Architecture flaws exposed live

1. **No "macro context" feature.** Agent has no way to ask: "is the index trending against my long bias right now?"
2. **Score system is brittle.** A score of 7.8 on TORNTPHARM (clear leader) and a score of 7.6 on a bouncing-from-low SBIN look identical to the gate logic. The score is the wrong abstraction.
3. **Disarmed-setup logic is binary.** A FAILED_BREAKDOWN is either always-on or always-off. There's no "FAILED_BREAKDOWN is valid IF index is also bouncing AND stock is in top-N strength" gating.
4. **No mid-trade structural re-evaluation.** Position is held to SL or TP — no logic for "the structure has changed, exit now." Today TORNTPHARM/MARICO both had degrading order books mid-trade; system ignored.
5. **`SETUP_TIME_WEIGHTS`-style hardcoded constants persist.** Hour-12-IST nudge (Fix #24), lunch-window gate (Fix #35), ORB time-window (Fix #46), 14:45 entry cutoff (Fix #60) — all violate Generic-First Design.

---

## 5. Agent vs Human Scalper Analysis (Today)

### 5.1 Score card

| | Agent | Human (paper plan) |
|---|------:|-------------------:|
| Trades taken | 1 (TORNTPHARM) | 3 triggered (TORNTPHARM, MARICO, ZYDUSLIFE) |
| Trades correctly avoided | dozens | 2 (LICI, MCX never triggered) |
| Wins | 1 (TORNTPHARM +₹92) | 0 (ZYDUSLIFE close +₹900 if held; my call was cut at −₹75) |
| Losses | 0 | 2 (TORNTPHARM SL, MARICO SL) |
| **Net P&L** | **+₹92** | **−₹1,800 to −₹2,775** depending on ZYDUSLIFE handling |

**Agent beat human plan by ₹1,900–2,900.**

### 5.2 What the agent understood that I did NOT (today)

1. **The macro environment was hostile to longs.** The agent's lunch gate (raised on negative morning P&L) effectively encoded "small drawdown + uncertain market = don't take new risk." I scanned for structurally-strong stocks without checking what the index was doing to them. Index closed −1.5%; my "structurally strong" picks got dragged down with the tape.

2. **Doing nothing is a valid action.** I kept hunting for trades to validate my filter. The agent sat in cash from 10:45 onward. **Cash is a position.** Real elite scalpers know this; I forgot.

3. **₹0 is better than -₹2k.** Discipline asymmetry: 2-3 missed wins hurt less than 2-3 unnecessary losses. The agent's over-filtering today happened to align with optimal action.

### 5.3 What I understood that the agent did NOT

1. **LICHSGFIN at 12:54 was a real opportunity.** RVOL 14× with tight spread on a single-stock structural break. Agent skipped because sector was NBFC, not top-3. The hardcoded top-3 list is fundamentally wrong design — it should be **dynamically ranked from live data** with thresholds adjusting to total sector dispersion that day.

2. **MARICO's "low RVOL" was sustained absorption, not low volume.** Agent's 2.0 RVOL floor treats all volume the same. A 1.3 RVOL sustained over 30 minutes is structurally different from a 4.0 RVOL spike — the former is institutional accumulation, the latter is event-driven. **Different structural patterns, different thresholds.**

3. **5-level depth aggregate beats top-of-book ratio.** Top-of-book can be spoofed by one large order. MCX showed top-of-book 1.18 buy-dominant but 5-level aggregate 1.64 buy-dominant — the depth told the truth. Today's filter spec needs this baked in.

4. **Compression coils are real setups.** LICI was 0.0% on the day, in a tight 1.48% range, with persistent bid stack — a "fight against the index" coil. Pure-momentum filter would never see this. (Caveat: LICI's coil released DOWN today, so my entry would have correctly never triggered. But the setup-type is real.)

5. **Pharma decouple was a measurable institutional theme.** 10 pharma names green on a −0.9% Nifty mid-day was real flow. Sector-decouple is a structural pattern the system has no way to express.

### 5.4 What separates the agent from a REAL professional scalping engine

- **No live market-state read.** A pro engine measures, every tick: index slope, breadth direction, volatility expansion, sector flow, leadership concentration. The agent has none of these.
- **No mid-trade re-evaluation.** A pro engine asks every snapshot: "is this trade still working? Has the structural thesis changed?" The agent only checks price stops.
- **No flexible setup library.** A pro engine has 5-8 setups each with continuous quality gates and adaptive thresholds. The agent has 1 effective setup with hard binary gates.
- **No multi-snapshot signal confirmation.** A pro engine waits for persistence; the agent reacts to single-tick signals.
- **No order-flow direction.** A pro engine measures `LTP vs avg_price`, depth-tier growth, trade-through-offer signature; the agent reads bid_qty vs sell_qty only.
- **No participation read.** A pro engine knows whether today is institutional-led, retail-frothy, narrow-leadership, or broad — and trades differently in each. The agent does not.

---

## 6. Architecture Problems

### 6.1 Overengineering

**6.1.1 — 0-to-10 score with multiplicative nudges.** Score = `setup_quality + volume + market_alignment + relative_strength + news` × regime multiplier, then +/−nudges for: PDH break, sector flow, breadth penalty, hour-of-day, RAG history, signal age decay, confluence multiplier. **Eight inputs feeding a single float.** The score is a black box even to the engineer. When score=7.8 fires a trade that loses, no one can say which nudge was wrong. Replace with **a 6-rule binary checklist** (per Phase F plan) where each rejection is attributable to one specific rule.

**6.1.2 — `SCORE_SIZE_TIERS`.** A++/A+/A/B grade → ₹15k/₹11.25k/₹7.5k/₹3.75k risk. Four tiers feels institutional-rigorous but the data shows grade A++ has worse P&L than grade A (calibration inversion). The whole hierarchy is built on an unreliable scoring function. Collapse to 3 tiers max — S/A/B — qualified by **structural facts** (confluence count, sector strength rank, PDH break), not score level.

**6.1.3 — Hour-of-day score nudges + lunch midday gate.** Fix #24 hour-of-day nudges and Fix #35 lunch-window gate both encode clock categories. Per Three Laws: time is not a feature, it's correlated with measurable structural facts. Delete both; replace with spread/RVOL/vol-expansion filters that happen to fire when needed (which may correlate with time-of-day, but isn't determined by it).

**6.1.4 — Multiple persistence layers.** `trade_state.db` (SQLite) + `chroma_store/` (ChromaDB) + `state/pending_pullback.py` (in-memory) + `news_cache.json` (disk) + various log files. Necessary surface area, but the boundaries are unclear. ChromaDB is used for RAG but its vectors aren't optimised. SQLite handles positions but `watchlist` is now serving 3 different concepts (focus, pending-pullback overflow, historical record). Needs consolidation per Phase C/D plan.

### 6.2 Underengineering

**6.2.1 — No "market state" object.** The most important missing abstraction. Every tick should compute:

```python
@dataclass
class MarketState:
    # Index structure
    index_slope_5min: float          # bps/min, rolling
    index_slope_15min: float
    index_lower_lows_count: int      # consecutive in last hour
    index_distance_from_vwap_pct: float
    # Breadth
    breadth_above_vwap_pct: float
    breadth_trend: Literal["improving", "deteriorating", "flat"]
    breadth_velocity: float          # pct change per minute
    # Volatility
    nifty_atr_pct_relative_to_5d_avg: float
    sector_dispersion_pct: float     # how spread out are sector returns
    # Participation
    leadership_concentration: float  # 0-1, higher = narrower leadership
    sector_flow_direction: dict[str, float]  # sector → strength score (continuous, not top-3 binary)
```

Every entry decision and every mid-trade decision should reference this object. Currently the system has fragments (`breadth_cache`, `top_sectors`, `regime`) but no integrated state.

**6.2.2 — No trend quality classifier.** Per-stock, every tick, compute:

```python
def classify_trend_quality(candles_5m: list[Candle]) -> TrendState:
    # Returns one of:
    # BUILDING / LINEAR_UP / PARABOLIC / DISTRIBUTING /
    # BREAKING_DOWN / BOUNCING_WEAK / RECLAIMING / CHOPPY
    ...
```

Without this, the system treats a stock at fresh HOD identically to a stock that just bounced 1% off session lows.

**6.2.3 — No multi-snapshot confirmation framework.** Every signal should have a `requires_persistence: int` field. Single-snapshot OK for entry triggers; 2-3 snapshot persistence required for mid-trade exit signals. Today's ZYDUSLIFE single-snapshot depth-flip was a false signal that cost ₹900 of would-be P&L.

**6.2.4 — No expected-time-to-target check at entry.** Every entry should compute: given this setup type's historical median time-to-TP1, will the trade have runway? If estimated TP1 time > remaining_session_runway − safety_buffer, **skip the entry**. Not a clock rule — a runway rule. Generic across all hours.

### 6.3 Rigid logic

- **Top-3 sector list is binary.** Either in top-3 or not. Real flow is continuous — sector 4 might be 0.05% behind sector 3 but treated as "no priority." Replace with continuous sector-strength score (rank-position OR z-score against universe average).
- **MOMENTUM_BREAKOUT RVOL floor is one number.** Real structural breakouts can be spike-driven (RVOL 3+) OR absorption-driven (RVOL 1.3 sustained). Different patterns need different floors. Detector should classify which pattern and use the appropriate threshold.
- **Setup-disarmed list is binary.** "Either FAILED_BREAKDOWN is on or off." Should be context-gated: FAILED_BREAKDOWN valid IF index above VWAP AND stock day_pct > 0 AND in top-tier sector.

### 6.4 Static assumptions

- **`MAX_POSITIONS = 5`** — reasonable for ₹3L cap, wrong for ₹20L cap, wrong on a 5-pattern-simultaneously day. Should adapt to: cap available, number of structurally clean signals present, sector concentration of existing positions.
- **`PER_TRADE_RISK = ₹1500`** — fixed absolute number. Should be: `min(₹1500, 0.5% × capital, 0.3% × measured_volatility_factor)`.
- **`SPREAD_MAX = 0.10%`** — universal threshold. Some thin names will have 0.15% spread that's still tradeable; some hyper-liquid names with 0.02% spread should require 0.05% max. Adapt to the name's own typical spread distribution.

### 6.5 Dangerous abstractions

**6.5.1 — `entry_reason` as a parsed string.** The system parses `regime` out of an `entry_reason` text. Fragile and slow. Fix #14 added a `regime` column to the positions table but parsing remains as fallback. Delete the parser, require the column.

**6.5.2 — Confluence as a score multiplier (1.15× / 1.25×).** Confluence is a structural fact: "2 setups fired together" or "3 setups fired together." Multiplying a float score by 1.15 is engineering theatre — it doesn't change which trade is taken. Replace with: confluence ≥ 2 is a qualifier for Tier A sizing, confluence ≥ 3 is a qualifier for Tier S sizing. Binary, structural.

**6.5.3 — News in scoring.** Fix moved news LLM out of hot path (Fix #56). Good. But news still influences score via `news_score` component (0-1, penalty -0.5). News is mostly noise for intraday scalps. **Delete the news_score input from scoring.** Let news inform the premarket brief (cold path) only.

---

## 7. Core Intelligence Improvements Needed

### 7.1 Dynamic regime adaptation

Replace the current 4-regime label (TRENDING/CHOPPY/RECOVERING/EVENT) with a **continuous regime vector** computed every tick:

- `index_directional_strength` — measured from slope, lower-lows count, distance from VWAP. Range [-1, +1].
- `volatility_regime` — measured from current Nifty ATR / 5-day-avg-ATR. Continuous.
- `participation_breadth` — measured from breadth %, breadth trend, sector dispersion. Continuous.
- `leadership_concentration` — measured from top-5-stocks-contribution-to-index-move. Continuous.

Each setup type has weights against these dimensions, **learned from rolling history**, not declared by humans. A momentum_breakout might historically have +0.6 expectancy when `index_directional_strength > +0.3` and -0.3 when `index_directional_strength < -0.5`. The system reads the current regime vector, looks up each setup's expected-edge in this regime, and gates entries accordingly.

### 7.2 Adaptive participation analysis

Compute every tick: *"What kind of market is this right now?"*

- **Broad participation** (≥60% above VWAP AND ≤2 dominant sectors): all setups eligible, normal size
- **Narrow leadership** (35-55% above VWAP AND ≤2 sectors dominating): only top-sector entries, reduced size
- **Defensive rotation** (breadth declining AND defensive sectors gaining): no momentum_breakout, only PERSISTENT_LEADER / reclaim setups
- **Broad weakness** (≤35% above VWAP AND index slope negative): no longs, stand aside (no shorts because the system is long-only by mandate)

This is the **macro context filter that was missing today**. It's generic, structural, continuously measured.

### 7.3 Momentum quality analysis

For every momentum signal, ask:

1. Is the breakout bar's range > 1.3× mean of prior 5 bars? (Fix #29 — already exists)
2. Is the trigger bar AND the prior bar green? (Fix #30 — already exists)
3. **Is the move on real volume OR on sustained absorption?** (NEW — classify spike vs grind via RVOL trend)
4. **Is the index supporting or fighting this move?** (NEW — index direction must not be opposite)
5. **Is the sector flow positive?** (NEW — continuous sector strength, not top-3 binary)
6. **Are the next 1-2 bars showing follow-through?** (NEW — 2-snapshot persistence check before sizing up)

A signal scoring 6/6 = Tier S size. 5/6 = Tier A. 4/6 = Tier B. <4/6 = no entry. Binary structural facts, not floating-point arithmetic.

### 7.4 Breakout quality analysis

The current MOMENTUM_BREAKOUT detector takes "5-min candle breaks 20-bar high" as a binary fact. Add quality dimensions:

- **Distance broken** — closing 0.3% above resistance vs 0.05% above (the former is real, the latter is a fake)
- **Volume profile of the break** — explosive (spike RVOL ≥3) vs accumulation (sustained RVOL 1.3-2.0 for 15+ min)
- **Post-break behavior** — held above for 2 bars vs immediate reversal (requires multi-bar evaluation)
- **Order book at break** — bid stack growing or evaporating (depth-tier monitoring)

Each contributes to a **break-quality score** that gates entry. Today's TORNTPHARM had high break-quality on entry (broke 4540 with 1.80 bid/sell, sustained volume) — but the macro context (index falling) wasn't a feature.

### 7.5 Fake breakout detection

A real fake-breakout signature:

- Breaks high on volume → next 2 bars are red AND closes back inside the prior range → depth deteriorates → bid stack shrinks below the breakout level

Current system has no logic for this. Build a `FAKE_BREAKOUT_DETECTED` monitor that runs every tick on positions opened in the last 10 minutes. If signature confirmed → exit immediately, don't wait for SL.

### 7.6 Trend continuation probability

For an open position 15 minutes after entry, compute:

- **Structure score:** is the higher-highs / higher-lows pattern intact?
- **Volume score:** is the volume profile supporting continuation (drying up on pullbacks, expanding on pushes)?
- **Order book score:** is bid stack still dominant?
- **Macro score:** is the index still supportive?

If `total_score > threshold`: hold or add (trail SL up).
If `total_score < lower_threshold`: exit early, don't wait for SL.

This is **mid-trade re-evaluation** — the biggest pro/system gap.

### 7.7 Liquidity behavior understanding

For each name in universe, maintain rolling stats:
- 5-day average spread
- 5-day average depth at top-of-book
- 5-day average ratio of (filled volume / total visible volume)

At entry, compare CURRENT spread/depth/fill-ratio to the name's own 5-day norm. If today's spread is 2× the 5-day average → liquidity is degraded → reduce size by half OR skip. This catches "name-specific liquidity events" (e.g., a big institutional order has thinned out the book temporarily).

### 7.8 Intraday structure understanding

Every name needs a **structural state** at every tick:
- Is it building a base?
- Is it in an established trend (HH/HL)?
- Is it failing at resistance?
- Is it reclaiming key levels?
- Is it distributing at highs?

This is partially what the setup detectors do, but currently it's one-or-zero. Build a continuous structural classifier that runs on every name in the universe every 30 seconds. Then setups become **structural-state filters** on top of price/volume rules.

### 7.9 Volatility adaptation

Current Fix #25 adapts trail multiplier (0.7×ATR in CHOPPY, 0.4×ATR when RVOL≥2). Good direction, too coarse. Build a continuous **volatility regime**:

- **Compressed** (current ATR < 70% of 5-day-avg ATR) → tighter stops, smaller targets, faster timeouts
- **Normal** (70-130%) → standard parameters
- **Expanded** (130-200%) → wider stops, larger targets, longer timeouts
- **Extreme** (>200%) → reduce size 50%, only highest-conviction trades

All thresholds adapt; no fixed ATR multipliers.

### 7.10 Dynamic confidence modeling

Replace the 0-10 score with **a binary checklist + a confidence vector**:

- **Pass/fail:** Did the trade pass all 6 mandatory rules? (Yes = take it. No = skip.)
- **Confidence dimensions:**
  - Structural quality (0-1) — based on consolidation tightness, break distance, follow-through
  - Volume profile (0-1) — spike vs grind, sustained vs flash
  - Macro alignment (0-1) — index/sector/breadth tailwind
  - Microstructure (0-1) — order book + spread + depth + trade-direction drift

Position size = base risk × confidence_product. A trade that's 0.9 × 0.8 × 0.7 × 0.6 = 0.30 confidence gets 30% of full size. A 0.9 × 0.9 × 0.9 × 0.9 = 0.66 gets 66%. **Confidence is a continuous structural fact, not a score gate.**

---

## 8. Scalping Psychology Translation (Real Trader → Machine)

| When traders become AGGRESSIVE | Machine equivalent |
|---|---|
| Multiple structural patterns converge on one name | Confluence ≥ 3 AND sector_flow_positive AND macro_supportive → Tier S sizing |
| Macro tailwind + clean setup + strong order book | All 4 confidence dimensions > 0.7 → full size, accept tighter stop |
| Recent personal wins, market behaving as expected | Day-P&L positive AND last 3 trades classified-as-good-process (RAG critique) → temporary +0.1 size multiplier |
| Volatility expansion + clear directional setup | volatility_expanded AND direction_clear → wider stop, larger target, full size |

| When traders REDUCE SIZE | Machine equivalent |
|---|---|
| Macro environment hostile to trade direction | macro_alignment_score < 0.4 → size × 0.5 |
| Recent personal losses or bad processes | Day-P&L negative OR last 2 trades bad-process → size × loser-streak-gradient (Fix #31 — keep) |
| Volatility extreme or unclear regime | volatility_extreme OR regime_unclear → size × 0.5 |
| Setup quality good but order book thin or degrading | microstructure_score < 0.5 → size × 0.5 OR skip |

| When traders AVOID TRADES | Machine equivalent |
|---|---|
| Range-bound, low-information tape | sector_dispersion < threshold AND volatility_compressed → standby mode |
| Conflicting signals (e.g., setup says long, index says down) | macro_alignment_score < 0.3 → skip entry regardless of other scores |
| Event risk imminent | premarket_brief flagged event → reduce all sizes 50% OR skip |
| Recent fakeouts on similar setups | RAG query: same setup × same regime, last 5 trades, WR < 40% → skip (Fix #44 — keep, expand) |

| When traders SENSE WEAKNESS | Machine equivalent |
|---|---|
| Volume drying up while price grinds higher | rvol_trend < 0.7 AND price_still_advancing → exit half OR trail tighter |
| Bid stack thinning, sellers stacking on offers | 5-level depth ratio dropping over 3 consecutive snapshots → tighten stop to entry |
| Index reversing while my long holds | index_direction flipped AND my_position long → re-evaluate immediately; if mid-trade-structure-score also degraded, exit |
| Sector basket fading while my stock holds | stock day_pct > sector_basket_avg + 1.5% gap → tighten stop (likely to follow sector down) |

| When traders DISTRUST BREAKOUTS | Machine equivalent |
|---|---|
| Breaks high but immediately retraces | next 2 bars after break are red AND close below break level → mark as fakeout candidate, exit position immediately |
| Volume doesn't expand on the break | break-bar RVOL < prior 5 bars' avg RVOL → fakeout flag, reduce position |
| Order book inverts immediately after break | depth ratio < 1.0 within 60 seconds of break → fakeout flag, exit |
| Index isn't supporting the move | index_slope_5min < 0 while stock breaks high → fakeout candidate, reduce position |

| When traders RECOGNIZE TRAPS | Machine equivalent |
|---|---|
| "Too obvious" breakout (round-number break with no preparation) | break of round-number level + no prior consolidation + RVOL spike (not grind) → high fakeout probability, skip |
| Gap-up that immediately stalls | open > prev_close + 1% AND first 30 min produced no follow-through → mark as "exhausted gap," do not long |
| Stop-run pattern (sweep just below support → reversal) | new low + reclaim within 5 min on volume → potentially valid LONG signal (this is the "failed_breakdown" pattern, but only when structural conditions are right) |

---

## 9. Immediate High-Priority Fixes

### P0 — Ship within 48 hours (highest expected impact, low complexity)

**P0.1 — Replace top-of-book bid/sell ratio with 5-level aggregate** *(Universal pre-entry filter)*

Reason: Top-of-book ratio can be spoofed by a single order. Today's live data: MCX had 0.42 top-of-book but 1.64 5-level aggregate. The depth was the truth.

Implementation: In `agents/crew.py::_allocate`, replace the existing bid/sell check with:
```python
def order_book_strength_ratio(depth: dict) -> float:
    buy_total = sum(level["quantity"] for level in depth["buy"][:5])
    sell_total = sum(level["quantity"] for level in depth["sell"][:5])
    return buy_total / sell_total if sell_total else 99.0
```
Threshold: `ORDER_BOOK_RATIO_MIN = 1.5` in `config/settings.py`. Apply to all setups.

Expected impact: cleaner entries; rejects ~30% of current entries that look strong on top-of-book but have weak depth. Today this would have correctly rejected the 7 dead-cat-bounce false positives at tick #1 post-restart.

Complexity: 1 hour.

---

**P0.2 — Add `day_pct > 0` + fresh-day-high gate to MOMENTUM_BREAKOUT** *(Fix #7)*

Reason: Today the detector fired on 6 stocks DOWN on the day (SBIN −3.6%, RBL −1.6%, etc.) because the 5-min bar broke an intermediate high. These were dead-cat bounces, not breakouts.

Implementation: In `tools/pattern_tools.py::_detect_momentum_breakout`, before returning a valid signal:
```python
if quote.day_pct < 0.0:
    return None  # only longs in positive-day stocks
if (quote.day_high - quote.ltp) / quote.day_high > 0.005:
    return None  # must be at/near fresh day high, not extended
```
Both thresholds in config.

Expected impact: eliminates the largest class of false positives. Today this would have rejected ALL 7 of the tick #1 post-restart cluster.

Complexity: 30 minutes.

---

**P0.3 — Macro context gate (continuous, not clock-based)**

Reason: Today's −1.5% Nifty close destroyed otherwise-good structural longs. Need a measurable macro context that gates sizing OR skips entries entirely.

Implementation: New module `agents/market_state.py`:
```python
def compute_market_state(kite, breadth_pct, top_sectors) -> MarketState:
    nifty_ohlc = kite.get_ohlc("NSE:NIFTY 50")
    nifty_5m_candles = kite.get_candles("NSE:NIFTY 50", days=1, interval="5minute")
    
    # Index slope (last 6 bars = 30 min)
    last_6 = nifty_5m_candles[-6:]
    slope_pct = (last_6[-1].close - last_6[0].close) / last_6[0].close
    
    # Lower-lows count (last 12 bars = 60 min)
    last_12 = nifty_5m_candles[-12:]
    lower_lows = sum(1 for i in range(1, len(last_12)) if last_12[i].low < last_12[i-1].low)
    
    # Distance from VWAP
    nifty_vwap = compute_vwap(nifty_5m_candles)
    dist_vwap_pct = (nifty_ohlc.last - nifty_vwap) / nifty_vwap
    
    return MarketState(
        index_slope_pct=slope_pct,
        index_lower_lows=lower_lows,
        index_dist_vwap_pct=dist_vwap_pct,
        breadth_pct=breadth_pct,
        # ... etc
    )

def macro_alignment_score(state: MarketState, direction: str = "long") -> float:
    if direction != "long":
        return 0.0  # system is long-only
    score = 1.0
    if state.index_slope_pct < -0.003:    score -= 0.3   # index falling
    if state.index_lower_lows >= 4:        score -= 0.3   # consecutive lower lows
    if state.index_dist_vwap_pct < -0.005: score -= 0.2   # below VWAP
    if state.breadth_pct < 40:             score -= 0.2   # narrow tape
    return max(0.0, score)
```

Apply in `_allocate`: if `macro_alignment_score < 0.4`: skip entry (regardless of other gates). If `0.4-0.6`: size × 0.5. If `>0.6`: full size.

Expected impact: today this would have prevented or downsized TORNTPHARM and MARICO entries (both passed structural filters; both lost). Saves the largest single loss-class in the data.

Complexity: 3-4 hours.

---

**P0.4 — Multi-snapshot persistence for exit signals**

Reason: Single-snapshot exit signals (like depth-flip) are too noisy. Today's ZYDUSLIFE call to cut at 953.5 was based on one snapshot; the stock recovered to 960 (+₹900 missed).

Implementation: New helper in `agents/crew.py::_manage_positions`:
```python
def should_exit_on_microstructure(position, last_3_snapshots: list[Snapshot]) -> bool:
    # Require: 3 consecutive snapshots of depth_ratio < 1.0
    # AND: price below entry
    # AND: volume declining (last bar vol < prior 5 bars avg)
    consec_weak = all(s.depth_ratio < 1.0 for s in last_3_snapshots[-3:])
    price_below = position.current_ltp < position.entry_price
    vol_declining = last_3_snapshots[-1].volume < statistics.mean(s.volume for s in last_3_snapshots[:-1])
    return consec_weak and price_below and vol_declining
```

Use this as a structural exit signal BEFORE the SL is hit. Saves bleeds where structure has clearly broken but price stop hasn't fired.

Complexity: 2-3 hours.

---

**P0.5 — Delete hour-of-day score nudges (Fix #24) and lunch-window gate (Fix #35)**

Reason: Both encode clock categories, violating Law 3. Their effects (raise threshold in choppy lunch trading) are real but should be derived from **measured volatility/spread state**, not clock.

Implementation:
1. Remove `HOUR_GATE_NUDGES` from `config/settings.py`
2. Remove the lunch midday gate block from `agents/crew.py::_score_signals`
3. Add a new generic gate: `volatility_compression_gate` — if `nifty_5min_atr < 0.6 × 5-day-avg-ATR` AND `mean_spread_in_universe > 1.3 × 5-day-avg-spread`, raise effective threshold by +0.3. This generic rule fires when the market is structurally low-information, which often correlates with mid-day but isn't determined by the clock.

Expected impact: removes 2 hardcoded constants; replaces with measurable structural rule that adapts automatically.

Complexity: 2 hours.

---

### P1 — Ship within 1 week

**P1.1 — Continuous sector strength score (replace binary top-3)**

Replace `top_3_sectors = ['IT', 'PHARMA', 'METAL']` with continuous per-sector scoring:
```python
def compute_sector_strength(stocks_in_sector: list[Quote]) -> float:
    # Return z-score against universe average
    sector_avg_pct = mean(s.day_pct for s in stocks_in_sector)
    universe_avg_pct = mean(s.day_pct for s in all_stocks)
    universe_stdev = stdev(...)
    return (sector_avg_pct - universe_avg_pct) / universe_stdev
```

Use as continuous sizing-tier qualifier: z > +1.5 → Tier S eligibility, z > +0.5 → Tier A, z > -0.5 → Tier B.

Today this would have caught LICHSGFIN: NBFC sector z-score may have been positive even if not top-3, qualifying the trade.

Complexity: 3-4 hours.

---

**P1.2 — Mid-trade structural re-evaluation**

Every position, every tick, compute:
- Has price made HH in last 15 min? (intact trend)
- Has order-book depth ratio held > 1.0?
- Has volume profile supported continuation?
- Is index still favorable?

If 2+ of 4 deteriorate: tighten stop to BE. If 3+ of 4 deteriorate: exit immediately.

This replaces the simple "stop hit / target hit / time stop" with structural intelligence.

Complexity: 6-8 hours.

---

**P1.3 — Time-to-target check at entry (NOT a clock rule)**

```python
def has_runway(setup_type: str, current_time_ist: time) -> bool:
    median_time_to_tp1 = SETUP_HISTORICAL_TIME_TO_TP1[setup_type]  # from rolling history
    remaining_session_runway = mins_until_force_close(current_time_ist)
    safety_buffer_min = 10
    return remaining_session_runway > median_time_to_tp1 + safety_buffer_min
```

Replaces blunt `NO_NEW_ENTRY_AFTER=14:45` with a runway check that's setup-aware. A FAILED_BREAKDOWN with median time-to-TP1 of 15 min can still enter at 14:55. A TREND_PULLBACK with median 45 min cannot enter after 14:20.

Complexity: 2-3 hours.

---

**P1.4 — Trend quality classifier per stock**

Replace per-tick "is_breakout_bar" binary with full structural state:

```python
def classify_structural_state(candles_5m) -> StructuralState:
    # Returns: BUILDING / LINEAR_UP / PARABOLIC / DISTRIBUTING / 
    #          BREAKING_DOWN / BOUNCING / RECLAIMING / CHOPPY
    ...
```

Used as filter:
- MOMENTUM_BREAKOUT only fires on LINEAR_UP state (not BOUNCING or BREAKING_DOWN)
- FAILED_BREAKDOWN only fires on RECLAIMING state
- etc.

Complexity: 6-10 hours.

---

**P1.5 — Volatility-adaptive thresholds**

Every key threshold (RVOL min, spread max, stop multiplier, TP1 target) should be `base_value × volatility_regime_factor`:

```python
def get_adaptive_threshold(threshold_name: str, current_state: MarketState):
    base = THRESHOLDS[threshold_name]
    vol_factor = current_state.nifty_atr_pct / 5d_avg_atr_pct
    if vol_factor < 0.7:
        return base * compressed_adjustment[threshold_name]
    elif vol_factor > 1.3:
        return base * expanded_adjustment[threshold_name]
    return base
```

Complexity: 4-6 hours.

---

### P2 — Ship within 1 month

**P2.1 — Replace 0-10 score with 6-rule binary checklist + confidence vector** *(Phase F of migration plan)*

Replace the multi-input multiplicative score with:
- 6 mandatory binary rules (must all pass)
- 4 confidence dimensions (0-1) used for sizing

Removes engineering theater; makes every rejection attributable to one specific rule.

Complexity: 2-3 days (per Phase F estimate).

---

**P2.2 — Discovery Engine** *(Phase B of migration plan)*

Scan broader universe (80-150 names) every 60s for early-stage structural signals. Promote names to focus list dynamically. Today's MARICO/LICHSGFIN/MCX would all have been caught by this.

Complexity: 2-3 days.

---

**P2.3 — Focus list state machine** *(Phase C of migration plan)*

Names flow through COLD → PROMOTED → ARMED → ENGAGED → COOLED states. Premarket brief seeds. Discovery promotes. Setups arm. Entries engage. Failures cool.

Complexity: 1-2 days.

---

**P2.4 — Sector rotation handoff detector (generic, no hardcoded sectors)**

When 1 sector loses 2+ leaders and another sector gains 2+ leaders in the same 15-min window → flag rotation, increase sizing in the gaining sector for the next 30 min.

Generic: iterates SECTOR_MAP, counts new-HODs vs fades per sector, no hardcoded sector names.

Complexity: 4-6 hours.

---

**P2.5 — Premarket brief job** *(Phase H of migration plan)*

Daily 08:30 LLM call reading overnight global flows, sector-specific news, results-day calendar. Seeds focus list with 10-12 names with bias/levels.

Complexity: 1-2 days.

---

## 10. Concrete Action Plan

### Week 1 (this week)

**Day 1 (tonight):**
- P0.1 — 5-level depth aggregate filter (1h)
- P0.2 — MOMENTUM_BREAKOUT day_pct + fresh-HOD gate (30m)
- Pre-flight check on server
- Commit + deploy + restart service

**Day 2:**
- P0.3 — Macro context gate (3-4h)
- P0.4 — Multi-snapshot persistence for exit signals (2-3h)
- Pre-flight + deploy

**Day 3:**
- P0.5 — Delete hour-of-day nudges + lunch gate; add generic volatility-compression gate (2h)
- Paper-trade observation day with all P0 fixes live

**Day 4-5:**
- P1.1 — Continuous sector strength score (3-4h)
- P1.3 — Time-to-target runway check (2-3h)
- Continued paper observation

**Day 6-7:**
- P1.5 — Volatility-adaptive thresholds (4-6h)
- Weekend code review + cleanup

**Acceptance gate after Week 1:**
- 5+ trading sessions of paper data with P0 fixes
- Mean R per trade ≥ +0.20 (up from +0.075)
- Stall rate < 50% (down from 71%)
- Zero entries on negative-day stocks via momentum_breakout
- All trades have order_book_5_level_ratio ≥ 1.5 at entry

### Week 2

**Day 8-10:**
- P1.2 — Mid-trade structural re-evaluation (6-8h)
- P1.4 — Trend quality classifier (6-10h)

**Day 11-14:**
- Validation across 5+ sessions
- If acceptance gate met → green-light Week 3 P2 work

### Week 3-4 (P2)

- Replace score system with 6-rule checklist (Phase F)
- Build Discovery Engine (Phase B)
- Build focus list state machine (Phase C)
- Build sector rotation handoff detector
- Build premarket brief job (Phase H)

### What to DELETE in cleanup

- `tools/score_tools.py` (after checklist ships)
- `MIN_SCORE_*` constants
- `SCORE_SIZE_TIERS` (replace with structural-qualifier tiers)
- `HOUR_GATE_NUDGES`
- `CONFLUENCE_MULTIPLIER_*`
- News LLM call from scoring path (already done — confirm)
- Lunch-window gate code
- ORB time-window enforcement (replace with "ORB only fires when opening range is structurally complete AND no fresh data invalidates it" — no clock gate)
- The 14:45 NO_NEW_ENTRY_AFTER clock rule (replace with runway check)

### What to SIMPLIFY

- Setup detectors: from "if all these conditions" to "if structural state == LINEAR_UP AND break_quality > threshold AND order_book_aligned"
- Position management: from "if time > 25min AND pnl_r in range" to "if mid_trade_structural_score < threshold"
- Sizing: from 4 grade-based tiers to 3 confidence-based tiers (S/A/B)
- Regime: from 4 labels to 1 continuous vector

### What to REDESIGN COMPLETELY

- **Scoring system → Checklist + confidence vector** (Phase F)
- **Setup library → 4 reusable structural building blocks** (consolidation, breakout, reclaim, failure) that compose into different patterns
- **Watchlist → 3 distinct concepts**: focus list (live attention), pending-pullback (waiting for retest), historical journal (post-trade)

---

## 11. The Final Honest Read

This system is the **honest implementation of a flawed thesis**. The thesis was: "score signals, multiply by regime, gate by hour, size by grade." That thesis has been tested for 280+ trades and produced near-zero net edge. The current Phase A response (kill 6 setups, keep one) is correct directionally but is a damage-control move, not an edge-finding move.

**The edge is not in the score.** The edge is in:

1. **Reading what the market is actually doing** (macro context, structural state, order flow direction)
2. **Knowing which patterns work in which market states** (learned from data, not declared)
3. **Adjusting size and target by measured confidence** (4-dim vector, not 1-dim score)
4. **Refusing to trade when conviction is low** (cash is a position)
5. **Acting on mid-trade structural signals** (not just price stops)

The migration plan in `docs/07_Scalper_Architecture_Migration.md` has the right destination (Phase F checklist, Phase B discovery, Phase C focus list). The plan is correct. What was missing is the **macro context layer** — which today's live session brutally exposed.

**The honest verdict:** the system is 3-4 weeks of focused work away from being a real scalping engine. Not 6 months. Not "more research." Focused work, with the P0/P1/P2 priorities above, paper-traded continuously, with the operator reading every EOD critique.

The operator's discipline today — calling out clock-shaped reasoning, calling out hardcoded sector assumptions, demanding generic-first design, comparing agent vs paper-plan honestly — is the difference between a "trading bot project" and a system that might actually work. Keep this discipline. The code follows.

---

*End of report. Next action: ship P0.1 + P0.2 tonight, observe tomorrow, P0.3 + P0.4 + P0.5 by end of week.*
