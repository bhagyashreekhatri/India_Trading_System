# 02 — Current Implementation Summary

> Verified against the actual repo on disk. All `[VERIFY]` blocks resolved. Differences from the original skill memory are flagged with **CORRECTION**.
>
> **Status 2026-04-28:** Fixes 1–7 deployed. The architecture below describes the *current* state — TZ-aware writes, score-calibration retuned, daily-loss kill switch, overnight veto, `sl_hit` vs `sl_trail_hit`, hardened Groq path with persistent cache, multi-setup confluence, turnover-based scanner, broker-side SL-M, tick-size rounding. See `PROJECT_MEMORY.md` for the deployment table.

---

## 1. Verified architecture

The system is a **single-process, pure-Python orchestrator** (`agents/crew.py::TradingCrew`) that runs an entry-and-management loop every 3 minutes during market hours. There is no CrewAI / LangGraph runtime in the live path — both are in `requirements.txt` and the legacy `agents/*.py` files import them, but those legacy files are **dead code** (not imported by `main.py` or `crew.py`).

```
                    main.py  (3-min scheduler + 60s pre-market polling)
                          │
                          ▼
                ┌─────────────────────────────┐
                │  TradingCrew (pure Python)  │
                └─────────────────────────────┘
                          │
                          ▼
   _manage_positions()  (every tick — SL / TP1 / TP2 / trail / EOD)
                          │
                          ▼
   _ok_to_trade()  (time gate: 09:20 → 14:45, no weekend, midday note)
                          │
                          ▼
   _detect_regime()      (every 5 ticks ≈ 15 min — Nifty + BankNifty + VWAP)
   _detect_breadth()     (every 5 ticks — top-50 % positive on day)
                          │
                          ▼
   _scan_market()        (FULL_UNIVERSE batch quote → top 60 by |chg|)
   _reorder_by_sector()  (promote stocks in top-3 sectors)
                          │
                          ▼
   _detect_setups()      (per stock: pattern_tools._detect_all_setups)
                          │
                          ▼
   _score_signals()      (engine.calculate per setup;
                          news.get_news_for_symbol → Groq sentiment;
                          per-setup-type score floor; midday +0.5;
                          consec-loss conservative threshold)
                          │
                          ▼
   _allocate()           (sizing + sector cap + cooldown + proximity → enter)
                          │
                          ▼
                ┌────────────────────────┐    ┌────────────────────────┐
                │ TradeStateManager      │    │ ChromaMemory           │
                │ SQLite (positions,     │    │ (3 collections,        │
                │ watchlist,             │    │  signal_patterns       │
                │ session_stats)         │    │  written on every exit)│
                └────────────────────────┘    └────────────────────────┘
                          │                              │
                          ▼                              ▼
                   Telegram alerts              Streamlit dashboard
                   (entry/TP1/exit/             (live + analytics +
                    trail/breadth/EOD/          learning lab tabs)
                    health/kill/premarket)
```

## 2. Tech stack — verified

| Layer | Tool | Version (locked) | Notes |
|---|---|---|---|
| Python | CPython | 3.11 (per `venv/pyvenv.cfg`) | |
| Orchestrator | **Pure Python `TradingCrew`** | — | **CORRECTION**: skill memory said CrewAI; user prompt said LangGraph. *Both wrong.* `PROJECT_MEMORY.md` confirms "Pure Python orchestration — TradingCrew class (NOT CrewAI — removed)". |
| LLM provider | **Groq, `llama-3.3-70b-versatile`** | groq 0.4.2 | Used **only** in `data/news_client.py::_score_sentiment_with_llm`. No other Groq call site in the live path. |
| LangChain | langchain 0.1.20 | | Imported only by legacy `tools/*` `@tool` decorators which are not used by `crew.py`. **Effectively dead** in the runtime path. |
| CrewAI | crewai 0.28.0 | | Imported only by legacy `agents/{scanner,regime,setup,volume_rs,news,scoring,allocator,position}_agent.py`. **Dead code.** |
| Vector memory | ChromaDB | 0.4.24 (not 0.4.22) | 3 collections: `news_signals`, `signal_patterns`, `regime_context` |
| Broker | Kite Connect | 5.0.1 | Both data and orders. `PAPER_TRADING=True` short-circuits orders to paper IDs. |
| News | NewsAPI | 0.2.7 (newsapi-python) | Daily-cached per symbol; rate-limit-aware (sets internal flag once 429 hit). |
| Dashboard | Streamlit | 1.31.1 + plotly + streamlit-autorefresh | 3 tabs: Live, Analytics, Learning Lab. |
| State DB | SQLite | bundled | `trade_state.db` |
| Alerts | Telegram Bot API | requests-based | 9 alert helpers. |
| Misc | pydantic 2.5.3, ta 0.11.0, pandas 2.1.4, numpy 1.26.3, sqlalchemy 2.0.30, pytz 2024.1, schedule 1.2.1, httpx <0.28 | | `sqlalchemy` listed but never imported. |

## 3. Modules — built / dead / missing

### Live and active ✅

| File | LOC | Role |
|---|---|---|
| `main.py` | 443 | Scheduler, health check, premarket runner, EOD trigger |
| `agents/crew.py` | 938 | The whole orchestrator. Single source of truth for the loop. |
| `data/kite_client.py` | 282 | Quotes, candles, VWAP, spread, paper/live orders, SL-M |
| `data/news_client.py` | 176 | NewsAPI fetch + Groq sentiment + LLM/rule blend |
| `memory/trade_state.py` | 435 | SQLite ORM-light: positions, watchlist, session_stats, summaries |
| `memory/chroma_client.py` | 205 | 3 collections; news / signal-outcome / regime CRUD |
| `scoring/engine.py` | 428 | Pure scoring math + ScoreComponents + grade thresholds |
| `tests/test_engine.py` | 289 | 11 unit tests for engine (all pass per project memory) |
| `config/settings.py` | 94 | Every threshold and toggle |
| `config/universe.py` | 184 | 150 deduped stocks, sector map, sector leaders helpers |
| `tools/pattern_tools.py` | 473 | Setup detectors (`_detect_all_setups`) + ORB + gap analysis |
| `tools/volume_tools.py` | 351 | Volume / RS / breadth / sector strength (used internally by crew) |
| `tools/score_tools.py` | 468 | LangChain-tool-shaped wrappers — **but only `_calc_quantity` etc. are used live; all `@tool`-decorated entry points are unused.** |
| `tools/telegram_tools.py` | 237 | 9 alert functions (entry, TP1, exit, trail, breadth, EOD, kill, premarket, health) |
| `tools/check_learning.py` | 173 | Manual stand-alone summary script (dev tool) |
| `tools/force_exit.py` | 73 | Manual stand-alone exit-by-symbol script (dev tool) |
| `dashboard/app.py` | 311 | Streamlit entry, sidebar controls, tab dispatch |
| `dashboard/live_tab.py` | 356 | Live positions + signals + watchlist |
| `dashboard/analytics_tab.py` | 265 | Win-rate by setup/grade + trade log |
| `dashboard/learning_tab.py` | 381 | Learning Lab: setup matrix, grade accuracy, time heatmap, equity curve |
| `jobs/eod_job.py` | 226 | EOD outcome storage + Telegram report + Friday weekly scorecard |
| `kite_login.py` | 189 | Morning OAuth → access token → optional `--push` to server |
| `deploy/setup_server.sh` | — | One-time DigitalOcean droplet provisioning |
| `deploy/trading-system.service` | — | systemd unit (User=root, WorkingDirectory=/root/india_trading) |

### Dead code ⚠️ (in repo, not imported by runtime)

| File | LOC | Notes |
|---|---|---|
| `agents/scanner_agent.py` | 62 | CrewAI Agent factory + task template. Not imported. |
| `agents/regime_agent.py` | 66 | Same. |
| `agents/setup_agent.py` | 69 | Same. |
| `agents/volume_rs_agent.py` | 64 | Same. |
| `agents/news_agent.py` | 63 | Same. |
| `agents/scoring_agent.py` | 89 | Same. |
| `agents/allocator_agent.py` | 83 | Same. |
| `agents/position_agent.py` | 91 | Same. |
| `tools/kite_tools.py` | 58 | LangChain `@tool` wrappers. The underlying singletons / functions in `data/kite_client.py` are used; these wrappers are not. |
| `tools/news_tools.py` | 60 | Same — `data/news_client.py` is used directly. |
| `tools/chroma_tools.py` | 35 | Same — `memory/chroma_client.py` is used directly. |

These ~680 LOC of dead code force `crewai==0.28.0` and `langchain==0.1.20` into the dependency graph. They are also a continuing source of **confusion** for anyone reading the repo (skill memory believed them to be live).

### Missing (nothing built, but referenced as roadmap items in PROJECT_MEMORY)

- Multi-setup confluence scoring (next-week priority #1).
- PDH/PDL levels.
- Multi-timeframe (15-min) confirmation.
- Inside-bar 8th setup.
- Nifty PCR data into regime.
- ChromaDB **read-side RAG** loop into scoring (writes happen; queries don't gate scoring).

## 4. Loop cadence — verified

| Cadence | What runs | Where |
|---|---|---|
| Every tick (~3 min) | `_manage_positions` (always first), then `_ok_to_trade` gate, then scan/regime/breadth/detect/score/allocate | `main.py` → `TradingCrew.run_tick` |
| Every 5 ticks (~15 min) | Regime + breadth re-detection (cached between) | `_detect_regime`, `_detect_breadth` |
| 09:00–09:15 (once) | Pre-market gap analysis on top 50 names + Telegram report | `main.py::run_premarket` |
| 15:00 onwards (on tick) | EOD force-close all open positions | `_manage_positions` (line 709) |
| 15:35–15:50 (once) | EOD job: write outcomes to Chroma, send Telegram, Friday scorecard | `jobs/eod_job.py::run_eod_job` |
| Weekend / off-hours | Sleep 1 h | `main.py` while-loop |

## 5. Scoring formula — verified against `engine.py`

Confirmed formula:

```
Raw = setup_quality(0–3) + volume_strength(0–2) + market_alignment(0–2)
    + relative_strength(0–2) + news_sentiment(−0.5 … +1)
Final = clamp(Raw × Regime_Multiplier, 0, 10)
```

Verified:

- News with `has_news=False` returns **0.5 baseline** — so every stock without news gets +0.5 free into Raw. This is a known design choice but inflates the floor across the universe.
- News penalty path returns **−0.5** on `llm_score < 0.3`.
- Choppy-regime penalty inside `_score_market_alignment` is an extra `−0.5` (separate from the 0.6 / 1.2 multiplier on the Raw).
- Hard reject on `liquidity_pass=False` (returns C-grade with `is_valid=False` regardless of other scores).
- Proximity check at **0.7 %** — matches `PROXIMITY_MAX_PCT`.

### Setup enum vs setup count — **CORRECTION**

`PROJECT_MEMORY.md` claims **7 setups** (including ORB). The `SetupType` enum has **6** members — ORB is missing. ORB signals are produced by `tools/pattern_tools._detect_orb_breakout` but **labelled as `SetupType.MOMENTUM_BREAKOUT`** before reaching the engine (line 187 of `pattern_tools.py`). This means ORB inherits MOMENTUM_BREAKOUT regime multipliers and is invisible in setup-level analytics. Ranges from "design choice" to "silent bug" depending on how you read it.

### Regime multipliers — verified against `engine.py`

|                   | TRENDING | CHOPPY | RECOVERING | EVENT |
|---|---|---|---|---|
| momentum_breakout | 1.2 | 0.6 | 1.0 | 0.7 |
| vwap_pullback     | 1.0 | 1.2 | 1.0 | 0.7 |
| vwap_reclaim      | 1.0 | 1.1 | 1.4 | 0.7 |
| failed_breakdown  | 1.0 | 1.1 | 1.1 | 0.7 |
| range_breakout    | 1.1 | 0.7 | 0.9 | 0.7 |
| recovery_setup    | 0.8 | 0.8 | 1.3 | 0.7 |

Match the table in `PROJECT_MEMORY.md`.

### Grades — verified

`A++ ≥ 9` `A+ ≥ 8` `A ≥ 7` `B ≥ 5` `C < 5`. Matches.

## 6. Risk parameters — verified against `config/settings.py`

| Parameter | Doc / memory value | **Actual code value** | Note |
|---|---|---|---|
| `PAPER_TRADING` | True | **True** ✅ | |
| `CAPITAL` | ₹2,00,000 | **₹15,00,000** | **CORRECTION**: PROJECT_MEMORY says ₹2 L; settings says ₹15 L. Risk-per-trade therefore = ₹15,000 not ₹2,000. |
| `MAX_POSITIONS` | 10 | **10** ✅ | Skill memory said 5, PROJECT_MEMORY says 10. Code = 10. |
| `MAX_SECTOR_EXPOSURE` | 30 % | **30 %** (`MAX_SECTOR_EXPOSURE=0.30`) | But not enforced; see file 03 |
| `MAX_SAME_SECTOR_POSITIONS` | — | **3** | This is what's actually enforced (count, not value) |
| `RISK_PER_TRADE_PCT` | 1 % | **1 %** ✅ | |
| `MAX_POSITION_VALUE_PCT` | — | **20 %** | Hard cap per position |
| `TARGET_R1` / `TARGET_R2` | 1.0 / 2.0 | **1.0 / 2.0** ✅ | |
| `TRAILING_ATR_MULTIPLIER` | 0.5 | **0.5** ✅ | After TP1 hit |
| `BREAKEVEN_AFTER_TP1` | True | **True** ✅ | But SL is moved to entry inside `_partial_exit_tp1` regardless of this flag |
| `SCAN_INTERVAL_MIN` | 3 | **3** ✅ | Faster than the 5 min skill memory implied |
| `MIN_SCORE_ENTRY` | 7.0 | **7.0** ✅ | Grade A floor |
| `MIN_SCORE_ENTRY_CONSERVATIVE` | 8.0 | **8.0** ✅ | Used after 3 consec losses or in midday |
| `MIN_SCORE_WATCHLIST` | 5.0 | **5.0** ✅ | B-grade goes to watchlist |
| `PROXIMITY_MAX_PCT` | 0.7 % | **0.7 %** ✅ | |
| `VOLUME_MIN/STRONG/VERY_STRONG` | 1.2 / 1.5 / 2.5 | **1.2 / 1.5 / 2.5** ✅ | |
| `BREADTH_BULLISH / BEARISH` | 65 % / 40 % | **65 % / 40 %** ✅ | |
| `BREADTH_SAMPLE_SIZE` | 50 | **50** ✅ | |
| `MAX_CONSECUTIVE_LOSSES` | 3 | **3** ✅ | |
| `CONSERVATIVE_SIZE_PCT` | 50 % | **50 %** ✅ | |
| `NO_ENTRY_BEFORE_MIN` | 5 | **5** (i.e., 09:20) ✅ | |
| `ORB_MINUTES` | 15 | **15** ✅ | |
| `ORB_MIN/MAX_RANGE_PCT` | 0.3 / 2.5 | **0.3 / 2.5** ✅ | |
| `PRIME_TIME_START/END` | 09:30 / 11:30 | **09:30 / 11:30** ✅ | Defined; not actually enforced anywhere |
| `MIDDAY_AVOID_START/END` | 13:00 / 14:00 | **13:00 / 14:00** ✅ | Raises score gate in this window |
| `NO_NEW_ENTRY_AFTER` | 14:45 | **14:45** ✅ | |
| `EOD_CLOSE_TIME` | 15:00 | **15:00** ✅ | Aggressive vs the 15:15 cushion in file 01 |
| `MARKET_OPEN / CLOSE` | 09:15 / 15:30 | **09:15 / 15:30** ✅ | |
| `TIMEZONE` | Asia/Kolkata | **Asia/Kolkata** ✅ | Used everywhere via `zoneinfo` |

## 7. Where Groq actually fires — call-site inventory

Single call site in the live path: **`data/news_client.py::_score_sentiment_with_llm`** (line 82).

Path that reaches it:
```
TradingCrew._score_signals()  ← per setup detected this tick
   → self._get_news(sym)
       → NewsClient.get_news_for_symbol(sym)
           → cache hit? return.
           → else: _fetch_headlines (NewsAPI) → if any:
               → _score_sentiment_with_llm  ← Groq HTTP call
```

Cache key is `f"{symbol}_{datetime.now().strftime('%Y%m%d')}"` (per-day, in-memory dict on `NewsClient` instance). So:

- **Per process lifetime:** at most 1 Groq call per (symbol, day) — *if NewsAPI returned headlines for that symbol that day.*
- **Worst-case daily Groq calls:** ≤ unique stocks with both setups detected and NewsAPI hits today. Realistic upper bound on a 150-stock universe is ~30–60 calls/day.
- **NewsAPI rate-limit guard** (line 75): if NewsAPI returns rateLimited, sets `self._rate_limited_today = True` and short-circuits future fetches. Implication: if NewsAPI exhausts before Groq quota, Groq stops being called too.

Why 429s have happened anyway (hypothesised):

- NewsAPI may sometimes succeed for many symbols at session start — the first 30 min of trading can fan out 20–40 Groq calls in a 5–10 minute window. Burst RPM, not aggregate RPD, is the likely failure mode.
- Cache is **per process**: a service restart (which the systemd unit allows on failure) wipes it, forcing re-scoring of stocks already scored that day.
- No tenacity / retry on the Groq path — the bare `except Exception` swallows 429 and returns neutral 0.5, so the symptom is silent score corruption (not crash). **The user "saw 429 errors" probably means in the logs, not in trading outcomes.**

## 8. ChromaDB — write-only at present

- Writes happen on **every closed trade** (`crew._full_exit` line 851 + `eod_job` line 59).
- Reads exist (`query_similar_signals`, `get_recent_news_sentiment`, `get_regime_history`) but are **not called from the live scoring path**. Confirmed.
- PROJECT_MEMORY explicitly says "RAG loop NOT wired ❌ … wait until 50+ closed trades."
- ChromaDB is therefore an event-sink, not a learning loop, today.

## 9. State of the data on this machine

- `trade_state.db` (local) — **0 rows in `positions`, 0 in `watchlist`, no `session_stats` table.** Schema is **pre-migration** (old shape; missing initial_sl, tp1_hit, tp1_price, tp2_price, quantity_remaining, score_breakdown, direction).
- `chroma_store/chroma.sqlite3` (local) — 3 collections exist, **0 embeddings, 0 metadata.**
- The 151 paper trades are **not on this machine.** They live on `168.144.101.223:/root/india_trading/trade_state.db` and `…/chroma_store/`.

→ File **04** cannot show real numbers until the server's DB is pulled local. See file 04 for the exact `scp` and analysis commands; the analytics script will run as soon as the file lands.

## 10. Dashboard — *almost* read-only

The dashboard sidebar in `dashboard/app.py` writes `system_controls.json`, which `main.py::load_controls` reads on every tick. So the dashboard *is* a write surface for three controls (kill switch, min score, max positions) — but **no order-placement path is exposed.** The "read-only" claim is true with respect to orders, not config.

## 11. Production deployment — current

- **Server:** DigitalOcean Bangalore droplet, IP `168.144.101.223`, root user.
- **Path:** `/root/india_trading` (systemd unit confirms).
- **Service:** `trading-system.service` — `Restart=on-failure`, `RestartSec=30`, `TimeoutStopSec=60`, `User=root`. Auto-starts at boot.
- **Daily token push:** `python kite_login.py --push` from the Mac; `kite_login.py` SSH-seds the new token into the server's `.env` and `systemctl restart`s the unit.
- **GitHub:** `bhagyashreekhatri/India_Trading_System`. PROJECT_MEMORY rules require a commit + push + remote pull + restart after every fix.
- **Note:** `deploy/README_DEPLOY.md` references `/opt/trading` and a `trading` user — outdated. The real deploy is `root` at `/root/india_trading`. Doc drift; harmless but should be reconciled.

## 12. Pending fixes already identified by the owner

Per `PROJECT_MEMORY.md` §"Pending bug fixes":

1. **Kite historical-data retry** — *already in `data/kite_client.py::get_candles` lines 86, 104, 122* (3 attempts, 1 s and 2 s backoff). Local has it. Server may not (says "NOT pushed yet").
2. **`get_historical_data` → `get_candles` rename** — *already applied locally* in `tools/pattern_tools.py` lines 118 (`_get_orb_levels`) and 251 (`_gap_analysis`). Server may not have it.
3. **HDFC delisted, replaced with HDFCAMC in SECTOR_LEADERS** — *already applied locally* (line 90 of `config/settings.py` shows HDFCAMC). Server still has HDFC.

→ **All three local-only fixes need to be pushed to the server.** They are not architectural changes; they are bug fixes that were authored after the last deploy.
