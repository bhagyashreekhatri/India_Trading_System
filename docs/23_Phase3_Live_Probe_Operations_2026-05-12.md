# Doc 23 — Phase 3 Live Probe Operations Spec

*Drafted: 2026-05-12. This is the operations playbook for the first real-money deployment. Read end-to-end before flipping `PAPER_TRADING=False`.*

## 1. What Phase 3 is — and what it isn't

**Phase 3 is** a strictly bounded, ₹50,000 real-money probe lasting 10-15 trading sessions. The goal is to **validate that the agent's behaviour in production matches its behaviour in paper** — that fills happen at expected prices, that SL-M orders arrive at the broker, that Telegram alerts fire, that the daily-loss kill switch actually freezes new entries.

**Phase 3 is NOT** an attempt to make money. ₹50k is the test budget. Expected outcome range is **-₹2,500 to +₹2,500** over the probe period — well within noise. Anything outside that band (especially below) is a signal of a real production bug we missed in paper.

**Phase 3 is NOT** the start of Phase 4 (₹3L) or Phase 5 (₹20L). Scaling decisions are explicitly gated on the success criteria in §8.

## 2. Pre-flight gates — ALL must pass before flipping live

| # | Gate | Pass criterion |
|---|---|---|
| 1 | Phase 2.0 telemetry visible | `[MarketState]`, `[FHH]`, `[Day-Type]`, `[Vol-State]` lines all observed in journalctl across ≥3 sessions |
| 2 | Phase 2.1 Discovery shadow logs clean | ≥5 sessions with `[Discovery] ADMIT` lines, no exception traces, candidates make intuitive sense |
| 3 | Phase 2.3 Decoupling shadow logs clean | ≥5 sessions, near-misses logged correctly, no false positives that visibly contradict the rule |
| 4 | Conviction-engine forward observation | ≥3 conviction-engine fires (any decision — admit OR skip) across the validation window; logs match the documented rules |
| 5 | Telegram entry+exit alerts working | Manual test: trigger a paper-mode entry, confirm Telegram receives entry alert; close manually, confirm exit alert |
| 6 | Daily-loss kill switch tested | Inject a synthetic -2.5% paper loss; confirm `[Allocator] 🔴 DAILY-LOSS KILL` log + entries blocked for rest of session |
| 7 | Overnight position veto tested | Boot with a stale open position in DB; confirm boot-time force-close |
| 8 | Broker SL-M placement verified | Paper-mode placement of an SL-M order returns a non-empty `sl_order_id`; cancel works |
| 9 | Tick-size rounding live-tested | Place a paper order for a ₹0.05-tick name and a ₹0.10-tick name; confirm both round correctly |
| 10 | EOD partial-unwind tested | Hold a paper position past 14:45 without TP1; confirm force-exit with reason `eod_partial_unwind` |
| 11 | EOD self-critique fires | After a paper session with ≥1 closed trade, confirm `[EOD] 🧠 Got N self-critiques` line + ChromaDB write |
| 12 | Discovery+Decoupling flags = True | Both `DISCOVERY_ALLOW_TRADES` and `STOCK_DECOUPLING_ENABLED` flipped to True ≥5 sessions before Phase 3 start (so we observe their effect in paper first) |

**If ANY gate fails**, do not flip live. Document the failure, fix it, restart the gate from gate 1.

## 3. Capital recalibration for ₹50k

The defaults in `config/settings.py` are calibrated for a ₹3L planned capital (₹15L paper). They scale linearly. For Phase 3:

```python
# ── Phase 3 probe-mode settings (set in deploy/config or as overrides) ──
CAPITAL                  = 50_000      # was 1_500_000
MAX_POSITIONS            =  3          # was 10  — fewer concurrent positions
DAILY_LOSS_KILL_PCT      =  0.025      # unchanged % → ₹1,250 absolute (~3 stops)
DAILY_PROFIT_LOCKOUT_PCT =  0.030      # unchanged % → ₹1,500 absolute
DAILY_PROFIT_TIGHTEN_PCT =  0.020      # unchanged % → ₹1,000 absolute

CONVICTION_RISK_INR = {
    "S": 500.0,    # was 1500 — 1% of probe capital
    "A": 500.0,    # was 1500 — 1% of probe capital
    "B": 250.0,    # was  750 — 0.5% of probe capital (B-tier already half-size)
}
CONVICTION_TARGET_INR = {
    "S": 1000.0,   # was 3000 — 2R target
    "A":  833.0,   # was 2500 — 1.67R target
    "B":  500.0,   # was 1500 — 2R target (on smaller risk)
}
```

**Sanity check the math:**
- 1 losing S/A trade: -₹500 (-1.0% of probe capital)
- 1 losing B trade: -₹250 (-0.5%)
- 3 consecutive losing S trades: -₹1,500 → hits the -₹1,250 daily-loss kill switch at trade 3, halts the day
- The probe **CANNOT lose more than ₹1,250 in one session** by design

## 4. Daily operations checklist

### Pre-market (08:00-09:00 IST)
1. SSH to server, run `systemctl status trading-system`. Confirm "active (running)".
2. Tail journalctl, watch for the boot sequence:
   ```
   ✅ Health check passed — all systems go!
   [Crew] Conviction-engine pipeline loaded (Phase 0 + 1 rebuild)
   [Crew] Day-type classifier + volatility state agents active
   [Discovery] seeded candidate pool — N NSE EQ names ...
   [Crew] Discovery engine loaded — shadow mode OFF  ← MUST say OFF (production)
   ```
3. Confirm Telegram pre-market gap report arrives by 09:00 IST.

### Market open (09:15 IST)
1. Watch tick 1 fire at 09:15:06 IST.
2. Confirm the time-gate kicks in for the first ~5 min.
3. Around 09:51 (first-40-min blindness ends), expect setups to start being detected.

### 10:15 IST — macro lock
- The `[MarketState]` log line MUST fire. If it doesn't appear by 10:16, there's a problem — investigate immediately.

### Mid-session (11:00 IST – 13:30 IST)
1. Check Telegram for any entry alerts.
2. If a trade fires, verify in Kite Web UI that:
   - The market order placed
   - The SL-M placed at the right trigger price
   - The position appears in holdings
3. Cross-check the agent's `[Allocator] ✅ ENTERED` log against the Kite order ID.

### Post-13:30 IST
- No new entries (per `NO_NEW_ENTRY_AFTER = 14:45`, but the runway check — Phase 2.6 — may tighten this).
- Position management only.

### EOD (15:00 IST and after)
1. Verify EOD partial-unwind fires at 14:45 if any non-TP1-hit positions exist.
2. Verify position closeout at 15:00 if any still open.
3. Confirm EOD job runs after 15:35:
   ```
   [EOD] 🧠 Got N self-critiques from LLM
   📱 Telegram EOD report sent!
   ```
4. Tally session P&L manually against Kite Web. Should match exactly.

### Weekly review (every Friday after EOD)
1. Confirm weekly scorecard prints in console.
2. Compute weekly P&L %. If beyond bounds (see §6), trigger review.
3. Run `python3 scripts/analyze_exit_distribution.py` to refresh the historical analytics.

## 5. Kill switches (all already wired)

| Trigger | Action | Status |
|---|---|---|
| Per-trade loss = 1R (₹500 S/A, ₹250 B) | SL-M auto-exit at the broker | ✅ Fix #6 |
| Daily loss ≥ -₹1,250 (-2.5%) | Block new entries; manage open positions | ✅ Fix #3b |
| Daily profit ≥ +₹1,500 (+3%) | Lock out new entries; manage open | ✅ Fix #11 |
| Daily profit ≥ +₹1,000 (+2%) | Raise score gate to conservative | ✅ Fix #11 |
| Symbol auto-blacklist after 2 losses | Block symbol for 7 trading days | ✅ Fix #27 / Phase 2.1 |
| Overnight position from prior session | Force-close at boot | ✅ Fix #3a |
| Macro STRONG_RED at 10:15 | Block all longs | ✅ Phase 0 |
| NIFTY whipsaw (both FHH+FHL broken) | Freeze new entries | ✅ Phase 1.3 |
| TREND_FORMING_DN day-type | Block new longs | ✅ Phase 1.5 |
| Manual kill | `systemctl stop trading-system` | ✅ Always |

### New for Phase 3 (NOT yet implemented — see §11):

| Trigger | Action |
|---|---|
| Weekly drawdown ≥ -₹3,750 (-7.5%) | Auto-pause until manual review |
| Monthly closed-trade R-mean < 0 | Auto-pause until retrospective |
| 5 consecutive losing days | Auto-pause until review |

These are Phase 3.0.1 additions (~30 LOC). Doc 23.1 will spec them.

## 6. Success / failure thresholds

After 10-15 sessions of Phase 3:

### Continue → Phase 4 (₹3L) if:
- Total P&L between **-₹1,000 and +₹2,500** (noise band tolerable on the low side)
- At least 5 trades executed (otherwise insufficient sample)
- Mean R per closed trade ≥ -0.2R
- Zero production bugs that required restart or manual intervention
- All Telegram alerts delivered correctly
- All SL-M orders executed at intended prices

### Pause → root-cause if:
- P&L ≤ -₹1,500 (worse than max-loss budget — implies kill switch leaked)
- Mean R per trade < -0.5R (sustained adverse selection)
- 3+ trades with execution slippage > 0.3% from intended entry
- Any case where SL-M didn't fire on a loss

### Revert → revisit design if:
- P&L ≤ -₹2,500 (full half-loss — design issue, not noise)
- 5+ losing days in 10 sessions (rule selection broken)
- Any case where the agent took a position it logged as SKIP (state corruption)

## 7. Capital tranching schedule

Phase 3 is intentionally non-monotonic. The probe is a single ₹50k tranche, NOT a ramp.

```
Week 1   ₹50,000  probe (this doc)
Week 2   ₹50,000  probe (continued — same capital)
Week 3   REVIEW   — if pass-criteria met → Phase 4 spec drafted
Week 4   ₹1,00,000 Phase 4 first half
Week 5   ₹1,00,000 (or scale to ₹3L if Week 4 clean)
Month 2  ₹3,00,000 Phase 4 full
Month 3  REVIEW
Month 4  ₹10,00,000 Phase 5 first half
Month 5  ₹20,00,000 Phase 5 full
```

At any point, a kill-switch breach reverts to the previous tranche size and triggers a written retrospective.

## 8. Roles & responsibilities

- **You (Bhagya):** flip flags, watch journalctl, run pre-flight, decide Phase 4 entry. The agent is autonomous within its parameters, but YOU are the only one who pushes capital tranches up.
- **The agent:** trade execution + position management + EOD learning loop.
- **The dashboard:** read-only monitoring at `localhost:8501`. Do not enter manual trades from the dashboard during the probe — keep everything controlled by the agent for a clean data set.

## 9. Communication channels

- **Telegram:** real-time entry/exit/EOD/kill-switch alerts
- **journalctl:** authoritative log
- **Kite Web:** broker-side verification (orders, holdings, account P&L)
- **trade_state.db** (SQLite, on server): system-of-record for trade outcomes

If Telegram and journalctl disagree on a trade outcome, **journalctl wins**. If journalctl and trade_state.db disagree, **trade_state.db wins** (it's what powers RAG learning and EOD self-critique).

## 10. The decision to go live

Going live is a **single, irreversible-for-the-session** decision: change `PAPER_TRADING=False` in `config/settings.py`, commit, push, restart service. Once flipped, every `kite.place_order` call hits real markets.

**Do this ONLY:**
1. Before market open (between 08:00 and 09:00 IST), so you have time to abort if boot fails.
2. After **all 12 pre-flight gates** (§2) have been documented as passing for ≥1 session each.
3. With Telegram already verified delivering to your phone.
4. With phone within reach for the entire trading day.

**Do NOT do this:**
1. Mid-session.
2. On a Friday (you don't want to discover a bug going into a weekend).
3. On a major-event day (RBI / Fed / budget / election counting).
4. When you're not in front of a computer for at least the first hour.

## 11. What's still pending — Phase 3.0.1 enhancements

These don't block Phase 3 launch but improve the safety envelope:

1. **Weekly-drawdown kill switch** — `WEEKLY_LOSS_KILL_PCT = 0.075`. ~15 LOC in `state.get_week_pnl()` + crew tick check.
2. **Monthly negative-R-mean review** — runs in `eod_job.py` on the last trading day of each month; emits an EOD critique covering the month.
3. **5-consecutive-losing-days auto-pause** — `state.get_consecutive_losing_days()` + crew boot-time check.

All three can ship as a single Phase 3.0.1 patch (~45 LOC). Recommend shipping before going live but not blocking.

## 12. Why this is a probe, not a deployment

Reframe the mental model:
- **A deployment** assumes the system works and we're harvesting alpha.
- **A probe** assumes the system might be broken in ways paper trading couldn't reveal — slippage, partial fills, SL-M not arriving at the broker, Kite SDK error paths, time zone bugs across sessions, etc.

The probe's goal is to surface those failure modes at ₹50k cost, not at ₹20L cost. Anything we learn here saves real money later.

## 13. Estimated timeline

| Item | Effort |
|---|---|
| Phase 2.5 deploy (hygiene) | 5 min |
| 1 session forward observation of new telemetry | 1 day |
| Forward validation of Discovery shadow (5 sessions) | 1 week |
| Forward validation of Decoupling shadow (5 sessions, can overlap) | 1 week |
| Flip `DISCOVERY_ALLOW_TRADES=True` + observe in paper (5 sessions) | 1 week |
| Flip `STOCK_DECOUPLING_ENABLED=True` + observe in paper (5 sessions) | 1 week |
| Phase 2.6 runway check implementation + 2 sessions shadow | 3 days |
| Phase 3.0.1 weekly/monthly kill switches | 1 day |
| Pre-flight gate validation (12 gates × 1 session each) | 2 days |
| **Earliest Phase 3 go-live** | **~3 weeks from 2026-05-12** |

Realistically: target **early June 2026** for the first ₹50k probe session, given holidays and adjustment buffer.

## 14. What's explicitly out of scope for Phase 3

- Sector-aware macro (doc 20 — rejected based on METAL fade evidence)
- News-driven entries (cold-path only)
- Options / F&O (cash equity only)
- Short selling on the cash side (long-only)
- Pre-market / post-market entries (regular session 09:15-15:30 IST only)
- Tax-loss harvesting / portfolio optimisation (single-name scalp only)

---

*Cross-refs: doc 17 (rebuild plan), doc 18 (rebuild status), doc 19-22 (Phase 2 features), PROJECT_MEMORY (Fix log + Three Laws).*
