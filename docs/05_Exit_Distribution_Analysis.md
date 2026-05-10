# Exit Distribution Analysis

*Generated: 2026-05-10T08:38:20 | DB: `trade_state_server_snapshot.db` | n = 280 closed trades*

> Read-only analysis. Informs Phase A decision: single-target vs partials.

---

## ⚡ DECISION

🟡 **MIXED SIGNAL — compare net P&L of simulations below.**

Median R 0.03, TP1-then-SL rate 0.0%. Neither side wins cleanly. Use the simulation block below to decide on net P&L grounds.

**Net P&L comparison — costs scaled to actual per-trade position size**
(avg cost: ₹760/trade — fixed ₹226 + 0.16% of position value):**

| Strategy | Net P&L (₹) | Avg ₹/trade | Hit rate |
|---|---:|---:|---:|
| **Actual (current partials)** | -40,343 | -144 | TP1 17.1% |
| Simulated single-target @ 0.6R | -115,258 | -412 | 16.4% |
| Simulated single-target @ 0.8R | -91,168 | -326 | 14.3% |
| Simulated single-target @ 1.0R | -70,845 | -253 | 10.7% |

---

## 1. Headline numbers

- **Total closed trades:** 280
- **Win rate:** 53.9% (151 W / 129 L)
- **TP1 hit rate:** 17.1%
- **Mean R per trade:** +0.075R
- **Median R per trade:** +0.030R
- **Mean ₹ per trade:** ₹+615
- **Median ₹ per trade:** ₹+22

## 2. Realised R distribution

| Percentile | R-multiple |
|---|---:|
| p10 | -1.00R |
| p25 | -0.13R |
| **p50 (median)** | **+0.03R** |
| p75 | +0.19R |
| p90 | +1.09R |

## 3. ₹ P&L distribution

| Percentile | ₹ |
|---|---:|
| p10 | -1,123 |
| p25 | -228 |
| **p50 (median)** | **+22** |
| p75 | +649 |
| p90 | +2,064 |

## 4. What happens AFTER TP1 hits

- TP1 hit then trade went on to runner / TP2: **66.7%**
- TP1 hit but trade reversed and stopped out (worst pattern): **0.0%**
- TP1 hit and exit at TP1 only (no runner): **33.3%**

> If TP1-then-SL > 25%, partials are actively bleeding from runners that turn into losers.

## 5. Time to TP1

- Median: 38.5 min  (from entry_time to exit_time as proxy)
- p90: 89.0 min

## 6. Exit reason buckets

| Bucket | Count | % |
|---|---:|---:|
| stalled_no_movement | 199 | 71.1% |
| tp2_or_runner | 32 | 11.4% |
| sl_hit_clean | 29 | 10.4% |
| tp1_only | 16 | 5.7% |
| other | 4 | 1.4% |

## 7. Per-setup P&L summary (high-level — see setup_audit.py for full)

| Setup | n | Mean R |
|---|---:|---:|
| momentum_breakout | 147 | +0.159R |
| recovery_setup | 72 | -0.015R |
| failed_breakdown | 31 | +0.002R |
| vwap_reclaim | 12 | -0.022R |
| trend_pullback | 10 | -0.132R |
| vwap_pullback | 7 | -0.010R |
| range_breakout | 1 | +0.120R |

---

## Methodology notes

1. **Cost model — scales with actual position size.** Each trade's cost is computed from its
   own (entry × qty), not a fixed assumption. Components: ₹226 fixed (brokerage+STT+exchange+
   GST+SEBI+stamp) + 0.16% of position value (0.10% spread + 0.06% slippage).
2. **Partials extra cost** = half-fixed (₹113) + 0.08% of half-position value, charged on every
   trade where TP1 hit (i.e., one extra mid-trade exit was paid for).
3. **Single-target simulation** approximates max-favourable-excursion using realised pnl_r. True
   MFE requires candle replay (Phase A+ work). The approximation is conservative — it under-
   counts trades that touched a higher target and reversed before exit, so simulated single-
   target hit rates are likely undercounted.
4. **Net P&L** = gross trade P&L − all-in costs scaled to each trade's own position size.

---

## What happens next

- If decision = KILL PARTIALS: Phase A ships single-target exit logic + sizing to deliver
  ₹1k-5k per trade in the bottom-of-target band.
- If decision = KEEP PARTIALS: Phase A keeps the partial logic but tightens TP1 to the target
  derived from the median R distribution.
- If decision = MIXED: pick the simulation column with highest net P&L; that's the rule.

This decision is APPROVED by the operator before Phase A code change ships.
