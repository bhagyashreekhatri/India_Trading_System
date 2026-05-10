# 01 — Project Overview and Goal

> **Project:** India_Trading_System (NSE Intraday Scalping Agent)
> **Owner:** Bhagya
> **Mode:** Paper trading → Live (after Phase 6 readiness gate)
> **Document status:** Active project bible — update with every architectural decision.

---

## 1. Vision

Build an **agentic, LLM-driven intraday scalping system** for NSE liquid equities that thinks, reacts, and executes like a god-level professional Indian equity scalper. The agent:

- Reads tape and order flow context across 60–100 active stocks every 5 minutes (and on faster polls during high-volatility windows).
- Generates **frequent, high-probability scalp setups** — momentum breakouts, VWAP pullbacks, VWAP reclaims, failed breakdowns, range breakouts, recovery setups.
- Targets **₹1,500 – ₹3,000 net P&L per trade** *after* brokerage, STT, exchange charges, GST, SEBI fees, stamp duty, and slippage.
- Runs **without rigid trade-count caps** — 20 to 100+ trades a day are acceptable, *if and only if* each trade clears the score gate.
- Operates within strict **Groq rate-limit discipline** — every LLM token is treated as a scarce resource.

## 2. Why Intraday Scalping on NSE

NSE intraday equities offer:

- Tight bid-ask spreads on Nifty 500 names → predictable slippage cost.
- Deep liquidity in F&O underlyings (most of our 75-stock universe is F&O eligible).
- Strong intraday auto-square-off rules → leverage available without overnight gap risk.
- Reliable VWAP behaviour → institutional flow signature is detectable.
- Cross-asset context (Nifty / Bank Nifty / India VIX / FII-DII flows) is queryable in near real-time.

This combination makes systematic, high-frequency scalping more tractable here than in many global markets — provided execution latency, costs, and rate limits are respected.

## 3. Success Metrics (12-week rolling)

| Metric | Target | Hard Floor | Notes |
|---|---|---|---|
| Net P&L per winning trade | ₹1,500 – ₹3,000 | ≥ ₹800 | After all costs incl. slippage |
| Win rate | 55–62 % | ≥ 50 % | Across A / A+ / A++ trades |
| Average R:R realised | ≥ 1.4 : 1 | ≥ 1.2 : 1 | Stop = 1R, target = 1.5R minimum |
| Profit factor | ≥ 1.8 | ≥ 1.4 | Gross win ÷ gross loss |
| Max daily drawdown | ≤ 1.5 % of capital | ≤ 2.5 % | Hard kill-switch at 2.5 % |
| Max consecutive losing trades | ≤ 5 | ≤ 7 | Auto-pause after 7 |
| Slippage vs signal price | < 0.10 % | < 0.20 % | Otherwise R:R is broken |
| Groq 429 incidents | 0 / day | < 3 / day | Phase 1 acceptance gate |
| Decision latency (signal → order) | < 4 s | < 8 s | End-to-end |
| Trades per day | 20–100+ (no cap) | n/a | Quality gated, not count gated |

## 4. Profit & Cost Model

A scalper only stays alive if cost math is honest. Per-leg cost stack on NSE intraday equity (Zerodha):

- Brokerage: lower of ₹20 or 0.03 %
- STT: 0.025 % on sell side
- Exchange transaction charge: 0.00322 % NSE
- GST: 18 % on (brokerage + transaction + SEBI)
- SEBI: 0.0001 %
- Stamp duty: 0.003 % on buy side

**Round-trip ≈ 0.07–0.10 %** of turnover for typical lot sizes — meaning the trade must move enough net basis points for the gross profit to clear costs *and* hit the ₹1,500 floor.

The scoring engine and capital allocator must use the **net target**, not gross. (See `scoring/engine.py` — verify `target_R` and slippage assumptions are net of these.)

## 5. Risk Rules (Non-Negotiable)

These are floor rules. The agent must not be able to override them.

1. `PAPER_TRADING = True` until Phase 6 sign-off.
2. Capital: ₹2,00,000 paper book.
3. Max concurrent positions: **5**.
4. Max sector exposure: **30 %** of capital.
5. Risk per trade: **1 %** of capital (₹2,000) — sized off stop distance.
6. Minimum target: **1.5 R**. No exceptions.
7. Skip trade if entry price is more than **0.7 %** from the signal price (R:R broken).
8. Per-stock cool-down: **30 minutes** after any exit.
9. **No entries before 09:20 IST** (post-opening liquidity stabilisation).
10. **No entries after 15:00 IST** (square-off pressure window).
11. **Auto square-off all open positions by 15:15 IST** (well before 15:25 hard cut-off).
12. Daily loss kill-switch: **2.5 %** of capital → close all, freeze entries until next session.
13. 7 consecutive losses → auto-pause for 60 minutes, log to ChromaDB for post-mortem.
14. India VIX > 20 *and* Nifty 5-min ATR > 1.5× 20-period mean → **EVENT regime**, half size, score multiplier 0.7.

## 6. Indian Market Specifics

These constraints shape every design choice:

- **Trading hours:** 09:15–15:30 IST. Pre-open 09:00–09:08.
- **Auto square-off (Zerodha MIS):** 15:20 for equity. Build a 15:15 self-square cushion.
- **Circuit filters:** 5 / 10 / 20 % daily bands. Avoid stocks within 1 % of band — slippage explodes.
- **Tick size:** ₹0.05 most stocks, ₹0.01 sub-₹100. Stop and target rounding must respect tick.
- **Lot size on equity intraday:** none (single share), but sizing must round down to integer.
- **Order types used:** LIMIT (preferred), SL-M for stops, MARKET only on emergency exit.
- **F&O underlyings list rotates** — universe must be reviewed weekly.
- **Holidays + half days** — calendar must be loaded at boot, not hard-coded.
- **Halts on news / corporate action** — Kite returns specific status; agent must not panic-retry.
- **Index expiry days** (Tue Bank Nifty, Thu Nifty) → choppy regime more likely, reduce momentum-BO weight.
- **FII/DII print at ~18:00 IST** → next-day regime adjustment.

## 7. Trading Universe

75 liquid NSE stocks (per `config/universe.py`), F&O eligible, mapped to sectors for the 30 % cap. Universe selection criteria (verify these are encoded):

- 20-day average daily turnover ≥ ₹100 cr.
- Average true range ≥ 1.2 % (enough room to scalp).
- Tight spread (top-of-book ≤ 0.05 % typical).
- Currently F&O eligible.
- Not under SEBI surveillance / ASM / GSM stage 2+.

## 8. The Scalper's North Star

> *“I do not predict. I react fast, take what the tape gives, and refuse to give it back.”*

Every architectural choice — agent routing, scoring, sizing, exits, the rate-limit budget, the learning loop — is judged against one question: **does this make the agent behave more like a disciplined god-level scalper, or less?**

If less, it gets cut. No exceptions.
