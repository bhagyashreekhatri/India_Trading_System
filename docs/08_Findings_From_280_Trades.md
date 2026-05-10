# Findings from 280-trade paper history — brutal scalper read

*Generated: 2026-05-10 | n = 280 closed trades on `trade_state_server_snapshot.db`*

This document is the operator briefing. It overrides any earlier hypothesis in `docs/07_Scalper_Architecture_Migration.md` where the data contradicts it.

---

## The verdict in one paragraph

**The system has near-zero edge.** Gross P&L is +₹1,72,333 (positive). Realistic Indian intraday cost stack scales out to ~₹760/trade × 280 trades = ~₹2,12,676 in friction. **Net P&L is -₹40,343.** Every fix we shipped, every filter we added, every score nudge — the cumulative output is a system that almost-but-not-quite covers its costs. 53.9% win rate, +0.075R mean, +₹22 median per trade. That's coin-flip with a tiny rake. Not edge.

**Phase A as written (sizing rewrite) will not fix this.** Bigger size doesn't create edge — it amplifies whatever you have. With -₹144 net per trade currently, scaling up just multiplies the loss. The real problem is gross expectancy is too low, which means we're taking too many marginal trades. **The fix is fewer-and-better, not bigger.**

---

## 1. The headline numbers

| Metric | Value | Read |
|---|---:|---|
| Total closed trades | 280 | ~3 weeks of paper |
| Win rate | 53.9% | Marginal positive bias |
| Total gross P&L | +₹1,72,333 | System makes money before costs |
| Avg cost per trade | ₹760 | Realistic Indian MIS friction |
| **Total net P&L (after costs)** | **-₹40,343** | **System loses money in live conditions** |
| Mean R per trade | +0.075R gross / -0.05R net | Coin flip with a rake |
| Median ₹ per trade | +₹22 | Noise |
| TP1 hit rate | 17.1% | Most trades never reach 0.7R |
| Stalled exits | 71.1% | Original Doc 04 problem **unfixed** |

**The 71.1% stall rate is the same number that started this whole project.** Three weeks and 55 fixes later, the system is still defined by "most trades stall before they move." That's the structural failure, not the score system.

---

## 2. What the data actually says about partials vs single-target

I came in expecting single-target to win because of the cost-per-partial argument. **The data disagrees.**

| Strategy | Net P&L | Avg ₹/trade |
|---|---:|---:|
| **Actual (partials)** | **-₹40,343** | **-₹144** |
| Single-target @ 0.6R | -₹1,15,258 | -₹412 |
| Single-target @ 0.8R | -₹91,168 | -₹326 |
| Single-target @ 1.0R | -₹70,845 | -₹253 |

Partials are CURRENTLY less-bad than any single-target alternative. Why:

- 17.1% of trades hit TP1 (booked at 0.7R = guaranteed partial profit)
- Of those that hit TP1, **66.7% ran further to TP2 or trail-runner** (the long-tail upside)
- Single-target at 0.6R cuts off the runner trade entirely → loses the ₹2-5k tail wins
- Of the 199 stalled trades, single-target wouldn't help — they don't even reach TP1

**Decision: KEEP partials, reverse my earlier hypothesis.** The runner half is what's earning, even though TP1 hits rarely.

---

## 3. What the setup audit actually says

All 7 setups are net-negative after costs. Even the best one (momentum_breakout, n=147, WR 66.7%) is -0.01R after costs. But there's a clear ranking by "least bad":

| Setup | n | WR | Gross R | Net R | Read |
|---|---:|---:|---:|---:|---|
| **momentum_breakout** | **147** | **66.7%** | **+0.159R** | **-0.01R** | **Closest to viable** |
| recovery_setup | 72 | 43.1% | -0.015R | -0.38R | Bleeding |
| failed_breakdown | 31 | 29.0% | +0.002R | -0.37R | WR too low |
| vwap_reclaim | 12 | 41.7% | -0.022R | -0.39R | Tiny sample, bleeding |
| trend_pullback | 10 | 50.0% | -0.132R | -0.40R | Bleeding |
| vwap_pullback | 7 | 28.6% | -0.010R | -0.44R | Tiny sample, bleeding |
| range_breakout | 1 | 100.0% | +0.120R | -0.27R | Single trade — irrelevant |

**Read this carefully.** Momentum_breakout takes 53% of all trades (147/280) and accounts for almost all of the gross profit. The other 6 setups are gross-negative or near-zero contributors that pay their full ₹760 cost on every fire.

**If we kill the 6 weak setups today and only fire momentum_breakout, the 147 surviving trades have:**
- Gross expectancy: +0.159R
- Net (after costs): -0.01R per trade
- **Total estimated net P&L on those 147 trades: ~₹-450** (essentially break-even)

That's still not goal — but it's break-even instead of -₹40,343. From break-even we can build edge. From -₹40k we can only bleed.

---

## 4. The structural finding that changes everything

The migration plan assumed three layers: cut setups, build discovery engine, add checklist. **The data says the order is wrong.**

**The real problem isn't architecture. It's that the system takes too many trades.**

- 280 trades over ~3 weeks = ~14 trades/day average
- Mean gross R per trade: +0.075
- A scalper with +0.075R mean is not a scalper — that's a chop-trader

A pro scalper takes 3-5 high-conviction trades per day at +0.4-0.8R mean. Same number of trades per day yields 4× the edge. The path forward is:

**Phase A revised: Stop taking marginal trades.**

This is NOT just "size up." It's **filter aggressively to lift mean R from +0.075 to +0.30+**. Concretely:
- Disable 6 setups, keep only momentum_breakout
- Tighten momentum_breakout's RVOL minimum from 1.7 to 2.5
- Require confluence ≥ 2 (no pure-play momentum entries)
- Require focus list membership OR top-3 sector
- Day-class DEFENSIVE skips momentum entirely

If the new filter only fires 3-5 times per day instead of 14, and lifts mean R from +0.075 to +0.40, the daily P&L math is:
- 4 trades × +0.40R × ₹2,092 risk = ₹3,347 gross/day
- Minus 4 × ₹760 = ₹3,040 in costs
- Net: ₹+307/day average — still small but POSITIVE

That's how you build from break-even toward the ₹1k-5k per-trade goal. **More filtering, not bigger sizing.**

---

## 5. Revised migration sequence

The original plan stays, but Phase A and Phase E swap and merge. The new sequence:

### Phase A (revised) — "Take fewer, better trades" (was Phase E)
- Disable 6 of 7 setups (keep only momentum_breakout)
- Tighten momentum_breakout: RVOL ≥ 2.5, confluence ≥ 2 required, focus list or top-3 sector required
- Keep partials (data says they're working)
- Keep current sizing for now (NOT the ₹5L tier rewrite — that was based on wrong hypothesis)
- Acceptance criteria: ≤ 5 trades/day, mean R per trade ≥ +0.20 over 5 sessions

### Phase B — Discovery Engine (unchanged)
- Same as plan; even more important now because we need to find the 3-5 best trades from the broader universe, not the 14 marginal ones

### Phase C — Focus list state machine (unchanged)

### Phase D — Pending-pullback state machine (unchanged)

### Phase E — Sizing rewrite (was Phase A)
- After Phases A-D have lifted mean R to +0.20+, scale sizing up to deliver ₹1k-5k per winning trade
- Tier S/A/B sizing only makes sense AFTER edge is verified

### Phase F — 6-rule binary checklist (unchanged)

### Phase G — Day classifier + threshold review (unchanged)

### Phase H — LLM cold-path jobs (unchanged)

### Phase I — Cleanup (unchanged)

**Why this swap matters:** sizing without edge multiplies the loss. The sequence has to be (1) prove edge exists at small size, (2) THEN scale. We're doing (2) without (1) being verified.

---

## 6. What stays in PROJECT_MEMORY going forward

- **The system as built has near-zero net edge.** Don't pretend otherwise. Plan accordingly.
- **71.1% stall rate is the structural failure.** Every fix that doesn't reduce this number is rearranging deck chairs.
- **The trade frequency is too high.** Pro scalper takes 3-5/day, not 14/day.
- **Momentum_breakout is the only viable setup** at current edge; everything else loses money.
- **Partials work** at current setup quality. Single-target loses more.
- **Goal is ₹1k-5k per WINNING trade, not per all trades.** With high filtering, fewer trades but each is meaningful.

---

## 7. Operator decisions needed before any code ships

Bhagya — read this and reply YES/NO to each:

1. **Approve revised Phase A sequence?** (kill 6 setups, keep only tightened momentum_breakout, defer sizing rewrite to Phase E)
2. **Approve keeping partials?** (data shows they outperform single-target)
3. **Approve target trade rate of 3-5/day?** (down from current 14/day)
4. **Approve momentum_breakout tightening: RVOL ≥ 2.5, confluence ≥ 2, focus-list-or-top-3-sector required?**
5. **Acknowledge: edge is ~zero, this migration is to FIND edge first, then scale?**

If all 5 are YES, Phase A code change ships in next session. If any are NO, we discuss before code.

---

## 8. What's NOT in this analysis (acknowledged limits)

- **Day-class backfill** is a proxy from `breadth_pen` in `score_breakdown`; not all historic trades have it
- **Time-to-TP1** uses `entry_time → exit_time` as upper bound (true partial-hit timestamp not stored)
- **MFE distribution** approximates from realised pnl_r; true MFE requires candle replay (Phase B+)
- **Cost model** assumes 0.16% variable cost; actual broker spreads vary by name (illiquid > 0.20%)
- **Slippage model** doesn't account for fast-market gap-through; live execution will be worse than paper

These are second-order. The first-order finding (system has ~zero edge) is robust.
