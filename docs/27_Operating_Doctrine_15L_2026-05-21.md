# Operating Doctrine — ₹15L NSE Equity Book (2026-05-21)

**Mandate:** Protect capital. Grow it consistently. Build a survivable long-term
operation. Optimize for survival, expectancy, consistency, compounding — never
for excitement or daily activity.

> Status of the numbers below: cost/liquidity figures are NSE arithmetic.
> Win-rate / drawdown / return figures are **professional estimates, not a
> verified backtest.** A clean 1–2yr multi-regime backtest is the next step
> (see §10). Do not treat the return ranges as promises.

---

## 1. Core philosophy

- **Capital preservation first.** The job is to still be here in 5 years. A thin
  edge only compounds if it is never exposed to a ruinous loss.
- **Selectivity beats frequency.** Edge is concentrated in specific regimes and
  setups. Trading every day is a leak, not a virtue.
- **Cash is a position.** On many days the correct trade is none.
- **Two engines, each where it has edge:** machine scalps (speed/discipline/
  frequency); human governs and trades the slower timeframe (regime/judgment).

---

## 2. Capital allocation

| Bucket | Size | Purpose |
|---|---|---|
| Reserve / liquid | ~₹9–11L (60–70%) | Buffer; never at risk; dry powder for A-regimes |
| Core working capital | ~₹3–4L | Discretionary/systematic intraday–short-swing (the compounding engine) |
| Scalp satellite | ~₹1–2L notional/trade, ≤5 concurrent | Automated, regime-gated, OFF in chop |

**Never deploy the full ₹15L.** Default posture is mostly flat. Full risk
budget is engaged only in high-probability regimes (§7).

---

## 3. Risk management (hard rules)

- **Risk per trade:** 0.25–0.5% of capital = **₹3,750–₹7,500**. Sized by
  distance to invalidation, not by a fixed share count.
- **Daily loss limit:** **₹30,000 (~2%)** → halt new entries for the day.
- **Monthly circuit breaker:** **−5% to −6%** in a month → stop all new risk,
  go to review, resume only after written diagnosis.
- **Max gross exposure:** cap well below full leverage; never "all in."
- **Per-trade liquidity cap:** position ≤ a small % of the name's recent 5-min
  volume, so you are never the move (slippage control).
- **No averaging down. Ever.** Scale OUT of strength, never INTO weakness.
- **Costs are a line item.** Every trade's target must clear round-trip friction
  (~0.05–0.07% all-in + slippage) with margin. This kills sub-0.4% scalp targets
  unless automated and high-hit-rate.

---

## 4. Position sizing formula

```
qty = risk_rupees / (entry - stop)            # structure-based
qty = min(qty, notional_cap / entry)          # notional cap
qty = min(qty, liquidity_cap)                 # ≤ x% of recent volume
```

Scalp satellite uses fixed notional (₹2L) + the ATR-scaled stop already shipped.
Core book uses risk-based sizing at 0.25–0.5% with 1:2+ reward:risk.

---

## 5. Regime filter (governs both engines)

Classify the day before risking anything:

- **Trend (up/down):** index expanding from VWAP, breakouts holding, breadth
  one-sided. → Best regime. Press with the trend.
- **Range / balanced:** price mean-reverts around VWAP, breakouts fail. → Fade
  edges small, or sit. Scalp satellite: reduce or OFF.
- **Low volatility:** no range to pay costs. → Mostly flat.
- **High-vol / panic:** biggest R and biggest danger. → Smaller size, wider
  stops, A+ setups only.

**Scalp engine is ENABLED only when:** RVOL/volatility adequate AND not a pure
bearish-breadth chop day. It is OFF on low-vol chop (e.g. 2026-05-21 morning:
TREND_FORMING_DN + bearish breadth → death-by-scratches).

**Both engines stand down on:** scheduled event days (policy/results/expiry
whips), the first few minutes of violent gaps, post-cap, and operator tilt.

---

## 6. When to stay FLAT

Mid-range chop · low RVOL · pre/post major news · spread wide / book thin ·
index vs stock disagree · can't define risk in one sentence · daily cap hit ·
you're tilted or revenge-seeking. **Flat is the default, not the exception.**

---

## 7. When to deploy AGGRESSIVELY

Only when ALL align: clean trend day · breadth + volume confirming · your A-setup
· defined tight risk · costs comfortably cleared by the target. Then scale size
toward the upper risk band and let winners run. These days are rare and carry
most of the year's P&L — do not dilute them by having blown the budget on chop.

---

## 8. Trading frequency

- Core book: a handful of high-quality trades per week. Not daily.
- Scalp satellite: many small shots, but ONLY in enabled regimes, hard-capped
  by the daily loss limit and max concurrent positions.
- Measure quality (expectancy per trade, net of costs), never trade count.

---

## 9. Automation map

| Function | Owner |
|---|---|
| High-frequency scalp execution | **Machine** (can't be out-clicked; enforces discipline) |
| Order-flow / live book reading | **Machine** (the dynamic stream) |
| Regime classification | Machine assists, **human decides** |
| Intraday / short-swing entries | **Human** (discretionary + systematic signals) |
| Risk posture (run hot / size down / flat) | **Human** governs |
| Journal + weekly review + tuning | **Human** |

The human's highest-value work is **governing the machine and reading regime**,
not clicking entries.

---

## 10. Honest expectations & next step

- **Year 1 success = not blowing up + proving a small real edge.** Flat-to-
  modestly-green with controlled drawdowns. Scale only after a full cycle
  (trends + chop + one panic) is survived.
- Realistic compounding in capable hands is **modest** (low single-digit % per
  month on deployed capital, *with losing months*), not 10%+/month. Most retail
  does worse. Plan for that, not for the fantasy.
- **Verification backtest to run next:** fetch NIFTY + a liquid basket over
  1–2yr → label each day by regime (trend/range/vol) → simulate the scalp rules
  AND a simple intraday trend/mean-reversion rule bar-by-bar with real costs +
  slippage → walk-forward → report win rate, expectancy, max drawdown, and
  return *by regime*. Only then do the return ranges above become facts.

---

## 11. The decision

**Semi-automated hybrid, capital-preservation-first.** Automated scalp engine as
a small, capped, regime-gated satellite (OFF in chop). Discretionary +
systematic intraday/short-swing as the core compounding engine. Majority of
capital in reserve. Aggressive deployment only in high-probability regimes.

Rationale: puts the machine where humans can't win (speed, discipline,
frequency) and the human where machines can't win (regime, selectivity,
judgment), and refuses to bet the franchise on manual scalping — the one style
the cost math and the algos have made nearly unwinnable for a solo human.
