# 01 — Project Overview and Goal

> **Project:** India_Trading_System (NSE Intraday Scalping Agent)
> **Owner:** Bhagya
> **Mode:** Paper trading (validation phase) → Live trading once edge is verified
> **Last updated:** 2026-05-10 — post Phase A + Phase D shipping, awaiting live validation

---

## 1. The goal in one line

**₹1,000 – ₹5,000 net profit per TRADE.** Per-trade, not per-day. Each trade stands alone.

Scalper-pro mindset, NOT institutional hedge fund. The system trades like a desk scalper watching the tape — it picks 3-5 high-conviction trades a day and sits on hands the rest of the time. Idle is a valid state.

## 2. Mindset hierarchy (locked)

**Scalper decides WHAT. Engineer decides HOW. Data decides WHO WAS RIGHT.**

- Trader-designed behavior, engineer-built implementation, data-validated evolution.
- Architecture serves execution quality — not the other way around.
- Where they conflict, scalper wins, engineer adapts (fail-closed defaults).

Every code change passes three tests in order:
1. **Scalper test** — would a pro scalper take/skip this trade BECAUSE of this code?
2. **Engineer test** — if this fails, does the system fail SAFE (skip) not OPEN (wrong trade)?
3. **Data test** — can we measure at EOD whether this decision was right?

If any answer is "no," the code doesn't ship.

## 3. The brutal truth (as of 280-trade audit, 2026-05-10)

The system has near-zero net edge currently:

- **Gross P&L over 280 paper trades:** +₹1,72,333
- **Realistic Indian intraday costs:** ~₹2,12,676 (₹760/trade × 280)
- **Net P&L:** **-₹40,343** (loses money in live conditions)
- **Win rate:** 53.9% (coin flip)
- **Mean R:** +0.075R gross / -0.05R net (rake eats it)
- **Stalled-no-movement exits:** 71.1% (unchanged from baseline despite 55 fixes)

The 55 fixes shipped through May 8 stabilized the infrastructure but did NOT produce edge. The migration that started 2026-05-10 (Phase A + Phase D) is the structural rework to FIND edge. See `08_Findings_From_280_Trades.md` for the full read.

## 4. Architecture in one paragraph

Pure-Python single-process orchestrator (`agents/crew.py::TradingCrew`) running an entry-and-management loop every 3 minutes during NSE hours (09:15–15:30 IST). LLM (Groq) is in cold-paths only: pre-market briefing (planned), EOD self-critique, weekly review. **NO LLM in the hot trading loop.** All entry/scoring/exit decisions are deterministic Python with sub-100ms latency budgets. State persistence: SQLite (`trade_state.db`) for trades + watchlist; ChromaDB for RAG (signal patterns, trade critiques, news). Broker: Kite Connect with broker-side SL-M orders.

## 5. Risk rules (non-negotiable)

The floor rules. The agent cannot override these.

1. `PAPER_TRADING = True` until edge is verified on 2 weeks of clean data
2. Per-trade max loss: **₹1,500** (hard cap)
3. Daily loss kill-switch: **-2.5%** of capital → freeze entries
4. Daily profit lockout: **+3%** of capital → freeze; **+2%** → tighten gate
5. Max concurrent positions: **5** (was 10, reducing to scalper-manageable size)
6. Cooldown after loss: **45 minutes** (anti-revenge)
7. Cooldown after win: **15 minutes** (let continuation fire)
8. No new entries before 09:20 IST or after 13:30 IST
9. Force square-off all positions by 15:00 IST
10. RAG proven-loser veto: skip stocks with ≥10 trades AND WR <35% historically
11. Spread filter: skip if bid-ask spread > 0.10%
12. Tick-size rounding to ₹0.05 on every order
13. Broker-side SL-M orders (stops live on the exchange, not in script)
14. Live LTP refetched at order time (no stale signal-price entries)

## 6. Current strategy (Phase A + Phase D, shipped 2026-05-10)

**Phase A — fewer, better trades:**
- Only `momentum_breakout` setup is armed for entries (6 setups disarmed)
- RVOL ≥ 2.0 hard floor
- Entry requires confluence ≥ 2 OR sector in top-3 by intraday breadth
- Goal: drop trade rate from 14/day → 3-5/day, lift mean R from +0.075 → +0.30+

**Phase D — pending-pullback retest (entry timing fix):**
- When a high-score signal fires but proximity_failed (price ran past trigger), don't skip — mark `PENDING_RETEST`
- Watch 10 minutes for price to retest trigger ± 0.3%
- On retest, fire entry. Catches NBCC-class moves that Phase A's 0.7% proximity gate would otherwise reject.

Both phases reversible via independent config flags. Validating tomorrow under live tape.

## 7. Indian market cost reality (this doesn't change)

Per round-trip on NSE intraday equity (MIS), Zerodha:
- Brokerage: ₹40 (₹20 buy + ₹20 sell)
- STT: 0.025% on sell side
- Exchange charges: 0.00322%
- GST: 18% on brokerage + exchange
- SEBI: ₹10/cr
- Stamp duty: 0.003% buy side
- Spread cost: ~0.10% of position value (0.05% per side × 2)
- Slippage: ~0.06% of position value

**Total cost: ₹226 fixed + 0.16% of position value.** A ₹5L position pays ~₹1,026 per round trip. Costs scale with size; this is non-negotiable. The strategy must produce gross moves large enough to clear this floor AND hit the ₹1,000-5,000 target.

## 8. Trading universe

150 liquid NSE stocks (`config/universe.py`), F&O-eligible, sector-mapped. Universe selection:
- 20-day average daily turnover ≥ ₹100 cr
- Tight spread, deep top-of-book
- Currently F&O eligible
- Not under SEBI surveillance / ASM / GSM stage 2+

**Note (current limitation):** the system has no dynamic intraday focus list yet. Phase B (Discovery Engine, planned post-Phase-A-validation) will add real-time promotion of names that wake up mid-session.

## 9. The North Star

> *"I do not predict. I react fast, take what the tape gives, and refuse to give it back."*

Every architectural choice is judged against one question:

**Would a pro scalper take this trade BECAUSE of this code?**

If the answer is unclear, the code is too theoretical. If the answer is "no," the code gets cut.

---

## See also

- `README.md` — index of all docs
- `07_Scalper_Architecture_Migration.md` — current 9-phase migration plan
- `08_Findings_From_280_Trades.md` — brutal data-driven read of where we are
- `../PROJECT_MEMORY.md` — single source of truth for all 58 deployed fixes
