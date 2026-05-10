# Setup Deletion Audit

*Generated: 2026-05-10T08:38:21 | DB: `trade_state_server_snapshot.db` | n = 280 closed trades*

> Read-only audit. Informs Phase E decision: which of 8 setups to delete, keep, or modify.

---

## ⚡ DECISIONS AT A GLANCE

| Setup | n | WR | Net Expectancy | Pure-play | Decision |
|---|---:|---:|---:|---:|---|
| momentum_breakout | 147 | 66.7% | -0.005R | 49.0% | 🔴 KILL |
| recovery_setup | 72 | 43.1% | -0.380R | 75.0% | 🔴 KILL |
| failed_breakdown | 31 | 29.0% | -0.374R | 87.1% | 🔴 KILL |
| vwap_reclaim | 12 | 41.7% | -0.394R | 58.3% | 🔴 KILL |
| trend_pullback | 10 | 50.0% | -0.404R | 30.0% | 🔴 KILL |
| vwap_pullback | 7 | 28.6% | -0.444R | 28.6% | 🔴 KILL |
| range_breakout | 1 | 100.0% | -0.269R | 100.0% | 🔴 KILL |

---

## Decision rules applied

- **🔴 KILL** if after-cost expectancy < 0R **OR** overall WR < 30.0% **OR** zero pure-play trades
- **🟢 SURVIVES** if after-cost expectancy ≥ +0.1R **AND** pure-play ≥ 5.0% **AND** WR ≥ 35.0% in ≥ 2 day-classes
- **🟡 MODIFY** otherwise (suggests day-class gating or demotion to confluence-only)

---

## Per-setup detailed metrics

### momentum_breakout — 🔴 KILL

**Trades:** 147  (98W / 49L = WR **66.7%**)  
**Total P&L:** ₹+106,190  
**Mean R (gross):** +0.159R  |  **Mean R (after costs):** -0.005R  
**Median R:** +0.100R  
**Stalled exit rate:** 55.1%  |  **Clean SL hit rate:** 13.6%  
**Avg confluence count:** 1.87  |  **Pure-play (this setup only):** 72 (49.0%)  
**Avg risk per trade:** ₹4,056  |  **Cost in R-multiples:** 0.164R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 03:00 | 3 | 33.3% |
| 04:00 | 15 | 80.0% |
| 05:00 | 13 | 69.2% |
| 06:00 | 19 | 94.7% |
| 07:00 | 9 | 88.9% |
| 08:00 | 7 | 100.0% |
| 09:00 | 10 | 60.0% |
| 10:00 | 13 | 46.2% |
| 11:00 | 15 | 53.3% |
| 12:00 | 13 | 38.5% |
| 13:00 | 7 | 42.9% |
| 14:00 | 23 | 65.2% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 142 | 66.9% |
| DEFENSIVE | 5 | 60.0% |

**Reasons for decision:**

- After-cost expectancy -0.005R < 0

---

### recovery_setup — 🔴 KILL

**Trades:** 72  (31W / 41L = WR **43.1%**)  
**Total P&L:** ₹-734  
**Mean R (gross):** -0.015R  |  **Mean R (after costs):** -0.380R  
**Median R:** -0.035R  
**Stalled exit rate:** 65.3%  |  **Clean SL hit rate:** 22.2%  
**Avg confluence count:** 1.43  |  **Pure-play (this setup only):** 54 (75.0%)  
**Avg risk per trade:** ₹1,570  |  **Cost in R-multiples:** 0.366R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 03:00 | 27 | 33.3% |
| 04:00 | 7 | 57.1% |
| 05:00 | 8 | 50.0% |
| 06:00 | 4 | 75.0% |
| 07:00 | 6 | 33.3% |
| 09:00 | 7 | 71.4% |
| 10:00 | 5 | 20.0% |
| 12:00 | 7 | 28.6% |
| 14:00 | 1 | 100.0% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 67 | 43.3% |
| DEFENSIVE | 5 | 40.0% |

**Reasons for decision:**

- After-cost expectancy -0.380R < 0

---

### failed_breakdown — 🔴 KILL

**Trades:** 31  (9W / 22L = WR **29.0%**)  
**Total P&L:** ₹+59,879  
**Mean R (gross):** +0.002R  |  **Mean R (after costs):** -0.374R  
**Median R:** -0.050R  
**Stalled exit rate:** 90.3%  |  **Clean SL hit rate:** 6.5%  
**Avg confluence count:** 1.32  |  **Pure-play (this setup only):** 27 (87.1%)  
**Avg risk per trade:** ₹4,128  |  **Cost in R-multiples:** 0.376R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 03:00 | 3 | 33.3% |
| 04:00 | 1 | 100.0% |
| 05:00 | 1 | 0.0% |
| 06:00 | 9 | 44.4% |
| 07:00 | 7 | 28.6% |
| 08:00 | 3 | 33.3% |
| 09:00 | 3 | 0.0% |
| 11:00 | 2 | 0.0% |
| 12:00 | 1 | 0.0% |
| 14:00 | 1 | 0.0% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 29 | 31.0% |
| DEFENSIVE | 2 | 0.0% |

**Reasons for decision:**

- After-cost expectancy -0.374R < 0
- Overall WR 29.0% < 30.0%

---

### vwap_reclaim — 🔴 KILL

**Trades:** 12  (5W / 7L = WR **41.7%**)  
**Total P&L:** ₹+867  
**Mean R (gross):** -0.022R  |  **Mean R (after costs):** -0.394R  
**Median R:** -0.030R  
**Stalled exit rate:** 66.7%  |  **Clean SL hit rate:** 16.7%  
**Avg confluence count:** 1.42  |  **Pure-play (this setup only):** 7 (58.3%)  
**Avg risk per trade:** ₹1,384  |  **Cost in R-multiples:** 0.372R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 04:00 | 3 | 66.7% |
| 05:00 | 1 | 100.0% |
| 07:00 | 1 | 0.0% |
| 09:00 | 5 | 20.0% |
| 10:00 | 2 | 50.0% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 12 | 41.7% |

**Reasons for decision:**

- After-cost expectancy -0.394R < 0

---

### trend_pullback — 🔴 KILL

**Trades:** 10  (5W / 5L = WR **50.0%**)  
**Total P&L:** ₹+5,941  
**Mean R (gross):** -0.132R  |  **Mean R (after costs):** -0.404R  
**Median R:** -0.025R  
**Stalled exit rate:** 40.0%  |  **Clean SL hit rate:** 30.0%  
**Avg confluence count:** 2.2  |  **Pure-play (this setup only):** 3 (30.0%)  
**Avg risk per trade:** ₹1,708  |  **Cost in R-multiples:** 0.272R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 09:00 | 4 | 50.0% |
| 10:00 | 1 | 0.0% |
| 11:00 | 2 | 50.0% |
| 12:00 | 1 | 100.0% |
| 13:00 | 1 | 100.0% |
| 14:00 | 1 | 0.0% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 7 | 42.9% |
| DEFENSIVE | 3 | 66.7% |

**Reasons for decision:**

- After-cost expectancy -0.404R < 0

---

### vwap_pullback — 🔴 KILL

**Trades:** 7  (2W / 5L = WR **28.6%**)  
**Total P&L:** ₹+44  
**Mean R (gross):** -0.010R  |  **Mean R (after costs):** -0.444R  
**Median R:** -0.200R  
**Stalled exit rate:** 71.4%  |  **Clean SL hit rate:** 0.0%  
**Avg confluence count:** 2  |  **Pure-play (this setup only):** 2 (28.6%)  
**Avg risk per trade:** ₹1,062  |  **Cost in R-multiples:** 0.434R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 10:00 | 3 | 33.3% |
| 12:00 | 3 | 33.3% |
| 13:00 | 1 | 0.0% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 6 | 33.3% |
| DEFENSIVE | 1 | 0.0% |

**Reasons for decision:**

- After-cost expectancy -0.444R < 0
- Overall WR 28.6% < 30.0%

---

### range_breakout — 🔴 KILL

**Trades:** 1  (1W / 0L = WR **100.0%**)  
**Total P&L:** ₹+145  
**Mean R (gross):** +0.120R  |  **Mean R (after costs):** -0.269R  
**Median R:** +0.120R  
**Stalled exit rate:** 100.0%  |  **Clean SL hit rate:** 0.0%  
**Avg confluence count:** 1  |  **Pure-play (this setup only):** 1 (100.0%)  
**Avg risk per trade:** ₹1,195  |  **Cost in R-multiples:** 0.389R  

**By hour of day (IST):**

| Hour | n | WR |
|---:|---:|---:|
| 12:00 | 1 | 100.0% |

**By day-class (PRESS/SELECTIVE/DEFENSIVE):**

| Day-class | n | WR |
|---|---:|---:|
| SELECTIVE | 1 | 100.0% |

**Reasons for decision:**

- After-cost expectancy -0.269R < 0

---

## Counterfactual deletion summary

If we delete every setup currently flagged **🔴 KILL**:

- **Trades removed:** 280
- **P&L removed:** ₹+172,332
- **If P&L removed is negative**, killing these setups improves total P&L by that amount
- **Setups to delete:** momentum_breakout, recovery_setup, failed_breakdown, vwap_reclaim, trend_pullback, vwap_pullback, range_breakout

## Methodology notes

1. **After-cost expectancy in R** uses ₹1,026 per round-trip (₹226 fixed + ₹500 spread + ₹300
   slippage), converted to R-multiples using each setup's average per-trade risk.
2. **Pure-play trade** = a trade where this setup was the ONLY one that fired (confluence_count=1).
   A setup with high pure-play rate carries unique edge that other setups don't catch.
3. **Day-class backfill** uses regime + score_breakdown.breadth_pen as a proxy. Trades from before
   regime persistence (Fix #14) may default to SELECTIVE.
4. **Stall rate** counts exit_reason matches: stall, time_stop, no_movement, eod_partial_unwind.
5. **Setup audit is decision input only.** Final survive/kill/modify decisions require operator
   approval. The script does not auto-modify code.

---

## What happens next

1. Operator reviews this report.
2. Operator approves which 🔴 setups to delete and how 🟡 setups should be modified.
3. Phase E ships the deletion + modification commit.
4. `tests/test_engine.py` is updated to remove tests for deleted setups.
5. Setup count reduces from 8 → fewer (target ≤ 4).
