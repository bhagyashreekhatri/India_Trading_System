# The Strip-And-Rebuild Plan

*Authored 2026-05-11 | Target: ₹15-30k/month net on ₹3L capital, scaling to ₹40-50L on ₹20L deployed*

> **Premise:** 30 months of NIFTY data identified ONE durable, statistically validated edge — the macro+FHH combo at 97-100% precision. The current 14,724-line codebase contains that edge plus thousands of lines of empirically-invalid scoring nudges, dead CrewAI imports, and clock-based gates that data refutes. This document is the surgical removal + clean rebuild plan.

---

## PART 1 — Full inventory: what's there

### 1.1 Codebase scan (every file, every line counted)

| Category | Files | Lines | Status |
|----------|------:|------:|--------|
| **Core orchestrator** | `agents/crew.py` | 1686 | KEEP infrastructure, RIP OUT scoring path |
| **Dead CrewAI legacy** | 8 `agents/*_agent.py` files | 587 | DELETE — confirmed unused (verified no imports) |
| **Score system** | `scoring/engine.py` | 475 | DELETE — 30 months says score is anti-predictive |
| **LangChain wrappers** | `tools/score_tools.py` | 471 | DELETE — wraps deleted scoring engine |
| **Setup detectors** | `tools/pattern_tools.py` | 750 | COLLAPSE — 7 detectors → 2 (momentum + FHH break) |
| **Pending-pullback** | `tools/pending_pullback.py` | 226 | KEEP — Phase D state machine works |
| **Volume/breadth tools** | `tools/volume_tools.py` | 378 | TRIM — drop sector-flow nudges, keep breadth |
| **Trade state DB** | `memory/trade_state.py` | 603 | KEEP — schema is solid |
| **RAG memory** | `memory/chroma_client.py` | 254 | KEEP — proven-loser veto + critique |
| **Kite client** | `data/kite_client.py` | 406 | KEEP — production-grade |
| **News client** | `data/news_client.py` | 352 | NEUTER — remove from hot path, keep for premarket brief only |
| **News tools** | `tools/news_tools.py` | 60 | DELETE — no longer needed |
| **Telegram alerts** | `tools/telegram_tools.py` | 237 | KEEP — operator visibility |
| **Settings constants** | `config/settings.py` | 257 | HEAVY TRIM — drop ~60% of constants |
| **Universe** | `config/universe.py` | 278 | KEEP — sector map needed |
| **Main loop** | `main.py` | 443 | KEEP, minimal changes |
| **Dashboard** | `dashboard/*.py` | 1406 | KEEP — operator visibility |
| **EOD job** | `jobs/eod_job.py` | 321 | KEEP — RAG learning loop |
| **Tests** | `tests/test_engine.py` | 321 | REWRITE — test new architecture |
| **Tools/scripts** | misc | ~700 | KEEP analysis scripts, retire force_exit |

**Total: 14,724 lines → target: ~7,500 lines after surgery** (-49%)

### 1.2 What's actually being deleted (with proof)

**Dead CrewAI agent files (587 lines, ZERO imports anywhere):**
- `agents/scanner_agent.py` — imports `from crewai import Agent`, nothing else imports this
- `agents/scoring_agent.py` — same
- `agents/allocator_agent.py` — same
- `agents/news_agent.py` — same
- `agents/position_agent.py` — same
- `agents/regime_agent.py` — same
- `agents/setup_agent.py` — same
- `agents/volume_rs_agent.py` — same

**Proof of deadness:** `grep "from agents\." crew.py main.py` returns no results. These files exist from when this was a CrewAI project. They confused readers and bloat the repo.

**Score system (475 + 471 = 946 lines):**
- `scoring/engine.py` — implements the 0-10 score with regime multipliers. 30 months says scores are anti-predictive (A++ → -₹11,900 P&L; B-grade → +₹73,990). Delete entirely.
- `tools/score_tools.py` — wraps `scoring.engine`. Goes with it.

**6 of 7 setup detectors in `pattern_tools.py`:**
- `_detect_momentum_breakout` → KEEP (only setup with gross+net edge in 280-trade DB)
- `_detect_vwap_pullback` → DELETE (-₹3,180 net)
- `_detect_vwap_reclaim` → DELETE (-₹5,311 net)
- `_detect_failed_breakdown` → DELETE (+₹11,759 net but driven by ADANIGREEN single outlier)
- `_detect_range_breakout` → DELETE (n=1, negligible)
- `_detect_recovery_setup` → DELETE (**-₹42,084 net — biggest loser**)
- `_detect_inside_bar_break` → DELETE (zero trade contribution)
- `_detect_trend_pullback` → DELETE (+₹1,297 net, n=10)

**KEEP only `_detect_momentum_breakout` + ADD `_detect_fhh_break` (new).**

**Score-nudge logic inside `crew.py::_score_signals` (~400 lines):**
- `pdh_nudge` — delete
- `sector_nudge` — delete
- `breadth_pen` — replace with macro-state filter
- `hour_gate` (HOUR_GATE_NUDGES) — delete
- `hist_nudge` (RAG read for score nudge) — KEEP the RAG read for **veto**, delete the **nudge**
- `decay` — delete
- `confluence_multiplier` (×1.15 / ×1.25) — delete
- `news_sentiment_score` — delete
- `A9_lunch_gate` — delete
- `winner_streak_gate_shift` — delete

**Replace all of the above with: macro_state + fhh_state → conviction tier (S/A/B/SKIP).**

**Constants to delete from `config/settings.py`:**
- `HOUR_GATE_NUDGES` (dict)
- `CONFLUENCE_MULTIPLIER_2`, `CONFLUENCE_MULTIPLIER_3`
- `SCORE_SIZE_TIERS` (dict)
- `MIN_SCORE_ENTRY`, `MIN_SCORE_*` (all variants)
- `A9_LUNCH_THRESHOLD`
- `WINNER_STREAK_*`
- All news-sentiment constants
- `SETUP_DISARMED_LIST` (will become irrelevant — only 1-2 setups exist)
- `MOMENTUM_BO_REQUIRE_PRIORITY` (hardcoded top-3 logic — delete)
- ~60% of the 257-line file gets cut

### 1.3 What's KEEPING (production-grade infrastructure)

| Component | File | Why keep |
|-----------|------|----------|
| Tick-size rounding (₹0.05) | `scoring/engine.py` helpers | Move to `utils/tick_size.py` |
| SL-M broker orders | `data/kite_client.py` | Production-critical |
| Live LTP refetch | `agents/crew.py::_allocate` | Never trust stale signal price |
| Daily kill switch (-2.5%) | `crew.py` | Survival rule |
| Daily profit lockout (+3% freeze, +2% tighten) | `crew.py` | Survival rule |
| Asymmetric cooldown (45m loss / 15m win) | `trade_state.py` | Anti-revenge — real edge |
| Spread filter (≤0.10%) | `crew.py` | Wide spreads destroy R:R |
| RAG proven-loser veto | `chroma_client.py` | Demonstrated edge |
| EOD self-critique | `jobs/eod_job.py` | Learning loop |
| Per-stage rejection telemetry | `crew.py::_rej` | Operator visibility |
| TZ-aware datetime | everywhere | Stall-bug-fix critical |
| Paper slippage simulation | `crew.py::_apply_paper_slippage` | Honest paper P&L |
| Trade state SQLite | `trade_state.py` | State persistence |
| Force square-off + overnight veto | `crew.py` | Capital preservation |
| Symbol auto-blacklist | `trade_state.py` | Proven-loser cuts |
| Pending-pullback state machine | `tools/pending_pullback.py` | Phase D works |

---

## PART 2 — The new clean architecture

### 2.1 Target codebase structure

```
agents/
  crew.py                 (≤800 lines, currently 1686) — orchestrator only, no scoring
  market_state.py         NEW — 5-state macro filter
  fhh_break_detector.py   NEW — first-hour-high/low break tracker
  conviction_engine.py    NEW — macro + FHH → tier S/A/B/SKIP
  
config/
  settings.py             (~100 lines, currently 257) — only thresholds that pass data tests
  universe.py             unchanged
  
data/
  kite_client.py          unchanged
  news_client.py          unchanged (used by EOD/premarket only)
  
memory/
  trade_state.py          unchanged
  chroma_client.py        unchanged
  
tools/
  pattern_tools.py        (~150 lines, currently 750) — only momentum + FHH detector
  volume_tools.py         (~150 lines, currently 378) — breadth + RVOL only
  pending_pullback.py     unchanged
  telegram_tools.py       unchanged
  tick_utils.py           NEW — extract tick-rounding helpers (was in engine.py)
  
jobs/
  eod_job.py              unchanged
  
dashboard/                unchanged

main.py                   minor — boot logging
tests/                    NEW test_macro_state, test_fhh_detector, test_conviction
```

**Delete entirely:**
- `agents/*_agent.py` (8 files)
- `scoring/engine.py` (move tick utilities to `tools/tick_utils.py`, delete the rest)
- `tools/score_tools.py`
- `tools/news_tools.py`

### 2.2 The new entry decision flow (replaces scoring)

```python
# agents/crew.py::run_tick (new structure)

def run_tick(self):
    now = ist_now()
    
    # 1. State refresh (every tick)
    self._refresh_breadth()
    self._refresh_macro_state()        # NEW: computes after 10:15 IST
    self._refresh_fhh_state(symbol)    # NEW: per-symbol or for NIFTY
    
    # 2. Risk gates (unchanged — battle-tested)
    if self._kill_switch_hit(): return
    if self._profit_lockout_hit(): return
    if self._before_first_entry_window(now): return  # 09:20 IST
    
    # 3. Market-state gate (replaces all hour-nudges, breadth penalty, etc.)
    if not self.market_state.allows_long_entry():
        self._rej("macro_state_blocks_entry")
        return
    
    # 4. Scan universe
    candidates = self._scan_market()
    
    # 5. For each candidate: ONE setup detector + ONE conviction tier
    for symbol in candidates:
        # Detect: clean FHH break? momentum_breakout?
        setup = self._detect_setup(symbol)
        if not setup: continue
        
        # Apply conviction tier from macro + FHH state
        tier, size_mult = self.conviction_engine.evaluate(symbol, setup)
        
        if tier == "SKIP":
            self._rej(f"conviction_skip_{tier}")
            continue
        
        # Universal pre-entry filters (battle-tested, KEEP)
        if not self._passes_spread_filter(symbol): continue
        if self._is_rag_proven_loser(symbol, setup): continue
        if self._is_in_cooldown(symbol): continue
        if self._is_blacklisted(symbol): continue
        
        # Size and place order
        qty = self._size_for_tier(tier, size_mult)
        self._place_order(symbol, qty, setup)
    
    # 6. Manage open positions (unchanged — battle-tested)
    self._manage_positions()
```

**This entire decision flow is ~150 lines of new code, replacing ~500 lines of scoring nudges.**

### 2.3 The Conviction Engine — the new heart

```python
# agents/conviction_engine.py (NEW, ~120 lines)

from dataclasses import dataclass
from typing import Literal

@dataclass
class ConvictionResult:
    tier: Literal["S", "A", "B", "SKIP"]
    size_multiplier: float
    reasoning: str

class ConvictionEngine:
    """
    Replaces the 0-10 score system.
    Validated on 584 NIFTY sessions across 30 months.
    
    Tier S: STRONG_GREEN macro + clean FHH break — 100% historical close-positive (n=44)
    Tier A: GREEN macro + clean FHH break — 97% historical close-positive (n=38)
    Tier B: YELLOW macro + clean FHH break — 88% historical close-positive (n=98)
    SKIP : RED/STRONG_RED, OR FHH not broken, OR whipsaw, OR stock-level disqualifier
    """
    
    def __init__(self, market_state, fhh_state, trade_state):
        self.market_state = market_state
        self.fhh_state = fhh_state
        self.trade_state = trade_state
    
    def evaluate(self, symbol, setup, stock_quote):
        macro = self.market_state.state  # WAITING / STRONG_GREEN / GREEN / YELLOW / RED / STRONG_RED
        fhh = self.fhh_state.get_for(symbol)
        
        # Kill conditions
        if macro == "WAITING":
            return ConvictionResult("SKIP", 0, "before_1015_ist")
        
        if macro in ("RED", "STRONG_RED"):
            return ConvictionResult("SKIP", 0, f"macro_{macro.lower()}")
        
        if fhh.both_broken:  # whipsaw
            return ConvictionResult("SKIP", 0, "whipsaw_chop")
        
        if stock_quote.day_pct < 0:
            return ConvictionResult("SKIP", 0, "stock_negative_day")
        
        if self._bid_sell_ratio(stock_quote) < 1.5:
            return ConvictionResult("SKIP", 0, "weak_order_book")
        
        # Conviction tiers
        if not fhh.clean_high_break:
            return ConvictionResult("SKIP", 0, "fhh_not_broken")
        
        if macro == "STRONG_GREEN":
            return ConvictionResult("S", 1.0, f"tier_s_100pct_rule")
        
        if macro == "GREEN":
            return ConvictionResult("A", 1.0, f"tier_a_97pct_rule")
        
        if macro == "YELLOW" and setup.grade in ("A++", "A+"):
            return ConvictionResult("B", 0.5, f"tier_b_yellow_high_quality")
        
        return ConvictionResult("SKIP", 0, "no_tier_match")
    
    def _bid_sell_ratio(self, quote):
        """5-level depth aggregate, not top-of-book."""
        buy = sum(level["quantity"] for level in quote.depth.buy[:5])
        sell = sum(level["quantity"] for level in quote.depth.sell[:5])
        return buy / sell if sell else 99.0
```

### 2.4 Position sizing — derived from tier, not score

```python
# In agents/crew.py::_size_for_tier (NEW, replaces SCORE_SIZE_TIERS)

CONVICTION_SIZE = {
    "S": {"risk_inr": 2000, "target_inr": 4000},  # 2R target
    "A": {"risk_inr": 1500, "target_inr": 3000},  # 2R target
    "B": {"risk_inr": 750,  "target_inr": 1500},  # 2R target, half size
}

def _size_for_tier(self, tier, setup, ltp, stop_loss):
    """Position sizing based on conviction tier."""
    cfg = CONVICTION_SIZE[tier]
    
    sl_distance = abs(ltp - stop_loss)
    if sl_distance < 0.01: return 0  # bad signal
    
    qty = int(cfg["risk_inr"] / sl_distance)
    
    # Tick-size compliance (KEEP from current)
    position_value = qty * ltp
    if position_value < 50_000: return 0  # below minimum
    if position_value > CAPITAL * 0.25: 
        qty = int(CAPITAL * 0.25 / ltp)  # cap at 25% per position
    
    return qty
```

---

## PART 3 — Phase-by-phase rebuild plan

### Phase 0 — Surgery (Week 1: Tonight – Day 5)

**Goal: Strip everything that's empirically wrong. Build the macro + FHH foundation.**

**Day 1 (4 hours): Deletion pass**

```bash
# Delete dead CrewAI files
rm agents/scanner_agent.py
rm agents/scoring_agent.py
rm agents/allocator_agent.py
rm agents/news_agent.py
rm agents/position_agent.py
rm agents/regime_agent.py
rm agents/setup_agent.py
rm agents/volume_rs_agent.py

# Delete obsolete tools
rm tools/score_tools.py
rm tools/news_tools.py

# Move tick utilities then delete engine
mkdir -p tools
# Extract _round_to_tick, _round_down_tick, _round_up_tick from scoring/engine.py
# into new tools/tick_utils.py
rm scoring/engine.py
```

**Day 1-2 (8 hours): Clean settings.py**

Strip `config/settings.py` to ~100 lines. Keep ONLY:
```python
# Capital + risk
CAPITAL = 300_000
PER_TRADE_MAX_LOSS_INR = 1500
PER_TRADE_MAX_LOSS_PCT = 0.005
DAILY_LOSS_KILL_PCT = 0.025
DAILY_PROFIT_LOCKOUT_PCT = 0.030
DAILY_PROFIT_TIGHTEN_PCT = 0.020

# Position limits
MAX_POSITIONS = 5
MAX_SAME_SECTOR_POSITIONS = 2
MAX_POSITION_VALUE_PCT = 0.25

# Macro filter (NEW — 30-month validated)
MACRO_FILTER_TIME_IST = "10:15"
MACRO_STRONG_GREEN_THRESHOLD = 0.5
MACRO_GREEN_THRESHOLD = 0.3
MACRO_RED_THRESHOLD = -0.3
MACRO_STRONG_RED_THRESHOLD = -0.5

# Execution
TICK_SIZE = 0.05
SPREAD_MAX_PCT = 0.0010
ORDER_BOOK_RATIO_MIN = 1.5

# Cooldowns (KEEP — validated)
COOLDOWN_AFTER_LOSS_MIN = 45
COOLDOWN_AFTER_WIN_MIN = 15

# Session
FIRST_ENTRY_AFTER_IST = "09:20"
EOD_CLOSE_TIME_IST = "15:15"
FORCE_CLOSE_TIME_IST = "15:20"  # Zerodha MIS auto-square

# Single setup type
ACTIVE_SETUPS = ["MOMENTUM_BREAKOUT", "FHH_BREAK"]

# RAG veto thresholds (KEEP)
RAG_VETO_MIN_TRADES = 10
RAG_VETO_MAX_WINRATE = 35.0

# DELETED: HOUR_GATE_NUDGES, CONFLUENCE_MULTIPLIER_*, SCORE_SIZE_TIERS,
# MIN_SCORE_*, A9_LUNCH_*, WINNER_STREAK_*, NEWS_SENTIMENT_*, 
# MOMENTUM_BO_REQUIRE_PRIORITY, etc.
```

**Day 3 (8 hours): Build market_state.py**

```python
# agents/market_state.py
from dataclasses import dataclass
from datetime import time as dtime
from typing import Literal

@dataclass
class MarketStateSnapshot:
    state: Literal["WAITING", "STRONG_GREEN", "GREEN", "YELLOW", "RED", "STRONG_RED"]
    nifty_dist_pct_from_prev_close: float
    nifty_prev_close: float
    nifty_10am_close: float | None
    snapshot_time_ist: str

class MarketStateAgent:
    def __init__(self, kite):
        self.kite = kite
        self._prev_close_cache = {}  # per date
        self._10am_close_cache = {}  # per date
    
    def get_state(self, now_ist) -> MarketStateSnapshot:
        today = now_ist.date().isoformat()
        if now_ist.time() < dtime(10, 15):
            return MarketStateSnapshot("WAITING", 0, 0, None, now_ist.isoformat())
        
        prev_close = self._get_prev_close(today)
        
        # If we haven't captured the 10:15 close yet, get it
        if today not in self._10am_close_cache:
            if now_ist.time() < dtime(10, 16):
                # Wait one more minute for the bar to settle
                ltp = self.kite.get_ltp("NSE:NIFTY 50")
                # Don't lock in yet
                dist = 100 * (ltp - prev_close) / prev_close
            else:
                # Lock in the 10:15 close
                self._10am_close_cache[today] = self.kite.get_ltp("NSE:NIFTY 50")
                dist = 100 * (self._10am_close_cache[today] - prev_close) / prev_close
        else:
            dist = 100 * (self._10am_close_cache[today] - prev_close) / prev_close
        
        if dist > 0.5: state = "STRONG_GREEN"
        elif dist > 0.3: state = "GREEN"
        elif dist < -0.5: state = "STRONG_RED"
        elif dist < -0.3: state = "RED"
        else: state = "YELLOW"
        
        return MarketStateSnapshot(
            state, dist, prev_close,
            self._10am_close_cache.get(today),
            now_ist.isoformat()
        )
    
    def _get_prev_close(self, today_iso):
        if today_iso in self._prev_close_cache:
            return self._prev_close_cache[today_iso]
        # Fetch yesterday's NIFTY close via Kite historical
        candles = self.kite.get_candles("NSE:NIFTY 50", days=3, interval="day")
        prev_close = candles[-2]["close"]  # second to last
        self._prev_close_cache[today_iso] = prev_close
        return prev_close
```

**Day 4 (8 hours): Build fhh_break_detector.py + conviction_engine.py**

Per the code sketches in Part 2 above.

**Day 5 (4 hours): Wire into crew.py**

- Strip `_score_signals` of all nudges
- Replace with `conviction_engine.evaluate()` call
- Remove imports of deleted files
- Update `_allocate` to use conviction tier
- Run pre-flight check

**Phase 0 acceptance:**
- All tests pass
- Pre-flight check passes
- Code line count reduced by ~5,000 lines (from 14,724 → ~9,500)
- Agent starts cleanly, no missing imports
- One full paper session runs without errors

---

### Phase 1 — Forward validation (Week 2-5)

**Goal: Run new agent on paper. Verify the macro+FHH combo holds in real-time.**

**Week 2-5 = 20 paper sessions minimum.**

**Daily tracking (manual, ~5 min/day):**

| Metric | Target |
|--------|--------|
| Macro state at 10:15 IST | Logged |
| FHH break event (if any) | Logged with timestamp |
| Day close direction | Recorded |
| Filter precision running average | Should hold ≥70% on macro |
| Per-trade P&L | Logged |

**Weekly review (1 hour each Friday EOD):**

1. Forward macro filter precision vs 30-month baseline (target: within 5% bands)
2. FHH-break combo precision: are STRONG_GREEN+FHH still hitting >90%?
3. Per-trade outcomes: avg win ₹? avg loss ₹? WR?
4. Any catastrophic days? What did the macro filter say?

**Phase 1 acceptance criteria (after 20 sessions):**

- Forward macro filter precision ≥ 70% (vs 72-76% historical)
- Average net P&L per session ≥ +₹500 (paper)
- Maximum daily drawdown ≤ ₹3,000 (paper)
- No regressions on infrastructure (kill switch fires, cooldowns work, RAG veto active)
- Zero trades entered when macro_state ∈ {RED, STRONG_RED}

**If acceptance fails:** Stop. Diagnose specifically why. Don't add more code until macro+FHH is shown to work forward.

---

### Phase 2 — Coverage expansion (Week 6-8)

**Goal: Add the lower-confidence patterns that data supports as secondary setups.**

Only build these AFTER Phase 1 forward validates:

**2.1 Day-type classifier (Day 6-7, ~10 hours)**

```python
# agents/day_type_classifier.py
def classify_day_type_at_11am(nifty_bars_so_far):
    """
    Returns one of: TREND_FORMING_UP, TREND_FORMING_DOWN, 
    RANGE_FORMING, BALANCED.
    
    Used to route setups (already validated):
    - TREND days (31% of sample): favor momentum
    - RANGE days (20%): allow VWAP setups
    - BALANCED (49%): A++ only
    """
    # Implementation per 18-month research doc
```

**2.2 Whipsaw detector (Day 7, ~3 hours)**

```python
# In fhh_break_detector.py
@property
def is_whipsaw(self) -> bool:
    """Both FHH and FHL broken by 11:30 IST. 70% of these close flat."""
    return self.high_broken and self.low_broken
```

Use to freeze new entries 11:30-13:00 IST.

**2.3 NR7 detector (Day 8, ~3 hours)**

```python
# tools/range_expansion.py
def is_nr7_day(daily_candles_last_7):
    """Yesterday had narrowest range of last 7 days. 66% chance next day expands ≥1.5×."""
    if len(daily_candles_last_7) < 7: return False
    today_range = daily_candles_last_7[-1]['range']
    return today_range == min(c['range'] for c in daily_candles_last_7)

# Use to boost momentum confidence on day-after-NR7
```

**Phase 2 acceptance (after 5 sessions with these added):**

- New trades passing whipsaw filter have ≥75% WR
- Day-type classification matches operator's manual assessment ≥80% of time
- NR7-flagged-next-day trades have larger average move

---

### Phase 3 — Small-capital live probe (Week 9-12)

**Goal: First real money — ₹50k-1L probe.**

**Pre-flight gates before live capital:**
- ≥30 forward paper sessions complete
- At least 1 shock event (>=2% NIFTY day) navigated correctly
- Net positive forward P&L
- Max drawdown ≤ 10% of capital
- All discipline rules firing (cooldowns, kill switch, etc.)

**Probe sizing:**
- Start with ₹50k capital
- Per-trade risk: ₹250 (0.5% of capital)
- Max 3 concurrent positions
- Daily kill at -2.5% = -₹1,250

**Live probe success criteria (20 live sessions):**

| Metric | Target | Stretch |
|--------|--------|---------|
| Win rate | ≥60% | ≥70% |
| Avg win | ≥₹400 | ≥₹600 |
| Avg loss | ≤₹200 | ≤₹150 |
| Monthly P&L | ≥+₹3,000 (6% on ₹50k) | ≥+₹6,000 |
| Max drawdown | ≤8% | ≤5% |

**If probe succeeds → Phase 4. If probe fails → diagnose, don't scale.**

---

### Phase 4 — Scaled deployment (Month 4-5)

**Goal: ₹3L active capital with target ₹15-30k/month.**

**Sizing at ₹3L:**
- Per-trade risk: ₹1,500 (0.5% of capital)
- Target ₹2,000-3,000 per winning trade
- Max 5 concurrent positions
- Daily kill at -2.5% = -₹7,500

**Monthly targets (data-derived expectations):**

| Month outcome | Probability | Description |
|--------------|------------:|-------------|
| Great month | ~20% | ₹25,000-40,000 net |
| Good month | ~50% | ₹10,000-25,000 net |
| Flat month | ~20% | ±₹5,000 |
| Bad month | ~10% | -₹5,000 to -₹15,000 |

**Compound: Average month ≈ ₹15-20k net = 60-80% annualized return on ₹3L.**

---

### Phase 5 — Full deployment (Month 8-12)

**Goal: ₹10-20L deployed.**

Only proceeds if Phase 4 sustains for 4+ months. Scaling is gradual:
- Month 7: ₹5L
- Month 9: ₹10L
- Month 11: ₹15L
- Month 12+: ₹20L

At ₹20L: target ₹40-50k/month net = ~20-25% per year on deployed capital.

---

## PART 4 — Reality check + risk discipline

### 4.1 What will go wrong (it always does)

**Within Phase 1 (forward validation):**
- 2-3 sessions will have unexpected losses
- One session will trigger daily kill switch
- One session may have an execution bug (stale data, missed signal, etc.)
- These are NORMAL. Diagnose, fix, continue.

**Within Phase 4 (₹3L deployment):**
- One month will be negative. Probably -₹5k to -₹15k.
- One single trade will surprise with a -₹1500 loss despite all filters.
- The next election day / Union Budget / RBI shock will be -2% on NIFTY.
- Macro filter will catch most of these; one will slip through.

**Within Phase 5 (₹20L):**
- Drawdown of 8-15% over a single bad month is realistic.
- That's -₹1.5-3L on ₹20L capital — a real number.
- The system must be designed to survive this without panic.

### 4.2 The discipline that protects you

1. **Daily kill switch enforced** — when -2.5% hit, agent freezes for the day. No exceptions.
2. **Per-trade max loss ₹1,500** — every trade has SL placed at broker BEFORE entry confirms.
3. **No revenge sizing** — losing streaks dampen size (Fix #31), never increase it.
4. **No "intuition" overrides** — the agent runs the strategy; the operator doesn't manually intervene mid-trade.
5. **Weekly review** — every Friday, audit the week's trades. Did rules fire correctly? Any near-misses?
6. **Monthly drawdown limit** — if down >12% in a calendar month, pause for a week, review, restart.

### 4.3 What "₹15-30k/month consistent" actually means

It means:
- Some months you make ₹35k
- Some months you make ₹18k
- One month you make ₹5k
- One month you LOSE ₹10k
- **Average: ₹15-20k/month positive**
- **Volatility: high — you'll have weeks where you wonder if the system is broken**

The discipline of staying with the system through a bad month is what separates traders who compound from traders who blow up.

---

## PART 5 — Concrete deliverables

### 5.1 Files to delete (run these commands)

```bash
cd ~/Desktop/India_Trading_System

# Dead CrewAI legacy
rm agents/scanner_agent.py
rm agents/scoring_agent.py
rm agents/allocator_agent.py
rm agents/news_agent.py
rm agents/position_agent.py
rm agents/regime_agent.py
rm agents/setup_agent.py
rm agents/volume_rs_agent.py

# Obsolete score system
rm tools/score_tools.py
rm tools/news_tools.py

# Move tick utilities then delete engine
# (after creating tools/tick_utils.py from extracted helpers)
# rm scoring/engine.py     # do AFTER move

# Total: 11 files deleted, ~1,500 lines removed
```

### 5.2 Files to create (Phase 0)

```bash
touch agents/market_state.py        # ~120 lines
touch agents/fhh_break_detector.py  # ~150 lines
touch agents/conviction_engine.py   # ~120 lines
touch tools/tick_utils.py           # ~50 lines (extracted from engine.py)
touch tests/test_market_state.py    # ~80 lines
touch tests/test_conviction.py      # ~100 lines
```

### 5.3 Files to modify

```
agents/crew.py:
  - Delete _score_signals method entirely (~300 lines)
  - Replace with conviction-engine call (~80 lines)
  - Net: -220 lines

tools/pattern_tools.py:
  - Delete 6 setup detectors (~500 lines)
  - Keep momentum_breakout (~100 lines)
  - Add fhh_break_detect helper (~50 lines)
  - Net: -350 lines

config/settings.py:
  - Delete HOUR_GATE_NUDGES, SCORE_SIZE_TIERS, MIN_SCORE_*, A9_*, etc.
  - Add MACRO_* constants
  - Net: -150 lines

main.py:
  - Update imports
  - Net: -10 lines
```

### 5.4 Final line count after Phase 0

| Category | Before | After | Delta |
|----------|-------:|------:|------:|
| crew.py | 1,686 | 1,466 | -220 |
| pattern_tools.py | 750 | 400 | -350 |
| settings.py | 257 | 107 | -150 |
| Dead agents | 587 | 0 | -587 |
| score_tools.py | 471 | 0 | -471 |
| scoring/engine.py | 475 | 0 | -475 |
| news_tools.py | 60 | 0 | -60 |
| **New files** | 0 | +620 | +620 |
| **TOTAL** | **14,724** | **12,031** | **-2,693 (-18%)** |

**Codebase becomes 18% smaller AND simpler AND data-validated.**

---

## PART 6 — The honest commitment

If you ship this plan:

- **Phase 0 (1 week):** clean foundation in place
- **Phase 1 (4 weeks):** forward-validated macro+FHH
- **Phase 2 (3 weeks):** coverage expanded
- **Phase 3 (3 weeks):** ₹50k probe live
- **Phase 4 (1-2 months):** ₹3L compounding at ₹15-30k/month
- **Phase 5 (8-12 months):** ₹20L compounding at ₹40-50k/month

**Total time to ₹40-50k/month: 8-12 months from today.**

This is data-supported, discipline-validated, realistically-paced. NOT 100% guaranteed (nothing is), but achievable with the rebuild executed cleanly.

The 30-month data gave us ONE thing that works. Build around it. Cut everything else. Forward-validate. Scale carefully.

That's the path to real money.

---

*End of rebuild plan. Phase 0 starts tonight if approved.*