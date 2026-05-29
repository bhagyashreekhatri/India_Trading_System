# 30 — Pre-Live Audit (Daily-Income Frame) — 2026-05-29

*Auditor brief: brutally honest, scalper voice, no institutional framing. You picked
the **daily-income** frame, so I audited against "can this put green on the board
often enough that you'd run it every day?" — and I flag every place the pressure to
be-green-today costs you money. Data is what's actually on disk: the 280-trade
snapshot, the code as it sits today, the unit tests. No invented backtest.*

---

## 1. What I think your goal is

You want **daily income from NSE intraday**, executed by hand on Zerodha while a
paper agent is your signal source. You're at ₹2L today, building toward a ₹15L
operation. Two engines feed you: a **conviction path** (macro 10:15 + NIFTY FHH
break → tier S/A/B, the thing that booked the +₹1.72L paper history) and a newer
**scalp path** (above-VWAP + up-bar + volume + live order-book, bolted on May 21
precisely because conviction was taking *zero* trades for days and you wanted to
trade daily). You execute every paper ENTER/EXIT manually, mirror sizing off a ₹2L
book, and you want to start clicking live orders. I'm auditing for: does the thing
actually make money after costs, where is it leaking, what's drifted from the docs,
and what to fix *before* the first live click — with hard rules against scoring-engine
surgery, net-new complexity, and edge claims without sample size.

**One honest correction baked into this audit:** the daily-income goal and your own
Doctrine (doc 27) point in opposite directions, and I'll show you with numbers where
that tension is already costing you. I'm not going to relitigate it — you made the
call — but I won't let it hide.

---

## 2. What's working (each with a number)

- **The exit-side return-check bugs are actually closed.** Doc 26 (May 19) listed
  B2 as OPEN. Code today: `_full_exit` (crew.py ~line 2208) and `_partial_exit_tp1`
  (~line 2240) both check `place_order` return and roll back the DB / leave the
  position open / fire a Telegram alert when the broker returns no order id. That
  loss class — DB says "closed" while shares never sold — is handled. Good.

- **The order-flow brain is genuinely solid engineering.** `tools/orderflow_metrics.py`
  is pure, has no I/O, and passes 7/7 unit tests. The "buyers dominate OR book
  improving+lifting OR wall absorbed" read (`supportive()`) is a real tape read, and
  it falls back to the frozen ratio when the stream isn't warm. This is the best-built
  piece in the system.

- **The conviction path's winners are real when they hit.** Re-running the 280: the
  workhorse `sl_trail_hit` is **+0.97R over 25 trades (+₹28,224 net)** and `tp2_hit`
  is **+1.92R over 7 trades (+₹70,960 net)**. When this system catches a runner, the
  trail logic banks it. Don't touch the trail.

- **Stall-exit OFF was the right call, and the data backs it harder than doc 28 said.**
  `stalled_no_movement` was 162 trades (58%) at +₹12,707 gross but **−₹114,594 net
  after costs**. Cutting trades flat and paying the full round-trip rake 162 times was
  the single biggest bleed in the old behavior. Killing the early cut is correct.

- **Costs are honestly modeled in paper.** Slippage bumped to 12/22/8 bps (Fix #180)
  so paper converges *toward* live, not away. Most retail paper-tests lie in the
  optimistic direction; yours is calibrated to get worse before live. That's discipline.

---

## 3. What's leaking — ranked by money at stake

### LEAK #1 — Your safety nets are scaled to ₹15L, but you're trading ₹2L. (Biggest, and it's live tomorrow.)

`settings.py:27` `CAPITAL = 1_500_000`. `PROBE_MODE_ENABLED = False`, so `_allocate`
sizes every percentage kill-switch against **₹15L** (`get_active_capital()` →
`CAPITAL`). But doc 29 says you mirror at **₹2,00,000**. So:

| Guard | Setting | Fires at (₹15L) | As % of your ₹2L book |
|---|---|---|---|
| Daily loss kill | 2.5% | **₹37,500** | **18.75%** |
| Weekly loss kill | 7.5% | **₹1,12,500** | **56%** |
| Daily profit lockout | 3.0% | ₹45,000 | 22.5% |
| Scalp daily loss cap | flat ₹30,000 | ₹30,000 | **15%** |
| Scalp notional/position | flat ₹2,00,000 | ₹2,00,000 | **100% of book, ×5 slots = ₹10L** |

**The number that matters:** the daily-loss freeze that should stop you out around
**₹5,000** (2.5% of ₹2L) won't trip until **₹37,500** — by then you've lost ~19% of
your account in one session and no circuit fired. For a daily-income operator this is
the worst possible failure: the one day you most need to be stopped, nothing stops you.
This is a **doc-vs-code contradiction** (doc 29 "₹2,00,000" vs settings "₹15,00,000"),
it's the highest money-at-stake item, and it's a one-line fix. Ships now (§5).

### LEAK #2 — You're about to mirror a system whose current configuration has *zero* measured trades.

Every number in doc 28 — the +₹1.72L, the 53.9% WR, the grade table — comes from
trades dated **Apr 20 → May 8** (I checked: `entry_time` max in the snapshot is
2026-05-08; **0 trades on/after 2026-05-11**). That's *before* the conviction rebuild,
before macro/FHH gating, before Fixes #159–206, and the scalp engine didn't exist
until May 21. The grades in that table (`A++`, `A+`…) are from the **old scoring
engine that conviction now bypasses** (Fix #160/#184). So:

- The conviction engine in its *current* form has no closed-trade track record on disk.
- The scalp engine — your actual daily-income workhorse — has **no P&L anywhere I can
  reach**. `logs/scalp_trades.jsonl` doesn't exist locally; the only data is server
  journalctl. I cannot give you a scalp win rate or expectancy because **there isn't a
  measurable one yet.**

You're not going live on a proven system. You're going live on a *rebuilt* system
whose proof belongs to its ancestor. That's not a reason to stop — it's a reason to
size like you have no edge yet (see §5) and to capture the scalp ledger from day one.

### LEAK #3 — The old system's profit was a lottery, and that's death for a daily goal.

Profit concentration on the 280: **top 5 trades = 67% of gross, top 20 = 99%.** After
costs, net was **−₹29,500 (−₹105/trade)** — I applied doc 01's own cost formula (₹226
fixed + 0.16% of notional; mean ₹721/trade). The +₹1.72L "edge" is ~20 lucky trades on
top of 260 that collectively bled the rake. **There is no daily income in that shape.**
You can't paycheck off a distribution where 7% of trades carry all the money. This is
exactly the tension you waved off: a daily-income *target* pushes you to take the
marginal 2pm trade to make the day green, and the marginal trade is the one that pays
₹721 in costs to stall flat. The math says: trade fewer, let runners run, accept red
days. The income comes monthly, from the tail, not daily.

### LEAK #4 — A++ grade is anti-predictive, and it's worse after costs.

`A++` (≥9.0): **41.5% WR, −₹47,522 net** — the *worst* bucket. `A` (7–8): 59.7% WR,
+₹1,204 net. The top grade loses the most. Doc 28 flagged this; with the rake it's
uglier. **But:** conviction bypasses the stub grade for entry decisions now (Fix #184),
so this mostly bites only the YELLOW-tier path (which still requires grade A/A+/A++ at
`conviction_engine.py:456`). Real but second-order. **No scoring surgery** — you don't
have 30 post-rebuild trades to justify it. Monitor (§6).

### LEAK #5 — The scalp engine's 2:1 isn't 2:1 after costs.

Nominal +0.8% target / −0.4% stop = 2:1. On a ₹2L notional, round-trip cost ≈ ₹546
(₹226 + 0.16%×₹2L). So a win nets ≈ ₹1,054 and a loss ≈ −₹1,346 → real R:R ≈ **0.78:1**,
and breakeven win rate ≈ **56%**. That's the cost drag doc 27 warned about, made
concrete. It's not fatal — a genuinely good above-VWAP/lifting-book read can clear 56%
— but you have **no data** showing it does. Until the ledger says otherwise, treat the
scalp path as unproven, not as your income engine.

---

## 4. Code-vs-doctrine drift (specific)

- **`settings.py:27` `CAPITAL=1_500_000` vs doc 29 "paper capital ₹2,00,000".** The
  whole risk surface is mis-scaled. (Leak #1.)

- **`settings.py:745` `SCALP_MODE_ENABLED=True` vs Doctrine §5/§11 "scalp satellite is
  small, capped, OFF in chop."** The scalp engine has no macro/regime gate at the
  entry — it's the *opposite* of "OFF in chop." Its only chop defense is the
  `SCALP_LOSS_STREAK_HALT=4` *after* the fact (4 losers in a row). Doctrine wants it
  off *before* chop; code lets it take 4 losing shots first. Not wrong for a daily-income
  frame, but it directly contradicts the doctrine you wrote 8 days ago.

- **`settings.py:763` `SCALP_TIME_STOP_MIN=90`.** A 90-minute hold is not a scalp.
  The module docstring says "sneak in; if it doesn't go, leave"; the live config lets a
  flat trade sit for an hour and a half tying up a slot. Drift between the design intent
  and the shipped number.

- **`tests/test_scalp_engine.py` validates `ScalpConfig()` defaults
  (`scratch_enabled=True`, `time_stop_min=20`), NOT the live settings
  (`SCALP_SCRATCH_ENABLED=False`, `SCALP_TIME_STOP_MIN=90`).** The scratch test (line 99)
  asserts behavior that is *disabled in production*. Your green tests describe a config
  you don't run. False confidence.

- **B5 (HOD proximity) still architecturally open.** `conviction_engine.py:136` reads
  `stock_quote.get("high")` = Kite **session** high, exactly what doc 25 flagged. The
  "fix" was widening the gate to 2.0% (Fix #192), not the rolling-intraday-high the doc
  prescribed. On a multi-leg trend day this still rejects the clean second-leg retest.
  Band-aided, not closed.

- **`PROJECT_MEMORY.md` header still says "Last updated 2026-05-18"** but contains
  Fixes up to #205 (May 20). The memory file's own freshness stamp is stale — doc 26
  flagged the same class of drift and it's still there.

- **Dormant clock gate survives:** `tools/pattern_tools.py` `_detect_orb_breakout` still
  carries the hardcoded 09:30–10:30 gate (Three-Laws Law-1 violation). Banner says DO
  NOT CALL; it's dead, but it's still in the tree.

- **`NO_NEW_ENTRY_AFTER="14:45"` coexists with the live runway check** (doc 22 §12 said
  move to "15:25" after 5 validated sessions). Two overlapping late-day gates; runway
  was meant to replace the clock. Redundant, mildly strangling.

---

## 5. Ship now (pre-live) — 3 surgical changes

### SHIP #1 — Re-scale the risk surface to your real book. (Highest leverage, lowest risk.)

This is the one that matters before you click anything. Right now your guards protect a
₹15L book you don't have. Two clean options:

**Option A (recommended, matches doc 23's intent):** flip to probe mode so the existing
`get_active_*()` plumbing does the scaling for you, and set the probe capital to your
real ₹2L. Keep `PAPER_TRADING=True` so the agent stays paper and you keep mirroring by
hand — the Fix #187 boot assertion only blocks `PAPER=False AND PROBE=False`, so
`PAPER=True, PROBE=True` is allowed.

```python
# config/settings.py
PROBE_MODE_ENABLED = True          # was False — turns on get_active_capital() scaling
PROBE_CAPITAL      = 200_000       # was 50_000 — set to your actual mirror book
PROBE_MAX_POSITIONS = 3
```
Effect: daily-loss freeze now fires at ₹5,000 (2.5% of ₹2L), weekly at ₹15,000, profit
lockout at ₹6,000 — all proportionate to what you're actually risking.

**Then fix the two flat-rupee scalp numbers that probe mode does NOT scale:**
```python
SCALP_NOTIONAL_INR       = 40_000   # was 200_000 → 5 slots × 40k = ₹2L, not ₹10L
SCALP_DAILY_LOSS_CAP_INR = 4_000    # was 30_000 → 2% of ₹2L, not 15%
```
**Regression risk: LOW.** It's config; the plumbing already exists and is unit-exercised.
The only behavior change is smaller size and tighter circuits — which is the safe
direction for day one. **Verify after editing:** boot the agent, confirm the log prints
`active_capital=200000` and the scalp notional line shows ₹40k.

### SHIP #2 — Make the scalp ledger real before you mirror a single scalp.

You're about to act on scalp signals you can't measure. Before day one, confirm
`logs/scalp_trades.jsonl` is actually being written on the server (the code at
`crew.py:599 _log_scalp` writes it; the file is absent in the snapshot, so either the
dir doesn't exist or nothing's fired). **Action:** `mkdir -p logs` on the box, and on
day one tail it. If after 3 sessions there's no row, the scalp path isn't firing and
you're mirroring nothing — which is its own answer. **Regression risk: NONE** (logging
only). This is the data that unblocks every scalp decision in §6.

### SHIP #3 — Align the scalp unit test with the live config, or stop trusting it.

One-line change so your green checkmark describes the system you run:
```python
# tests/test_scalp_engine.py — build cfg from live settings, not dataclass defaults
import config.settings as S
cfg = ScalpConfig.from_settings(S)   # was: cfg = ScalpConfig()
```
Then fix the scratch test to assert the *disabled* path (no scratch fire). **Regression
risk: LOW** (test-only), but it'll likely turn one assertion red — which is the point:
better a red test than a false green. Do this *before* live so you know your exit logic
is tested as-run.

*(I am deliberately NOT shipping a fix for B5, A++, or the scalp entry gate. No 30-trade
post-rebuild evidence exists to justify touching them — your hard rule, and it's right.)*

---

## 6. Monitor 2 weeks, then revisit (needs real data first)

1. **Scalp expectancy.** Once `scalp_trades.jsonl` has ~30 closed rows: compute net
   win rate and net R *after the ₹546-ish round-trip*. If net WR < 56%, the scalp path
   is a cost furnace and the daily-income engine doesn't exist — that's the single most
   important measurement in the whole system. *Speculative until measured.*

2. **Did `tp2_hit` roughly double per 100 trades with stall-exit off?** Doc 28's own
   test. If runners don't run more now, the targets are too far. Needs post-rebuild
   closed trades you don't yet have.

3. **A++ / YELLOW-tier P&L.** If A++ stays net-negative over 30+ *new* trades, demote
   A++ recovery_setup and add a confirmation bar. Not before 30 trades. *Scoring-engine-adjacent
   — needs evidence by your own rule.*

4. **Does the live macro-recovery unlock (`MACRO_RECHECK_ENABLED=True`) actually catch
   recovery days without false fires?** It went live (Fix #205) on the strength of one
   day (2026-05-20, PCBL). One day is an anecdote. Watch it for false upgrades on
   bleed-then-bounce-then-fail tapes.

5. **Is the runway check strangling late-day admits?** With `NO_NEW_ENTRY_AFTER=14:45`
   AND runway both live, count how many would-be admits die after 14:00. If runway is
   doing its job, retire the 14:45 clock (doc 22 §12).

---

## 7. Kill / simplify

- **Pick ONE late-day gate.** `NO_NEW_ENTRY_AFTER=14:45` and the runway check overlap.
  After you confirm runway works (§6.5), delete the clock constant. Removes a
  redundant strangler. (Removes complexity — satisfies your no-net-new-complexity rule.)

- **Delete the dormant `_detect_orb_breakout` clock gate** (`pattern_tools.py:~205`).
  It's dead and it's a standing Three-Laws violation. Either remove the function or strip
  the 09:30–10:30 gate. Pure debt removal.

- **`SCALP_TIME_STOP_MIN=90` → ~30.** A 90-min hold isn't a scalp and pins a slot.
  Either cut it to ~30 to match the module's "leave if it doesn't go" intent, or rename
  the engine honestly — it's a short-swing path, not a scalp. (Behavioral, low-confidence
  — I'd A/B this via the ledger before committing, so technically §6, but the *naming*
  drift should die now.)

- **Don't build anything new before live.** You have two engines and ~3k LOC in the
  orchestrator. The scalp path already added a whole second decision surface. Resist any
  feature until the scalp ledger tells you the daily engine even works.

---

## 8. Open questions for you (max 5)

1. **What's your actual free margin on Zerodha tomorrow — cash ₹2L, or ₹2L with MIS
   leverage?** It changes whether 5 × ₹40k scalp slots is even executable and whether
   Ship #1's numbers are right.

2. **When conviction and scalp both fire on the same name same minute, what do you do by
   hand?** The code runs them as isolated paths; your manual mirror has one wallet. I
   didn't find a dedup rule. Which signal wins?

3. **Is the scalp engine actually firing on the server right now, or still silent like
   conviction was pre-May-21?** (i.e., does `scalp_trades.jsonl` have rows on the box?)
   This determines whether you have a daily engine at all.

4. **For the daily-income goal: are you willing to take red days, or will you
   discretionarily add trades to force green?** Your override budget is 2/day — be honest
   about whether that becomes "2 revenge entries" on a red afternoon. The data says that's
   the leak.

5. **Do you want me to wire the ₹2L scaling as probe-mode (Option A) or just hardcode
   `CAPITAL=200000`?** Probe mode is cleaner but changes more flags at once; the hardcode
   is blunter but a true one-liner. Your call before I touch settings.

---

Bhagya — here's what I'd do tomorrow morning before you click your first live order:

1. **Re-scale to ₹2L (Ship #1).** Don't click anything while your daily-loss freeze sits
   at ₹37,500. Set probe capital = ₹2L, scalp notional = ₹40k, scalp daily cap = ₹4k.
2. **Confirm the scalp ledger is writing** (`logs/scalp_trades.jsonl` on the box). If it's
   empty after the open, you have no daily engine yet — mirror conviction only.
3. **Size like you have no proven edge — because on the current build you don't.** The
   +₹1.72L belongs to the old system. Take half the qty the agent prints for the first week.
4. **Pre-commit to taking red days.** The money is in ~7% of trades; forcing a green
   afternoon is how you hand the rake back. Cap overrides at 2 and journal every one.
5. **Fix the scalp test to use the live config** so your one green checkmark isn't lying
   about the exit logic you're actually trading.

---

## Addendum — build session (2026-05-29, same day)

Operator clarified after the audit: real account = **₹15L CASH in PAPER**, operator
executes real Zerodha fills **manually**, agent stays `PAPER_TRADING=True` as the signal
source. Goal = daily-income scalper. This **supersedes parts of §3–§5 above**:

- **Leak #1 (mis-scaled switches) largely dissolves.** With a real ₹15L book, the % kill-
  switches (daily 2.5%=₹37,500, weekly 7.5%) are correctly sized. The real issue was
  `RISK_PER_TRADE_PCT=1%` = ₹15,000/trade = 2× Doctrine's 0.5% ceiling — **fixed to 0.5%**
  (Fix #207). Note: `CONVICTION_RISK_INR` (₹1500…) is vestigial — sizing uses
  `RISK_PER_TRADE_PCT` at `crew.py:2043`.
- **B2 and B3 are already CLOSED** (Fix #170 / Fix #195) — verified in code. Doc 25/26's
  "open" status is stale. No new code added (no-bloat rule).
- **Scalp notional kept at ₹2L** (not the live-safety ₹1L) — it's paper; realistic notional
  makes the cost-% drag in the ledger honest.

**Shipped this session (all parse-clean, all unit tests green):**

| Fix | What | Files | Reversible |
|---|---|---|---|
| #207 | `RISK_PER_TRADE_PCT` 1%→0.5% (doctrine max) | `settings.py` | set 0.01 |
| #208 | Bidirectional conviction↔scalp dedup (1 position/symbol) | `crew.py` | n/a (safety) |
| #209 | **Scalp runner capture** — bank ½ at +0.8%, SL→breakeven, trail rest by ATR | `scalp_engine.py`, `crew.py`, `settings.py`, tests | `SCALP_PARTIAL_TRAIL_ENABLED=False` |

**Why #209 is the profit lever (and its honest limit):** the only P&L data in the project
(280 conviction trades) shows ~100% of net profit came from runners; the hard 2:1 scalp
exit capped exactly those. Illustration on one +3% name @ ₹2L: runner-mode books ₹3,500 vs
₹1,600 hard-2:1 (+₹1,900). **This is the mechanism, not measured edge.** Whether scalps net
green after costs is unknown until `logs/scalp_trades.jsonl` has ~30 closed scalps. The
scalp 2:1 only breaks even above ~56% WR after costs — the ledger is the judge.

**Still the #1 open question:** the current build (conviction tiers + scalp + OF brain +
runner capture) has **zero closed trades on disk**. Validate on the ledger before scaling
`RISK_PER_TRADE_PCT` back toward 1% or adding any new feature.
