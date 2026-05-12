# Doc 19 — Discovery Engine Spec (Phase 2.1)

*Drafted: 2026-05-12, ~10:00 IST — same day live-tape evidence triggered the prioritisation.*

## 1. Why this jumped from P2 to P0

Today's live tape (2026-05-12, intraday, ~09:50 IST snapshot of 208 liquid names) made the gap impossible to ignore:

| Rank | Symbol            | %chg     | In agent universe? |
|------|-------------------|----------|--------------------|
| 1    | **JINDRILL**      | **+7.09%** (intraday hi +10.81%) | **NO** |
| 2    | **OIL** (Oil India)| **+5.59%** (intraday hi +7.63%)  | **NO** |
| 3    | CMSINFO           | +5.26%   | NO |
| 4    | ONGC              | +4.88%   | YES |
| 5    | HINDCOPPER        | +2.64%   | YES |
| ...  | ...               | ...      | ... |
| Loss #1 | JSWENERGY       | -5.56%   | NO |
| Loss #2 | BSOFT           | -5.04%   | NO |

The **top two gainers** of the morning sit outside the 150-stock hardcoded universe in `config/universe.py`. Both ride the same catalyst (crude / oil-upstream rotation) that the agent's universe member ONGC also rode — but JINDRILL ran 4-5x harder because it's a mid-cap leveraged play on the same theme. Same story on the short side: JSWENERGY and BSOFT are the cleanest down-moves and the agent cannot see them.

Without a Discovery Engine the agent is structurally locked out of the **highest-conviction trade of any given day** roughly 30-50% of sessions (rough estimate — needs back-test in §10).

This document specifies a self-contained scanner that fixes the gap **without** re-introducing hardcoding. It follows the Three Laws (locked at the top of PROJECT_MEMORY): generic-first, data-driven, no symbol/sector hardcoding.

## 2. Goal in one sentence

> Every 5 minutes during market hours, surface NSE EQ names that have moved beyond a configurable threshold on confirming volume, validate them against liquidity and spread gates, and inject them into the live trading universe under bounded safety constraints.

## 3. Non-goals

- Do **not** replace the core 150-stock universe — it remains the stable backbone.
- Do **not** add names based on absolute size, brand recognition, sector membership, or any analyst opinion. The only inputs are price + volume + liquidity.
- Do **not** create a parallel signal pipeline. Discovered names must flow through the same conviction engine, scoring stub, sizing, and risk controls.
- Do **not** persist discovered names overnight. The pool is rebuilt every session morning.

## 4. Three Laws compliance

| Law | How this spec complies |
|---|---|
| 1. No symbol hardcoding | The candidate pool is pulled from `kite.instruments(NSE)` at startup, filtered by series=EQ. |
| 2. No clock-gate hardcoding | The scanner runs on a fixed cadence (5 min) but never references specific clock times like "09:30" or "11:00". The 10:15 macro filter is unchanged and remains independent of discovery. |
| 3. Empirically derived thresholds | The ±3% trigger, 1.5x volume, ₹10cr turnover floors come from the 30-month NIFTY pattern library and are written as **settings constants**, not buried magic numbers. They are tunable per regime if the weekly threshold-review job (Phase G) ever ships. |

## 5. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       discovery_engine.py                         │
│                                                                  │
│   ┌────────────────┐    ┌────────────────┐    ┌────────────────┐ │
│   │ candidate pool │ →  │  hot scanner   │ →  │ admission gate │ │
│   │ (all NSE EQ)   │    │  (5-min cron)  │    │  + telemetry   │ │
│   └────────────────┘    └────────────────┘    └────────────────┘ │
│           │                      │                     │         │
│           ▼                      ▼                     ▼         │
│      seeded once          kite.get_ohlc           live_universe  │
│      at boot              (batch ≤ 500)           (in-memory)    │
└──────────────────────────────────────────────────────────────────┘
                                                       │
                                                       ▼
                                            ┌──────────────────────┐
                                            │   agents/crew.py     │
                                            │   .scan_symbols() now│
                                            │   = core ∪ discovery │
                                            └──────────────────────┘
```

**One new file**: `agents/discovery_engine.py` (~250 LOC).
**One settings block added** to `config/settings.py`.
**One line change** in `agents/crew.py`'s tick loop where the symbol list is iterated.

## 6. Module interface

```python
# agents/discovery_engine.py

@dataclass(frozen=True)
class DiscoveryCandidate:
    symbol:           str
    pct_change:       float       # signed
    volume_ratio:     float       # current_hour / avg_hour_20d
    avg_turnover_inr: float       # 20-day avg ₹
    spread_pct:       float
    score:            float       # composite admission score, 0–1
    detected_at:      datetime
    reason:           str         # human-readable trigger

@dataclass
class DiscoveryState:
    discovered_today: dict[str, DiscoveryCandidate]   # symbol → candidate
    blacklist:        dict[str, datetime]              # symbol → expires_at
    last_scan_at:     Optional[datetime]
    scans_this_session: int

class DiscoveryEngine:
    def __init__(self, kite, settings, state_store) -> None: ...

    def seed_candidate_pool(self) -> int:
        """
        At boot: pull all NSE EQ instruments via kite.instruments('NSE'),
        filter series == 'EQ' and segment == 'NSE', drop ETFs (name contains
        ETF/BeES/Liquid). Apply turnover gate using `avg_daily_turnover_inr`
        from a 20-day computed snapshot persisted to state_store.
        Returns count of seeded names. Expected: ~600–900.
        """

    def run_scan(self, now: datetime) -> list[DiscoveryCandidate]:
        """
        Pulled every 5 minutes by jobs/discovery_cron.py.
        Steps:
          1. Batch-fetch OHLC for current candidate pool via kite.get_ohlc
             (up to 500 per call, chunk if needed).
          2. Compute pct_change vs prev close, volume_ratio vs 20d hourly avg.
          3. Apply hard filters (see §7).
          4. Apply admission scoring (see §8).
          5. Bound by MAX_NEW_ADDS_PER_SCAN, MAX_TOTAL_DISCOVERY.
          6. Update self.state.discovered_today.
          7. Log every add/remove with reason.
          8. Return delta list (just the new additions this scan).
        Failures: log + return [] — never raise. Backoff on Kite 429.
        """

    def get_live_universe(self, core: list[str]) -> list[str]:
        """
        crew.py calls this each tick. Returns core ∪ currently-active
        discovery names, after pruning stale/blacklisted entries.
        Pruning rule: if symbol has fallen back inside ±1% chg for ≥15 min
        with volume_ratio < 1.0, remove it.
        """

    def report_trade_outcome(self, symbol: str, r_multiple: float) -> None:
        """
        Called by crew.py on every closed position. If `symbol` came from
        discovery and r_multiple < -1.0, increment loss counter. After
        DISCOVERY_BLACKLIST_LOSS_THRESHOLD losses (default 2), blacklist
        the symbol for DISCOVERY_BLACKLIST_DAYS (default 7) trading days.
        """
```

## 7. Hard filters (must ALL pass)

| Filter | Threshold | Rationale |
|---|---|---|
| `abs(pct_change)` | ≥ **2.5%** (settings.`DISCOVERY_MIN_PCT_MOVE`) | Below 2.5% the move is noise on most large-caps and the conviction engine's HOD-proximity / FHH-break logic won't cleanly resolve. |
| `volume_ratio` | ≥ **1.5x** (settings.`DISCOVERY_MIN_VOLUME_RATIO`) | A move without volume is a spread-and-thin-liquidity flicker. 1.5x is the same threshold the agent uses for momentum_breakout volume veto (Fix #22). |
| `avg_turnover_inr` (20d) | ≥ **₹10 cr** (settings.`DISCOVERY_MIN_AVG_TURNOVER_INR`) | Sub-₹10cr/day names cannot be exited cleanly at the position sizes the agent runs even on ₹3L capital. Adopted from Fix #5c (turnover filter). |
| `spread_pct` | ≤ **0.15%** (settings.`DISCOVERY_MAX_SPREAD_PCT`) | Existing entry-spread gate is 0.10% (settings.SPREAD_MAX_PCT). 0.15% slightly relaxed for discovery to allow mid-caps that widen briefly during fast moves. |
| `in_blacklist` | must be False | Auto-blacklist from prior loss + manual blacklist file at `config/discovery_blacklist.txt`. |
| `is_etf_or_index` | must be False | Filter by name pattern `(ETF\|BeES\|LIQUID\|GILT\|NIFTY)` and instrument segment. |
| `in_core_universe` | must be False | Avoid double-add. |

## 8. Admission scoring (soft — for ranking when MAX_NEW_ADDS_PER_SCAN exceeded)

When more candidates pass filters than the cap allows, rank by:

```python
score = (
    0.40 * tanh(pct_change_z_score) +           # how outlier the move is
    0.30 * min(volume_ratio / 3.0, 1.0) +       # volume conviction
    0.20 * (1.0 - pull_from_extreme_pct/0.05) + # near intraday hi/lo
    0.10 * min(avg_turnover_inr / 5e8, 1.0)     # liquidity bonus
)
```

`pct_change_z_score` is computed against today's NIFTY 50 % change — so a +5% move on a -1% day is more outlier than +5% on a +3% day. This keeps the engine generic and regime-aware without hardcoding regime states.

## 9. Safety bounds

| Bound | Default | Setting |
|---|---|---|
| Max new adds per single scan | 5 | `DISCOVERY_MAX_NEW_ADDS_PER_SCAN` |
| Max total live-discovery names at once | 15 | `DISCOVERY_MAX_TOTAL` |
| Discovery names per session (cumulative cap) | 40 | `DISCOVERY_MAX_PER_SESSION` |
| Auto-blacklist after N losses | 2 | `DISCOVERY_BLACKLIST_LOSS_THRESHOLD` |
| Blacklist duration (trading days) | 7 | `DISCOVERY_BLACKLIST_DAYS` |
| Scanner cadence (seconds) | 300 | `DISCOVERY_SCAN_INTERVAL_SEC` |
| First-scan delay after market open | 15 min | `DISCOVERY_FIRST_SCAN_DELAY_MIN` |

The first-scan delay ensures we never admit names during the 09:15-09:30 IST open auction noise — same principle as the existing 40-min blindness in crew.py (Fix #21), but bounded to a smaller window because discovery doesn't depend on the FHH structure.

## 10. Acceptance tests

### 10.1 Live-replay against today (2026-05-12) tape

Hook discovery_engine into a back-test driver pointed at today's intraday minute data. At each 5-min boundary from 09:30 onward, run `run_scan()` and assert:

- 09:30 scan **must surface JINDRILL** (already +5%+ by then, volume 0.6x avg in first 15 min but accelerating fast).
- 09:35 scan **must surface OIL India** (+5%+, volume strong).
- 09:30 scan **must NOT surface** RELIANCE, HDFCBANK (already in core).
- 09:30 scan **must NOT surface** any ETF, IDEA at ₹11 (turnover too low to clear the gate? — actually IDEA's turnover is high; better example: any sub-₹100cr-mcap name on a thin move).
- 09:50 scan: JSWENERGY and BSOFT appear on shortable side.

### 10.2 Negative test: low-quality mover

Inject a synthetic candidate at `pct_change = +8%`, `volume_ratio = 0.7`, `avg_turnover = ₹4 cr`. Must be **rejected** by the volume gate. If it passes, the filter is broken.

### 10.3 Stress test: scanner overload

Inject 50 synthetic candidates all passing filters at once (simulates a panic open). Must admit only `MAX_NEW_ADDS_PER_SCAN = 5`, ranked by admission score. The other 45 must NOT be admitted on subsequent scans unless their score improves — without this rule, the engine churns.

### 10.4 Blacklist cycle

Simulate two losing trades on a discovered name → assert it's blacklisted. Advance trading clock 7 days → assert blacklist expires and name is admittable again.

## 11. Integration changes (one-shot, low surface area)

- `agents/discovery_engine.py` — new file (~250 LOC).
- `config/settings.py` — add the 7 constants above (~10 lines).
- `agents/crew.py`:
  ```python
  # in __init__
  self.discovery = DiscoveryEngine(self.kite, settings, self.state)
  self.discovery.seed_candidate_pool()
  # in tick(): replace
  - for symbol in self.symbols:
  + for symbol in self.discovery.get_live_universe(self.symbols):
  # in on_position_closed():
  + self.discovery.report_trade_outcome(p.symbol, r_multiple)
  ```
- `jobs/discovery_cron.py` — new tiny file that loops every 300s and calls `crew.discovery.run_scan(now())`. Can be an asyncio task inside the main crew event loop — no separate process needed.

## 12. Failure-mode handling

| Failure | Response |
|---|---|
| `kite.get_ohlc` returns partial data | Process what we got, retry the missing chunk on the next scan. |
| `kite.get_ohlc` returns 429 / 500 | Exponential backoff (already implemented in `data/kite_client.py`). Skip this scan window. |
| Sandbox / dev mode without Kite | Engine seeds an empty pool, `get_live_universe` returns `core` unchanged. Zero impact on core path. |
| Candidate pool seeding fails at boot | Log loudly, disable discovery for the session, run on core universe only. |
| State store write fails | Discovery state is in-memory and rebuilt each session — no persistence needed beyond blacklist (which IS persisted to `discovery_blacklist.json`). |
| Conviction engine rejects every discovered name | Expected behaviour — discovery only adds to the candidate pool, it doesn't force entries. If conviction sees 0 valid setups on those names, none trade. |

## 13. Telemetry

Every scan emits to `logs/discovery.jsonl`:

```json
{"ts": "2026-05-12T09:50:00+05:30", "scan_idx": 4, "candidates_seen": 612,
 "passed_filters": 7, "admitted": 5, "admitted_names": ["JINDRILL", "OIL", "CMSINFO", "JSWENERGY", "BSOFT"],
 "rejected": [{"sym": "NOWNAME", "reason": "spread_too_wide", "spread_pct": 0.34}, ...]}
```

The dashboard's existing "Live" tab gets a new "Discovery" panel showing currently-admitted names, with click-through to the trigger reason and current chg/volume.

## 14. Phase 2.1 cutover plan

| Step | Action | Duration |
|---|---|---|
| 1 | Implement `discovery_engine.py` + tests | 4 hr |
| 2 | Add settings constants + cron hook | 30 min |
| 3 | Replay against doc-16 30-month tape — assert engine surfaces "leader of the day" >70% of sessions | 2 hr |
| 4 | Ship to server in **shadow mode** (engine runs, admits names, but a feature flag `DISCOVERY_ALLOW_TRADES=False` prevents conviction engine from acting on discovered names) | 1 day |
| 5 | Review shadow logs for 3 sessions. Confirm no false-positive flood, blacklist behaves sanely, no unexpected adds. | 3 sessions |
| 6 | Flip `DISCOVERY_ALLOW_TRADES=True`. Cap discovery-name **sizing at 50%** of core-name sizing for first 10 trades. | Week 1 |
| 7 | After 10 discovery trades, evaluate hit-rate and R-multiple vs core. If hit-rate ≥ core × 0.8, full-size. If below, hold or revert. | Week 2 |

## 15. What this does NOT solve

- **Sector-aware macro** — separate spec (doc 20, Phase 2.2). Today's tape shows STRONG_RED on NIFTY but oil-upstream and metals are ripping. Discovery surfaces the names; sector-aware macro is what *unblocks* longs against an index-negative day. Both ship together for full effect, but discovery can ship first and run shadow.
- **Continuation-quality detector** — separate (Phase 2.3). Discovery surfaces a +7% name but doesn't tell us if the move is parabolic-exhausted vs early-grinding. The conviction engine's existing HOD-proximity / FHH-break logic provides a first-cut answer, but a real classifier (LINEAR_UP / PARABOLIC / DISTRIBUTING) is the natural follow-on.
- **News catalyst attribution** — out of scope for this phase. Discovery doesn't need to know *why* the name is moving; the price+volume signal is enough. Cold-path news enrichment (already exists for core universe) can extend to discovered names in Phase 2.4 if useful.

## 16. Today's quick-and-dirty manual workaround

While discovery_engine ships, the manual workaround for today (2026-05-12) is:
1. Look at the top-mover scan I ran at 09:50 IST.
2. The agent is conviction-blocked on longs anyway (macro STRONG_RED) — so the only loss from not having discovery today is missing the **manual ONGC long** which is in the core universe and blocked solely by the macro filter (the Phase 2.2 problem, not the Phase 2.1 problem).
3. For shorts: the IT names in core universe (PERSISTENT, COFORGE, LTTS, TECHM) are sufficient — the discovery-side losers JSWENERGY / BSOFT are nice-to-have, not must-have.

So today specifically, **doc-20 (sector-aware macro)** is the higher-impact ship than this doc — but this doc is the foundational prerequisite for capturing tomorrow's JINDRILL-equivalent. Both stay on the roadmap.

---

*Status: SPEC. No code yet. Goes into Phase 2.1 implementation queue.*
*Cross-refs: doc 15 (Pattern Library — mover detection), doc 17 (Rebuild Plan — Phase 2.1), Three Laws (PROJECT_MEMORY.md top section).*
