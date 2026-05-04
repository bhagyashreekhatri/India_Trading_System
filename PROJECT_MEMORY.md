# NSE Trading System — Project Memory
*Last updated: 2026-04-28 | Phase 2 COMPLETE | Hardening fixes 1–7 deployed*

---

## ✅ Fixes deployed 2026-04-28 (read before writing code)

| # | Fix | Files | Verified by |
|---|---|---|---|
| 1 | **Stall-bug TZ correction** — `_entry_dt_aware` auto-detects host TZ; `entry_time` now written IST-aware via `_now_iso_ist()`; `is_in_cooldown` + `get_win_rate_by_hour` IST-corrected | `agents/crew.py`, `memory/trade_state.py` | sandbox UTC sim: 5-min entry reads as 5 min (was 335) |
| 2 | **Score calibration** — news baseline 0.5 → 0.0; RECOVERING regime mults: recovery_setup 1.3→1.0, momentum_breakout 1.0→1.1, failed_breakdown 1.1→0.8 | `scoring/engine.py` | replay on 151 trades: A WR 70%, A+ WR 76.5%, calibration monotonic |
| 3 | **Operational guards** — overnight veto (force-close any prior-session position), daily-loss kill switch (-2.5% of CAPITAL → freeze entries), `sl_hit` vs `sl_trail_hit` distinction | `agents/crew.py`, `config/settings.py` | targeted sim of all three guards |
| 4 | **Groq hardening** — typed retries (RateLimitError honours Retry-After, APITimeout/Connection backoff), `response_format=json_object`, `timeout=10s`, persistent disk cache `news_cache.json`, telemetry counters | `data/news_client.py` | mocked 6-path test (success/429-retry/4×429/JSONErr/BadReq/cache-restart) |
| 5 | **Multi-setup + confluence + turnover scanner** — `_detect_setups_multi` returns all matches; `confluence_count` tagged; multipliers x1.15/x1.25; scanner uses `turnover ≥ ₹50L` not raw shares | `tools/pattern_tools.py`, `agents/crew.py`, `config/settings.py` | 3 setups fired together on synthetic strong breakout |
| 6 | **Broker-side SL-M orders** — placed on entry, cancelled+replaced on TP1 / trail, cancelled before full exit; `sl_order_id` column on Position | `data/kite_client.py`, `memory/trade_state.py`, `agents/crew.py` | syntax + 10/10 engine tests |
| 7 | **Tick-size rounding (₹0.05)** — `_round_to_tick`/`_round_down_tick`/`_round_up_tick` in engine; applied in `_make_signal` (entry/SL/TP1/TP2), `_calc_tp` (both), trail SL | `scoring/engine.py`, `tools/pattern_tools.py`, `tools/score_tools.py`, `agents/crew.py`, `config/settings.py` | rounding cases verified |
| 8 | **Real-VWAP breadth** — per-tick `_vwap_cache` populated by setup detection; breadth + sector strength use real VWAP (fallback `last>open`) | `tools/volume_tools.py`, `agents/crew.py` | both bias directions fixed in mock test |
| 9 | **Sizing floor** — per-position cap 20%→10% (10 pos × ₹1.5L = ₹15L exact); risk floor 0.03% (₹450); position floor 3% (₹45k); below floor → watchlist | `config/settings.py`, `agents/crew.py` | DIVISLAB/ONGC/NMDC qty=1 trades blocked, legitimate trades enter |
| 10 | **TREND_PULLBACK setup** — strong-mover (≥3% day) second-leg pullback entry; mother-bar trend + pullback + resumption green bar | `scoring/engine.py`, `tools/pattern_tools.py`, `tests/test_engine.py` | 6 scenarios; SAPPHIRE-class detected with tick-aligned prices |
| 11 | **Daily-profit lockout** — +3% capital P&L → freeze new entries; +2% → tighten gate to 8.0 (A+/A++ only). Mirror of Fix #3 kill switch on the upside | `config/settings.py`, `agents/crew.py` | thresholds verified at all PnL levels |
| 12 | **INSIDE_BAR_BREAK setup** — 3-bar pattern: mother + inside + breakout above mother high; VWAP bias filter; tick-aligned | `scoring/engine.py`, `tools/pattern_tools.py` | 5 scenarios incl. defensive bounds |
| Dash | **Dashboard learning_tab TZ fix** — `pd.to_datetime(format='ISO8601')` handles mix of naive (legacy) + IST-aware (Fix #1) timestamps | `dashboard/learning_tab.py` | mixed-format parse verified |
| 13 | **Honest fill prices** — refetch live LTP at order time (`_allocate`); refetch at TP1 / full-exit. Stops paper P&L being inflated by 20–25 min stale signal-bar prices | `agents/crew.py` | M&MFIN class bug — entry now matches live LTP |
| 14 | **Persist regime as a column** on `positions`. ChromaDB write + EOD job both prefer the persisted regime; substring parser is fallback only for legacy rows | `memory/trade_state.py`, `agents/crew.py`, `jobs/eod_job.py` | schema migrated; new entries write regime |
| 15 | **Sector flow gating** — top-3 sectors get +0.3 score boost; weak-3 get -0.5 penalty. Trade with the flow, not against it | `agents/crew.py` | uses breadth_cache top/weak sectors; saved in score_breakdown |
| 16 | **Paper-mode slippage simulation** — 5bps entry / 10bps stop / 3bps target worsens paper fills to model live broker reality. Auto-skipped in live mode | `config/settings.py`, `agents/crew.py` | helper `_apply_paper_slippage`; applied in `_allocate`, `_partial_exit_tp1`, `_full_exit` |
| 17 | **PDH/PDL scoring boost** — entry > previous day's high earns +0.3 score nudge. Cached per-day per-symbol so only one Kite call per stock per session | `data/kite_client.py`, `agents/crew.py` | `get_pdh_pdl()`; saved as `pdh_nudge` in score_breakdown |
| 18 | **NewsAPI company-name aliases** — `COMPANY_NAMES` dict (~80 names) + `get_company_name()`; query NewsAPI with `"<company>" OR <symbol>` instead of bare ticker. Doubles news hit-rate | `config/universe.py`, `data/news_client.py` | "RELIANCE" now matches "Reliance Industries" headlines |
| 19 | **Leaders watchlist — relaxed proximity** — stocks up ≥3% with RS≥1.5% get 1.5% proximity ceiling (vs 0.7%). Catches trending entries that strict proximity rejects | `config/settings.py`, `agents/crew.py` | 6 threshold cases verified |
| 20 | **15-min HTF trend filter** — `get_htf_trend()` classifies last 4 fifteen-min bars as up/down/neutral via HH-HL count. LONG entries vetoed when HTF is DOWN. Defensive `neutral` default on any data shortage | `data/kite_client.py`, `agents/crew.py` | up/down/neutral/short cases verified |
| 21 | **Today-only VWAP/df after weekends** — `days=1` returned 0 bars on Mondays after weekends/holidays (Sun has no market data) → ALL stocks failed `len(df) ≥ 8` check → 0 setups. Now `days=3` + `_filter_to_today()` filter. Also fixes VWAP polluted by prior-session volume | `data/kite_client.py` | engine tests pass; observed log root cause was `few_candles=60/60` after weekend |
| 22 | **A1 — Volume veto for momentum_breakout** — RVOL < 2.0 → reject. Real breakouts come on volume; 60% of low-volume "breakouts" fade. New constant `MOMENTUM_BO_MIN_RVOL=2.0` | `config/settings.py`, `agents/crew.py` | engine tests pass |
| 23 | **A6 — Score-based sizing tiers** — risk scaled by grade: A++ ₹15k, A+ ₹11.25k, A ₹7.5k, B ₹3.75k. Concentrates capital in highest-conviction trades; combines multiplicatively with conservative-mode dampener | `config/settings.py`, `agents/crew.py` | size scaling verified |
| 24 | **A5 — Time-of-day score-gate nudges** — 9 IST +0.5, 10 IST +0.3, 12 IST -0.2 (best hour per file 04). Raises bar in noisy/losing hours, lowers in proven hour | `config/settings.py`, `agents/crew.py` | engine tests pass |
| 25 | **B2 — Volatility-adaptive trail** — `_try_trail_sl` multiplier now context-aware: 0.7×ATR in CHOPPY regime (tighter), 0.4×ATR when RVOL≥2 (looser, let hot trades run), else 0.5×ATR | `agents/crew.py` | engine tests pass |
| 26 | **C1 — Smart re-entry rule** — after 30-min cooldown, allow 2nd entry on same stock at 50% size; hard cap 2/day. New `count_today_trades_on()` in trade_state | `memory/trade_state.py`, `agents/crew.py` | engine tests pass |

**Constants added to `config/settings.py`:**
`DAILY_LOSS_KILL_PCT=0.025`, `DAILY_PROFIT_LOCKOUT_PCT=0.030`, `DAILY_PROFIT_TIGHTEN_PCT=0.020`, `CONFLUENCE_MULTIPLIER_2=1.15`, `CONFLUENCE_MULTIPLIER_3=1.25`, `SCAN_MIN_TURNOVER=5_000_000`, `TICK_SIZE=0.05`, `MIN_RISK_PER_TRADE_PCT=0.0003`, `MIN_POSITION_VALUE_PCT=0.03`, `MAX_POSITION_VALUE_PCT=0.10` (was 0.20).

**Schema additions on `positions`:** `sl_order_id TEXT DEFAULT ''`, `regime TEXT DEFAULT ''`.

**SetupType enum now (8 setups):** MOMENTUM_BREAKOUT, VWAP_PULLBACK, VWAP_RECLAIM, FAILED_BREAKDOWN, RANGE_BREAKOUT, RECOVERY_SETUP, **TREND_PULLBACK** (Fix #10), **INSIDE_BAR_BREAK** (Fix #12). All have multipliers across all 4 regimes.

**New runtime files:** `news_cache.json` (persistent Groq cache; in `.gitignore`).

**Helpers in `agents/crew.py`:** `_entry_dt_aware`, kill-switch block at top of `_allocate`, overnight-veto block at top of `_manage_positions`, multi-setup integration in `_detect_setups`, confluence multiplier in `_score_signals`, SL-M place/cancel/replace plumbing throughout.

**Helpers in `memory/trade_state.py`:** `_now_iso_ist`, `_to_ist`, `update_sl_order_id`. `Position` dataclass has `sl_order_id` field.

**Behaviour to expect post-deploy:**
- `stalled_no_movement` exits should drop from 71 % → < 25 %.
- A++ count should fall sharply (calibration tightened); A WR should hold ~70 %.
- Logs show `⚡ CONFLUENCE x{n}` lines, `🛑 SL-M placed`, `🛑 DAILY-LOSS KILL SWITCH`, `⚠ OVERNIGHT VETO`.
- `news_cache.json` present after first session; reload logged on restart.
- All generated prices are multiples of ₹0.05.



---

## 🔥 OPEN CRITICAL BUG — paper-trade fill-price mismatch (flagged 2026-04-29)
```
Symptom (Bhagya, live observation 2026-04-29):
  Telegram entry alert says M&MFIN bought @ ₹320.55.
  Dashboard shows entry ₹320.55.
  Within seconds, actual LTP on Kite is ₹322.05 — a ₹1.50 (~0.47%) gap.

Likely cause:
  state.open_position() stores entry_price = signal["entry_price"], which is
  the CLOSE of the trigger bar (from _detect_setups, possibly 1-3 minutes old).
  Then kite.place_order() runs — in paper mode it just stamps a fake order id,
  it does NOT refresh the actual fill price.
  → Paper P&L is computed against an optimistic entry that wouldn't be
    achievable live. All "wins" today are inflated by this slippage gap.

Where the fix likely belongs:
  - agents/crew.py::_allocate — after place_order returns, refetch quotes,
    overwrite Position.entry_price with the actual LTP.
  - OR: don't call open_position until AFTER fetching the live LTP at order time.
  - Same fix needed for partial_exit_tp1 and full_exit (exit price should be
    actual fill, not signal-bar close).

Implications for the production go-live (2-3 weeks out):
  - Live mode will reveal the true edge (with real slippage). Today's
    paper P&L is overstated by roughly the size of this gap × number of trades.
  - Real round-trip slippage on a tight scalp could be 0.3-0.6%, which
    eats much of the targeted ₹1500-3000 net per trade.

Status: ✅ FIXED 2026-04-29 as Fix #13.
  - _allocate now fetches FRESH LTP, validates proximity vs live, uses live LTP as fill
  - _partial_exit_tp1 refetches LTP at TP1 fire
  - _full_exit refetches LTP at exit
  - All paths fall back gracefully on quote failure
```

## 🚨 PRODUCTION MANDATE (Bhagya's rule, 2026-04-28)
```
This agent will move to LIVE TRADING with REAL MONEY in 2–3 weeks.
Before suggesting or writing ANY code:
  - Treat every line as production code that will handle real INR.
  - No hallucinated function names, classes, or imports — verify against the repo.
  - No vague pseudocode — every fix must be concrete, testable, and deterministic.
  - Defensive bounds (None checks, div-by-zero, empty df) on every new function.
  - All new prices must go through tick-rounding (Fix #7 helpers).
  - All new timestamps must be IST-aware (Fix #1 helpers).
  - All new scoring inputs must integrate with the regime-multiplier table.
  - When adding a SetupType: enum + REGIME_MULTIPLIERS row + tests, ALL three.
  - Verify with python -c "import ast; ast.parse(...)" + run tests/test_engine.py
    after every code change.
  - If unsure about behaviour → ask. Never guess on production code.
```

## ⚡ TOKEN DISCIPLINE — STRICT (Bhagya's rule)
```
Opus 4.7 burns tokens fast. Every Claude session must:
- Be concise. No preamble. No "Here's what I'll do" intros.
- Use Edit (not Write) when modifying files. Read only the lines needed.
- Batch related tool calls in one message — avoid round-trip confirmations.
- Short prose in chat replies. No verbose markdown unless creating a deliverable doc.
- Never re-read files already read in the same session.
- Status updates: 1–2 sentences max.
- Long deliverables (.md docs, full code files): full content is fine — that's the work product.
```

## ⚡ Claude rules for every code change session
```
AFTER EVERY BUG FIX OR CODE CHANGE — always do these 3 things automatically:

1. Commit + push (tell Bhagya to run from Mac terminal):
   cd ~/Desktop/India_Trading_System
   rm -f .git/HEAD.lock .git/index.lock   # clear locks if needed
   git add <changed files>
   git commit -m "fix: description"
   git push origin main

2. Deploy to server:
   ssh root@168.144.101.223 "cd /root/india_trading && git reset --hard HEAD && git pull && systemctl restart trading-system && echo Done"

3. Check live logs:
   ssh root@168.144.101.223 "journalctl -u trading-system -f"

Never just say "fix is done" — always provide all 3 commands at the end.
```

---

## Project identity
- **Owner:** Bhagya (Bhagyashree Khatri)
- **Project:** India_Trading_System
- **Location:** ~/Desktop/India_Trading_System (Mac)
- **Server:** DigitalOcean 168.144.101.223 (systemd service: trading-system)
- **Dashboard:** http://168.144.101.223:8501 (3 tabs working)
- **Type:** NSE intraday paper trading → live later

---

## Tech stack
```
Python 3.x
Pure Python orchestration — TradingCrew class (NOT CrewAI — removed)
Groq llama-3.3-70b  — news sentiment ONLY (not scoring)
ChromaDB 0.4.22     — vector memory (3 collections)
Kite Connect 5.0.1  — Zerodha (data + orders)
NewsAPI             — Bhagya has API key
Streamlit 1.31.1    — read-only dashboard (3 tabs)
SQLite              — trade state DB
python-dotenv       — .env management
Telegram Bot API    — real-time alerts
```

---

## Architecture: Pure Python TradingCrew (no CrewAI)

`agents/crew.py` → one `TradingCrew` class with 8 internal methods:
```
_scan_market()        150 stocks → batch quotes → top active
_detect_regime()      Nifty+BankNifty VWAP → TRENDING/CHOPPY/RECOVERING/EVENT
_detect_breadth()     50-stock sample vs VWAP → breadth_pct + top sectors
_detect_setups()      calls _detect_all_setups() per stock (pattern_tools)
_score_signals()      ScoringEngine + time filter + consecutive loss guard
_allocate()           position sizing + sector cap + proximity check + all gates
_manage_positions()   TP1 partial exit + trailing SL + full exit + EOD close
run_tick()            calls all above → returns summary dict
```

---

## 7 Setup types
```
1. momentum_breakout    — breaks above 20-bar high, volume 1.5× avg
2. vwap_pullback        — pullback to VWAP in uptrend, bullish candle
3. vwap_reclaim         — price reclaims VWAP after being below
4. failed_breakdown     — breaks below support, immediately reverses
5. range_breakout       — 10-bar range ≤2%, breaks with volume
6. recovery_setup       — fell >3% from open, recovering above VWAP
7. orb                  — Opening Range Breakout (9:15–9:30 range)
```

---

## Scoring formula
```
Raw Score = setup_quality(0-3) + volume(0-2) + market_alignment(0-2)
          + relative_strength(0-2) + news(0-1, penalty -0.5)
Final = Raw × Regime Multiplier (capped 10)

Regime multipliers:
                    TRENDING  CHOPPY  RECOVERING  EVENT
momentum_breakout     1.2     0.6      1.0        0.7
vwap_pullback         1.0     1.2      1.0        0.7
vwap_reclaim          1.0     1.1      1.4        0.7
failed_breakdown      1.0     1.1      1.1        0.7
range_breakout        1.1     0.7      0.9        0.7
recovery_setup        0.8     0.8      1.3        0.7
orb                   1.1     0.8      1.0        0.7

Grades:
A++ 9-10  → full size immediately
A+  8-9   → full size
A   7-8   → standard size
B   5-7   → half size, capital idle only
C   <5    → ignore
```

---

## Trading rules
```
PAPER_TRADING = True
Capital ₹2,00,000 | Max 10 positions | Max 30% per sector
Risk 1% = ₹2,000 per trade | qty = floor(2000 / sl_distance)
TP1 = 1R (50% exit) | TP2 = 2R (remaining 50%)
Trailing SL: after TP1 → trail by 0.5×ATR per tick
Price >0.7% from signal = skip
30-min cooldown per stock after exit
No entry before 9:20 | No entry after 14:45
Midday 13:00–14:00: score threshold +0.5
Breadth gate: <40% stocks above VWAP → no new entries
3 consecutive losses → conservative mode (score=8.0, size=50%)
EOD force-close at 15:00
3 human controls: kill switch | score threshold | max positions
```

---

## Key Position fields (do NOT use old names)
```python
# USE THESE:
tp1_price, tp2_price    # NOT target_price
entry_reason            # NOT reason
initial_sl              # original stop loss for R calculation
tp1_hit: bool           # True after partial exit
quantity_remaining      # after TP1 partial exit
```

---

## ChromaDB status
```
3 collections: signal_patterns, news_signals, regime_context
STATUS: Storing data ✅ | RAG loop NOT wired ❌

⚠️ DO NOT wire RAG into scoring yet
Need 50+ closed trades first (~2-3 weeks paper trading)
Empty DB = 0% win rate = incorrectly blocks all entries
Phase 3 ETA: mid-May 2026
```

---

## Files — ALL BUILT (Phase 1 + 2 complete)
```
config/settings.py       ✅ all params incl. TP1/TP2/trailing/breadth
config/universe.py       ✅ 150 stocks + SECTOR_MAP + SECTOR_LEADERS
data/kite_client.py      ✅ KiteDataClient
data/news_client.py      ✅ NewsClient + Groq sentiment
scoring/engine.py        ✅ ScoringEngine — 10/10 tests passing
tests/test_engine.py     ✅ full test suite
memory/trade_state.py    ✅ TradeStateManager (SQLite)
memory/chroma_client.py  ✅ ChromaMemory (3 collections)
tools/kite_tools.py      ✅
tools/volume_tools.py    ✅ breadth + sector strength
tools/pattern_tools.py   ✅ 7 setups + ORB + gap analysis
tools/news_tools.py      ✅
tools/chroma_tools.py    ✅
tools/score_tools.py     ✅ partial_exit_tp1(), close_position()
tools/telegram_tools.py  ✅ 9 alert functions
agents/crew.py           ✅ TradingCrew (pure Python)
dashboard/app.py         ✅ 3-tab Streamlit
dashboard/live_tab.py    ✅ breadth + TP1 badge + score breakdown
dashboard/analytics_tab.py ✅
dashboard/learning_tab.py  ✅ Tab 3
jobs/eod_job.py          ✅ Chroma + Telegram + weekly scorecard
main.py                  ✅ 3-min loop + premarket at 9:00
```

---

## ✅ ~~Pending bug fixes~~ — DEPLOYED 2026-04-28 (kept for history)

### Fix 1: Kite historical data retry logic — CODE ALREADY WRITTEN, NOT DEPLOYED
```
File: data/kite_client.py → get_candles()
Problem: "Request failed (kt-common)" — Kite API overload, skips stock entirely
Fix: Retry up to 3 times with 1s, 2s backoff — code already in local kite_client.py
Status: NOT pushed to server yet (server was running during market hours)
```

### Fix 2: ORB + Gap analysis broken — get_historical_data() doesn't exist — CODE FIXED LOCALLY
```
File: tools/pattern_tools.py
Problem: _get_orb_levels() and _gap_analysis() both call kite.get_historical_data()
         which does NOT exist on KiteDataClient — actual method is get_candles()
         Both fail silently (try/except returns None) → ORB never fires, premarket gaps always empty
Fix: Already applied locally:
  _get_orb_levels  line 118: get_historical_data(symbol, interval="minute", lookback_days=1)
                           → get_candles(symbol, interval="minute", days=1)
  _gap_analysis    line 251: get_historical_data(symbol, interval="day", lookback_days=3)
                           → get_candles(symbol, interval="day", days=3)
Status: Fixed in local tools/pattern_tools.py — NOT pushed to server yet
```

### Fix 3: HDFC delisted in SECTOR_LEADERS — CODE FIXED LOCALLY
```
File: config/settings.py
Problem: SECTOR_LEADERS["FINANCIAL"] had "HDFC" — merged with HDFCBANK in July 2023, delisted.
         Kite can't find instrument token → sector strength for FINANCIAL always silently fails.
Fix: Replaced "HDFC" with "HDFCAMC" (HDFC Asset Management — active & liquid)
Status: Fixed in local config/settings.py — NOT pushed to server yet
```

### EOD deploy command (all 3 fixes together):
```bash
cd ~/Desktop/India_Trading_System
rm -f .git/HEAD.lock .git/index.lock
git add data/kite_client.py tools/pattern_tools.py config/settings.py
git commit -m "fix: kite retry logic + fix get_historical_data method name + replace delisted HDFC in sector leaders"
git push origin main
ssh root@168.144.101.223 "cd /root/india_trading && git reset --hard HEAD && git pull && systemctl restart trading-system && echo Done"
```

---

## Next week priorities 🔲

### #1 — Multi-setup confluence scoring ⭐ (Bhagya's idea)
```
When stock triggers 2+ setups simultaneously:
  2 setups → Raw Score × 1.15
  3 setups → Raw Score × 1.25

Show "⚡ CONFLUENCE" badge on dashboard signals table
Log in entry_reason: "VWAP Pullback + Momentum BO (confluence x2)"

How to build:
  1. agents/crew.py → _score_signals():
     setups = _detect_all_setups(sym)  # already returns all matches
     confluence_multiplier = 1.0 + (0.15 if len(setups)==2 else 0.25 if len(setups)>=3 else 0)
     raw_score = raw_score * confluence_multiplier
  2. scoring/engine.py → add confluence_bonus kwarg to .score()
  3. dashboard/live_tab.py → show ⚡ badge if len(setups) >= 2
```

### #2 — PDH/PDL levels
```
Previous day high/low as key levels
Break above PDH: +0.3 to setup_quality
Hold above PDH on pullback: +0.2 bonus
Add to pattern_tools.py detection
```

### #3 — Multi-timeframe (15-min confirmation)
```
Currently: 5-min candles only
Add: 15-min trend must agree with setup direction
Reduces false signals in choppy market
```

### #4 — Inside bar setup (8th setup type)
```
inside_bar: tight range compression → energy coiling
High win rate on confirmed breakout
Add to pattern_tools.py → _detect_all_setups()
```

### #5 — Nifty PCR data
```
PCR > 1.2 → bullish → raise regime towards TRENDING
PCR < 0.8 → bearish → extra caution
Wire into _detect_regime() in crew.py
```

---

## Phase 3: RAG loop (wait ~mid-May 2026)
```
After 50+ closed trades:
  historical_edge = chroma.query_similar_signals(setup_type, regime)
  Add as 6th scoring component: weight 0–0.5 bonus
  Wire: crew.py _score_signals() → engine.score(historical_edge=...)
```

---

## Server deploy commands
```bash
# Server: DigitalOcean 168.144.101.223 (root, password auth)
# Project path on server: /root/india_trading   ← lowercase, NOT India_Trading_System
# Venv: /root/india_trading/venv/bin/python
# GitHub repo: https://github.com/bhagyashreekhatri/India_Trading_System

# Full one-liner deploy from Mac terminal:
ssh root@168.144.101.223 "cd /root/india_trading && git reset --hard HEAD && git pull && systemctl restart trading-system && echo Done"

# Check service:
ssh root@168.144.101.223 "systemctl status trading-system"

# Live logs:
ssh root@168.144.101.223 "journalctl -u trading-system -f"
```

---

## Day 1 observation checklist (tomorrow)
Things to watch and decide after first live day:
- How many trades does the agent take? (expect 5-15/day)
- Which setups fire most often?
- Are scores reasonable? Any setups consistently <5 (never firing)?
- Any false entries? (price moved, R:R broken)
- Breadth gate triggering? (good or too restrictive?)
- Consecutive loss protection activating?
- Telegram alerts arriving correctly?
- EOD report at 15:35 — did it run?
