# Phase A Smoke Test — Counterfactual Replay

*Generated: 2026-05-10T09:28:53 | n input = 280 closed trades*

> Replays historical trades through the new Phase A filters. Cannot predict
> tomorrow's tape — only shows what filter logic would have done yesterday.

---

## Headline comparison

| Metric | Actual (no Phase A) | STRICT mode | APPROX mode |
|---|---:|---:|---:|
| Trades taken | 280 | 45 | 71 |
| Trades/day | 23.33 | 7.5 | 6.45 |
| Win rate | 53.9% | 51.1% | 63.4% |
| **Mean R** | **+0.075R** | **+0.107R** | **+0.114R** |
| Median R | +0.030R | +0.010R | +0.050R |
| Gross P&L | ₹+172,333 | ₹+10,195 | ₹+24,646 |
| Total costs | ₹201,833 | ₹21,385 | ₹36,886 |
| **Net P&L** | **₹-29,500** | **₹-11,190** | **₹-12,239** |
| Avg ₹/trade (net) | ₹-105 | ₹-249 | ₹-172 |

## Filter kill counts

### STRICT mode (confluence ≥ 2 required, sector check skipped)
- `setup_disarmed_recovery_setup`: 72 trades killed
- `momentum_no_priority`: 57 trades killed
- `momentum_low_volume`: 45 trades killed
- `setup_disarmed_failed_breakdown`: 31 trades killed
- `setup_disarmed_vwap_reclaim`: 12 trades killed
- `setup_disarmed_trend_pullback`: 10 trades killed
- `setup_disarmed_vwap_pullback`: 7 trades killed
- `setup_disarmed_range_breakout`: 1 trades killed

**Total killed: 235 of 280**
**Survivors: 45 (16.1%)**

### APPROX mode (confluence ≥ 2 OR sector ∈ {IT, PHARMA, AUTO, BANKING, FINANCE, METALS, ENERGY, FMCG, REALTY})
- `setup_disarmed_recovery_setup`: 72 trades killed
- `momentum_low_volume`: 45 trades killed
- `setup_disarmed_failed_breakdown`: 31 trades killed
- `momentum_no_priority`: 31 trades killed
- `setup_disarmed_vwap_reclaim`: 12 trades killed
- `setup_disarmed_trend_pullback`: 10 trades killed
- `setup_disarmed_vwap_pullback`: 7 trades killed
- `setup_disarmed_range_breakout`: 1 trades killed

**Total killed: 209 of 280**
**Survivors: 71 (25.4%)**

---

## What this means

### Best case (APPROX mode — closer to real live behaviour)
- Trades drop from **23.33/day → 6.45/day** (72% reduction)
- Mean R lifts from **+0.075R → +0.114R** (+0.039R improvement)
- Net P&L: **₹-29,500 → ₹-12,239** (delta: ₹+17,261)

### Worst case (STRICT mode — pure confluence requirement, no sector OR fallback)
- Trades drop to **7.5/day**
- Mean R: **+0.107R**
- Net P&L: **₹-11,190**

### Decision criteria (from `docs/08_Findings_From_280_Trades.md`)
- Target trade rate: 3-5/day
- Target mean R: +0.30R+
- Target: net P&L ≥ break-even, ideally positive

### Verdict
🟡 **PHASE A IS MARGINAL** — improvement is small. Consider whether to ship as-is or revise priority criteria.

---

## Methodology caveats

1. **`top_sectors` not stored historically** — STRICT mode skips sector check; APPROX mode uses
   a hand-picked list of historically-frequent top sectors. Real live behaviour falls between
   these two passes.
2. **RVOL not stored** — used `volume_strength` score from `score_breakdown` as proxy. A
   `volume_strength ≥ 1.4` roughly corresponds to RVOL ≥ 2.0 per the scoring engine's mapping.
   May misclassify edge cases.
3. **No counterfactual entry timing** — Phase A allows confluence-detection to keep running on
   disarmed setups, which means real-tomorrow `confluence_count` may differ from historical
   confluence count (the disarmed detectors fire less often if scoring filters them earlier).
   This estimate slightly overcounts surviving confluence-priority trades.
4. **Cost model** scales with actual position size. Same model as `analyze_exit_distribution.py`.
5. **APPROX sector list** is heuristic — actual top-3 changes per session. A real momentum trade
   in CEMENT (not in the list) on a day CEMENT was strong would be incorrectly killed in this
   simulation but would correctly fire live.

---

## Bottom line

If APPROX projection shows positive direction (mean R up, net P&L up, trade rate down toward
target), Phase A deserves to run. Tomorrow's data is the real test.

If projection is negative or marginal, revise filters BEFORE deployment.
