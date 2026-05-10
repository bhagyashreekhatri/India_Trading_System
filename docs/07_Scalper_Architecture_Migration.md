# Scalper Architecture Migration Plan

*Authored: 2026-05-08 — based on 280-trade paper history + 55 deployed fixes*

This document is the single source of truth for the architectural migration from the current "score-based institutional engine wearing a scalper costume" to a true scalper-pro execution system.

It is written for both Bhagya (operator) and any future Claude session that picks up this work after context compaction.

---

## 0. Read this first — non-negotiables

### 0.1 The goal
**₹1,000–₹5,000 net profit per trade**, consistently, on real Indian intraday tape, with capital preservation as the floor.

Per-trade target. NOT per-day. NOT per-month. Each trade stands alone.

### 0.2 The mindset hierarchy (locked)
**Scalper decides WHAT. Engineer decides HOW. Data decides WHO WAS RIGHT.**

- Scalper-first behaviour, engineer-quality implementation, data-validated evolution.
- Architecture serves execution quality — not the other way around.
- Where they conflict, scalper wins, engineer adapts (fail-closed, fail-fast, fail-readable).
- Every code decision must pass three tests in order:
  1. **Scalper test** — would a pro scalper take/skip this trade BECAUSE of this code?
  2. **Engineer test** — if this fails, does the system fail SAFE (skip) not OPEN (wrong trade)?
  3. **Data test** — can we measure at EOD whether this decision was right?
- If any test is "no", the code does not ship.

### 0.3 The forbidden patterns
- LLM in the hot path (entry/scoring/exit decisions) — **never**
- Hardcoded thresholds as immutable doctrine — **never**
- "Score with multipliers" or weighted-pass logic — **dead pattern**
- Setups that exist because they "feel useful" — **must prove edge**
- Chasing runaway names — **wait for retest, or skip**
- Trades that can't be expressed as `setup / level / trigger / stop / invalidation / target` — **don't take**

---

## 1. What's been built and works (KEEP — production-critical)

These are the non-negotiable foundations. Most are infrastructure that survives the architectural shift.

| Component | File(s) | Why kept |
|---|---|---|
| **Tick-size rounding (₹0.05)** | `scoring/engine.py`, `tools/pattern_tools.py`, `agents/crew.py` | NSE order requirement; production-critical |
| **SL-M broker orders** | `data/kite_client.py`, `agents/crew.py` | Stop must live on exchange, not in script |
| **Live LTP refetch at order time** | `agents/crew.py` `_allocate`, `_partial_exit_tp1`, `_full_exit` | Never trust stale signal price |
| **Daily kill switch ±2.5%** | `config/settings.py`, `agents/crew.py` | Survival rule |
| **Daily profit lockout +3% / tighten +2%** | `config/settings.py`, `agents/crew.py` | Survival rule (don't give back) |
| **Asymmetric cooldown (45m loss / 15m win)** | `memory/trade_state.py`, `agents/crew.py` | Anti-revenge — real edge |
| **Spread filter ≤ 0.10%** | `agents/crew.py`, `data/kite_client.py` | Wide spreads silently destroy R:R |
| **RAG proven-loser veto** | `agents/crew.py`, `memory/chroma_client.py` | Demonstrated edge — kept TVSMOTOR/WESTLIFE off book |
| **EOD self-critique loop** | `jobs/eod_job.py`, `memory/chroma_client.py` | The learning loop heart |
| **Per-stage rejection telemetry** | `agents/crew.py` `_rej` + `_reject_counts` | We can finally SEE why we don't trade |
| **Force square-off + EOD partial unwind** | `agents/crew.py` | We don't carry overnight, ever |
| **Overnight veto at boot** | `agents/crew.py` `_manage_positions` | Catches stuck-from-yesterday positions |
| **Today-only VWAP filter** | `data/kite_client.py` `_filter_to_today` | Mondays / post-holidays don't break setups |
| **Paper-mode slippage simulation** | `agents/crew.py` `_apply_paper_slippage` | Honest paper P&L matches live behaviour |
| **News pre-cache infrastructure** | `data/news_client.py`, `news_cache.json` | Cache mechanism is good — the calling layer is what changes |
| **TZ-aware datetime helpers** | `memory/trade_state.py`, `agents/crew.py` | Stall-bug fix; non-negotiable for correctness |
| **Rejection bucket telemetry (Fix #52)** | `agents/crew.py` | `proximity_failed_to_watchlist` measures NBCC-class skips |
| **Dashboard fresh-token logic (Fix #55)** | `dashboard/live_tab.py` | Daily Kite token refresh works without manual restart |
| **Tick-book-cache infrastructure** | (to be confirmed in `data/kite_client.py`) | Caching layer reused for new discovery engine |

**Discipline:** if a phase below proposes touching any KEEP item, that phase needs explicit re-justification. These earned their place through 280 trades of paper validation.

---

## 2. What's been built and is wrong (DEPRECATE — remove or replace)

The system has structural decisions that smell like "institutional engine wearing scalper costume." These are honestly broken, not just suboptimal.

| Component | File(s) | Why it's wrong | Replacement |
|---|---|---|---|
| **0-10 score with multiplicative nudges** | `scoring/engine.py`, `agents/crew.py` `_score_signals` | Hides the real question (is this setup valid?) behind 6 layers of float arithmetic | 6-rule binary checklist (Phase E) |
| **Score-tier sizing (A++ → ₹15k risk)** | `config/settings.py` `SCORE_SIZE_TIERS`, `agents/crew.py` | Sizes for hedge-fund position book, not ₹1-5k scalper target. ₹15L per trade is wrong species | 3 discrete tiers (S/A/B) pegged to ₹ target (Phase A) |
| **News LLM call inside `_score_signals`** | `data/news_client.py`, `agents/crew.py` | 1-3s per stock × 10 setups = 15-30s of LLM in a 180s tick. Move is gone before we score | LLM only at premarket brief (Phase F+); news cache stays for in-session lookups but no fresh LLM calls |
| **Score nudges (PDH, sector, breadth, hour, hist, decay, confluence)** | `agents/crew.py` `_score_signals` | Each is a real signal squashed into floating-point noise | Binary checklist rules + sizing tier qualifiers (Phase E) |
| **Confluence multiplier on score (1.15 / 1.25)** | `agents/crew.py`, `config/settings.py` `CONFLUENCE_MULTIPLIER_*` | Same trade outcome, abstraction layer between trader and chart | Confluence becomes a sizing-tier qualifier, not a score boost (Phase A) |
| **8 setup types** | `scoring/engine.py` `SetupType`, `tools/pattern_tools.py` | Mediocre at all instead of mastering 3-4 | Cut to 4 (or whatever audit proves) (Phase D) |
| **Single-tier 3-min scan** | `agents/crew.py` tick loop | NBCC-class moves 0.7% in 90s — we see them 90s late | Two-tier: focus 30s, broader 60s w/ Discovery Engine (Phase B+C) |
| **Watchlist as dumping ground** | `memory/trade_state.py` watchlist | Holds B-grade + proximity-failed + below-gate together | Three separate concepts: focus list (live attention), pending-pullback (waiting for retest), historical journal (post-trade) (Phase B+C) |
| **Static stock universe (60 names)** | `config/universe.py`, scanner | No focus list, no discovery, every name treated identically | Focus tier (15 names, dynamic) + broader tier (80 names) (Phase B+C) |
| **`MAX_POSITIONS = 10`** | `config/settings.py` | A scalper can't watch 10 positions effectively | Reduce to 5 (Phase A) |
| **TP1 partial @ 0.7R + TP2 runner** | `config/settings.py`, `agents/crew.py` `_partial_exit_tp1` | Partials pay round-trip costs twice. ~₹1,000 friction per trade may eat the partial. Pending exit-distribution analysis | Single-target exit pegged to ₹ goal (Phase A, contingent on data) |
| **`tools/score_tools.py`** | (file) | Wraps the score system being deleted | Delete after Phase E |
| **`MIN_SCORE_*` constants** | `config/settings.py` | Score-system residue | Delete after Phase E |
| **Hour-of-day score nudges** | `config/settings.py` `HOUR_GATE_NUDGES`, `agents/crew.py` | Treats time-of-day as score adjustment instead of setup gating | Replace with day-class-aware setup arming (Phase F) |
| **Sector-flow score nudge** | `agents/crew.py` `sector_nudge` | Sector strength should gate eligibility, not nudge a score | Becomes a sizing-tier qualifier (Phase A) or arms VWAP_RECLAIM/MOMENTUM_BO (Phase F) |
| **ORB time-window enforced inside detector** | `tools/pattern_tools.py` | Enforcement is right, location is wrong (mixing concerns) | Stays correct in Phase A; clean up in Phase E refactor |

**Discipline:** items above will be deprecated *in their phase*, not in a big-bang rewrite. Each one has a defined replacement and a defined removal date.

---

## 3. Pre-flight analyses (READ-ONLY — run before any code ships)

These two analyses run **on the server's 280-trade DB**, produce two markdown documents, and inform every destructive decision in Phases A–E. They touch nothing in the live system.

### 3.1 Exit distribution analysis → `docs/05_Exit_Distribution_Analysis.md`

**Question it answers:** Should we kill TP1 partials and go single-target?

**Required outputs:**
- Distribution of Max Favourable Excursion (MFE) in R-multiples — p10, p25, p50, p75, p90
- % of trades that hit TP1 (any flavour)
- Of TP1 hits: % that went on to TP2, % that reversed and stopped
- Time-to-TP1 distribution (5min, 15min, 30min buckets)
- Counterfactual: if we had a single 0.6R target, what % would have hit?
- Counterfactual: total net P&L under (a) current partials, (b) single target at 0.6R, (c) single target at 1R, after realistic ₹1,000 round-trip friction

**Decision rule:**
- If median MFE < 1R AND >25% of TP1 hits reversed to SL → **kill partials, single-target wins**
- If median MFE > 1R AND <15% of TP1 hits reversed → **partials may earn from runner**
- If bimodal (small + big) → compute net P&L per option, pick winner

**Code:** `scripts/analyze_exit_distribution.py` (read-only, runs on DB copy)

### 3.2 Setup deletion audit → `docs/05_Setup_Deletion_Audit.md`

**Question it answers:** Which of the 8 setups have proven edge?

**Required outputs per setup (8 setups):**
- Total trades taken; % of total signal pool
- Win rate; mean R; median R; after-cost expectancy (with ₹1,000 friction)
- Avg time-to-resolution
- Stalled-exit rate
- Breakdown by hour-of-day (09–13 IST)
- Breakdown by day-class (PRESS / SELECTIVE / DEFENSIVE — backfilled from breadth + nifty change)
- Confluence overlap matrix: when this setup fired, what other setups also fired?
- Pure-play count (this setup was the ONLY one that fired)
- Counterfactual deletion: if removed, how many trades would another setup have caught instead, with what expectancy?

**Decision rules per setup:**
- **Survives** if: after-cost expectancy ≥ +0.1R AND ≥5% pure-play AND WR ≥ 35% in ≥2 day-classes
- **Killed** if: after-cost expectancy < 0 OR zero pure-play OR WR < 30% across all day-classes
- **Modified** if: strong in one regime / weak in another → make day-class-gated; OR strong as confluence trigger / weak standalone → demote to "trigger only"

**Code:** `scripts/setup_audit.py` (read-only)

### 3.3 Threshold counterfactual baseline → `docs/05_Threshold_Counterfactuals.md` (deferred — Phase F)

For each currently-hardcoded threshold, compute what would have happened at ±10% and ±20% values on the historical trade set. Becomes the baseline for the weekly threshold review job in Phase F.

---

## 4. Migration phases — sequenced, each defensible

Each phase is reversible. Each phase has acceptance criteria. No phase begins until the previous phase's acceptance criteria are met for at least 2 trading sessions.

### Phase A — Sizing rewrite + max-loss cap (config-only, ~½ day)

**Depends on:** Exit distribution analysis (§3.1) — to confirm single-target vs partials.

**What changes:**
- New constants in `config/settings.py`:
  - `TIER_S_INR = 700_000` (focus + confluence + PDH break)
  - `TIER_A_INR = 500_000` (focus OR confluence-with-momentum)
  - `TIER_B_INR = 250_000` (entry valid but no qualifier)
  - `MAX_LOSS_INR = 1500` (per-trade hard cap)
  - `TARGET_S_INR = 4000`, `TARGET_A_INR = 2000`, `TARGET_B_INR = 1200`
- **If exit-distribution analysis says single-target wins:** delete `_partial_exit_tp1` invocation; place a single SELL at `entry × (1 + target_pct)` along with the SL-M
- `MAX_POSITIONS` 10 → 5
- Sizing logic in `agents/crew.py` `_allocate` derives qty from `target_inr / size` and `max_loss_inr / sl_distance_pct`

**What does NOT change:**
- Score system, setup detection, scanning interval, regime logic — all untouched
- We're only changing how big we go and where we exit

**Acceptance criteria:**
- 10 paper trades taken under new sizing
- Net P&L per winning trade lands in ₹1,000–₹5,000 range
- Loss per trade ≤ ₹1,500 with no breaches
- No bug regressions in `tests/test_engine.py`

**Rollback:** revert `config/settings.py`; restart. Code is config-driven so no logic backout needed.

**Files touched:** `config/settings.py`, `agents/crew.py` (~20 lines), `memory/trade_state.py` (no schema change).

---

### Phase B — Discovery Engine, first-class (~2-3 days)

**Depends on:** Phase A acceptance.

**What gets built:**
- New module `agents/discovery_engine.py`
- Six alarm rules (R1–R6 — see plan in conversation)
- Runs every 60s on broader 80-name universe
- Emits promotion events to `state/focus_list.py`
- Per-name compute < 10ms (must be lightweight)
- All rules importable from `config/discovery_rules.py` (configurable)

**Engineer-grade requirements:**
- Idempotent: same minute-bar inputs → same alarm output
- Bounded retry on Kite errors (3× exponential backoff, then skip name for this cycle)
- Crash-safe: alarm state stored in-memory only; on restart, recomputed from candle data
- Observable: every alarm fire logged with rule + values to `logs/discovery.jsonl`

**Acceptance criteria:**
- 1 full session paper-traded
- ≥ 3 alarm fires per day on average
- ≥ 50% of fires lead to a promoted name that subsequently shows continued momentum (range ≥ 0.5% in next 15 min)
- Hot-path latency unaffected: discovery runs in its own thread / async, never blocks main tick

**Rollback:** disable via `config/discovery_rules.py` `ENABLED = False`. Discovery engine returns empty promotions; system falls back to static universe.

**Files added:** `agents/discovery_engine.py`, `config/discovery_rules.py`, `logs/discovery.jsonl`.

---

### Phase C — Focus list state machine (~1-2 days)

**Depends on:** Phase B (needs promotion events).

**What gets built:**
- New module `state/focus_list.py` (NOT in `memory/` — this is hot-path state, not historical record)
- States per name: `COLD / PROMOTED / ARMED / ENGAGED / COOLED`
- Promotion triggers: R1–R6 from Discovery Engine + premarket-brief-flagged names + intraday catalysts
- Stay rules (S1–S4)
- Demotion rules (D1–D6)
- Capacity: max 15, hard floor 5
- 30-min cooldown after demotion
- Audit trail to `state/focus_log.jsonl`

**Engineer-grade requirements:**
- Atomic state transitions (in-process locking; no half-promoted ghosts)
- Recoverable on crash: `focus_log.jsonl` is the source of truth; restart replays today's events to rebuild state
- Capped log retention: rotate daily

**Acceptance criteria:**
- 2 sessions paper-traded
- Avg focus list size between 5 and 15 throughout session
- ≥ 30% of trades come from intraday-promoted names (proves dynamic discovery is working)
- No name stuck in `COOLED` indefinitely

**Rollback:** `state/focus_list.py` `STATIC_FALLBACK = True` — focus list reverts to top-12-by-overnight-turnover; no dynamic transitions.

**Files added:** `state/focus_list.py`, `state/focus_log.jsonl`.

---

### Phase D — Pending-pullback state machine (~1-2 days)

**Depends on:** Phase C (focus list provides the names being watched).

**What gets built:**
- New module `state/pending_pullback.py`
- When a setup fires AND proximity_failed AND drift ≤ 2% AND score ≥ A-equivalent → mark `PENDING_RETEST`
- Watch for 10 minutes for price to retest trigger ± 0.3%
- On retest with volume holding → emit READY signal back to entry path
- On 10-min expiry or drift > 2% → mark DEAD
- Persist pending state to disk so crash-restart doesn't lose context

**Engineer-grade requirements:**
- Idempotent: re-injecting the same setup signal doesn't duplicate pending entries
- One pending entry per (symbol, setup_type) — newer overwrites older
- Audit trail to `state/pending_log.jsonl`

**Acceptance criteria:**
- 5 sessions paper-traded
- ≥ 1 NBCC-class entry captured per session via pending-pullback
- ≥ 60% of pending-promoted entries are net-profitable (data-test threshold)
- Zero false fires (entered when retest didn't happen)

**Rollback:** disable in `config`; entry path reverts to current proximity-fail-skip behaviour.

**Files added:** `state/pending_pullback.py`, `state/pending_log.jsonl`.

---

### Phase E — Setup pruning (based on §3.2 audit) (~1 day)

**Depends on:** Setup audit (§3.2) results.

**What changes:**
- For each setup the audit kills: remove from `SetupType` enum, delete detector function, remove from regime multiplier table (table itself goes away in Phase F)
- For each setup the audit modifies: update detector to be day-class-gated, or demote to confluence-only role
- Tests in `tests/test_engine.py` updated to remove deleted setups

**Acceptance criteria:**
- All `tests/test_engine.py` tests pass
- 1 session paper-traded with the trimmed setup list
- Setup-firing volume per session reduces by ≥ 30% (less noise)
- Setup quality (avg R per trade) increases ≥ 0.1R

**Rollback:** `git revert` of the setup pruning commit. Setups are in single-file enums + detectors so blast radius is contained.

**Files touched:** `scoring/engine.py`, `tools/pattern_tools.py`, `tests/test_engine.py`.

---

### Phase F — 6-rule binary checklist replaces score (~2-3 days, biggest change)

**Depends on:** Phases A–E. This is the architectural climax.

**What changes:**
- New module `agents/checklist_engine.py`
- 6 rules per signal, all binary, all must pass:
  1. Setup-specific RVOL minimum (regime-aware, from `config/thresholds.py`)
  2. Spread ≤ setup max
  3. Within proximity OR pending-pullback retest happened
  4. Day-class compatible (e.g., no MOMENTUM in DEFENSIVE)
  5. Stock not RAG-vetoed (kept verbatim from current Fix #44)
  6. `risk_clear()` — kill switch, cooldown, position cap, sector cap
- `_score_signals` in `agents/crew.py` is replaced by `_check_signals` which uses checklist_engine
- `scoring/engine.py` becomes deprecated (kept as reference, no longer imported by crew)
- Sizing tier (S/A/B) determined by qualifiers, not by score
- All score nudges deleted (PDH, sector, breadth, hour, hist, decay, confluence-as-multiplier)
- Confluence becomes a sizing-tier qualifier (3+ confluence ⇒ Tier S eligibility)
- Sector-strength becomes a sizing-tier qualifier (top-3 sector ⇒ Tier A or S eligibility)
- PDH break becomes a sizing-tier qualifier (PDH break ⇒ Tier S eligibility)

**Engineer-grade requirements:**
- Each rejection logged with the *single* rule that failed (no "multiple rules failed" — first fail short-circuits, named explicitly)
- Checklist evaluation < 5ms per signal
- Test coverage: every rule has a positive-pass test and a negative-fail test in `tests/test_checklist.py`

**Acceptance criteria:**
- 5 sessions paper-traded under the new checklist
- Win rate within ±5% of pre-migration baseline (we're not losing edge)
- Avg ₹/trade lands in ₹1,000–₹5,000 range (we ARE hitting the goal)
- Rejection telemetry shows clean per-rule attribution (no "uncategorised skip")

**Rollback:** `agents/crew.py` retains a `USE_CHECKLIST = True` flag for the first 2 weeks. Setting it False reverts to the score path. After 2 weeks of clean checklist operation, the flag and score path are deleted in Phase H.

**Files added:** `agents/checklist_engine.py`, `tests/test_checklist.py`.
**Files touched:** `agents/crew.py` (major), `config/thresholds.py` (new central file).

---

### Phase G — Day classifier + threshold review job (~1-2 days)

**Depends on:** Phase F.

**What gets built:**

**G1: Day classifier** — `agents/day_classifier.py`
- 3 states only: `PRESS / SELECTIVE / DEFENSIVE`
- Classifier rules:
  - PRESS: breadth > 55% AND nifty 5-min range expanding AND vol > 1.0× avg
  - DEFENSIVE: breadth < 35% OR nifty change < -0.5% from prev close
  - SELECTIVE: everything else
- Refresh every 15 min
- Touches one knob: which sizing tiers are eligible
  - PRESS: all 3 tiers eligible
  - SELECTIVE: S + A only (skip B)
  - DEFENSIVE: S only, half size, focus list only

**G2: Threshold review job** — `jobs/threshold_review.py`
- Runs Sunday 11:00 IST
- For every threshold in `config/thresholds.py`, computes counterfactual at ±10% values on the past week's signals
- Outputs `docs/threshold_review_YYYY-MM-DD.md`
- **Does NOT auto-tune.** Human reads the report and decides whether to change values.

**Acceptance criteria:**
- 1 week of operation
- Day classifier correctly identifies day-type ≥ 80% of the time (subjective check by operator)
- Threshold review produces a readable report with at least 3 actionable recommendations

**Rollback:** day classifier returns `SELECTIVE` always (= no behaviour change); threshold review is a separate job that has zero hot-path impact.

**Files added:** `agents/day_classifier.py`, `jobs/threshold_review.py`.

---

### Phase H — LLM cold-path infrastructure (~2-3 days)

**Depends on:** Phase G.

**What gets built:**

**H1: Premarket brief** — `jobs/premarket_brief.py`
- Runs 08:30 IST daily
- Single LLM call (Groq) reading: overnight US/Asia close, FII/DII flows, sector buzz, real corporate news from feed
- Outputs `state/focus_list_seed.json` — 12 names with bias, sector context, key levels
- Names get auto-promoted to focus list at 09:00 boot
- Stays valid till 11:00 — names without follow-through get demoted by Phase B/C decay rules

**H2: Weekly review** — `jobs/weekly_review.py` (kept simple — already partly exists in EOD critique)
- Runs Saturday 11:00
- LLM aggregates 5 days of trades + critiques
- Outputs `docs/weekly_review_YYYY-WW.md`
- Recommends: which gates to tighten, which to loosen, which setups to disarm

**Acceptance criteria:**
- 2 weeks of premarket briefs deployed
- ≥ 25% of trades come from premarket-flagged names (proves the brief has predictive value)
- Weekly review report is read and at least 1 recommendation is actioned per week

**Rollback:** disable cron jobs; system continues to work without briefs.

**Files added:** `jobs/premarket_brief.py`, `jobs/weekly_review.py`, `state/focus_list_seed.json`.

---

### Phase I — Cleanup deprecated code (~1 day)

**Depends on:** All previous phases stable for ≥ 2 weeks.

**What gets deleted:**
- `tools/score_tools.py`
- `MIN_SCORE_*` constants in `config/settings.py`
- `SCORE_SIZE_TIERS` in `config/settings.py`
- `HOUR_GATE_NUDGES` in `config/settings.py`
- `CONFLUENCE_MULTIPLIER_*` in `config/settings.py`
- All score-nudge code in `agents/crew.py` (PDH nudge, sector nudge, breadth penalty as score, hist nudge as score, decay)
- `scoring/engine.py` `calculate()` method (kept the file, kept Grade enum, deleted the multiplier logic)
- News LLM call from `_score_signals` path
- `USE_CHECKLIST` flag and the score fallback path
- 4 deleted setups' detector functions
- `tests/test_engine.py` cases for deleted code

**What gets renamed:**
- `_score_signals` → `_check_signals` everywhere
- `final_score` → derived metadata (we keep computing a debug score for telemetry only, not for decisions)

**Acceptance criteria:**
- All tests pass
- 1 session paper-traded after cleanup
- Codebase line count reduces ≥ 20%
- Net new abstractions added in cleanup: zero

**Rollback:** `git revert` the cleanup commit. Cleanup is the LAST step — at this point every replacement is proven, so rollback is unlikely.

---

## 5. Decision matrix — what fires when

| Decision | Made by | Frequency | Latency budget |
|---|---|---|---|
| Premarket focus list | LLM (cold path) | Once daily 08:30 | 60s |
| Day classification | Pure Python rules | Every 15 min | < 100ms |
| Discovery alarms | Pure Python rules | Every 60s | < 10ms/name |
| Focus list promotion/demotion | State machine | Every 5 min | < 50ms |
| Setup detection | Pure Python pattern math | Every 30s focus / 60s broader | < 50ms/name |
| Pending-pullback retest | Pure Python state check | Every tick | < 5ms |
| Entry checklist | 6 binary rules | Per signal | < 5ms |
| Sizing tier | Pure Python qualifiers | Per entry | < 1ms |
| Order placement | Kite API | Per entry | network bound |
| TP/SL trail (single target — no trail under single-target model) | Kite SL-M update | Per tick when applicable | network bound |
| EOD critique | LLM (cold path) | Once daily 15:30 | 30s |
| Weekly review | LLM (cold path) | Once weekly Saturday | 60s |
| Threshold review | Pure Python counterfactual | Once weekly Sunday | 5 minutes |

**No LLM call appears in the < 100ms latency budget rows.** That's the design.

---

## 6. Sequencing — what to do this week

| Day | Activity |
|---|---|
| Day 0 (today) | This document committed. Server-side analyses §3.1 and §3.2 written and run on 280-trade DB. Output → `docs/05_Exit_Distribution_Analysis.md` and `docs/05_Setup_Deletion_Audit.md` |
| Day 1 | Read analyses. Confirm sizing tier values. Phase A code change + deploy |
| Day 2 | Phase A acceptance testing — 10 trades minimum |
| Day 3-5 | Phase B discovery engine build + paper-trade |
| Day 6-7 | Phase C focus list state machine |
| Day 8-9 | Phase D pending-pullback state |
| Day 10 | Phase E setup pruning |
| Day 11-13 | Phase F checklist replaces score |
| Day 14 | Phase G day classifier + threshold review |
| Days 15-21 | Phase H LLM cold-path jobs + 2-week paper validation |
| Day 22+ | Phase I cleanup, then move toward live deployment |

**Hard rule:** before any phase begins, the previous phase must have ≥ 2 sessions of clean operation.

---

## 7. Definition of "done" for the migration

The migration is complete when ALL of the following are true:

1. Single 0–10 score is deleted (or fully replaced by the 6-rule checklist with score retained only as debug telemetry)
2. Setup count is 4 or fewer — proven, not intuited
3. Discovery Engine + dynamic focus list is live and produces ≥ 30% of daily trades
4. Pending-pullback state captures ≥ 1 NBCC-class trade per session avg
5. Sizing pegs trades to ₹1,000–₹5,000 net target band, with verified actual P&L distribution matching
6. Day classifier produces 3 states only and gates only sizing-tier eligibility
7. Weekly threshold review job is running and being acted on
8. Premarket brief is producing focus seed and contributing ≥ 25% of trades
9. EOD self-critique loop continues to update RAG
10. All hot-path decisions are sub-100ms and deterministic
11. All LLM calls are confined to cold paths (08:30 brief, 15:30 critique, weekly review)
12. PROJECT_MEMORY reflects the new architecture, not the old one
13. 2 full weeks of paper trading on the new architecture meet ₹1k–₹5k per-trade goal in ≥ 60% of winning trades
14. Code line count reduced by ≥ 20% from current baseline
15. Operator (Bhagya) trusts the system enough to begin live capital deployment

---

## 8. What this document is NOT

- It is **not** a guarantee of profitability. It's a structural plan to put the system in a position where edge can express itself.
- It is **not** a backtest plan. We're not optimising on historical data; we're building a live execution system that the historical data informs.
- It is **not** a complete code spec. Each phase will produce its own implementation document with file-by-file diffs.
- It is **not** immutable. If a phase produces results that contradict the plan, the plan changes — not the trader's discipline.

---

## 9. Operator checklist — what Bhagya must approve before each phase ships

**Before Phase A:**
- [ ] Read `docs/05_Exit_Distribution_Analysis.md`
- [ ] Approve: single-target vs partials decision
- [ ] Approve: tier sizing values (S/A/B in ₹)
- [ ] Approve: max-loss-per-trade ₹1,500

**Before Phase B:**
- [ ] Confirm Phase A acceptance (≥ 10 trades, P&L in target band)
- [ ] Approve: 6 alarm rules and their thresholds

**Before Phase C:**
- [ ] Confirm Phase B working (≥ 3 alarms/day, no hot-path slowdown)
- [ ] Approve: focus list capacity (15 max, 5 floor) and cooldown (30 min)

**Before Phase D:**
- [ ] Confirm Phase C working
- [ ] Approve: pending-pullback drift cap (2%) and watch window (10 min)

**Before Phase E:**
- [ ] Read `docs/05_Setup_Deletion_Audit.md`
- [ ] Approve which setups die, which survive, which get modified

**Before Phase F:**
- [ ] All previous phases stable for ≥ 2 sessions
- [ ] Approve: the exact 6-rule checklist text
- [ ] Approve: sizing-tier qualifiers (what makes a trade S vs A vs B)

**Before Phase G:**
- [ ] Approve: day classifier rules (breadth %, range expansion, vol thresholds)
- [ ] Approve: weekly threshold review schedule

**Before Phase H:**
- [ ] Approve: premarket brief LLM prompt template
- [ ] Approve: how brief output flows into focus list seeding

**Before Phase I:**
- [ ] All previous phases stable for ≥ 2 weeks
- [ ] Final sign-off on cleanup PR

---

## 10. Reference — current scaffolding

Current files that survive into the new architecture (with role changes):

```
agents/
  crew.py              → orchestrator, kept; _score_signals replaced by _check_signals
  regime_detector.py   → simplified, fed into day_classifier
  discovery_engine.py  ← NEW (Phase B)
  day_classifier.py    ← NEW (Phase G)
  checklist_engine.py  ← NEW (Phase F)

config/
  settings.py          → trimmed (delete score constants in Phase I)
  universe.py          → kept; broader-tier list expanded
  thresholds.py        ← NEW (Phase F) — central threshold registry
  discovery_rules.py   ← NEW (Phase B)

data/
  kite_client.py       → kept; tick-book cache used by discovery
  news_client.py       → kept for cache; LLM calls moved to premarket_brief

jobs/
  eod_job.py           → kept (self-critique loop)
  premarket_brief.py   ← NEW (Phase H)
  weekly_review.py     ← NEW (Phase H)
  threshold_review.py  ← NEW (Phase G)

memory/
  trade_state.py       → kept; new tables for focus_log, pending_log
  chroma_client.py     → kept; RAG continues to power proven-loser veto

scoring/
  engine.py            → DEPRECATED in Phase F, deleted in Phase I

state/                 ← NEW directory for hot-path state
  focus_list.py        ← Phase C
  focus_log.jsonl      ← Phase C
  pending_pullback.py  ← Phase D
  pending_log.jsonl    ← Phase D
  focus_list_seed.json ← Phase H

tests/
  test_engine.py       → trimmed (Phase E + I)
  test_checklist.py    ← NEW (Phase F)
  test_discovery.py    ← NEW (Phase B)
  test_focus_list.py   ← NEW (Phase C)
  test_pending.py      ← NEW (Phase D)

tools/
  pattern_tools.py     → trimmed in Phase E
  volume_tools.py      → kept (working)
  score_tools.py       → DELETED in Phase I

scripts/
  analyze_exit_distribution.py  ← NEW (§3.1)
  setup_audit.py                ← NEW (§3.2)

docs/
  05_Exit_Distribution_Analysis.md   ← §3.1 output
  05_Setup_Deletion_Audit.md         ← §3.2 output
  05_Threshold_Counterfactuals.md    ← §3.3 output (deferred Phase G)
  06_What_Needs_to_Be_Done.md        → SUPERSEDED by this doc
  07_Scalper_Architecture_Migration.md → THIS DOC
```

---

*End of migration plan. Next action: write and run the two pre-flight analyses (§3.1, §3.2) on the server's 280-trade DB.*
