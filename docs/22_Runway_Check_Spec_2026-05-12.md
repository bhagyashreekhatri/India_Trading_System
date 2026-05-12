# Doc 22 — Time-to-Target Runway Check (Phase 2.6)

*Drafted: 2026-05-12. Spec only — implementation deferred until Phase 2.1/2.3 shadow validation completes.*

## 1. Why this exists

`config/settings.py` currently has:
```python
NO_NEW_ENTRY_AFTER = "14:45"   # IST
```

A blunt clock cutoff. Two problems:

**Problem 1 — Setup-blind.** A FAILED_BREAKDOWN with a historical median time-to-TP1 of ~15 min could safely enter at 14:55 (40 min to 15:30 close + 15 min target window = comfortable). A TREND_PULLBACK with median TTP1 ~45 min cannot enter even at 14:00 if EOD-partial-unwind hits at 14:45. The single `14:45` cutoff is too tight for fast setups and too loose for slow ones.

**Problem 2 — Three Laws violation (clock category).** The 30-month research locked in the principle that clock-of-day categories are anti-predictive. `NO_NEW_ENTRY_AFTER` is the last surviving clock rule in the entry path. It should be replaced with a **structural** rule: *expected time to target* vs *remaining session runway*.

## 2. The rule

For each entry candidate at decision time `now`:

1. Look up the setup's **historical median time-to-TP1** from `memory/trade_state.db`:
   - Query closed positions of the same `setup_type` where `status = closed_win`.
   - Compute `(exit_time - entry_time)` in minutes.
   - Take the median across the last `RUNWAY_LOOKBACK_TRADES` (default 50) winning trades.
2. Compute **remaining session runway**:
   - `remaining_min = EOD_PARTIAL_UNWIND_TIME - now` (default unwind 14:45 IST per Fix #34)
3. Apply **safety factor**:
   - `required = median_TTP1 * RUNWAY_SAFETY_FACTOR` (default 1.5×)
4. Decide:
   - If `required > remaining_min` → **SKIP** with reason `runway_too_short_TTP1={median}m_remaining={remaining}m`
   - Else → ADMIT (continue to next conviction-engine check)

**Replaces**: the `NO_NEW_ENTRY_AFTER` time gate in `_ok_to_trade()`. The flat cutoff goes away. The runway check fires per-candidate inside the conviction engine.

## 3. Default constants (config/settings.py)

```python
RUNWAY_CHECK_ENABLED        = False    # SHADOW MODE — log only initially
RUNWAY_SAFETY_FACTOR        = 1.5      # buffer over median
RUNWAY_LOOKBACK_TRADES      = 50       # median window per setup
RUNWAY_MIN_REMAINING_MIN    = 20       # absolute floor — never enter < 20 min before EOD
RUNWAY_DEFAULT_TTP1_MIN     = 45       # fallback when no historical data for this setup
```

## 4. Three Laws compliance

| Law | Compliance |
|---|---|
| No symbol/sector hardcoding | Median TTP1 is per-setup, not per-symbol. |
| No clock categories | The `14:45` floor (`EOD_PARTIAL_UNWIND_TIME`) is a structural reference (the only forced-exit time the engine respects, validated by Fix #34's EOD partial unwind logic). The runway check is purely arithmetic — `expected_minutes_to_TP1 + buffer ≤ remaining_minutes_to_unwind`. |
| Empirically derived | Safety factor + lookback are settings; median TTP1 is empirically measured from trade_state. |

## 5. Bootstrap problem & fallback

**Concern:** the post-Phase-0-rebuild trade_state.db has effectively zero closed trades on the new setup taxonomy (`MOMENTUM_BREAKOUT` only). The median TTP1 query will return None for the first ~20-30 live entries.

**Fallback algorithm:**
1. Try setup-specific median TTP1 from last 50 closed wins.
2. If sample < 5 trades, fall back to `RUNWAY_DEFAULT_TTP1_MIN` (45 min).
3. Once the setup has 5+ wins, the cached median takes over.
4. Refresh the per-setup cache on every position close (cheap — single DB query).

Setup-specific bootstrap values can also be hardcoded in `RUNWAY_SETUP_DEFAULTS` for a slightly better cold-start:
```python
RUNWAY_SETUP_DEFAULTS = {
    "MOMENTUM_BREAKOUT": 30,   # typical post-FHH-break momentum trades close in 20-40 min
    "FHH_BREAK":         35,
}
```
Once empirical data accumulates, these defaults are ignored.

## 6. Integration

Single hook in `agents/conviction_engine.py.evaluate()`, immediately after the day-type gate (current Phase 1.5 check) and before the tier mapping:

```python
# Phase 2.6 — Runway check (replaces NO_NEW_ENTRY_AFTER clock rule)
if RUNWAY_CHECK_ENABLED:
    from agents.runway_check import evaluate_runway
    rc = evaluate_runway(setup_type=setup.setup_type, now=now, state_mgr=self.state)
    if not rc.ok:
        return _skip(
            f"runway_too_short_{rc.required_min}m_remaining_{rc.remaining_min}m",
            macro_state=macro_snap.state, fhh_state=fhh_state,
            failed=[rc.reason],
        )
elif RUNWAY_CHECK_LOG_SHADOW:
    # Log what we would have skipped, but don't block
    ...
```

The pure function `evaluate_runway()` lives in a new file `agents/runway_check.py` (~120 lines). Returns:

```python
@dataclass
class RunwayResult:
    ok:            bool
    required_min:  int
    remaining_min: int
    median_ttp1:   float
    sample_size:   int
    reason:        str
```

## 7. Acceptance tests

| Case | Input | Expected |
|---|---|---|
| Slow setup, late entry | MOMENTUM_BREAKOUT, median 30m, now=14:20, EOD 14:45 → remaining 25m, required 45m | SKIP |
| Fast setup, late entry | MOMENTUM_BREAKOUT, median 12m, now=14:20, remaining 25m, required 18m | ADMIT |
| Bootstrap fallback (no data) | new setup type, now=13:00, remaining 105m, fallback 45m, required 67.5m | ADMIT |
| Below absolute floor | any setup, now=14:35, remaining 10m < 20m floor | SKIP regardless of TTP1 |
| Morning entry | any setup, now=10:30, remaining 255m | ADMIT (cheap path) |

## 8. Shadow rollout

`RUNWAY_CHECK_ENABLED = False` by default. With `RUNWAY_CHECK_LOG_SHADOW = True`:

```
[Runway] MOMENTUM_BREAKOUT median TTP1 32.5m (n=18), remaining 22m, required 48m → would-skip
[Runway] MOMENTUM_BREAKOUT median TTP1 18.0m (n=18), remaining 95m, required 27m → would-admit
```

After 2 sessions of shadow logs show clean estimates (no extreme medians, no zero-sample cases dominating), flip the flag.

## 9. What this DOES NOT do

- **Does not predict trade outcome.** It only filters by expected time-to-target. A trade that has enough runway may still hit SL. A trade with tight runway might have hit TP1 if admitted — runway check is conservative by design.
- **Does not adjust target.** Doesn't widen/narrow TP1 based on runway; just admits or skips.
- **Does not replace the 89% STRONG_RED skip.** Runway runs AFTER macro filter. STRONG_RED still blocks longs regardless of runway.
- **Does not replace the EOD partial unwind** (Fix #34). That mechanism still force-exits any non-TP1-hit positions at 14:45. Runway check just prevents admitting new ones we won't have time to manage.

## 10. Risk & rollback

- If the median TTP1 query returns wildly inflated values (e.g. one stalled-out trade dominates), the runway check could become over-restrictive.
- **Mitigation:** safety factor of 1.5× is generous, and the absolute remaining floor (`RUNWAY_MIN_REMAINING_MIN = 20`) prevents pathologically tight checks.
- **Rollback:** flip `RUNWAY_CHECK_ENABLED = False`. The clock rule still exists (`NO_NEW_ENTRY_AFTER = 14:45`) as the safety net. Runway is an ADDITIONAL gate, not a replacement, until validated.

## 11. Future extension: per-setup AND per-regime

After 200+ trades accumulate, we can refine to:
```python
median_ttp1 = state.get_median_ttp1(
    setup_type="MOMENTUM_BREAKOUT",
    regime="trending",   # or STRONG_GREEN etc.
    lookback=50,
)
```

Trending-day momentum trades likely close faster than choppy-day ones. The schema already supports this (regime column from Fix #14). The first-pass implementation uses setup-only median; per-regime refinement is a follow-on if data shows meaningful dispersion.

## 12. Removal of `NO_NEW_ENTRY_AFTER` clock rule

After 5+ sessions with runway check ENABLED and showing positive expected R:
1. Set `NO_NEW_ENTRY_AFTER = "15:25"` (effective disable — just keeps the absolute "don't enter in last 5 min" guardrail).
2. The runway check becomes the primary time gate.

This is the final removal of clock categories from the entry path.

---

## 13. Implementation order

1. **agents/runway_check.py** — pure function `evaluate_runway()` + median-TTP1 query helper. ~120 LOC.
2. **memory/trade_state.py** — add `get_median_ttp1(setup_type, lookback)` method. ~25 LOC.
3. **config/settings.py** — 5 new constants.
4. **agents/conviction_engine.py** — wire the check after day-type gate. ~15 LOC.
5. **tests/test_runway.py** — five acceptance cases.
6. Shadow deploy. After 2-3 sessions, flip flag.

**Estimated effort:** 3-4 hours implementation + 2 days shadow observation before live trades influenced.

---

*Cross-refs: docs/11 §"runway check P1.3", docs/12 §"Time-to-target runway", PROJECT_MEMORY Fix #34 (EOD partial unwind 14:45), Three Laws.*
