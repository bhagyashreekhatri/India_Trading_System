# 06 — What Needs to Be Done

> **Status update 2026-04-28 — Fixes 1–7 deployed.** See `PROJECT_MEMORY.md` for the deployment table. Items closed below are marked `✅`.
>
> Closed in this cycle:
> - INF-03 (timezone single source) — partial: `_now_iso_ist`, `_to_ist`, `_entry_dt_aware` in place. Naive `datetime.now()` removed from `state.open_position`.
> - INF-08 (crash-safe cooldown) — implicit: cooldown reads from SQLite which now stores IST-aware times.
> - GRQ-06 (tenacity retry with Retry-After) ✅ Fix #4
> - GRQ-09 (token budget pre-check) — partial: `timeout=10s` and JSON mode in place; explicit token-budget enforcement still TODO.
> - RSK-03 (daily-loss kill switch 2.5 %) ✅ Fix #3
> - RSK-08 (broker-side SL-M) ✅ Fix #6
> - RSK-07 (tick-rounded SL) ✅ Fix #7
> - SCAN/Universe filter switch to turnover ✅ Fix #5
> - Multi-setup confluence (was a "next-week priority" in PROJECT_MEMORY) ✅ Fix #5
> - Overnight position veto ✅ Fix #3
> - sl_hit / sl_trail_hit distinction ✅ Fix #3
>
> Still open and high-priority:
> - **INF-05 boot reconciliation with broker** (LIVE-READINESS GATE — biggest remaining risk)
> - SHORT-01 add SHORT-side detectors (half the alpha unreachable)
> - RECON-02 every-60s position reconciler with broker truth
> - DEAD-01 remove dead `agents/*_agent.py` + `tools/{kite,news,chroma}_tools.py`; drop `crewai`/`langchain`
> - DASH-03 Groq budget widget (counters already in `NewsClient.stats`)
> - KILL-LIVE-01 daily-loss kill switch tested in production (force synthetic loss)
>
> **Done in this cycle (20 fixes total):**
> - ✅ Fix #1–#20 + dashboard TZ fix (see PROJECT_MEMORY.md table)
> - ✅ 8 setups (was 6) — added TREND_PULLBACK + INSIDE_BAR_BREAK
> - ✅ Daily-profit lockout (mirror of kill switch)
> - ✅ Honest live fill prices (no more 20-min stale entries)
> - ✅ Persisted regime column for accurate analytics
> - ✅ Sector flow gating (top/weak sector boost/penalty)
> - ✅ Paper slippage simulation (paper P&L now realistic)
> - ✅ PDH break bonus (entry > prior-day high → +0.3 score nudge)
> - ✅ NewsAPI company-name aliases (RELIANCE now matches "Reliance Industries")
> - ✅ Leaders watchlist — relaxed 1.5% proximity for strong movers
> - ✅ 15-min HTF trend filter — vetoes counter-trend longs


> Comprehensive backlog of gaps, fixes, and improvements required to take this from "ran a 151-trade paper week" to "god-level scalper, live-ready". Each item has a priority (P0–P3), an effort estimate, and a target phase. The phase mapping aligns with file 07.

Priority key:
- **P0** — blocker (live trading not allowed without it)
- **P1** — material profitability or stability impact
- **P2** — measurable improvement
- **P3** — polish / nice-to-have

Effort key: **S** = < 1 day, **M** = 1–3 days, **L** = > 3 days.

---

## 1. Stability & infrastructure (P0)

| ID | Item | Effort | Phase |
|---|---|---|---|
| INF-01 | Resolve **CrewAI vs LangGraph** ambiguity. Pick one orchestrator. Document why. | S | 0 |
| INF-02 | Reconcile build-state: which of the 20 pending modules are actually live? | S | 0 |
| INF-03 | Single source of truth for **timezone** — `Asia/Kolkata` everywhere. No naive datetimes. | S | 0 |
| INF-04 | **Config validation on boot** — fail fast if `.env` missing keys, holiday calendar absent, Kite token expired. | S | 0 |
| INF-05 | **Boot reconciliation** — read open positions from Kite, compare to SQLite, repair. | M | 1 |
| INF-06 | **Watchdog** — alert if a tick takes > 60 s; kill stuck pipeline. | S | 1 |
| INF-07 | **Structured JSON logs** with `trace_id` per signal threading through every agent. | M | 1 |
| INF-08 | **Crash-safe cool-down** — persisted, not in-memory. | S | 1 |
| INF-09 | **Daily Kite token refresh** automation (with manual fallback). | M | 1 |
| INF-10 | Deterministic random seeds for testing. | S | 0 |

## 2. Groq rate-limit defence (P0) — see file 05

| ID | Item | Effort | Phase |
|---|---|---|---|
| GRQ-01 | Audit every existing call to Groq — list call sites, frequencies, expected RPM. | S | 1 |
| GRQ-02 | Implement **GroqClient singleton** with semaphore + token-bucket budgeter. | M | 1 |
| GRQ-03 | Tiered model router (T0/T1/T2/T3). | M | 1 |
| GRQ-04 | **Batch news sentiment** — one call per tick for all new headlines. | S | 1 |
| GRQ-05 | **Batch scoring rationale** — single call for top-K candidates. | M | 1 |
| GRQ-06 | Tenacity retry with `Retry-After` honouring. | S | 1 |
| GRQ-07 | LRU + ChromaDB **semantic cache** for repeated rationales. | M | 1 |
| GRQ-08 | **Degraded mode** path (no Groq → deterministic + half-size). Tested. | M | 1 |
| GRQ-09 | Token-budget enforcement per call type (pre-call tokeniser check). | S | 1 |
| GRQ-10 | RPM/TPM/RPD/TPD telemetry → dashboard widget. | M | 1 |
| GRQ-11 | Priority queue (regime > position-mgr > scoring > sentiment > sanity). | M | 1 |
| GRQ-12 | Replay load-test: simulate worst-case 09:20 minute — must stay < 70 % RPM. | M | 1 |

## 3. Reasoning engine — making it think like a god-level scalper (P0/P1)

| ID | Item | Effort | Phase |
|---|---|---|---|
| RSN-01 | **Pre-trade sanity LLM call** with vetoes (gap > 2 %, halted, near circuit, news embargo). | M | 1 |
| RSN-02 | **Setup conflict adjudication** — only when deterministic detectors disagree. | M | 1 |
| RSN-03 | **Tape narrative**: 1-line summary of the last 15 min of price/volume per candidate, fed into rationale. | M | 1 |
| RSN-04 | **Mental-model prompts** aligned with file 08 strategies — no generic "you are a stock analyst" boilerplate. | S | 1 |
| RSN-05 | Force JSON-mode + Pydantic validation on every structured call. | S | 1 |
| RSN-06 | **Self-confidence score** in every LLM output, used to gate escalation to T2. | S | 1 |

## 4. Signal & market-context quality (P1)

| ID | Item | Effort | Phase |
|---|---|---|---|
| SIG-01 | **RVOL must be time-of-day-relative**, not full-day. | S | 2 |
| SIG-02 | **VWAP from agent's own tick stream**, not Kite snapshot. | M | 2 |
| SIG-03 | **Relative strength vs sector AND vs Nifty** — keep the worse of the two. | S | 2 |
| SIG-04 | **Breadth indicator** (advance/decline, % stocks > VWAP, % stocks > 5-EMA). | M | 2 |
| SIG-05 | **Cross-asset context** — Nifty / Bank Nifty / India VIX / DXY / crude — into regime input. | M | 2 |
| SIG-06 | **Volatility regime** (VIX percentile rank over 30 d) into setup multiplier. | S | 2 |
| SIG-07 | **Open-range filter** — no 09:20–09:30 entries unless the open range is > X bps and price closed beyond it. | S | 2 |
| SIG-08 | **Expiry-day mask** — Tue / Thu = increase chop weight. | S | 2 |
| SIG-09 | **Universe weekly refresh** — recompute liquidity, ATR, ASM/GSM membership. | M | 2 |
| SIG-10 | **Order-flow proxy** — top-of-book imbalance from Kite quote depth. | M | 2 |

## 5. Risk & money management (P0)

| ID | Item | Effort | Phase |
|---|---|---|---|
| RSK-01 | **1% per trade** sizing computed off broker's actual tick-rounded stop, not idealised stop. | S | 3 |
| RSK-02 | **Sector cap pre-check** before allocator commits. | S | 3 |
| RSK-03 | **Daily loss kill-switch** at 2.5 % — flat all + freeze entries. | S | 3 |
| RSK-04 | **7-loss cool-down** — auto-pause 60 min after 7 consecutive losses. | S | 3 |
| RSK-05 | **Slippage model** in the cost calc — not the optimistic "fill at signal". | M | 3 |
| RSK-06 | **Net-of-cost target_R** — current R math may be gross-of-cost. | S | 3 |
| RSK-07 | **Stop tick-rounded conservatively** (LONG: down, SHORT: up). | S | 3 |
| RSK-08 | **Broker-side SL-M order** placement (no Python-side stops). | M | 3 |
| RSK-09 | **Idempotent order placement** with client_order_id deduplication. | M | 3 |
| RSK-10 | **Margin / available-funds check** before sizing. | S | 3 |
| RSK-11 | **Auto square-off at 15:15** with 15:18 second pass and 15:20 emergency MARKET. | M | 3 |
| RSK-12 | **Position reconciler** every 60 s — broker truth ≠ SQLite → repair. | M | 3 |
| RSK-13 | **Drawdown-aware sizing**: > 1 % daily drawdown → 75 % size; > 1.5 % → 50 % size. | S | 3 |

## 6. Learning loop & adaptation (P1) — see file 09

| ID | Item | Effort | Phase |
|---|---|---|---|
| LRN-01 | EOD job writes **full reasoning chain** of every closed trade to `trade_memory`. | M | 4 |
| LRN-02 | **Self-critique per trade** at EOD (T3 model, batched). | M | 4 |
| LRN-03 | **Failure-pattern clustering** weekly — k-means on losing-trade feature vectors. | M | 4 |
| LRN-04 | **Regime × setup multiplier proposal** — auto-suggest, human-approve, paper-validate. | M | 4 |
| LRN-05 | **Symbol blacklist / watch-list** maintained from rolling 30-trade win-rate. | S | 4 |
| LRN-06 | **Time-of-day mask** per setup, learned not hard-coded. | M | 4 |
| LRN-07 | **A/B framework** for any change — half-universe runs new weights, half runs old, decide on rolling 30 trades. | L | 4 |
| LRN-08 | **Score calibration plot** in dashboard — score vs realised P&L. | M | 4 |
| LRN-09 | **Drift detection** — if rolling 30-trade win-rate drops below threshold, auto-pause and alert. | M | 4 |

## 7. Execution quality (P1)

| ID | Item | Effort | Phase |
|---|---|---|---|
| EXE-01 | **LIMIT entries with chase logic** — limit at signal, re-quote up to 3 times within 0.2 % then abandon. | M | 5 |
| EXE-02 | **Market entries forbidden** except emergency exit. | S | 5 |
| EXE-03 | **Partial-exit logic** — book half at 1R, trail rest. | M | 5 |
| EXE-04 | **Trail rule** — trail to 1-min higher-low (LONG) or lower-high (SHORT). | M | 5 |
| EXE-05 | **Time-stop** — exit if no movement after 15 min (configurable). | S | 5 |
| EXE-06 | **WebSocket ticks** instead of REST polling for entry / exit triggers. | L | 5 |
| EXE-07 | **Order-status reconciliation** — open orders not filled in 30 s → cancel. | S | 5 |

## 8. Data pipeline (P1)

| ID | Item | Effort | Phase |
|---|---|---|---|
| DAT-01 | Cache 1-min historical candles per symbol per session. | S | 2 |
| DAT-02 | Detect missing candles (esp. first bar) and gracefully skip. | S | 2 |
| DAT-03 | **Holiday calendar** loaded from NSE source on boot. | S | 0 |
| DAT-04 | **Half-day calendar** support (Diwali Muhurat etc.). | S | 0 |
| DAT-05 | NewsAPI dedup + recency filter. | S | 1 |
| DAT-06 | Symbol-name aliases for news matching (e.g., "Reliance Industries" ↔ "RELIANCE"). | S | 1 |

## 9. Dashboard & observability (P2)

| ID | Item | Effort | Phase |
|---|---|---|---|
| DSH-01 | **Live tab**: open positions, P&L, day's trades, regime, VIX, kill-switch state. | M | 5 |
| DSH-02 | **Analytics tab**: trade-log slices from file 04, score calibration, setup heat-map. | M | 5 |
| DSH-03 | **Groq budget widget** — RPM / TPM / RPD utilisation, cache hit ratio, retry counts. | M | 1 |
| DSH-04 | **Degraded-mode banner**. | S | 1 |
| DSH-05 | **Trade explanation expander** — show the LLM rationale + score components per trade. | M | 5 |
| DSH-06 | Read-only enforcement audited — no Streamlit `button → place order` paths. | S | 5 |

## 10. Testing (P1)

| ID | Item | Effort | Phase |
|---|---|---|---|
| TST-01 | Unit tests for every tool (mocked I/O). | L | 1 |
| TST-02 | Integration test: full tick on synthetic market data. | L | 5 |
| TST-03 | Load test: worst-case 09:20 minute against rate-limit budget. | M | 1 |
| TST-04 | Crash-recovery test: kill mid-tick, restart, no double order, no orphan position. | M | 5 |
| TST-05 | Replay backtest harness on the 151 trades — does the rebuilt agent reproduce them? | L | 4 |

## 11. Documentation (P2)

| ID | Item | Effort | Phase |
|---|---|---|---|
| DOC-01 | Keep these 9 docs evergreen — every architectural decision logged here. | ongoing | all |
| DOC-02 | `RUNBOOK.md` — operator playbook (how to start, stop, recover, switch to live). | M | 6 |
| DOC-03 | `CHANGELOG.md` — every weight change, every model swap. | ongoing | all |

## 12. Live-readiness gate (Phase 6)

Hard requirements before flipping `PAPER_TRADING = False`:

- [ ] 4 consecutive paper weeks meeting profit-factor and drawdown targets.
- [ ] Zero unhandled crashes in last 4 weeks.
- [ ] Zero Groq 429 errors in last 4 weeks.
- [ ] Slippage model validated against actual fills on a small live test.
- [ ] Boot reconciliation, watchdog, kill-switch, degraded-mode all individually tested.
- [ ] Operator runbook written and rehearsed.
- [ ] Capital cap enforced at code level, not just config.
- [ ] One-click flat-and-freeze available from dashboard.
