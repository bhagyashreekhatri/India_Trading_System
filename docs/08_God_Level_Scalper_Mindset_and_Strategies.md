# 08 — God-Level Scalper Mindset & Strategies

> The agent's prompts, weights, and exit logic are downstream of its mental model. This document is the mental model. If a future LLM prompt does not align with what's written here, the prompt is wrong.

---

## 1. The mental model

A god-level intraday scalper on NSE operates on three internal stories at all times:

1. **The market's story** — what regime we're in, what flow looks like, where the auction is taking place.
2. **The stock's story** — where it opened relative to yesterday, how it's behaving against its sector and Nifty, what the institutional footprint suggests.
3. **My own story** — am I sharp, am I tilted, what's my P&L, what's my next-trade size?

Decisions are an intersection. When all three align, you press. When two align, you participate cautiously. When only one aligns, you sit. When none align, you do something else with your day.

The agent's prompts and routing must keep these three threads explicit.

## 2. Operating principles

- **The tape is the truth.** Indicators describe; price action confirms. Where they conflict, price wins.
- **Take what the tape gives.** Not every day is a 5-trade day. Some days are 50, some are 5, some are 0. Forcing trades is the single biggest killer.
- **Cut losers without ceremony.** A scalp stop-loss is a small payment for the right to be wrong cheaply.
- **Let winners breathe — but only inside the scalp window.** A scalp turns into a position trade only when the structure clearly invites it; usually it doesn't.
- **One bad trade does not exist** — only bad trade *processes*. A losing trade taken with proper setup, sizing, stop, and exit logic is a *good* trade. A winning trade taken on a whim is still a *bad* trade.
- **Round numbers, prior-day high/low, VWAP, opening range** — these are the magnets. Trade with respect for them.
- **Respect the bid-ask.** A wide spread is the market telling you it doesn't want this trade. Don't argue.
- **Never average down on a scalp. Ever.**
- **Never add to a winner past the scalp R:R.** That's a different strategy; we're not running it.
- **Do not chase.** If price is > 0.7 % from the signal, the trade is gone. Move on.
- **The 09:15 candle is a trap as often as a tell.** Wait for the second 5-minute close on most days.

## 3. Time-of-day playbook

NSE intraday has distinct micro-regimes within each session. The agent should reason about *which one* it's in.

### 09:15–09:30 — **Opening drive**
- High volatility, gap-fill or gap-extend behaviour.
- Best for: failed-breakdown reversals, gap-and-go momentum on overnight catalyst stocks.
- Worst for: blind breakouts of overnight ranges (often fail).
- Rule: no entries before 09:20 unless on a *named* opening setup that we encoded.

### 09:30–10:30 — **First confirmation window**
- Real flow shows up. Sector rotation visible.
- Best for: VWAP pullback longs in trending sector leaders, momentum BO continuation.
- Highest *expected value* hour of the day. Allocate attention.

### 10:30–12:00 — **Trend extension or fade**
- If 09:30–10:30 trended cleanly, look for one more leg with VWAP as line in sand.
- If 09:30–10:30 was choppy, expect more chop. Reduce setup-quality threshold tolerance.

### 12:00–13:00 — **Lunch chop**
- Volume drops sharply. Liquidity in second-tier names evaporates.
- Default: **stand down**. Do not raise score gate; rather, raise the setup-quality bar implicitly by shrinking the universe to top-15 most liquid names.
- An exception: news-driven spikes in this window can be high-conviction.

### 13:00–14:30 — **Re-engagement**
- US futures open around this time on certain days; cross-asset risk-on/off cues land.
- Best for: trend-continuation on names that held VWAP through lunch (genuine strength).
- Be wary of late-day exhaustion in extended names.

### 14:30–15:00 — **Closing positioning**
- F&O traders square or build for the close. Index-heavy names whip.
- Last meaningful entry window. Tighter stops; smaller targets acceptable.

### 15:00–15:15 — **No-new-trade zone**
- Manage existing positions only. The 15:15 self-square cushion approaches.

### 15:15–15:20 — **Wind-down**
- All flat. Auto-square has done its job. EOD job begins.

## 4. Setup playbook (six setups, scalped well)

For each: **what it is**, **what confirms it**, **what kills it**, **typical R:R**, **best regime**, **worst regime**.

### 4.1 Momentum Breakout
- **What:** price clears a defined consolidation high (15-min or 30-min range) on expanding volume.
- **Confirm:** RVOL ≥ 1.8× time-of-day baseline. Close-of-bar above breakout level — not intra-bar wick. Sector index rising. RS positive.
- **Kill:** breakout candle closes back inside the range. Volume falls below 20-bar average on the next bar. Nifty rolling over.
- **R:R:** 1 : 1.8 typical. Stop just below breakout level (tick-rounded down). Target = 1.5R minimum, partial at 1R.
- **Best regime:** TRENDING. **Worst:** CHOPPY.

### 4.2 VWAP Pullback (Trend-continuation)
- **What:** stock trending up, pulls back to VWAP from above, holds, resumes.
- **Confirm:** clear higher-highs, higher-lows on 5-min before pullback. VWAP held with body, not just wick. RVOL on the resumption bar ≥ 1.5×. Sector and Nifty supportive.
- **Kill:** closes below VWAP with conviction (≥ 0.5× ATR). Volume on pullback exceeds volume on prior up-leg.
- **R:R:** 1 : 1.5 typical. Stop just below the pullback low. The cleanest scalp setup that exists.
- **Best regime:** TRENDING. **Workable:** CHOPPY (smaller targets).

### 4.3 VWAP Reclaim (Recovery)
- **What:** stock dropped below VWAP, pushes back through, holds.
- **Confirm:** reclaim bar closes above VWAP with body. Pullback to VWAP holds (no immediate failure). RVOL on reclaim ≥ 1.5×. Broader market either supportive or quiet.
- **Kill:** instant rejection back below VWAP. Sector continues falling.
- **R:R:** 1 : 1.5–2.0. Best on RECOVERING regime — multiplier is 1.4 for a reason.
- **Best regime:** RECOVERING. **Worst:** EVENT.

### 4.4 Failed Breakdown
- **What:** stock breaks a clear support, reverses sharply back above. The losing-shorts squeeze.
- **Confirm:** rejection candle on increased volume. Reclaim of the broken level within ≤ 3 bars. Sector neutral-to-positive on the reclaim.
- **Kill:** second break of support; consolidates below. Sector keeps falling.
- **R:R:** 1 : 1.5–2.5. Stop is *just* below the rejection low — tight stops are the whole point.
- **Best regime:** RECOVERING / CHOPPY. Worst: TRENDING down.

### 4.5 Range Breakout (Mid-day)
- **What:** stock builds a tight 30-min+ range mid-session, exits with conviction.
- **Confirm:** range width ≤ 0.5 × ATR — *tight* is the magic. Volume contracts inside the range, expands on the break. Nifty at least neutral.
- **Kill:** false break that returns inside in same bar. Choppy regime.
- **R:R:** 1 : 1.5. Stop inside the opposite end of the range (or mid, more conservative).
- **Best regime:** TRENDING. Worst: CHOPPY.

### 4.6 Recovery Setup (Specific)
- **What:** stock down sharply earlier, basing, sector turning, RS improving.
- **Confirm:** tight base ≥ 20 min. RS goes from negative to neutral or positive. Volume drying in base, returns on attempt.
- **Kill:** sector continues to fall. Base tightens but never breaks.
- **R:R:** 1 : 1.3–1.8. Smallest-targets setup; works because of regime tailwind.
- **Best regime:** RECOVERING. Worst: EVENT.

## 5. Vetoes (hard "no" rules)

These are pre-entry checks. Any one fails → skip. The agent does not negotiate with these.

- Stock is within 1 % of upper or lower circuit.
- Stock has corporate action / dividend / split today.
- News embargo: pending result/announcement within 60 min.
- Spread > 0.10 % of price.
- ATR collapsed (today's 20-bar ATR < 0.6 × 5-day mean) — no scalp room.
- VIX > 24 *and* setup is not VWAP pullback or failed breakdown — chop will eat you.
- Net daily P&L > +1.5 % already and 7 trades taken — quit while ahead, smaller sizes only.
- Net daily P&L < −1.5 % — drawdown sizing tier kicks in (see file 06 RSK-13).
- More than 3 stops in last 6 trades — pause for 30 min.

## 6. Exit logic (the part most agents get wrong)

A god-level scalper is defined by *exits*, not entries. Entries are easy; exits are where edge lives.

- **Initial stop** at 1R — broker-side SL-M, never a Python timer.
- **First scale** at 1R: book half. Move stop to breakeven on the rest.
- **Trail rule:** trail the remaining half to the previous 1-min higher-low (LONG) or lower-high (SHORT) once 1.2R is reached.
- **Time stop:** if no movement past 0.5R in 15 min and trade is in a CHOPPY regime, exit half. After 25 min flat, exit full.
- **VWAP-violation exit:** if a VWAP-pullback or reclaim trade closes *back* through VWAP with body, exit immediately. The thesis is invalidated.
- **Sector-roll exit:** if the trade's sector index moves > 0.5 ATR against the trade in a single bar, exit half regardless of stock action.
- **News-spike exit:** if a market-wide news spike hits (VIX +10 % in 5 min), reduce all positions by 50 % and re-evaluate.
- **End-of-day square:** 15:15 first pass (LIMIT), 15:18 second pass (LIMIT cross), 15:20 emergency MARKET. Done. No "let it run overnight."

## 7. Psychology (yes, the agent has it)

The agent does not feel emotions, but it can drift into emotion-equivalent failure modes. Encode counter-measures:

- **Tilt:** after 3 consecutive losses, the agent's score gate raises by 0.5 for the next 30 min. After 7 losses, hard pause.
- **Hubris:** after 3 consecutive A++ wins, the agent's sizing returns to standard, not maximum — over-confidence is statistical regression risk.
- **Boredom:** in low-volatility windows, the agent does *not* lower its score gate. The temptation to "do something" is the largest documented EV destroyer in scalping.
- **Anchoring:** never compare today's first-trade price to the previous-day close as motivation. Only the live tape matters.

## 8. Execution discipline

- LIMIT entries at signal price; allow up to 3 re-quotes within 0.2 % of signal; otherwise abandon.
- MARKET orders only for emergency exit (kill-switch, square-off, broker malfunction).
- Stops are SL-M, broker-side. Always.
- Idempotent placement — every order has a client_order_id; duplicate detection is mandatory.
- Cancel stale orders within 30 s if unfilled.

## 9. The single line every prompt must end with

When the agent reasons, force the LLM to close every rationale with this exact sentence:

> *"If the tape disagrees with this rationale, the tape wins."*

This is not decorative. It is a continuous reminder, in-context, that the model's narrative is subordinate to the price action. Cheap, effective.

## 10. What this document is not

It is not a backtested edge claim. It is the **mental scaffolding** that makes the agent's prompts, weights, and exits coherent. The numbers come from file 04, file 09, and the live data. This document tells us *what to believe* until the data tells us otherwise — and provides the language by which the data updates the beliefs.
