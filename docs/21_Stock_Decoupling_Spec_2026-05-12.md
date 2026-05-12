# Doc 21 — Stock-level Decoupling Rule (Phase 2.3)

*Drafted: 2026-05-12. Implemented same day. Ships in shadow mode (default OFF).*

## 1. Why this exists — the 2026-05-12 evidence

On a clean STRONG_RED day (NIFTY closed -1.83%), the conviction engine correctly blocked **every** long entry — exactly what the validated 89% precision rule prescribes. The agent stayed flat with ₹0 P&L. That was the right call for the **overall** tape: NIFTY did indeed end deep red.

But three specific single stocks decoupled and ran against the index all day:

| Stock | Morning %chg | Close %chg | Intraday hi |
|---|---|---|---|
| **ONGC** | +4.88% (in agent's universe) | +5.93% | +6.73% |
| OIL India | +5.59% (NOT in universe) | +7.66% | +9.51% |
| JINDRILL | +7.09% (NOT in universe) | +7.81% | +13.63% |

Phase 2.1 (Discovery Engine) addresses the **visibility** problem for OIL and JINDRILL — they were invisible to the agent's hardcoded 150-stock universe. But ONGC was *already in the universe* and got blocked solely by the macro filter. That's the gap Phase 2.3 closes.

## 2. Why not just relax the macro filter?

The macro filter is doing its job. On 2026-05-12 the rule's 89% precision held — NIFTY did close negative. The problem is that even on 89%-bearish days, **individual stocks** with single-stock catalysts can run hard against the macro. Today's catalyst was a crude rally lifting oil producers. Last month it might be a defence-spending headline lifting HAL/BEL while the rest of the market sells off.

We don't want to dial down the macro filter — that would invite losses on the 89% of days it's correctly bearish. We want a **narrow** override that admits the rare clean-decoupling cases under strict structural conditions.

## 3. Why not just use sector-aware macro (Phase 2.2)?

The original doc 20 proposal: if a sector is DECOUPLED_STRONG at 10:15 IST, admit longs in that sector even on macro RED. Today's tape **killed** this idea:

- METAL sector: morning +0.52% (DECOUPLED_STRONG by spec) → close **-0.35%**
- ENERGY sector: morning +0.10% (didn't qualify) → close -1.25%

If Phase 2.2 had shipped, it would have admitted longs in HINDCOPPER, HINDALCO, NATIONALUM at 10:15 IST (all METAL constituents). Each of those would have **lost money** by close. The sector signal was a head-fake.

But within the metal/oil basket, **specific stocks** held their gains:
- HINDALCO +1.75% close (held)
- HINDCOPPER +0.54% close (faded from +2.64%)
- ONGC +5.93% (held strongly)

The signal that holds isn't the sector — it's the **per-stock structural commitment**: large magnitude, real volume, holding HOD, with a sector that isn't *severely* falling. That's the per-stock rule, not the per-sector rule.

## 4. The rule — six conditions

A long entry is admitted at tier **B-** (half-size of B) on a macro RED or STRONG_RED day **if and only if** ALL six conditions hold:

| # | Condition | Default threshold | Setting |
|---|---|---|---|
| 1 | Stock %chg vs prev close ≥ +X% | **+4.0%** | `STOCK_DECOUPLING_MIN_PCT` |
| 2 | Stock volume ratio ≥ Y× | **1.5×** (today_vol / 20d_avg) | `STOCK_DECOUPLING_MIN_VOL_RATIO` |
| 3 | LTP within Z% of intraday high | **0.5%** | `STOCK_DECOUPLING_MAX_PULL_FROM_HOD_PCT` |
| 4 | Sector index chg ≥ floor | **-1.0%** | `STOCK_DECOUPLING_SECTOR_FLOOR_PCT` |
| 5 | Stock's own FHH cleanly broken | binary | (existing Phase 1.1 check) |
| 6 | Current time ≥ 11:00 IST | binary | `DECOUPLING_MIN_TIME_IST` constant |

If condition #5 fails (stock-FHH not broken, or whipsaw) the rule rejects regardless. Condition #6 prevents firing on the first-hour fakeouts.

## 5. Three Laws compliance

- **No symbol hardcoding** — works on any stock the agent already sees.
- **No clock category** — single time threshold (11:00 IST) for FHH-completion + ~45 min for the structure to stabilise. Empirically derived; not a discretionary clock window.
- **All thresholds in `config/settings.py`** — no buried magic numbers.

## 6. Tier mapping

When admitted, the trade enters at tier **B with size 0.5×** (effectively B-). This is intentional:
- Tier S (validated 98% close-positive on STRONG_GREEN+FHH) and tier A (97% on GREEN+FHH) reflect the highest-precision validated paths. Decoupling is a narrower claim — it shouldn't get equal size.
- B at half-size is a measured probe. If decoupling admits prove profitable over 10-20 trades, we can revisit the size multiplier.

## 7. What this DOES NOT do

- **Does NOT admit shorts on macro GREEN days.** Long-only by symmetry omission — the agent is currently long-only system. A mirror rule for shorts would be doc 21-bis later.
- **Does NOT bypass any universal pre-entry filter.** Spread, depth, HOD-proximity, RAG-veto, symbol blacklist all still apply.
- **Does NOT bypass stock-FHH break.** The stock must still have a clean first-hour-high break.
- **Does NOT trade on TREND_FORMING_DN day-type.** That gate still fires after the decoupling override.

## 8. Shadow rollout

- `STOCK_DECOUPLING_ENABLED = False` by default in `config/settings.py`.
- When False, the evaluator still runs and emits log lines:
  - `[Decoupling] ONGC ADMIT-SHADOW on macro STRONG_RED — stock +4.88% on 1.93× vol, ...` (rule would have admitted)
  - `[Decoupling] AMBUJACEM would-skip — stock_pct_+1.5%_below_+4.0%_floor` (near-miss with stock ≥ 2%)
- After 3-5 shadow sessions, review the log for:
  - How often does the rule admit? (target: 1-2 admits per week, not 20)
  - Of admitted shadows, what was the hypothetical R-multiple at close? (target: positive mean R)
  - Any false-positive admits (rule fires but the stock then collapsed)?
- If shadow looks clean, flip `STOCK_DECOUPLING_ENABLED = True`.

## 9. Acceptance tests (validated 2026-05-12)

10 cases pass — see `/tests/test_decoupling.py` (or the dev-time
`outputs/test_decoupling.py`). Key cases:

| Case | Expected | Actual |
|---|---|---|
| ONGC at 13:24 IST (+4.88%, vol×1.93, sector ENERGY -0.51%) | ADMIT | ADMIT ✓ |
| AMBUJACEM at 10:21 (only +1.5%, before 11:00 IST) | SKIP | SKIP ✓ |
| PERSISTENT -3.98% (negative — long-only rule) | SKIP | SKIP ✓ |
| ONGC-shape at 10:00 IST (too early) | SKIP | SKIP ✓ |
| ONGC +3.56%, but 1.2% below HOD (extended) | SKIP | SKIP ✓ |
| ONGC-shape with sector -1.51% (below floor) | SKIP | SKIP ✓ |
| ONGC-shape with vol×1.20 (below 1.5× floor) | SKIP | SKIP ✓ |
| ONGC-shape without stock-FHH break | SKIP | SKIP ✓ |
| Stock-FHH whipsaw | SKIP | SKIP ✓ |
| Symbol with no sector mapping (neutral pass) | ADMIT | ADMIT ✓ |

## 10. Integration

`agents/stock_decoupling.py` — module with the rule (pure, stateless).
`agents/conviction_engine.py` — hooked in the RED/STRONG_RED skip branch; default fall-through unless `STOCK_DECOUPLING_ENABLED=True` AND rule admits.
`config/settings.py` — 6 new constants + `SYMBOL_SECTOR_TO_INDEX` mapping.

Sector index lookup uses `SYMBOL_SECTOR_TO_INDEX[get_sector(symbol)]`. Symbols whose sector isn't mapped (REALTY, MEDIA, etc.) pass condition #4 with sector_pct=0 (treated neutral).

## 11. Composition with Phase 2.1 (Discovery Engine)

Both modules compose cleanly:
1. **Discovery surfaces** JINDRILL/OIL/CMSINFO (otherwise invisible names).
2. **Decoupling decides** whether to admit any of them at tier B- on a macro-RED day.

Result: an ONGC-class trade (in core universe) gets admitted by decoupling; a JINDRILL-class trade (outside core universe) requires Discovery + Decoupling to both pass.

## 12. What ships in this commit

- New: `agents/stock_decoupling.py` (293 lines)
- Modified: `agents/conviction_engine.py` (+62 lines override branch)
- Modified: `config/settings.py` (+33 lines for constants + SYMBOL_SECTOR_TO_INDEX mapping)
- New: this doc

Defaults: `STOCK_DECOUPLING_ENABLED = False` (shadow mode). Flip only after 3-5 sessions of shadow logs.

---

*Cross-refs: doc 16 (584-session macro analysis), doc 19 (Discovery Engine spec), doc 20 (sector-aware macro — rejected based on today's METAL fade evidence), PROJECT_MEMORY (Three Laws).*
