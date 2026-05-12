# Docs index

*Last updated: 2026-05-12 (docs 19 + 20 added — Phase 2.1 Discovery Engine + 2.2 Sector-Aware Macro specs)*

The single-source-of-truth fix log lives at `../PROJECT_MEMORY.md`. The docs in this folder are deeper-dive analyses, plans, and reference material.

## ⭐ Read this first

| # | File | What it is |
|---|---|---|
| **18** | **[`18_Rebuild_Status_2026-05-11.md`](18_Rebuild_Status_2026-05-11.md)** | **CURRENT STATUS — what's shipped, what's pending, every plan cross-checked. Start here.** |

## Strategy validation chain (read in order)

| # | File | What it is | When to read |
|---|---|---|---|
| 1 | [`01_Project_Overview_and_Goal.md`](01_Project_Overview_and_Goal.md) | Goal, mindset hierarchy, current state, risk rules | Start here for context |
| 2 | [`08_Findings_From_280_Trades.md`](08_Findings_From_280_Trades.md) | 280-trade audit: near-zero edge, 71% stall rate | The "why we rebuilt" doc |
| 3 | [`13_Scalper_Research_6Month_2026-05-11.md`](13_Scalper_Research_6Month_2026-05-11.md) | 6-month NIFTY research — discovered the 10:15 IST macro rule | First proof of edge |
| 4 | [`14_OOS_Validation_18Month_2026-05-11.md`](14_OOS_Validation_18Month_2026-05-11.md) | Jan-Nov 2025 out-of-sample test — rule holds across opposite regimes | Validation that it's not overfit |
| 5 | [`15_Setup_Pattern_Library_18mo_2026-05-11.md`](15_Setup_Pattern_Library_18mo_2026-05-11.md) | Setup library + FHH break combo discovery | Pattern catalog |
| 6 | [`16_30Month_Final_Analysis_2026-05-11.md`](16_30Month_Final_Analysis_2026-05-11.md) | 30-month final analysis + reality check on "sure shot" | Final data foundation |
| 7 | [`17_Rebuild_Plan_2026-05-11.md`](17_Rebuild_Plan_2026-05-11.md) | The full deletion + rebuild plan + Phase 0-5 timeline | The roadmap |
| 8 | [`18_Rebuild_Status_2026-05-11.md`](18_Rebuild_Status_2026-05-11.md) | **What's actually shipped today (Phase 0 + 1 + 1.5-1.7)** | **Current state** |
| 9 | [`19_Discovery_Engine_Spec_2026-05-12.md`](19_Discovery_Engine_Spec_2026-05-12.md) | Phase 2.1 — Top-mover scanner for invisible mid-caps (JINDRILL evidence) | Spec for next ship |
| 10 | [`20_Sector_Aware_Macro_Spec_2026-05-12.md`](20_Sector_Aware_Macro_Spec_2026-05-12.md) | Phase 2.2 — Sector decoupling relief on STRONG_RED days (ONGC blocked-but-clean evidence) | Spec for next ship |

## Reference docs (older context)

| File | What it is |
|---|---|
| [`04_Trade_Log_Analysis.md`](04_Trade_Log_Analysis.md) | Historical baseline analysis on the original 151-trade dataset |
| [`05_Exit_Distribution_Analysis.md`](05_Exit_Distribution_Analysis.md) | Decided "keep partials, kill single-target" — auto-generated |
| [`05_Setup_Deletion_Audit.md`](05_Setup_Deletion_Audit.md) | Decided which of 8 setups die — auto-generated |
| [`07_Scalper_Architecture_Migration.md`](07_Scalper_Architecture_Migration.md) | Original 9-phase migration plan (Phase A-I) — partially superseded by doc 17 |
| [`09_Phase_A_Smoke_Test.md`](09_Phase_A_Smoke_Test.md) | Counterfactual replay of Phase A filters — auto-generated |
| [`10_Live_Market_Observations_2026-05-11.md`](10_Live_Market_Observations_2026-05-11.md) | Live-tape journal from May 11 session (today) |
| [`11_System_Improvement_Report_2026-05-11.md`](11_System_Improvement_Report_2026-05-11.md) | Original P0/P1/P2 improvement priorities (largely superseded by docs 16-17) |
| [`12_Audit_1Month_Validation_2026-05-11.md`](12_Audit_1Month_Validation_2026-05-11.md) | Brutal honest audit of original P0 claims against 280-trade DB |

## Auto-generated docs

These regenerate when their script is re-run on a fresh DB snapshot. Don't edit by hand:
- `05_Exit_Distribution_Analysis.md`
- `05_Setup_Deletion_Audit.md`
- `09_Phase_A_Smoke_Test.md`

```bash
# Refresh against latest server data
scp root@168.144.101.223:/root/india_trading/trade_state.db trade_state_server_snapshot.db
python3 scripts/analyze_exit_distribution.py --db trade_state_server_snapshot.db --out docs
python3 scripts/setup_audit.py               --db trade_state_server_snapshot.db --out docs
python3 scripts/phase_a_smoke_test.py        --db trade_state_server_snapshot.db --out docs
```

## Numbering convention

Numbers (01, 04, 05x2, 07-18) reflect chronological order of analyses, not logical sequence. Gaps (no 02, 03, 06) are where stale docs were deleted. Don't fill them — keep each new analysis at its natural number for traceability.

## Phase status snapshot

| Phase | Plan | Status |
|-------|------|--------|
| Phase 0 — Foundation (macro+FHH+conviction) | doc 17 | ✅ COMPLETE (today) |
| Phase 0.5 — Strip empirically-wrong nudges | doc 17 | ✅ COMPLETE (today) |
| Phase 0.6 — Trim setup detectors | doc 17 | ✅ COMPLETE (today) |
| Phase 1.1 — Stock-level FHH + HOD proximity | doc 17 + 15 | ✅ COMPLETE (today) |
| Phase 1.2 — Pre-TP1 trail SL (Fix #71) | doc 11 + 15 | ✅ COMPLETE (today) |
| Phase 1.3 — Whipsaw freeze | doc 15 | ✅ COMPLETE (today) |
| Phase 1.5 — Day-type classifier | doc 15 + 17 | ✅ COMPLETE (today) |
| Phase 1.6 — NR7 expansion | doc 15 | ✅ COMPLETE (today) |
| Phase 1.7 — Volatility-adaptive sizing | doc 11 + 14 | ✅ COMPLETE (today) |
| Phase 1.8 — Cleanup deprecated constants | doc 17 | 🟡 DEFERRED — cosmetic, no behavior impact |
| Phase 2.1 — Discovery Engine (top-mover scanner) | doc 19 | 📝 SPEC drafted (2026-05-12), implementation pending |
| Phase 2.2 — Sector-aware macro filter | doc 20 | 📝 SPEC drafted (2026-05-12), implementation pending |
| Phase 2 — Forward validation (5-15 sessions) | doc 17 | ⏳ STARTS TOMORROW |
| Phase 3 — ₹50k live probe | doc 17 | ⏳ Week 2-3 |
| Phase 4 — ₹3L deployment | doc 17 | ⏳ Month 2 |
| Phase 5 — ₹20L deployment | doc 17 | ⏳ Month 4-5 |

## Charts

`charts/` contains baseline visualisations from the 151-trade analysis.
</content>
