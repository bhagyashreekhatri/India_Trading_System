# 03 — Code Review and Gap Analysis

> File-by-file review of the live codebase. Each file lists severity-tagged findings — 🔴 critical / 🟠 high / 🟡 medium / 🟢 nit — with line numbers and concrete fixes. Section A retains the audit framework. Section B is now populated.

---

## SECTION A — Audit framework (kept for reference)

Cross-cutting concerns to look for in every file:

- Groq call discipline: gating, batching, JSON mode, timeout, retry-with-jitter, TTL cache, model tier
- Concurrency safety in shared singletons
- Determinism for tests (seed, mocked I/O)
- Error budgets / circuit breakers per external dep
- Structured JSON logs with `trace_id`
- Type hints + docstrings on public surfaces
- Unit tests for pure functions; mocked I/O for external

Architectural smells to look for:
1. N×M LLM fan-out
2. Shared mutable state without locks
3. Re-prompting upstream context verbatim
4. Synchronous Kite calls inside an async loop
5. No idempotency on order placement
6. Stop loss as a Python-side timer
7. No reconciliation on boot
8. Drift between SQLite state and broker reality
9. News-driven entries with stale headlines
10. Cool-down implemented in-memory only

---

## SECTION B — Findings

> **Status update 2026-04-28:** the items below tagged `✅ FIXED` were closed in the
> Fix #1–#7 deployment cycle. See `PROJECT_MEMORY.md` for a one-page summary
> with files-changed and verification.

### Top-priority gaps (ranked by impact × effort)

**Closed in Fix #1–#7:**
- ✅ TIMEZONE-01 → Fix #1 (stall bug + `_entry_dt_aware` + IST-aware writes)
- ✅ SETUP CALIBRATION (A++ inversion) → Fix #2 (news 0.5→0, regime mults retuned)
- ✅ KILL-01 (no daily-loss kill) → Fix #3 (`DAILY_LOSS_KILL_PCT=0.025`)
- ✅ Overnight survival (ASIANPAINT 19.85h) → Fix #3 (overnight veto on every tick)
- ✅ `sl_hit` vs trail confusion → Fix #3 (`sl_trail_hit` exit reason)
- ✅ GROQ-01 (no retries, silent corruption) → Fix #4 (typed retries + Retry-After + JSON mode + persistent cache)
- ✅ Confluence impossible → Fix #5 (`_detect_setups_multi`)
- ✅ SCAN-01 (raw share volume) → Fix #5 (turnover-based filter, `SCAN_MIN_TURNOVER=₹50L`)
- ✅ EXIT-01 (no broker-side stop) → Fix #6 (SL-M placed on entry, replaced on TP1/trail, cancelled on full exit)
- ✅ TICK-01 (tick-size rejections) → Fix #7 (₹0.05 rounding on all generated prices)



| Rank | Severity | ID | Title | Effort | Impact |
|---|---|---|---|---|---|
| 1 | 🔴 | DEAD-01 | Remove dead `agents/*.py` and `tools/{kite,news,chroma}_tools.py`; drop `crewai`, `langchain` from requirements | S | Reduces install size, removes 429-risk surface from anyone who *thinks* the agents are live, restores doc honesty |
| 2 | 🔴 | RECON-01 | Boot-time reconciliation: read open positions from broker, compare to SQLite, repair drift, restart from broker truth | M | Without this, a server restart mid-session orphans positions silently |
| 3 | 🔴 | EXIT-01 | Stop loss is enforced **only by Python polling every 3 min** — no broker-side SL-M order. A 3-min gap is a 0.5–2 R adverse move on liquid names | M | Single largest live-trading risk |
| 4 | 🔴 | ORB-01 | `_get_orb_levels` filters by `time-of-day` only, so yesterday's 09:15–09:30 candles are mixed with today's | S | Wrong ORB high/low → ORB never triggers correctly |
| 5 | 🔴 | KILL-01 | No daily-loss kill switch in code (only a manual `kill_switch` flag) | S | A bad day can grow to far more than 2.5 % drawdown without auto-pause |
| 6 | 🔴 | TICK-01 | All entry / SL / TP prices use `round(.., 2)` — NSE tick size is ₹0.05 for most stocks; live orders will reject or slip | S | Live-mode blocker |
| 7 | 🟠 | SHORT-01 | The system can **never short** — no detector path produces SHORT direction, so half the alpha (down-trends) is unreachable | L | Mitigated in paper, doubles edge in live |
| 8 | 🟠 | BREADTH-01 | Breadth and sector strength use `change_pct >= 0` as a proxy for "above VWAP" — *not the same thing* | M | Breadth gate (BEARISH if < 40 % "above VWAP") fires on the wrong signal |
| 9 | 🟠 | NEWS-01 | News baseline of 0.5 when no headlines means every stock without news gets +0.5 free into Raw — **scoring inflation** across the universe | S | Drives more entries than designed; biases score-to-PNL calibration |
| 10 | 🟠 | GROQ-01 | No retry/backoff/Retry-After on the Groq sentiment call; failures swallowed and replaced with neutral 0.5 → silent score corruption | S | Easy fix, high value |
| 11 | 🟠 | TIMEZONE-01 | `Position.entry_time` written as `datetime.now().isoformat()` — *naive*, not IST-aware. Hour-of-day analytics are wrong on a UTC server | S | Server is UTC by deploy default; entries at 10:15 IST log as 04:45 UTC |
| 12 | 🟠 | RECON-02 | 30-min cool-down is queried from SQLite (good), but the cool-down record is just last `exit_time` — no idempotency for partial restarts within 30 min | S | |
| 13 | 🟠 | LIQ-01 | Spread liquidity threshold differs across files (0.15 % in `kite_tools.py`, 0.5 % in `volume_tools.py` and `crew.py::_get_volume_rs`) | S | One source of truth needed; 0.5 % is too loose for scalping ₹1,500–3,000 nets |
| 14 | 🟠 | SCAN-01 | Active filter `vol >= 10000` shares — meaningless at scale; should be turnover (price × volume) ≥ ₹X | S | |
| 15 | 🟠 | ORB-02 | ORB returns `SetupType.MOMENTUM_BREAKOUT` (line 187 of `pattern_tools.py`) — invisible in setup-level analytics & uses momentum's regime multipliers, not ORB-specific | S | Add ORB to enum, REGIME_MULTIPLIERS, tests |
| 16 | 🟠 | RANGE-01 | Range-breakout "tight" threshold is `< 2.0 %` — that's a 2 % range, not tight. Pro scalpers use < 0.5 × ATR or < 1 % | S | |
| 17 | 🟠 | NEWS-02 | NewsAPI query is `f"{query} stock India NSE"` against arbitrary noun tokens — false positives and missed company aliases (e.g., "Reliance Industries" vs "RELIANCE") | M | |
| 18 | 🟠 | EOD-01 | `eod_job._extract_regime` infers regime from substring search of `entry_reason`. Regime is *not* written into `entry_reason`. So every EOD-stored regime is "unknown" | S | Pass regime explicitly through `Position.score_breakdown` or a new column |
| 19 | 🟠 | SQL-01 | `_init_db` runs ALTER TABLE migrations at startup — silent failures on production may leave columns missing. No version tracking. | M | |
| 20 | 🟡 | SECT-01 | Sector-cap rule uses count (`MAX_SAME_SECTOR_POSITIONS=3`) not value (`MAX_SECTOR_EXPOSURE=0.30`). The 30 % is dead config | S | |
| 21 | 🟡 | RVOL-01 | `volume_ratio` uses iloc[-2] (last completed candle) — correct — but baseline is "last 20 completed candles regardless of time-of-day". A scalp at 09:20 is compared against 14:00–15:30 dust | M | Move to a same-time-of-day RVOL |
| 22 | 🟡 | VWAP-01 | VWAP is recomputed inside `KiteDataClient.calculate_vwap` from 5-min candles — that's correct method, but ATR / RVOL also use 5-min candles, so the smoothing window is implicit | S | |
| 23 | 🟡 | EVENT-01 | Regime "EVENT" defined only by `abs(nifty_change_pct) > 1.5%` — VIX, expiry days, RBI policy day are *not* used | S | |
| 24 | 🟡 | EXP-01 | No expiry-day mask (Tue Bank Nifty, Thu Nifty) | S | |
| 25 | 🟡 | TARG-01 | `target_R` math is gross-of-cost. Scalping ₹1,500 nets requires net targets, not gross | S | |
| 26 | 🟡 | LOG-01 | Logs use bare `print()` re-routed via builtins override — not structured; no `trace_id`; hard to slice in journalctl | M | |
| 27 | 🟡 | UNIVERSE-01 | Universe is static. No ASM/GSM/circuit-band check. No weekly liquidity refresh | M | |
| 28 | 🟡 | UNIVERSE-02 | `get_top_liquid_stocks` returns `NIFTY_50[:n]` — alphabetical-ish slice, not actually-liquid order | S | |
| 29 | 🟡 | DASH-01 | `live_tab.py` references `st.session_state["last_signals"]` etc., but the engine never writes to Streamlit session_state from a background process — the "agent pipeline" / "active signals" panels will only ever show defaults | S | These panels are decorative, not functional |
| 30 | 🟡 | TZ-02 | `crew.py` mixes `datetime.now()` (naive) and `datetime.now(IST)` — entry/exit times stored naive, IST math done with `IST` zoneinfo | S | |
| 31 | 🟡 | DUP-01 | `_calc_tp` defined in three different files (`tools/pattern_tools.py`, `tools/score_tools.py`, `agents/crew.py`) | S | DRY |
| 32 | 🟡 | DUP-02 | ATR computed in two places (`tools/pattern_tools.py::_atr` and `agents/crew.py::_calc_atr_from_df`) | S | |
| 33 | 🟢 | DOC-01 | Skill memory + `PROJECT_MEMORY.md` + `deploy/README_DEPLOY.md` disagree on capital, max_positions, deploy path, agent count | S | One source of truth = `docs/02`; mark others stale |

---

## File-by-file findings

Severity legend: 🔴 critical · 🟠 high · 🟡 medium · 🟢 nit · ✅ noted as good practice.

### `main.py` (443 LOC)

- 🔴 **[110-119]** No `try/except` budget around `health_check`'s Kite quote — if Kite is briefly slow, the *entire system refuses to start* even though the daily loop tolerates it. Wrap the live-quote test in 3-attempt retry with 10 s backoff.
- 🟠 **[121-129]** `is_market_open` uses `MARKET_OPEN`/`MARKET_CLOSE` strings (`09:15`/`15:30`) — not holiday-aware. Pull NSE holiday calendar at boot.
- 🟠 **[81-90]** `print()` redirected via `builtins.print` to logger — works, but *every* `print` in *every* imported module now logs through the root logger. Fragile and hides the real call site. Replace with a proper logger across the codebase.
- 🟡 **[121]** Smaller: `is_market_open` returns True for Saturday between 09:15–15:30 if `weekday >= 5` *short-circuit fails*. Re-read the function — it checks `weekday >= 5` and returns False. Fine; just confirming.
- 🟡 **[395-401]** EOD job triggers between 15:35 and 15:50 IST — and only if the engine is running. If `systemctl restart` happens in that window, EOD never runs that day. Move EOD to a separate systemd timer (`OnCalendar=Mon..Fri 15:35 Asia/Kolkata`).
- ✅ **[267-306]** `run_premarket` is well-bounded: top 50 names, abs gap ≥ 1.5 %, plus tradeable filter. Sensible.

### `agents/crew.py` (938 LOC)

- 🔴 **[336]** Inside `_detect_setups` the `last["high"] - last["low"]` denominator can be 0 on a tick that hasn't moved — guarded only by `if (last["high"] - last["low"]) > 0`. But the value `br = ...` is also computed here for diagnostic logging only — actual setup detection happens in `_detect_all_setups`. Diagnostic counts may be misleading, no functional bug.
- 🔴 **[504-508]** `SETUP_MIN_SCORES = {"failed_breakdown": 7.5}` is **hard-coded inside the function**. It is real learning ("20 % win rate historically") but invisible to anyone reading settings. Move to `config/settings.py`. Also: per-setup scores like this should be **data-driven** (Phase 4), not hard-coded.
- 🔴 **[698]** `quotes = self.kite.get_quotes(syms)` for *all open positions* — single batch ✅. But if the call fails, `quotes = {}` and every position falls back to `p.entry_price`, which means **no SL trigger this tick** — *positions silently held through stop levels.* Fail closed: if quote fetch fails → exit nothing this tick AND alert via Telegram.
- 🔴 **[709]** EOD `now.time() >= eod` — uses `_now_ist()` (TZ-aware) ✅. But `now.time()` strips TZ, and `eod = _parse_time(EOD_CLOSE_TIME)` is a naive `dtime`. Cross-comparison naive vs naive — works but fragile.
- 🟠 **[209-224]** Scanner: `chg >= 0.3 and vol >= 10000` — absolute share volume, not turnover. A ₹50 stock and ₹5,000 stock both clear the gate at 10k shares. Fix: `(price * volume) >= ₹50 lakh`.
- 🟠 **[210-224]** Scanner returns *top 60 by abs(change_pct)*, mixing bullish and bearish movers. Since we only have LONG detectors, half the candidates are wasted.
- 🟠 **[244-253]** Regime classifier is solely Nifty-based — `event` only when `abs(nifty_change_pct) > 1.5%`. No VIX, no breadth, no expiry-day flag. Brittle.
- 🟠 **[261-263]** `nifty_vwap_minutes`: hard-coded **±20** — unused fudge. Remove or compute from candle history.
- 🟠 **[395-403]** `_get_news` calls `chroma.store_news` *every tick* for the same headline if cache hit. Wait — actually the cache is in `NewsClient`, so on a cache hit `get_news_for_symbol` returns the cached `NewsData` and doesn't re-store. But on a *different* process restart same day, the cache is empty → re-fetch → re-score → re-store. Acceptable.
- 🟠 **[567-678]** `_allocate` re-fetches `open_pos` after every entry inside the loop — three extra DB calls per allocator pass. OK at low volume; profile if entries > 5/tick.
- 🟠 **[605-617]** Sizing pipeline computes `qty` from risk × dist, then caps at 20 % of capital, then caps at available capital. **Three caps, no rounding to broker lot/tick** — fine for paper, broken for live.
- 🟠 **[622]** `qty < 1` skip is silent. Log it to telemetry — these are the trades you almost took.
- 🟠 **[669-676]** Inside the entry loop the consec-loss alert fires *every tick* once consec ≥ 3. Telegram spam. Move to a once-per-day flag.
- 🔴 **[741-744]** Stall detection uses `entry_dt.replace(tzinfo=IST)` — but `p.entry_time` was written naive by `state.open_position` (`datetime.now().isoformat()` without IST). For a server in UTC this attaches `IST` to a UTC timestamp. The wall-clock value is interpreted as IST, so a 10:00 IST entry stored as 04:30 UTC reads as `04:30 IST` ≡ 23:00 UTC prior day. `now - entry_dt` then **adds 5h30 to apparent age**. The 45-min threshold is breached immediately at entry. Combined with the `|pnl_r| <= 0.15` filter, **most quiet positions get killed within the first tick of management as "stalled"** — opposite of the intended 45-min breathing room. *This single bug likely explains a meaningful chunk of "stalled_no_movement" exits in the trade log; verify in file 04.* On an IST-host server the bug is silent. The deploy default for DigitalOcean droplets is UTC unless explicitly changed; verify `timedatectl` on the server.
- 🟠 **[816-818]** `pnl_r` is computed against `p.quantity` (initial), but `total_pnl` is "partial TP1 PnL + final exit PnL". Mixing per-share R math against original-size denominator gives a slightly inflated R for half-exited trades. Document or fix.
- 🟡 **[114-118]** `_breadth_cache` and `_regime_cache` are dicts mutated across ticks — no thread-safety, but only one tick runs at a time. Confirmed safe.
- 🟡 **[437-446]** `STATUS_FILE.write_text(...)` every tick — fine, but no JSON schema; dashboard reads with no validation. Add a tiny pydantic model.
- 🟡 **[849-865]** Outcome string mapping uses substring of `reason`. Same `_extract_regime` weakness in EOD job — `regime=self._regime_cache.get("regime", "unknown")` here is fine because it's the live cache, not a parse. Inconsistent between live path and EOD path.
- 🟡 **[916]** `if abs(unreal) > abs(best_unreal)` — picks the *most extreme* (positive or negative) position, not the best. Comment says "best_open_pnl"; rename or fix.
- ✅ **[126-178]** Top-of-tick "manage first, scan after" sequencing is correct discipline.
- ✅ **[136-139]** Time gate is checked **after** position management — keeps SL/TP active even outside entry windows. Good.
- ✅ **[698, 909]** Batch quote calls in management and tick-summary — one call per tick, not per position. Good.

### `scoring/engine.py` (428 LOC)

- 🔴 **[9-15]** `SetupType` enum has 6 members; **ORB is missing.** Pattern detector silently maps ORB → MOMENTUM_BREAKOUT. Add `ORB = "orb"` to the enum, add a row to `REGIME_MULTIPLIERS`, add tests. Right now ORB inherits MOMENTUM_BREAKOUT × CHOPPY = 0.6 — overly punished by chop.
- 🟠 **[284-298]** `_score_news`: `not has_news` returns 0.5 — **scoring inflation**. Either rebase Raw to subtract 0.5 (so neutral = 0) or only credit on *real* positive signal.
- 🟠 **[247-265]** Choppy-regime applies a `−0.5` to market-alignment *and* a 0.6× regime multiplier on momentum_breakout. Double penalty in a single regime. Likely the cause of momentum_breakout very rarely firing in CHOPPY.
- 🟠 **[81-87]** `RelativeStrengthData.outperforming` is set but **never read** anywhere in the engine. It is computed in `tools/score_tools.py` and `tools/volume_tools.py`. Dead field.
- 🟡 **[51-52]** `RawSignal.detected_at: datetime = field(default_factory=datetime.now)` — naive `datetime.now()`. Should be `datetime.now(ZoneInfo("Asia/Kolkata"))`.
- 🟡 **[170-228]** `_score_setup_quality` is a tuple of (score, confidence) — confidence isn't used to gate anything; it's persisted on `Position.confidence` but never consulted again. Either gate on it or stop persisting it.
- 🟡 **[319-329]** `_check_proximity` ignores `direction` — for a SHORT signal, `current > entry` by 0.7 % should be *fine* (price ran in our favour to fill). Currently treats both directions identically. Cosmetic since system doesn't short.
- ✅ **[136-169]** Regime multiplier table is complete for all combinations; no missing key risk **except** for the missing `ORB` SetupType (above).
- ✅ **[400-417]** Final clamp `min(10.0, raw × mult)` enforces ceiling. Tested.

### `tests/test_engine.py` (289 LOC)

- 🟡 **[256-282]** `__main__` runner only registers 10 of the 11 tests defined (`test_underperforming_stock_gets_zero_rs_score` not in the list). Pytest picks it up; the script-mode runner does not.
- 🟡 No tests for ORB (because there is no ORB enum value). No tests for News-baseline-0.5 inflation. No tests for the EVENT 0.7× when input is *already* a low score (verifies clamp).
- ✅ Mocking style is clean — no I/O dependencies.

### `data/kite_client.py` (282 LOC)

- 🔴 **[225-252]** `place_order(order_type="MARKET", price=0)` for paper. For live, on `LIMIT` orders the call passes `price=price if order_type == "LIMIT" else None` — but on `MARKET` it passes `price=None` correctly. Looks OK.
- 🔴 **[253-283]** `place_sl_order` uses `KiteConnect.ORDER_TYPE_SLM` ✅ — but **this method is never called** from `crew.py`. Stops are managed by polling. *This is the single most important live-trading gap.*
- 🟠 **[31-39]** `_load_instruments` fetches *all* NSE instruments at boot — ~70k tokens — and stores in a dict. Quick, but no refresh during the day. If a stock is suspended mid-day, the cache still returns its old token.
- 🟠 **[55-77]** Quote parser silently drops symbols not in the response. No way to tell upstream that "I asked for 60 names, got 58 back". Add a return field for missing.
- 🟠 **[183-195]** `get_spread_pct` returns `999.0` when bid/ask is 0 — but `volume_tools._get_volume_rs` and `crew._get_volume_rs` both treat `999.0` as **PASS** ("don't penalize"). This means missing depth data → assumed liquid → false positive. Should be FAIL or DEFER.
- 🟠 **[156-180]** `get_volume_ratio` correctly uses `iloc[-2]` (last completed candle) ✅. But the 20-bar baseline is `iloc[-22:-2]` — **last 20 completed candles**, regardless of time-of-day. RVOL bug noted in top-priority list.
- 🟡 **[97-127]** `get_candles` retries 3 times (1 s, 2 s) — implements the fix from `PROJECT_MEMORY`. ✅
- 🟡 **[200-220]** `get_nifty_data` calls `get_quotes(["NIFTY 50"])` followed by `get_vwap("NIFTY 50")` (which itself fetches candles). 2 round-trips. Could be fused.
- 🟡 No connection pooling on the underlying `requests` session (Kite SDK manages this internally; verify if you go to live mode).

### `data/news_client.py` (176 LOC)

- 🔴 **[82-109]** `_score_sentiment_with_llm`: bare `except Exception` swallows all errors and returns neutral 0.5. **A Groq 429 looks identical to a model malformed JSON.** Add specific handling: 429 → backoff + retry with `Retry-After`; JSONDecodeError → log + return None (caller should also choose neutral).
- 🟠 **[92-97]** No `response_format={"type": "json_object"}`. The model is asked to "return ONLY this JSON" via prompt — fragile. Force JSON mode.
- 🟠 **[60-80]** NewsAPI query template `q=f"{query} stock India NSE"` is broad — catches macro / sectoral headlines and treats them as stock-specific. Add company-name aliases (mapping needed).
- 🟠 **[111-169]** `get_news_for_symbol` — daily cache on (symbol, date). On process restart, cache is gone → re-fetch + re-score. Use a persistent cache (SQLite or filesystem JSON) to survive restarts.
- 🟠 **[156-159]** `final_score = (llm_score * 0.8) + (rule_sentiment * 0.2)` — blend is fine, but `rule_sentiment` is *very* coarse (3 buckets: 0.25 / 0.5 / 0.75). On a weak LLM hour, 80 % of the score still comes from a cheap LLM call.
- 🟡 **[14-31]** `SENTIMENT_PROMPT` is conversational (~200 tokens). Trim by 30 %.
- 🟡 No timeout on `groq.chat.completions.create` — Groq client default is generous; specify `timeout=10`.

### `memory/trade_state.py` (435 LOC)

- 🔴 **[157-179]** `open_position` sets `initial_sl = stop_loss` and `target_price = tp2_price` — **immutable after creation.** Trail-SL updates `stop_loss` but never `initial_sl` ✅. Good.
- 🔴 **[157-179]** **No `client_order_id` / idempotency key.** A retry path that re-opens the same position (server restart mid-tick) would create a duplicate row. With paper this is mostly harmless; with live it doubles size.
- 🟠 **[80-156]** Schema migrations run silently with `try/except sqlite3.OperationalError: pass`. If a column add fails for any other reason it's hidden. Use `PRAGMA table_info` first.
- 🟠 **[131-156]** `_init_db` adds `sector` column inside `open_position` (line 166), not in `_init_db`. Inconsistent; always add columns at startup.
- 🟠 **[366-378]** `is_in_cooldown` parses `exit_time` with `datetime.fromisoformat(row["exit_time"])` — **naive comparison against `datetime.now()`** (also naive). On the UTC server, this is fine (both are UTC); but this is brittle and inconsistent with the IST-aware code in `crew.py`.
- 🟠 **[337-355]** `get_win_rate_by_hour` parses `entry_time` and uses `.hour` — also naive. On a UTC server, "best entry hour" reads ~5h30 earlier than reality.
- 🟠 **[286-301]** `get_summary().best_trade` and `worst_trade` use `min/max(pnls)` — but `pnls` is filtered to non-zero. Loses info if a trade had pnl ≈ 0.
- 🟡 **[277-284]** Capital math: `get_deployed_capital` sums `entry_price * quantity_remaining` — uses **entry price**, not current LTP. Dashboard's "in use" therefore stays static after price moves. Fine for sizing math, misleading for "deployed" display.
- 🟡 **[409-435]** `_row_to_position` uses `or` defaults extensively — masks missing fields silently.
- ✅ **[77]** `row_factory = sqlite3.Row` ✅
- ✅ **[122-132]** `session_stats` table — well thought out.

### `memory/chroma_client.py` (205 LOC)

- 🟠 **[51-72]** `query_news` filters by `symbol` only. No date filter — old news is mixed with recent.
- 🟠 **[131-163]** `query_similar_signals` filters by `setup_type` only. The query string includes regime, but the `where` does not. Result: signal_patterns from any regime are returned.
- 🟠 **[36-49]** `store_news` writes a doc with the headline as text. But `_score_sentiment_with_llm` is called once per (symbol, day) — so the same headline could be stored once per process restart. Add a unique `headline` hash to dedup.
- 🟡 **[195-205]** `get_regime_history` returns metadatas only — fine for now, but no filtering by date so it returns ancient regimes.
- 🟡 No embedding-model declaration: defaults to Chroma's `all-MiniLM-L6-v2`. Acceptable but fix the choice in config so model upgrades don't silently change behaviour.
- ✅ **[14-23]** Singleton-via-method-init is fine since `ChromaMemory` is created once in `crew.__init__`.

### `tools/pattern_tools.py` (473 LOC)

- 🔴 **[111-144]** `_get_orb_levels` filters candles by `x.time()` — **time-of-day only**. Passing `days=1` to `get_candles` returns yesterday + today. Yesterday's 09:15–09:30 candles **also match** the time filter, polluting today's ORB high/low.
  - Fix: filter the dataframe by `x.date() == today` first; then by time-of-day.
- 🔴 **[170]** `if range_pct < ORB_MIN_RANGE_PCT or range_pct > ORB_MAX_RANGE_PCT: return None` — silent. No log. ORB never firing → no idea why.
- 🟠 **[294-380]** `_detect_all_setups` returns the **first** match in priority order (ORB → FailedBreakdown → Recovery → VWAP Reclaim → VWAP Pullback → Momentum BO → Range BO). **Confluence detection is impossible** under this design (it's literally the next-week priority #1 in PROJECT_MEMORY). Refactor to return *all* matching setups; let the scorer pick.
- 🟠 **[302-380]** All setup conditions are LONG-only. There is **no** SHORT detector path. SHORT signals cannot be produced.
- 🟠 **[366-378]** Range Breakout `rng_pct < 2.0` — too loose. A 2 % range over 8 bars is not consolidation. Tighten to `< max(0.5 * ATR, 0.8 %)`.
- 🟠 **[156-189]** ORB labels itself `SetupType.MOMENTUM_BREAKOUT`. As long as engine has no `ORB` enum, this is a workaround. Document it; add `setup_subtype="orb"` field for analytics.
- 🟠 **[244-289]** `_gap_analysis` — the local `get_candles` interval has been correctly renamed to "day" (the fix applied locally). Confirm server has it.
- 🟡 **[194-239]** `_detect_failed_breakdown` only checks current bar; doesn't require *recent* downtrend before the breakdown. A breakdown that happens out of nowhere fires the same as one that follows a real downtrend.
- 🟡 **[40-48]** `_candle_quality` — `body_ratio = abs(close-open) / range`. For a doji (range = 0), returns (0, 0.5). The 0.5 default is harmless.
- 🟡 **[51-62]** `_atr` length is hard-coded 10. Fine, but it should be a config constant; same value used in `crew._calc_atr_from_df`.
- ✅ **[65-73]** `_calc_tp` and `_sl_from_atr` are clean utilities.

### `tools/volume_tools.py` (351 LOC)

- 🔴 **[156-198]** `_compute_breadth` uses `q.get("change_pct", 0) >= 0` as a proxy for "above VWAP". **Not the same.** A stock that opened up 1 % and is now below VWAP but still up 0.5 % on the day counts as "above VWAP". The breadth gate (BEARISH if < 40 %) fires on the wrong signal.
  - Fix: compute actual VWAP for the sample stocks (one extra batch quote covers it via `kite.calculate_vwap` if intraday candles already cached). Yes, slower; but correct.
- 🔴 **[218-282]** `_compute_sector_strength` uses the same proxy. Same fix.
- 🟠 **[75]** Spread threshold `< 0.5%` here; `< 0.15 %` in `tools/kite_tools.py::get_spread`. Pick one and put it in `settings.py`.
- 🟠 **[75, 134, 378]** `if spread >= 999.0: spread_ok = True` — when Kite returns no depth, we *assume* liquid. Should be DEFER (skip this tick) at minimum.
- 🟡 **[44-50]** Volume score interpolation can return up to 2.0 inside the (1.5, 2.5) branch. Bounded correctly.
- ✅ Functions used internally by crew are pure-Python and fast.

### `tools/score_tools.py` (468 LOC)

- 🟠 **[45-59]** `_calc_quantity` is a *duplicate* of the inline `qty = floor(risk_amount / dist)` block in `crew._allocate`. Two divergent sizing paths is one too many. Pick one.
- 🟠 The `@tool`-decorated functions in this file (`score_signal`, `can_enter_trade`, `open_position`, `partial_exit_tp1`, `close_position`, `update_stop_loss`, `get_open_positions`, `add_to_watchlist`) are **not used at runtime** — `crew.py` calls underlying functions directly. They are LangChain-tool surface for the dead CrewAI agents. Delete or move to `legacy/`.
- 🟡 The signature of `score_signal` is 25+ parameters — typical "Pydantic-via-CrewAI" pain. Not a bug, but unmaintainable.

### `tools/news_tools.py` / `tools/chroma_tools.py` / `tools/kite_tools.py`

- 🟠 **[ALL]** Same problem: dead LangChain wrappers around `data/*` and `memory/*` clients. Remove.

### `tools/telegram_tools.py` (237 LOC)

- 🟠 **[13-28]** No retry on `requests.post` Telegram. A 5xx blip silently drops the alert.
- 🟠 **[150-158]** `alert_market_breadth` is called **on every breadth refresh** (every 5 ticks ≈ 15 min). Spammy. Throttle to once per regime change.
- 🟢 **[31-238]** Otherwise tidy. Templates are readable; HTML formatting is consistent.

### `tools/check_learning.py` / `tools/force_exit.py`

- 🟢 Stand-alone admin scripts. Useful. `force_exit.py` uses `input()` for confirmation — unsuitable for non-interactive use; add a `--yes` flag.

### `dashboard/app.py` (311 LOC)

- 🟠 **[80-103]** `system_controls.json` is the IPC channel between dashboard and engine. No JSON schema, no validation on read. Add a tiny pydantic model both sides import.
- 🟠 **[107-118]** `@st.cache_resource` on `TradeStateManager` and `ChromaMemory` — fine for read-only views, but if engine restarts and dashboard kept its handle, SQLite reads still work (single-file DB). Confirmed no issue.
- 🟡 **[128-148]** The "market open" check string-parses `09:15` and `15:30` — duplicate of `is_market_open` logic in `main.py`. DRY.
- 🟡 **[294-311]** `streamlit_autorefresh` import-tested with JS fallback. Nice fallback; standard approach.
- ✅ Read-only with respect to orders. Three control writes are bounded.

### `dashboard/live_tab.py` (356 LOC)

- 🟠 **[97-103, 135-158, 161-187]** Reads from `st.session_state["last_signals"]`, `last_breadth`, `last_*_status`. The engine **never writes to Streamlit session_state** (it runs in a different process). These panels show defaults forever. Either pipe these through `system_status.json` (engine writes, dashboard reads) or remove the panels.

### `dashboard/learning_tab.py` (381 LOC)

- 🟠 **[197-227]** `get_win_rate_by_hour` returns hours from naive `entry_time`. On UTC server, all "best hour" labels are off by 5h30. Fix the underlying source (TZ-01 in trade_state).
- 🟡 **[362-373]** Style function checks substring `"Tp"` (capitalised) — won't match `tp1_hit`. Style is decorative.
- ✅ Comprehensive — equity curve, score distribution, hour heatmap, setup matrix.

### `dashboard/analytics_tab.py` (265 LOC)

- 🟢 Cleaner of the two analytics tabs; nice insights pane.

### `jobs/eod_job.py` (226 LOC)

- 🔴 **[57]** `regime = _extract_regime(trade.entry_reason or "")` — this is **the only place** the trade's regime is recovered for ChromaDB storage. But `entry_reason` is the human-readable reason, not always containing the regime word. Result: most stored regimes are `"unknown"`.
  - Fix: persist regime as a column on `Position` and pass it through.
- 🟠 **[145-150]** Friday weekly scorecard prints to stdout (i.e., journalctl) — not Telegram, not file, not dashboard. Lost on restart.
- 🟡 **[174-182]** `_extract_regime` substring search over four words is fragile; same as above.
- ✅ **[39-46]** Empty-day handling is graceful.

### `kite_login.py` (189 LOC)

- 🟠 **[136-145]** Regex parses `request_token` from URL — robust for the common cases. Edge case: URL-encoded ampersands.
- 🟠 **[56-99]** `push_token_to_server` uses `subprocess.run("ssh ...")` with shell=True. Token is shell-escaped via `replace("'", "'\"'\"'")` ✅. Be cautious about logging stdout if token leaks into journalctl.
- 🟢 Otherwise a clean morning helper.

### `config/settings.py` (94 LOC)

- 🟠 **[27]** `CAPITAL = 1_500_000` — drift with PROJECT_MEMORY.md (₹2 L). Update memory.
- 🟠 **[82-91]** `SECTOR_LEADERS` includes only 8 sectors; the `SECTOR_MAP` in `universe.py` has 30+ sectors. If a stock's sector isn't a `SECTOR_LEADERS` key, sector strength is ignored for it.
- 🟢 Otherwise comprehensive and well-commented.

### `config/universe.py` (184 LOC)

- 🟠 **[167-169]** `get_top_liquid_stocks(n) → NIFTY_50[:n]` — alphabetically-ordered slice. Not actually-liquid order. Replace with a daily ADTV-ranked list refreshed weekly.
- 🟠 The 150 names are static. No ASM/GSM membership check, no circuit-band check, no F&O eligibility check. Run the universe-refresh weekly job from file 06 §4 SIG-09.
- 🟢 Sector map is reasonably complete.

### `tests/`

- 🟡 Only the scoring engine is tested. No tests for `pattern_tools`, `volume_tools`, `news_client`, `trade_state`, `crew`. Integration tests would be the highest ROI testing additions.

### `agents/{scanner,regime,setup,volume_rs,news,scoring,allocator,position}_agent.py` (~600 LOC dead)

- 🔴 **[ALL]** Dead code. `from crewai import Agent` and `llm="groq/llama-3.3-70b-versatile"`. Each one of these, if ever called, would fire a Groq call per agent per tick — i.e., 8 Groq calls per tick, 75 ticks/day = 600 calls/day on the strong model. **The 429s the user saw are most likely from a previous build that did invoke these.** Today they are inert; tomorrow they could be re-enabled by accident.
  - Fix: move to `legacy/agents/` or delete. Drop `crewai` and `langchain` from `requirements.txt`.

### `requirements.txt`

- 🟠 `crewai==0.28.0`, `langchain==0.1.20`, `langchain-groq==0.1.3` are pinned but unused at runtime. Drop them.
- 🟢 Otherwise reasonable pins. `httpx<0.28.0` is a deliberate constraint (likely from a kiteconnect/groq compatibility issue).

---

## Cross-cutting observations

### What this codebase does well

1. **Pure-Python orchestration was the right call.** The 938-LOC `crew.py` is readable, debuggable, and avoids agentic-framework overhead.
2. **Single Groq call site.** Even if Groq vanished tomorrow, only sentiment scoring is affected — the scoring engine and risk path are math-only. This is excellent isolation.
3. **TP1+TP2 with breakeven shift after TP1 is professional.** The exit logic is the strongest part of the system.
4. **Health check on boot, Telegram everywhere, kill-switch via JSON** — operationally thoughtful.
5. **Clean separation of pure scoring (engine) from orchestrating (crew).** Tests for the engine pass; that's the most valuable test in the system.

### What this codebase does poorly

1. **No broker-side stops.** SL is enforced by polling. This is the largest live-trading risk. Three minutes of latency at the wrong moment can destroy a week of P&L.
2. **No reconciliation on boot.** A restart mid-session can leave SQLite and broker out of sync; nothing detects it.
3. **Naive datetimes everywhere SQLite touches.** On a UTC server (DigitalOcean default) every "today's trades", "win rate by hour", "is in cooldown" computation is silently shifted by 5h30. This is *the most insidious* class of bug.
4. **Breadth and sector strength are proxied via change_pct, not actual VWAP relation.** The breadth gate is therefore noisy.
5. **News scoring is a single Groq call with bare `except`.** 429s become silent score corruption.
6. **Dead code masquerading as live.** 600+ LOC of legacy agent files keep the dependency graph polluted and the architecture misunderstood.
7. **Confluence is impossible by design.** First-match-wins detector cannot stack setups.
8. **Tick-size rounding missing.** Live mode will reject orders.
9. **No daily-loss kill switch.** A 5 % loss day is unprotected.
10. **Long-only.** Half the alpha is unreachable.

### Severity-balanced fix sequence (pairs with file 06 / file 07)

Phase 0 (this week): DEAD-01, DOC-01, GROQ-01, NEWS-01 (1 line), TIMEZONE-01 (write-side fix).
Phase 1: GROQ-02..12 from file 06 §2.
Phase 1 also: ORB-01, BREADTH-01.
Phase 2: SHORT-01 (long project), RANGE-01, EVENT-01, EXP-01.
Phase 3: EXIT-01, KILL-01, TICK-01, RECON-01.
Phase 4: confluence + RAG read.
