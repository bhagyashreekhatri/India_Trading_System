# 09 — Learning Mode Design

> The agent must improve every day, not just trade every day. This document specifies how learning happens — what gets remembered, who critiques, who proposes changes, who approves them, how proposals get validated, and how rollouts and rollbacks work. The 151-trade week is the bootstrap dataset; every future trade extends it.

---

## 1. Goals

- Capture **every decision** the agent made and its outcome, with enough fidelity to second-guess in the morning.
- Convert outcomes into **structured lessons** — patterns, not anecdotes.
- Feed lessons back into prompts, weights, vetoes, and the regime × setup multiplier table — **without** breaking the live agent.
- Detect drift early and pause before damage accumulates.
- Keep the human in the loop on parameter changes, but make the proposal pipeline so good that approvals are a rubber stamp ≥ 80 % of the time.

## 2. What gets remembered

Three Chroma collections + one SQLite table.

### 2.1 `trade_memory` (Chroma)
For every closed trade, write **one document** containing:

```json
{
  "trade_id": "...",
  "ts_entry": "...",
  "ts_exit": "...",
  "symbol": "...",
  "sector": "...",
  "direction": "LONG|SHORT",
  "setup_type": "...",
  "regime": "...",
  "score": 8.4,
  "grade": "A+",
  "score_components": { "setup_quality": 2.5, "volume": 1.8, ... },
  "reasoning_chain": [
    {"agent": "regime", "summary": "...", "model": "T1", "tokens": 312},
    {"agent": "setup", "summary": "...", "model": "deterministic"},
    {"agent": "scoring", "summary": "...", "model": "T1", "tokens": 188},
    {"agent": "sanity", "summary": "...", "model": "T1", "tokens": 142}
  ],
  "vetoes_passed": ["spread_ok","not_near_circuit","no_news_embargo"],
  "entry_price": 2451.05,
  "stop_price": 2438.00,
  "target_price": 2470.00,
  "exit_price": 2467.30,
  "exit_reason": "TARGET",
  "qty": 30,
  "gross_pnl": 487.50,
  "costs": 78.40,
  "net_pnl": 409.10,
  "slippage_bps_entry": 4.1,
  "slippage_bps_exit": 5.0,
  "rvol_entry": 2.3,
  "rs_entry": 0.42,
  "vix_entry": 13.8,
  "nifty_move_during_trade_bps": 12,
  "news_at_entry": [{"id":"...","polarity":1,"magnitude":0.6}],
  "self_critique": null
}
```

`self_critique` is filled by the EOD job (§4).

The text used for embedding is a **compact narrative** — one paragraph mentioning setup, regime, score, what worked or failed, and the exit reason. This makes semantic search useful (e.g., "show me losing VWAP-pullback trades in CHOPPY regime").

### 2.2 `setup_memory` (Chroma)
Aggregated rolling stats per `(symbol, setup_type, regime)` triple. Updated nightly from `trade_memory`.

```json
{
  "key": "RELIANCE|VWAP_PULLBACK|TRENDING",
  "n_trades_30d": 8,
  "n_trades_90d": 19,
  "win_rate_30d": 0.62,
  "avg_net_pnl_30d": 612,
  "profit_factor_30d": 2.1,
  "last_outcome_streak": "WLLWWWW"
}
```

Used by the scoring agent to nudge: a hot triple gets a small bump; a cold triple gets a small fade. Bounded: ±0.3 of multiplier max.

### 2.3 `regime_memory` (Chroma)
Daily regime classification + features (Nifty trend, VIX percentile, breadth, FII/DII print). Lets the regime agent compare today to historical analogues.

### 2.4 `agent_telemetry` (SQLite)
Per-call: timestamp, agent, model tier, prompt tokens, completion tokens, latency, status, retry count, cache hit. Powers file 05's monitoring and the Groq dashboard widget.

## 3. The end-of-day pipeline

Triggered at 15:35 IST after square-off and reconciliation.

```
EOD job:
  1. Snapshot trade_memory adds for the day
  2. For each closed trade:
        a. Build self-critique prompt (T3 model, batched)
        b. Receive structured critique JSON
        c. Write back into trade_memory document
  3. Refresh setup_memory rolling aggregates
  4. Compute day's metrics → file 04 numbers
  5. Compute Groq budget burn-down → telemetry
  6. Run drift detector
  7. (Weekly only — Sundays) generate proposed parameter changes
  8. Render weekly review markdown into docs/weekly/YYYY-WW.md
```

## 4. Self-critique prompt (per closed trade, T3, batched)

Schema-locked output:

```json
{
  "trade_id": "...",
  "what_worked": ["..."],
  "what_didnt": ["..."],
  "process_grade": "A|B|C|D|F",
  "process_violations": ["entry_too_far_from_signal", "..."],
  "would_take_again": true,
  "improvement_action": "specific, code-actionable suggestion or 'none'",
  "tag": "good_trade_good_outcome | good_trade_bad_outcome | bad_trade_good_outcome | bad_trade_bad_outcome"
}
```

The 2×2 (process × outcome) tag is the single most useful learning artefact. **Bad-trade-good-outcome** is the most dangerous bucket — it teaches bad habits if rewarded. The agent must explicitly down-weight reasoning patterns that fall into it.

Batched: send 10 trades per call. Off-hours, T3 model. Costs scale linearly, not multiplicatively.

## 5. Failure-pattern clustering (weekly)

On Sundays, embed all losing trades from the trailing 30 days, run k-means / HDBSCAN to discover clusters, label each cluster with an LLM call ("what does this group of trades have in common?"), and surface to the weekly review.

Output looks like:

```
Cluster A (12 trades): "Late-entry VWAP pullbacks in CHOPPY regime"
  Recommendation: raise required pullback hold-time from 2 to 3 bars.
Cluster B (7 trades): "Failed breakdown reversals on expiry days"
  Recommendation: cap setup_quality contribution at 2.0 on expiry days.
Cluster C (6 trades): "Momentum BO long against falling sector"
  Recommendation: harden sector-alignment veto at 0.5 ATR sector-against threshold.
```

## 6. Proposal → approval → validation → rollout pipeline

This is the rigorous part. Nothing changes weights, prompts, or rules without going through it.

### 6.1 Proposal
A weekly job emits a `proposals/YYYY-WW.json` file:

```json
[
  {
    "id": "P-2026-W18-01",
    "type": "regime_multiplier",
    "change": {"setup": "MOMENTUM_BO", "regime": "CHOPPY", "from": 0.6, "to": 0.55},
    "evidence": {"n_trades": 23, "win_rate": 0.31, "profit_factor": 0.78},
    "expected_effect": "small_neg_filter_strengthen",
    "risk": "low"
  },
  {
    "id": "P-2026-W18-02",
    "type": "veto_rule",
    "change": "Add: skip if setup is RANGE_BREAKOUT and time-of-day in 12:00-13:00",
    "evidence": "...",
    "risk": "low"
  }
]
```

### 6.2 Approval
Bhagya reviews in the dashboard's *Proposals* tab. Each proposal: approve / reject / defer. Approved proposals go to validation, not directly to live.

### 6.3 Validation (replay + paper A/B)

For approved proposals:

1. **Replay validation:** run the proposal against the trailing 90-day trade dataset (replay harness from Phase 0). Generate a comparison table: net P&L, win rate, profit factor, max drawdown, with/without the change. Reject the proposal if the change degrades either profit factor or drawdown.
2. **Paper A/B (optional, for higher-risk changes):** for one trading week, half the universe runs the new rule, half runs the old. Track per-side metrics on rolling 30 trades. The change is rolled out only if the new side outperforms with statistical confidence.

### 6.4 Rollout
- Update the relevant config / prompt file.
- Bump the config version in `CHANGELOG.md`.
- Tag the date in `trade_memory` so future analysis can split before/after.
- Monitor for 5 trading days post-rollout; auto-rollback if rolling 30-trade win rate degrades by ≥ 5 pp.

## 7. Drift detector

Runs every EOD, and a fast version runs every 30 min during the session:

- Rolling 30-trade win rate falls below `(historical_win_rate - 5pp)` → **WARN**.
- Rolling 30-trade profit factor falls below `(historical_pf × 0.7)` → **PAUSE entries**, alert.
- Daily drawdown ≥ 1.5 % → drawdown sizing tier (file 08 §5; file 06 RSK-13).
- 7 consecutive losses → 60-min pause regardless of win-rate.

When PAUSED, the agent continues managing existing positions, does not enter new ones, and emits a banner. Resumption requires either time elapsed + metric recovery, or explicit operator un-pause.

## 8. Score-to-outcome calibration

A weekly calibration plot is generated:
- x-axis: score (0–10 in 0.5 buckets).
- y-axis: realised mean net P&L (and win rate).
- Overlaid: count of trades per bucket.

Healthy calibration is monotone increasing. Plateaus or inversions point to broken weights and feed file 04 §7's analysis.

## 9. Prompt-version learning

Prompts are files under `prompts/` with semver. Every prompt change is a proposal that goes through §6. We track per-prompt-version metrics:

- Token usage per call (target: down each version).
- Cache hit rate (target: up).
- Downstream score-to-outcome calibration slope (target: up).

Prompts are not edited in-place during a session. Ever. Even small wording changes go through the pipeline, because in agentic systems, small wording changes are not small.

## 10. The 151-trade bootstrap

Use the existing log to:

1. **Calibrate the scoring engine's weights** — file 04 §7 produces a current calibration; file 09 §6 proposes weight nudges.
2. **Seed setup_memory** — write 151 aggregated entries into the rolling stats.
3. **Bootstrap failure-pattern clustering** — even 151 trades produce 3–6 distinct clusters worth examining.
4. **Initialise self-critique** — run the §4 critique pass on all 151 retroactively. This single pass is the cheapest, highest-yield learning step in the project.
5. **Ground the regime × setup multiplier table** — replace the educated guesses with at least one round of data-informed multipliers.

## 11. Hard rules of learning mode

- Learning **never** writes directly to live config. Always proposal → approval → validation → rollout.
- Learning **never** changes the risk floor (1 %, 2.5 %, 1.5R, 5 positions, 30 % sector, 09:20 / 15:00 / 15:15 windows). Those are constants of the system.
- Learning **never** removes a veto. It can add vetoes; only humans remove them.
- Learning **never** raises position sizing without 4 weeks of stable performance behind it.
- Learning **always** logs its proposed-vs-applied delta. If a proposal failed validation, the *reason* is logged. We learn from rejected proposals too.

## 12. The shape of a good week (operator's view)

By Sunday evening, a `docs/weekly/YYYY-WW.md` exists with:

- Headline P&L, win rate, profit factor, max drawdown.
- Setup × regime heatmap.
- Top 3 winners and top 3 losers with self-critique.
- Failure-pattern clusters of the week.
- 3–6 proposals ready for approval.
- Token-burn-down and Groq health.
- Two sentences from the system: *what surprised us, what we'd do differently.*

That document is the heartbeat of the project. As long as it gets written every Sunday, the agent is learning.
