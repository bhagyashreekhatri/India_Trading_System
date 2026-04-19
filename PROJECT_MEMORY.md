# NSE Trading System — Project Memory
*Last updated: April 2026 | Phase 2 COMPLETE*

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
ssh root@168.144.101.223
git reset --hard HEAD && git clean -fd
git pull
systemctl restart trading-system

# GitHub SSH key (if needed):
# /root/.ssh/github_key (ed25519)
# git config core.sshCommand = "ssh -i /root/.ssh/github_key"
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
