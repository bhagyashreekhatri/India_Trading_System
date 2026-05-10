# 05 — Groq Optimization Strategy

> Groq is the **single highest operational risk** in the current architecture. Every architectural choice in Phase 1+ is judged through this filter: *will this survive at 9:25 IST when Nifty rips and 60 stocks need scoring at the same tick?*
>
> This document defines the rate-limit budget, the model-selection ladder, the call topology, the caching layers, the retry semantics, the fallback path, and the monitoring required to make 429 errors structurally impossible — not just rare.

---

## 1. The constraint, stated honestly

Groq's free / dev tiers enforce **per-minute** *and* **per-day** limits on:

- requests (RPM, RPD)
- tokens (TPM, TPD)

Hitting any of these throws **HTTP 429**. There is no graceful degradation built into Groq itself — it's our job. Even paid tiers throttle bursts. The agent has 6.25 hours of trading × 12 ticks/hour = **75 ticks/day**. Multiply by 60 active stocks × N agents and the math gets ugly fast.

**Order-of-magnitude budget (representative, replace with tier values once confirmed):**

| Resource | Conservative budget | Notes |
|---|---|---|
| RPM | 30 | Typical free dev tier |
| TPM | 30,000 | |
| RPD | 14,400 | |
| TPD | 500,000 | |

`[FILL: confirm tier and exact limits]`

A single 5-min tick may legitimately need ~5–10 LLM calls; budget therefore allows roughly that. Anything more and we burn the budget by 11:00 IST.

## 2. Design principles (in priority order)

1. **Determinism first, LLM last.** Any decision that can be made with code and numbers gets made with code. The LLM is invited only when reasoning genuinely needs natural-language judgement.
2. **One call per *decision*, not per *stock*.** Score 60 stocks → one batched call, not 60 calls.
3. **Cheap model by default, strong model on appeal.** Tiered ladder; escalate only on confidence < threshold.
4. **Cache by semantic key.** Same regime + same setup signature + same stock = cached for N seconds.
5. **Token frugality is non-negotiable.** Compress prompts; use field codes, not prose.
6. **Backoff with jitter, never hammer.** Tenacity with exponential + random jitter on every Groq call.
7. **Fallback path is offline.** If Groq is dead, the agent must keep trading using deterministic rules at reduced size.
8. **Every call is observed.** RPM / TPM utilisation logged per minute; alert at 70 %, choke at 85 %.

## 3. Model selection ladder

Use a tiered ladder. Names are current as of writing — verify in the Groq console; some IDs change.

| Tier | Model | Use case | Approx cost / latency profile |
|---|---|---|---|
| **T0 (utility)** | `llama-3.1-8b-instant` | Tag classification, news sentiment polarity, prompt-cache key generation | Fastest, lowest tokens |
| **T1 (default)** | `llama-3.3-70b-versatile` | Scoring rationale, setup explanation, regime narrative | Current default |
| **T2 (strong)** | `llama-3.3-70b-versatile` (high-quality prompt) or `qwen-2.5-32b` if available | Used only on **conflict** (e.g., setup says LONG but RS contradicts) | Low frequency |
| **T3 (deep)** | `mixtral-8x22b` / `deepseek-r1-distill-llama-70b` (when available) | Post-trade self-critique in EOD job, *not* during session | Off-hour only |

**Routing rule:**

```
default → T1
if input is binary classification or polarity tag → T0
if T1 confidence_score < 0.6 OR upstream agents disagree → T2
if EOD reasoning, regime-shift research, weight-tuning proposals → T3
```

Confidence is asked of the model itself in JSON output (`{"score": 8.2, "confidence": 0.78, "rationale": "..."}`).

## 4. Call topology — where each LLM call lives

**Goal:** maximum 5–8 LLM calls per 5-min tick at steady state.

| # | Call | Tier | Frequency | Notes |
|---|---|---|---|---|
| 1 | Regime classification | T1 | Every tick | Single call: Nifty / VIX / breadth → regime + reasoning |
| 2 | News sentiment batch | T0 | Every tick if new headlines | One call processes **all new** headlines in a single JSON array |
| 3 | Scoring rationale (top-K only) | T1 | Every tick | Run *deterministic* scoring on all 60; LLM only narrates the top 5–10 candidates |
| 4 | Setup conflict adjudication | T2 | On disagreement | Rare — only when deterministic detectors disagree |
| 5 | Position-manager exit reasoning | T1 | On exit-trigger only | Not every minute; only when a trail / breakeven / time-stop is being considered |
| 6 | Pre-entry sanity check | T1 | Per *entry*, not per signal | Quick "anything obviously wrong?" check |
| 7 | EOD self-critique (per closed trade) | T3 | After 15:30 | Off-session, batched |
| 8 | Weekly weight-tuning proposal | T3 | Weekly | Heavy reasoning, fine off-hours |

**What is *not* an LLM call (was, must not be):**

- Setup detection — pattern code, not LLM.
- Volume / RS computation — math, not LLM.
- Sizing — math, not LLM.
- Sector cap check — math, not LLM.
- Cool-down check — math, not LLM.
- Stop / target placement — math, not LLM.
- Most "is this a breakout?" calls — math, not LLM.

If any agent above currently hits Groq, file 03 must flag it and file 06 must list its replacement.

## 5. Batching

### 5.1 Batched scoring rationale

Instead of scoring 10 candidates with 10 calls, send one prompt:

```
You are a scalper. Below are 10 setups already pre-scored deterministically.
For each, return JSON {symbol, narrative, confidence, vetoes}.
SETUPS:
[... compact rows, no prose ...]
Respond with a JSON array of length 10.
```

Use `response_format={"type": "json_object"}` and a Pydantic schema that enforces array length.

### 5.2 Batched news sentiment

All new headlines in last tick → one call. Schema:

```json
{
  "items": [
    {"id": "abc", "polarity": -1|0|1, "magnitude": 0..1, "is_event": true|false}
  ]
}
```

### 5.3 Anti-pattern (do NOT do)

- Looping `for symbol in candidates: agent.kickoff(...)` — that's 60 calls.
- Re-sending the entire universe context to each agent — token waste.

## 6. Caching

Three caches, three lifetimes:

### 6.1 In-memory LRU cache (`functools.lru_cache` or `cachetools`)
- Keys derived from inputs that **do** change but not at every tick.
- TTL examples:
  - Sector classification → 24 h
  - Symbol → company-name expansion → 7 d
  - News article sentiment → forever (article id is unique)
  - Regime → 5 min (per tick)

### 6.2 ChromaDB-backed semantic cache
- For repeated reasoning patterns: same setup + same regime + similar volume / RS profile → reuse the LLM's last narrative if cosine similarity > 0.92 and < 30 min old.
- Saves expensive narrative calls when market is repeating itself.

### 6.3 Disk cache for prompt templates / few-shots
- Few-shot example sets are versioned; compiled prompts cached on disk so we don't recompose every call.

**Cache invalidation:** any settings change, any model change, any regime change clears the relevant cache namespace.

## 7. Token budget per prompt

Hard ceilings per call type. Enforce with a tokeniser pre-check (`tiktoken` or Groq's tokenizer).

| Call | Max input tokens | Max output tokens |
|---|---|---|
| Regime classification | 800 | 200 |
| News sentiment batch (10 items) | 1,500 | 600 |
| Scoring rationale batch (10 items) | 2,000 | 1,000 |
| Setup conflict adjudication | 1,200 | 400 |
| Position-manager exit | 600 | 200 |
| Pre-entry sanity check | 500 | 150 |
| EOD self-critique (per trade) | 1,500 | 800 |

If a prompt exceeds its budget, **summarise** upstream context — never just truncate mid-string.

## 8. Prompt engineering for token frugality

- Use **short field codes**, not prose, in repeated rows: `S=BREAKOUT V=2.1x RS=+0.4 PX=2451` not `Setup type is breakout, volume 2.1x average, relative strength positive 0.4, current price 2451`.
- Few-shots: 2–3 max, the most diverse, not the longest.
- System prompt: < 250 tokens, includes role + JSON-schema reminder + the three rules that matter.
- Drop conversational fluff ("please", "kindly").
- No markdown headers in prompts unless the model needs them; they're tokens.

## 9. Retry + backoff

Use `tenacity`. Standard retry policy for every Groq call:

```python
@retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
    wait=wait_random_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(5),
    before_sleep=lambda rs: log_retry(rs),
)
```

Special-case **429 with `Retry-After`** header — honour it exactly:

```python
if isinstance(e, RateLimitError) and (ra := e.headers.get("retry-after")):
    sleep(float(ra) + random.uniform(0.1, 0.5))
```

Never hammer; never zero-jitter.

## 10. Fallback path (degraded mode)

If Groq is unavailable for > 30 s or 429 budget choked at > 85 %:

1. Switch to **deterministic-only mode**.
   - Regime ← last known + heuristic refresh from Nifty + VIX numbers (no LLM).
   - Score ← engine's raw score (no LLM narrative).
   - News ← keyword polarity rules (-1 / 0 / +1) instead of LLM sentiment.
   - Conflict adjudication ← skip-the-trade default.
2. **Reduce position size to 50 %** — we trust ourselves less without the LLM layer.
3. Continue managing existing positions with code-only logic.
4. Surface a **degraded** banner on the dashboard.
5. Auto-recover when Groq budget returns to < 50 % utilisation for 5 consecutive minutes.

This is not a panic mode; it is a designed mode. Test it.

## 11. Concurrency & queuing

A single `GroqClient` singleton fronted by an `asyncio.Semaphore(N_concurrent)` and a `TokenBucket` rate limiter (per minute and per day).

```
producer  ── enqueue(call_spec) ──►  Queue ──►  worker(s)  ──►  Groq
                                       │
                                       └─►  budget guard (RPM/TPM)
```

- Concurrency cap is **lower** than Groq's parallel limit (`min(N_concurrent, RPM/60 × safety)`).
- Calls have priorities: regime > position-mgr > scoring batch > sentiment > sanity-check > EOD.
- Low-priority calls dropped first when budget tight.

## 12. Monitoring & alerting

Persist per-call telemetry (Prometheus / SQLite, your choice — start with SQLite):

- timestamp, model, latency_ms, prompt_tokens, completion_tokens, total_tokens, status, retry_count, was_cache_hit, priority.

Compute every minute:

- RPM utilisation %, TPM utilisation %, daily RPD %, daily TPD %.

Alert thresholds (dashboard banner + log):

- 70 % → yellow
- 85 % → orange (start dropping low-priority calls)
- 95 % → red (degraded mode)

EOD report includes a **token-burn-down** chart by hour and by call type. Anything above plan is a Phase 4 fix-list candidate.

## 13. Testing the rate-limit defence

Unit + integration tests required before Phase 6 sign-off:

1. **Mock Groq returning 429** → verify retry / fallback / no order placed twice.
2. **Mock Groq slow (3 s latency)** → verify timeout and budget recovery.
3. **Replay-mode load test:** simulate worst-case 09:20 IST opening minute — 60 candidates, 8 setups detected, regime EVENT — and confirm < 8 LLM calls / minute.
4. **Cache-hit ratio benchmark:** target ≥ 40 % steady-state.
5. **End-of-day burn-down:** verify daily token usage < 60 % of TPD ceiling at 15:30.

## 14. Five rules to print and tape to the monitor

1. **Code first, LLM last.**
2. **One call per decision, not per stock.**
3. **Cheap tier by default, strong tier on appeal.**
4. **Every call has a TTL'd cache key.**
5. **No exception is a 429.**
