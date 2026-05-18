# Doc 24 — Mid-Trade Structural Re-evaluation (Phase 2.7)

*Drafted: 2026-05-18. Module implemented + 10/10 acceptance tests pass. Shadow mode default.*

## 1. The problem

Existing position management is **reactive** — it only fires on price events (SL hit, TP1 hit, trailing stop, EOD force-close, time-stop). It does NOT re-check whether the original entry thesis still holds while the position is open.

So a clean entry at 10:30 IST can ride to full SL at 12:30 IST even when market structure invalidates at 11:00 IST.

**Classic failure mode this fixes:**
1. 10:30 IST — Enter LONG STOCK_X. Macro=GREEN, FHH break clean, HOD-proximity 0.2%, vol×2.5. All systems go.
2. 11:15 IST — NIFTY drops 60bps. Macro deteriorates toward YELLOW. Stock slips below VWAP.
3. 12:00 IST — Stock 1.2% below HOD, no follow-through. SL hasn't hit. Position still at full risk.
4. 12:30 IST — SL fires at full -1R loss.

Mid-trade re-eval catches step 3 and exits at break-even-or-better instead of riding to -1R.

## 2. The rule

For each open position, at most every **`MID_TRADE_REEVAL_INTERVAL_MIN`** (default 5 min), re-check three structural dimensions:

| # | Dimension | Pass criterion | Source |
|---|---|---|---|
| 1 | **Macro** | `market_state.allows_long_entry()` is True (STRONG_GREEN / GREEN / YELLOW) | `agents/market_state.py` |
| 2 | **VWAP** | Current LTP ≥ today's running VWAP | Computed from 5-min candles |
| 3 | **HOD** | LTP within `MID_TRADE_HOD_RELAX_PCT` of intraday high (default 1.5% — relaxed vs entry's 0.5%) | Today's quote |

**Action ladder:**

| Broken count | Action | Reasoning |
|---|---|---|
| 0-1 | **CONTINUE** | Single dim breaking is noise — let SL/TP/trail manage |
| 2 | **TIGHTEN_TO_BE** | Move SL to entry price. Caps remaining downside to slippage. |
| 3 | **CLOSE** | Exit at market with reason `thesis_invalidated`. Don't wait for SL. |

## 3. Why these dimensions

- **Macro**: 30-month evidence shows 89% of STRONG_RED-day longs close negative. If we entered on GREEN and macro flips to STRONG_RED, the probability our long survives drops sharply.
- **VWAP**: Standard institutional rule. Above VWAP = buyers in control. Below = sellers in control. A long that's lost VWAP is structurally fighting the tape.
- **HOD-proximity (relaxed)**: Entry rule is 0.5% (don't chase). Mid-trade rule is 1.5% — a healthy trade can pull back a bit. Beyond 1.5% off intraday high, the breakout is exhausted.

## 4. Three Laws compliance

| Law | How |
|---|---|
| No clock categories | Dimensions are pure structure — measured at any time |
| No symbol/sector hardcoding | Works on any open position |
| Empirically tunable | All 4 thresholds (interval, HOD relax, tighten threshold, close threshold) in `config/settings.py` |

## 5. Shadow rollout

`MID_TRADE_REEVAL_ENABLED = False` by default. `MID_TRADE_REEVAL_LOG_SHADOW = True` so we still see what the rule WOULD have done:

```
[Reeval] STOCK_X TIGHTEN-SHADOW — macro=STRONG_RED ltp=99.5 vwap=100.2 pull-from-HOD=2.10% — thesis_weakening — 2/3 dims broken (macro,vwap)
[Reeval] STOCK_Y CLOSE-SHADOW — macro=STRONG_RED ltp=98 vwap=99.5 pull-from-HOD=2.50% — thesis_invalidated — 3/3 dims broken (macro,vwap,hod)
```

After 3-5 sessions of clean shadow logs (and confirmation that the WOULD-have actions match human judgment), flip `MID_TRADE_REEVAL_ENABLED=True`.

## 6. Acceptance tests (10/10 pass)

| # | Case | Expected | Result |
|---|---|---|---|
| 1 | All clear (macro GREEN, above VWAP, near HOD) | CONTINUE | ✅ |
| 2 | Only macro broken (RED) — 1/3 | CONTINUE | ✅ |
| 3 | Only VWAP broken — 1/3 | CONTINUE | ✅ |
| 4 | Only HOD-extended — 1/3 | CONTINUE | ✅ |
| 5 | Macro RED + VWAP lost — 2/3 | TIGHTEN_TO_BE | ✅ |
| 6 | STRONG_RED + extended HOD — 2/3 | TIGHTEN_TO_BE | ✅ |
| 7 | All 3 dims broken | CLOSE | ✅ |
| 8 | Interval guard: 1 min after check → no re-check | ✅ | ✅ |
| 9 | Interval guard: 6 min after check → re-check allowed | ✅ | ✅ |
| 10 | drop_position cleans state on close | ✅ | ✅ |

## 7. Files changed

- **New:** `agents/mid_trade_reeval.py` (~180 lines)
- **Modified:** `agents/crew.py` (+~75 lines — init line + `_manage_positions` block)
- **Modified:** `config/settings.py` (+8 lines — 6 constants)

## 8. What this does NOT do

- **Does not check sector strength** — that's noise on the per-position scale (already gated at entry by Phase 2.3)
- **Does not check volume drying up** — would require sustained intraday volume tracking; deferred to Phase 2.8 if needed
- **Does not move SL up beyond breakeven** — that's the trailing-SL system (Fix #28). This module only protects DOWNSIDE.
- **Does not act on YELLOW alone** — YELLOW is half-size territory, not a thesis-broken signal. Only flips to RED/STRONG_RED count.

## 9. Composition with other Phase 2 modules

| Module | Relation |
|---|---|
| Phase 2.1 Discovery | Discovery surfaces candidate. Mid-trade re-eval kicks in only AFTER the position is open. Independent. |
| Phase 2.3 Stock decoupling | Decoupling admits longs at tier B- on macro-RED days. Mid-trade re-eval would CLOSE those positions if macro stays RED + VWAP/HOD break. That's the CORRECT behavior — decoupling admits are higher-risk, faster-exit. |
| Phase 2.6 Runway check | Runway prevents NEW entries with insufficient session-time. Mid-trade re-eval handles entries already in flight. Complementary. |
| Phase 1.2 Pre-TP1 trail | Pre-TP1 trail tightens SL after +0.5R held 10min (upside protection). Mid-trade re-eval tightens SL when thesis breaks (downside protection). Both can fire independently. |

---

*Cross-refs: docs/16 (584-session macro precision), docs/17 (rebuild plan §P1.5+), Three Laws (PROJECT_MEMORY).*
