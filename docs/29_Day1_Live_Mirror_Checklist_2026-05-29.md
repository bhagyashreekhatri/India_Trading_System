# Day-1 Live Mirror Checklist — Zerodha Manual Execution

**Status:** Paper agent stays in paper mode. **You** execute on Zerodha manually,
mirroring every paper entry/exit. The agent is your signal source, not your fills.

---

## Pre-market (08:45 – 09:14 IST)

- [ ] Zerodha Kite open in browser, Watchlist loaded with FULL_UNIVERSE
- [ ] Paper agent service running — `journalctl -u india-trading-agent -n 50` shows boot complete
- [ ] OrderFlowStream healthy — log shows `[OrderFlow] connected` and `live` (not shadow)
- [ ] Today's pause flag clear — log shows NO `CONSECUTIVE-LOSSES PAUSE` line
- [ ] Phone charged + Telegram open — agent alerts arrive here
- [ ] Total trading capital on Zerodha ≥ ₹2,00,000 free margin
- [ ] Decide your **max manual override budget** for today (recommend: **2 overrides**)

---

## Entry rule — when agent prints `ENTER`

```
[Allocator] ENTER ATGL @686.55 qty=291 sl=683.60 tp1=691.30 tp2=697.20
```

**Within 30 seconds of the print:**

1. Open Zerodha Kite, search ATGL
2. Place **CNC** or **MIS** buy order (MIS for intraday close-out) at **LIMIT** = paper entry price ± 0.1%
3. Quantity = paper qty (or scaled — see Sizing below)
4. After fill, **immediately** place stop-loss = paper sl
5. Place target order at tp1

**If you missed the entry window (>60 sec elapsed, price moved >0.3%):**
**→ SKIP.** Do not chase. Tomorrow has more setups.

**If your fill is worse than paper by >0.3%:**
**→ tighten stop proportionally** so your R-distance matches the paper's.

---

## Exit rule — when agent prints `EXIT`

```
[Position] EXIT ATGL @699.70 reason=target pnl=+1907
```

**Within 30 seconds:**

1. Cancel any open stop / target order on that name
2. Sell qty_remaining at **MARKET**
3. Log fill price in your journal

**If you can't get fill within 30 sec (illiquid moment, halt):**
**→ Sell market anyway.** Do not negotiate with the market.

---

## TP1 partial exit — when agent prints `TP1 HIT`

```
[Position] TP1 HIT ATGL @691.30 — 50% exit, SL → breakeven
```

1. Sell **50%** at market
2. Move stop on remaining 50% to your **entry price** (breakeven)
3. Trailing kicks in — agent will print `SL TRAIL` when stop moves higher; mirror it

---

## Sizing scale (if Zerodha capital ≠ paper ₹2,00,000)

Agent runs on paper capital ₹2,00,000. If your live capital is different:

| Live capital | Multiplier on paper qty |
|---|---|
| ₹1,00,000 | 0.5× |
| ₹2,00,000 | 1.0× |
| ₹3,00,000 | 1.5× |
| ₹5,00,000 | 2.5× |

Round DOWN to nearest lot for F&O, nearest 1 for cash equity.

**Cap per trade**: never let one position exceed 25% of your free margin. The agent
already caps at 25% — but if you're 1.5× scaling, recheck per trade.

---

## Hard rules (do not break)

1. **Never enter a trade the agent didn't enter.** Even if it looks better. Your gut
   is correct about 50% of the time. The system needs 30 days of clean data to learn.
2. **Never skip a trade the agent took.** Same reason. If you skip 3, the system's
   measured edge is wrong.
3. **Manual override budget = 2 per day, max.** An override means YOU exit early
   or skip an entry. Log the reason. If you exceed 2/day for 3 days in a row, the
   problem is you, not the agent.
4. **Stop = stop.** No "give it 10 more paise." 95% of stops that get extended become
   bigger stops.
5. **EOD square-off by 15:15 IST.** Agent does this automatically. Mirror it.
6. **No new entries after 14:30 IST.** Agent's runway check handles this; respect it.

---

## End-of-day reconciliation (15:30 – 15:45 IST)

- [ ] Open `docs/eod_reconciliation_template.csv` (or notebook page)
- [ ] For each trade today, log:
  - Symbol | Paper entry | Live entry | Slip ₹ | Paper exit | Live exit | Slip ₹ | Net diff
- [ ] If avg slip ₹ on entries > ₹50 per trade → review tomorrow's execution speed
- [ ] If avg slip on exits > ₹50 → switch to MARKET orders for exits (you're being slow)
- [ ] If 2+ trades had "missed window — skipped" → think about whether watchlist alerts
       fire fast enough; consider Kite mobile app on iPad next to laptop

---

## When things go wrong

| Situation | Action |
|---|---|
| Agent prints ENTER but no Telegram alert | Manual entry from log; tell me at EOD |
| Agent stops printing for >5 min | Check `journalctl -u india-trading-agent -n 100`; restart service |
| OrderFlowStream says `shadow` instead of `live` | Confirm `ORDERFLOW_SHADOW=False` in settings; restart |
| `CONSECUTIVE-LOSSES PAUSE` appears | Read the streak number. If you believe today's setups are valid, raise `CONSECUTIVE_LOSING_DAYS_PAUSE` by 1 in settings and restart. Don't lift it indefinitely. |
| Kite REST API throttles you (manual trading) | Slow down — you're overclicking. The agent already throttles itself |
| Mental: you start doubting an agent entry mid-day | Force yourself to take the NEXT 3 entries blind. Discipline beats opinion on Day 1 |

---

## Mental rules (the part that actually fails)

1. **You will hesitate on the 4th red trade in a row.** The agent has CHOP HALT
   (`SCALP_LOSS_STREAK_HALT=4`) for the scalp engine — when it halts, *stop too*.
   When it resumes, *resume too*.

2. **You will want to add size after 3 wins in a row.** Don't. The system already
   has tier-based sizing.

3. **You will see a setup the agent didn't pick.** Note it in your journal. End
   of week, check whether those would have been winners. If yes — tell me, we add
   the missing signal. If no — you've learned why the agent is right.

4. **You will see the agent miss a name on a screaming day** (like ATGL 2026-05-26).
   This is fine. The agent skips for structural reasons. Trust the process for 30 days,
   *then* we tune.

5. **Worst case for the system isn't a losing day** — it's a winning day where you
   second-guess and exit early. That trains the wrong behavior.

---

## Day-end Telegram summary

The agent will send a daily summary at ~15:35 IST with:
- Realized P&L (paper)
- Trades by setup
- Scalp halt status
- Tomorrow's bias from the regime detector

**Your job at EOD**: send a return Telegram with **your live P&L** and the **3 biggest
slip incidents**. This is the dataset we'll use to tune execution next week.

---

## Two-week review (2026-06-12)

We'll re-audit with the new live data and decide:
- Whether to scale capital up
- Whether to relax/tighten any gates based on real fills
- Whether to take the agent off paper mode and let it fire orders directly
