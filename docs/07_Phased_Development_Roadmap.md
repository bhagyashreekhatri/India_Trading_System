# 07 — Phased Development Roadmap

> **Status 2026-04-28:** Phase 0 done; substantial chunks of Phase 1 + Phase 3 also done via the Fix #1–#7 cycle. Remaining Phase 1 items: full Groq token-budget guard (RPM/TPM enforcement), priority queue across call types, degraded-mode end-to-end test. Remaining Phase 3 items: boot reconciliation (INF-05), every-60 s reconciler (RECON-02), drawdown-aware sizing tiers (RSK-13), broker-side reconciliation against SQLite. See `PROJECT_MEMORY.md` for the deployment table.


> Six phases (plus Phase 0 assessment). Each phase has scope, deliverables, success criteria, and an exit gate. **Do not move to the next phase until the gate is met.** This is non-negotiable — phases exist precisely so we don't ship instability disguised as features.

---

## Phase 0 — Assessment & Learning Mode Setup
**Duration target:** 2–3 days

### Scope
- Lock the source of truth on what is actually deployed today.
- Resolve the CrewAI-vs-LangGraph question.
- Reconcile the build-state list against the real repo.
- Ingest the 151-trade log and complete file 04.
- Stand up the *learning-mode harness* — a sandboxed environment where new weights, prompts, and rules can be evaluated against historical trades and live paper, with no order-placement side effects.

### Deliverables
- Final, verified version of file 02 (no `[VERIFY]` left).
- Complete file 03 Section B (real findings).
- Complete file 04 (real numbers, real charts).
- Decision recorded in `CHANGELOG.md`: orchestrator choice + reasoning.
- Learning-mode harness skeleton: ability to replay any past trade through any candidate scoring config and produce a comparison report.

### Success criteria / Phase 0 gate
- Every `[FILL]` in files 02, 03, 04 is closed.
- A single, brutal one-page summary of "what worked, what didn't, what's broken" is written and agreed.
- Harness can replay 5 sample trades end-to-end without touching Kite.

---

## Phase 1 — God-Level Scalper Reasoning Engine + Groq Optimization
**Duration target:** 1.5–2 weeks

### Scope
- Implement the **GroqClient singleton** with semaphore, token-bucket budget, tiered model router, retry-with-jitter, and `Retry-After` honouring (file 05 §9, §11).
- Replace ad-hoc LLM calls across agents with **batched** flows (file 05 §5).
- Stand up **LRU + ChromaDB semantic cache** (file 05 §6).
- Implement the **degraded-mode** path and prove it works (file 05 §10).
- Refactor the reasoning prompts to **think like a god-level scalper** (file 08): tape narrative, mental-model phrasing, vetoes, confidence scoring.
- Telemetry: RPM/TPM/RPD/TPD logged per minute; dashboard widget live.

### Deliverables
- `infra/groq_client.py` with the singleton + tests.
- `infra/groq_cache.py` (LRU + Chroma).
- `infra/budget.py` (rate limiter + priority queue).
- Refactored agents — every Groq call site documented.
- New prompt files in `prompts/` with versioning.
- Degraded-mode tested under simulated outage.
- Replay load-test report on worst-case 09:20 minute.

### Success criteria / Phase 1 gate
- **Zero 429s** in a 5-day paper run.
- Worst-minute Groq RPM utilisation **< 70 %**.
- Cache hit ratio **≥ 30 %** at steady state (will rise in Phase 4 with semantic cache fully populated).
- Degraded mode entered, ran for 5 min, recovered cleanly — verified by injection test.
- LLM-call audit shows **no per-stock fan-out** anywhere.

---

## Phase 2 — Advanced Signal Generation & Market Context
**Duration target:** 1.5–2 weeks

### Scope
- Upgrade signal quality (file 06 §4 — SIG-01 through SIG-10).
- Time-of-day-relative RVOL.
- Self-computed VWAP from tick stream.
- Dual-axis relative strength (sector + Nifty).
- Breadth indicators (advance/decline, % above VWAP, % above 5-EMA).
- Cross-asset regime input (Nifty / Bank Nifty / VIX / DXY / crude).
- Volatility-regime modifier (VIX percentile rank).
- Open-range filter for the first 10 minutes.
- Expiry-day regime mask.
- Universe auto-refresh (weekly job).
- Order-flow proxy from top-of-book depth.

### Deliverables
- `signals/rvol.py`, `signals/vwap.py`, `signals/rs.py`, `signals/breadth.py`, `signals/orderflow.py`.
- `signals/regime_features.py` aggregating cross-asset.
- Universe weekly refresh job in `jobs/`.
- Expanded scoring engine inputs (no breaking API change for existing agents).

### Success criteria / Phase 2 gate
- On replay against the 151-trade log, **upgraded signals improve win-rate by ≥ 3 pp** in the top-grade buckets, or — worst case — match it without increasing trade count.
- All new signal modules have ≥ 90 % unit-test coverage.
- No regression in Phase 1 gate metrics (429s, RPM, cache, degraded mode).

---

## Phase 3 — Professional Risk & Money Management
**Duration target:** 1.5–2 weeks

### Scope
- Implement file 06 §5 (RSK-01 through RSK-13).
- Sizing off the broker's tick-rounded stop, not idealised.
- Pre-allocator sector-cap check.
- Daily 2.5 % kill-switch + 7-loss cool-down.
- Slippage model in cost calc; net-of-cost target_R.
- Conservative tick-rounding on stops.
- **Broker-side SL-M orders** for every position (Python timers are not stops).
- Idempotent order placement with client_order_id.
- Margin / available-funds pre-check.
- 15:15 / 15:18 / 15:20 cascading auto-square.
- Boot-time + every-60s position reconciler.
- Drawdown-aware sizing tiers.

### Deliverables
- `risk/sizing.py`, `risk/limits.py`, `risk/kill_switch.py`.
- `execution/orders.py` upgraded with idempotency.
- `execution/reconciler.py`.
- Updated `agents/allocator_agent.py` and `agents/position_agent.py`.

### Success criteria / Phase 3 gate
- Chaos test: kill the agent mid-fill 10 times → zero orphan positions, zero double orders.
- Sector cap test: synthetic burst of 6 candidates in same sector → no more than allowed.
- Kill-switch test: daily P&L manually pushed to −2.5 % → flat all + freeze in < 5 s.
- Square-off test: 15:14 has 5 open positions → all flat by 15:18.

---

## Phase 4 — Continuous Learning & Adaptation System
**Duration target:** 2–3 weeks

### Scope
- File 09 in full.
- EOD job writes full reasoning chains.
- Per-trade self-critique using T3 model, batched, off-hours.
- Weekly failure-pattern clustering.
- Auto-proposed regime × setup multiplier table; human-approved; paper-validated; rolled out via A/B.
- Symbol blacklist / watch-list maintenance.
- Time-of-day mask learned, not hard-coded.
- Score calibration plot, dashboard tile.
- Drift detector — rolling-30 win-rate floor; auto-pause + alert.

### Deliverables
- `jobs/eod_job.py` complete.
- `learning/critique.py`, `learning/cluster.py`, `learning/proposer.py`, `learning/ab.py`, `learning/drift.py`.
- Dashboard analytics tab.
- Weekly review markdown auto-generated to `docs/weekly/YYYY-WW.md`.

### Success criteria / Phase 4 gate
- A full proposed-change cycle executed end-to-end (proposed → approved → A/B paper → rolled out or rejected).
- 4 weeks of weekly auto-reports generated without human edits to the pipeline.
- Drift detector verified by injecting a synthetic losing streak — auto-pause triggers.

---

## Phase 5 — Robust Execution & Monitoring
**Duration target:** 1.5–2 weeks

### Scope
- LIMIT-with-chase entry logic.
- MARKET-only-on-emergency rule.
- Partial exit at 1R + trail.
- Trail to 1-min higher-low / lower-high.
- Time-stop on no-movement.
- WebSocket ticks for entries / exits (replace REST polling).
- Order-status reconciler — cancel stale orders.
- Full dashboard build (live + analytics + Groq widget + degraded banner + trade-explanation expander).
- Crash-recovery test, integration test, full backtest replay of 151.

### Deliverables
- `execution/entry.py`, `execution/exit.py`, `execution/trail.py`.
- `data/kite_ws.py` WebSocket client.
- Dashboard fully live.
- Test suites green.

### Success criteria / Phase 5 gate
- Mean entry slippage ≤ 0.05 %; p95 ≤ 0.15 %.
- Replay of the 151 trades through Phase-5 stack reproduces or improves on net P&L per file 04.
- Crash-recovery: 10 random kills, zero orphans, zero double orders.
- Dashboard usable end-to-end without a single agent restart.

---

## Phase 6 — Optimization & Live Trading Readiness
**Duration target:** 2–3 weeks (paper, observation-heavy)

### Scope
- 4 consecutive paper weeks under "frozen" code (only weight-tuning via approved A/B).
- Final cost-model validation against tiny live test orders (1 share each on 5 trades) to measure actual slippage.
- Operator runbook written and rehearsed.
- One-click flat-and-freeze rehearsed.
- Final live-readiness gate (file 06 §12).

### Deliverables
- `RUNBOOK.md`.
- 4 weekly review reports auto-generated, all meeting targets.
- Live-mode toggle behind a typed-confirmation, not a config flag.

### Success criteria / Phase 6 gate (LIVE TRADING GATE)
- All file 06 §12 boxes ticked.
- Owner explicitly signs off on each gate item.
- First live week capped at 25 % of paper capital. Re-evaluate weekly.

---

## Cross-cutting expectations across all phases

- Every PR carries unit tests for changes and a one-line entry in `CHANGELOG.md`.
- Every weight, threshold, and prompt change is logged with date, reason, before/after metrics.
- Phase gates are evaluated **on data, not vibes** — replay results, paper results, telemetry numbers.
- Files 01–09 are kept current. If a file is contradicted by a decision, the file is updated.
