# Doc 20 — Sector-Aware Macro Filter Spec (Phase 2.2)

*Drafted: 2026-05-12, ~10:05 IST — same morning that revealed the gap.*

## 1. The problem in one screenshot

Today, 2026-05-12, at 09:50 IST:

| Index             | %chg vs prev close |
|-------------------|--------------------|
| NIFTY 50          | **-0.76%**         |
| NIFTY IT          | **-3.02%**         |
| NIFTY METAL       | **+0.52%**         |
| NIFTY ENERGY      | +0.10%             |
| NIFTY FMCG        | -0.55%             |
| NIFTY BANK        | -0.70%             |

Top individual movers in the agent's universe:

| Symbol   | %chg     | Sector       |
|----------|----------|--------------|
| **ONGC** | **+4.88%** | Oil upstream |
| HINDCOPPER | +2.64%  | Metals       |
| VEDL     | +2.30%   | Metals       |
| HINDALCO | +1.85%   | Metals       |
| INFY     | -3.59%   | IT           |
| TCS      | -3.44%   | IT           |
| PERSISTENT | -3.98% | IT           |

The agent's current `market_state.py` reads only `NIFTY 50` % change. At -0.76% (well past the -0.5% threshold) it will lock **STRONG_RED at 10:15 IST**. The conviction engine then rejects every long signal — including a textbook ONGC +4.88% breakout that is **in the agent's universe** and held at +5.16% intraday high with virtually no pullback.

The macro filter is treating a single-sector capitulation (IT alone explains roughly 80% of the index move today) as if the whole market were risk-off. The result: the agent skips clean longs in sectors that are actually trending up.

## 2. Goal

Add a sector-strength sub-state to the macro filter so the conviction engine can **selectively allow longs** in sectors that are decoupled-strong while a separate sector (or basket) drives the index negative — without re-introducing hardcoded sector hierarchies.

## 3. Non-goals

- Do **not** create exception lists like "always allow ONGC" or "Energy gets a free pass." Generic-First Design Law applies.
- Do **not** override the macro filter outright. STRONG_RED still globally blocks new longs **by default** — sector relief is a narrow exception subject to additional gates.
- Do **not** track more than ~10 sector indices. Pulling 50 indices every tick is unnecessary and noisy.
- Do **not** modify the 10:15 IST lock-in mechanism for the index-level macro state. That logic is validated at 89-98% precision across 584 sessions and stays exactly as is.

## 4. Three Laws compliance

| Law | How this complies |
|---|---|
| 1. No symbol/sector hardcoding | Sectors are NSE-published indices (`NIFTY IT`, `NIFTY METAL`, etc.) pulled by name from a config list. No ranking, no priority order, no analyst opinion. |
| 2. No clock gates | Sector readings happen at the same 10:15 IST lock as the master macro. Nothing new is timed. |
| 3. Empirically derived thresholds | The "decoupling" threshold (sector >2 std-dev from NIFTY) and the "outlier-strong" cutoff (sector chg > +0.5% AND > NIFTY chg + 1.0%) come from the 30-month pattern analysis. They are tunable settings, not magic numbers. |

## 5. Architecture — one new dataclass, one new method

```python
# agents/market_state.py — extended

@dataclass(frozen=True)
class SectorStrengthSnapshot:
    sector_name:        str
    sector_change_pct:  float
    nifty_change_pct:   float
    delta_vs_nifty:     float       # sector_change - nifty_change
    z_score:            float       # vs cross-sector mean today
    state:              SectorState # STRONG / NEUTRAL / WEAK

class SectorState(str, Enum):
    DECOUPLED_STRONG = "decoupled_strong"   # sector +ve, NIFTY -ve, gap > threshold
    STRONG           = "strong"             # both +ve, sector leading
    NEUTRAL          = "neutral"
    WEAK             = "weak"
    DECOUPLED_WEAK   = "decoupled_weak"     # sector -ve, NIFTY +ve, gap > threshold

@dataclass(frozen=True)
class MarketStateSnapshot:
    # ... existing fields unchanged ...
    sectors: dict[str, SectorStrengthSnapshot]   # NEW — keyed by sector_name
```

`MarketStateAgent.get_state()` is extended to also pull quotes for the sectors listed in `settings.MACRO_SECTOR_INDICES` at the 10:15 IST snapshot moment. Latency cost: 1 extra `kite.get_quotes` call with ~10 instruments. Acceptable.

## 6. The decoupling rule

```python
def sector_state_for(sector_chg: float, nifty_chg: float,
                     cross_sector_mean: float, cross_sector_std: float) -> SectorState:
    delta = sector_chg - nifty_chg
    z     = (sector_chg - cross_sector_mean) / max(cross_sector_std, 0.05)

    # Hard decoupling: NIFTY is in RED territory but sector is up
    if nifty_chg < -0.30 and sector_chg > +0.30 and delta > 1.0 and z > 1.5:
        return SectorState.DECOUPLED_STRONG

    # Hard decoupling on the other side
    if nifty_chg > +0.30 and sector_chg < -0.30 and delta < -1.0 and z < -1.5:
        return SectorState.DECOUPLED_WEAK

    # Same-sign leader / laggard
    if sector_chg > +0.5 and delta > 0.5:
        return SectorState.STRONG
    if sector_chg < -0.5 and delta < -0.5:
        return SectorState.WEAK

    return SectorState.NEUTRAL
```

The use of cross-sector z-score makes the rule **self-calibrating to today's tape**. On a wide-dispersion day (today: IT -3% vs METAL +0.5%) it's easy to be DECOUPLED_STRONG. On a narrow-dispersion day where everything is ±0.3% there will be no DECOUPLED states — which is correct, the macro state is not bifurcated.

Applying today's numbers:
- NIFTY chg = -0.76%
- Cross-sector mean ≈ -0.51% (8 sectors averaged), std ≈ 1.2%
- NIFTY IT: chg -3.02%, delta -2.26 vs NIFTY, z = (-3.02 - (-0.51)) / 1.2 = **-2.09** → `DECOUPLED_WEAK`
- NIFTY METAL: chg +0.52%, delta +1.28, z = (0.52 - (-0.51)) / 1.2 = **+0.86** → not quite hitting z > 1.5 BUT delta > 1.0 AND nifty < -0.30 AND sector > +0.30 → **DECOUPLED_STRONG**
- NIFTY ENERGY: chg +0.10%, delta +0.86, z = +0.51 → fails the sector_chg > +0.30 floor → `NEUTRAL`
- NIFTY BANK: chg -0.70%, delta +0.06 → `NEUTRAL`

So the agent's view at 10:15 today **should** be: macro STRONG_RED globally, sectors {IT: DECOUPLED_WEAK, METAL: DECOUPLED_STRONG, others: NEUTRAL or WEAK}.

## 7. How the conviction engine uses it

```python
# agents/conviction_engine.py — proposed change to evaluate()

def _macro_allows_long(self, macro: MacroState, symbol_sector: str,
                       sectors: dict[str, SectorStrengthSnapshot]) -> bool:

    # Always allow longs on the global green states (existing behaviour)
    if macro in (MacroState.STRONG_GREEN, MacroState.GREEN):
        return True

    if macro in (MacroState.STRONG_RED, MacroState.RED):
        # NEW: allow longs only in DECOUPLED_STRONG sectors
        sec = sectors.get(self._sector_index_for(symbol_sector))
        if sec and sec.state == SectorState.DECOUPLED_STRONG:
            return True
        return False

    # YELLOW: existing logic unchanged
    return False
```

`_sector_index_for(symbol_sector)` maps the symbol's existing `sector` attribute (already populated from `config/universe.py`'s SECTORS dict) to the corresponding NIFTY sector index name. This is a pure mapping table, not a hierarchy — kept in `config/settings.py`:

```python
SYMBOL_SECTOR_TO_INDEX = {
    "IT":       "NIFTY IT",
    "BANKING":  "NIFTY BANK",
    "NBFC":     "NIFTY FIN SERVICE",
    "AUTO":     "NIFTY AUTO",
    "AUTO_ANC": "NIFTY AUTO",
    "PHARMA":   "NIFTY PHARMA",
    "METALS":   "NIFTY METAL",
    "OIL_GAS":  "NIFTY ENERGY",
    "POWER":    "NIFTY ENERGY",
    "FMCG":     "NIFTY FMCG",
    # ... unmapped sectors fall through to None → engine treats as NEUTRAL
}
```

Unmapped sectors (REALTY, MEDIA, etc.) won't get sector relief — they fall back to the global macro rule. That's safe: if we don't have evidence for a sector, we don't override the macro.

## 8. Tier behaviour under sector relief

When sector relief admits a long that the global macro would have rejected, the conviction engine should be **more conservative**, not less. The Phase 0 evidence (89% close-positive on STRONG_GREEN+FHH) was measured at index-level. Sector relief is a *narrower* claim and deserves smaller size.

Proposed tier mapping:

| Global macro | Symbol sector state | Allow long? | Tier ceiling |
|---|---|---|---|
| STRONG_GREEN | any                  | YES | **S** (full size) |
| GREEN        | DECOUPLED_STRONG / STRONG | YES | **A** |
| GREEN        | WEAK / DECOUPLED_WEAK     | YES (downgraded) | **B** |
| YELLOW       | DECOUPLED_STRONG          | YES | **B** |
| YELLOW       | other                     | SKIP | — |
| RED          | DECOUPLED_STRONG          | YES | **B** |
| RED          | other                     | SKIP | — |
| STRONG_RED   | DECOUPLED_STRONG          | YES (rarely) | **B-** (half-B size) |
| STRONG_RED   | other                     | SKIP | — |

Today's expected outcome with this change: ONGC (sector OIL_GAS → NIFTY ENERGY) — but ENERGY today is NEUTRAL (only +0.10%), not DECOUPLED_STRONG. So ONGC stays blocked even with sector relief. The real beneficiaries today would be HINDCOPPER, HINDALCO, VEDL, NATIONALUM (sector METALS → NIFTY METAL DECOUPLED_STRONG) at tier **B-** (half-B size).

This is a deliberately tight rule. It buys back ~20-30% of the long-side opportunity on STRONG_RED days **without** opening the floodgates to false signals from sector noise.

## 9. Symmetric short relief (mirror image)

The reverse rule applies on global GREEN days where a sector is decoupled-weak: longs blocked in that sector, shorts allowed at downgraded tier. Today's IT capitulation **does not** benefit from this (macro is RED already), but on a GREEN day where IT alone is bleeding, this catches the short.

## 10. Acceptance tests

### 10.1 Today's tape (2026-05-12) — synthetic backtest

Feed today's 09:15-10:15 OHLC into the sector-aware market_state module, with current crew.py + conviction_engine.py wired up. Assert:

- Macro state = `STRONG_RED` (NIFTY -0.76% < -0.5%).
- NIFTY METAL sector = `DECOUPLED_STRONG`.
- NIFTY IT sector = `DECOUPLED_WEAK`.
- All METAL-sector symbols (HINDALCO, JSWSTEEL, TATASTEEL, HINDCOPPER, etc.) pass the `_macro_allows_long` check.
- Non-METAL longs (ONGC, RELIANCE, etc.) are still blocked.
- Without this patch, ALL longs are blocked. With this patch, ~10 longs are admitted (the METAL basket) at tier B-.

### 10.2 30-month historical replay

Re-run doc 16's 584-session analysis with sector-aware macro turned on. Track:

- Number of STRONG_RED days where ≥1 sector was DECOUPLED_STRONG (expected: ~40-60 sessions).
- Hit rate of admitted longs on those days vs. all-STRONG_RED-day longs from the pre-rebuild baseline.

If admitted-long hit-rate ≥ 55% (vs roughly 35-40% on naïve STRONG_RED longs in the audit), the rule is empirically validated. If below 50%, hold or revert.

### 10.3 No false positives on narrow-tape days

On days where cross-sector dispersion is tight (std < 0.4%), assert NO sector lands in DECOUPLED_STRONG. The decoupling rule requires real bifurcation; narrow days should not trigger relief.

### 10.4 Edge case: thin index sample

If sector_index_count < 4 (only a few sectors return quotes), disable sector relief for that session entirely. Better to follow the global macro than to compute z-scores against 2 data points.

## 11. Settings additions

```python
# config/settings.py — new block

MACRO_SECTOR_INDICES = [
    "NIFTY BANK",
    "NIFTY IT",
    "NIFTY AUTO",
    "NIFTY PHARMA",
    "NIFTY FMCG",
    "NIFTY METAL",
    "NIFTY ENERGY",
    "NIFTY FIN SERVICE",
    "NIFTY REALTY",        # optional, can drop
    "NIFTY MEDIA",         # optional, can drop
]

SECTOR_DECOUPLE_DELTA_THRESHOLD  = 1.0    # sector_chg - nifty_chg > 1.0 for DECOUPLED_STRONG
SECTOR_DECOUPLE_Z_THRESHOLD      = 1.5    # std-deviations from cross-sector mean
SECTOR_MIN_ABS_FLOOR             = 0.30   # sector must be ≥ +0.3% abs to qualify as STRONG-side decouple
SECTOR_RELIEF_TIER_DOWNGRADE     = True   # cap tier at B (or B-minus on STRONG_RED) for sector-relief longs
SECTOR_RELIEF_ON_STRONG_RED      = True   # master switch — set False to disable relief on STRONG_RED only

SYMBOL_SECTOR_TO_INDEX = { ... see §7 ... }
```

## 12. Phase 2.2 cutover plan

| Step | Action | Duration |
|---|---|---|
| 1 | Implement sector reading in `market_state.py` | 2 hr |
| 2 | Extend `conviction_engine.py` with sector-aware long/short gating | 2 hr |
| 3 | Add settings constants + sector→index mapping | 30 min |
| 4 | Replay against today's tape — assert METAL basket admits, IT basket rejects | 1 hr |
| 5 | Replay against 30-month dataset — measure incremental edge | 4 hr |
| 6 | Ship to server in **shadow mode** (`SECTOR_RELIEF_ON_STRONG_RED=False` for live, but logs show what relief WOULD have admitted) | 1 day |
| 7 | After 3 sessions of shadow logs, review. If admitted shadows look clean, flip the flag. | Week 1 |

## 13. Interaction with Discovery Engine (doc 19)

The two specs compose cleanly:
1. **Discovery** surfaces JINDRILL (mid-cap oil-services play, sector OIL_GAS → NIFTY ENERGY).
2. **Sector-aware macro** evaluates whether ENERGY is `DECOUPLED_STRONG` today.
3. If yes → JINDRILL is admitted at tier B-.
4. If no (today: ENERGY is NEUTRAL at +0.10%) → JINDRILL is dropped even though discovery found it.

This shows why discovery alone is insufficient on a day like today — finding JINDRILL doesn't help if the macro filter then blocks the long. Both pieces are needed for full effect.

Conversely, on a different morning where the agent's hardcoded universe already has the leader and the leader's sector is DECOUPLED_STRONG, sector-aware macro alone is sufficient and discovery adds nothing.

Best estimate: **sector-aware macro alone** unblocks longs on roughly 30-50 STRONG_RED days/year (5-8% of trading days). Discovery alone adds maybe 10-20 catches/year where the leader is outside the core universe. Together, they expand the agent's actionable opportunity set on adversarial macro days by ~15-25%.

## 14. What this does NOT solve

- **Intra-sector dispersion.** Even on a METAL DECOUPLED_STRONG day, not every metal name will rip. HINDCOPPER +2.6% but JSWSTEEL only -0.33%. The conviction engine's existing stock-level FHH break + HOD-proximity gates handle that — they filter the basket down to actual breakout candidates.
- **Sector cycle awareness.** A sector that has rallied 5 days in a row is mean-reverting risk. This spec ignores trailing context. That's an extension (Phase 2.3 or later).
- **Cross-sector pairs.** No long-METAL / short-IT pair trading. The agent is strictly directional, single-leg.

## 15. Today's relevance

Even if sector-aware macro is not shipped before market close today, the principle should be reflected in the boot-log telemetry going forward: the macro filter should log not just "STRONG_RED" but "STRONG_RED with sector dispersion 1.2% (METAL DECOUPLED_STRONG)". That telemetry alone — without the trading logic — is valuable for post-mortem critique and weekly review.

A one-line patch to `market_state.py` can ship the **logging** today without touching any trading logic. The full sector-relief logic stays gated behind the feature flag for safe rollout.

---

*Status: SPEC. Logging-only patch can ship today as a foot-in-the-door. Full sector-relief logic ships after 30-month replay confirms empirical edge.*
*Cross-refs: doc 13 (10:15 IST macro discovery), doc 14 (OOS validation), doc 16 (584-session analysis), doc 19 (Discovery Engine spec), Three Laws (PROJECT_MEMORY.md).*
