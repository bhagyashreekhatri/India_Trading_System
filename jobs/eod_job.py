"""
EOD Learning Job.
Runs automatically after market close (~15:35 IST).

What it does:
  1. Stores all today's closed trade outcomes in ChromaDB (system learns patterns)
  2. Sends Telegram EOD report with full daily summary
  3. Prints console summary with setup-by-setup win rates
  4. Weekly scorecard printed every Friday
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import json
from memory.trade_state import TradeStateManager
from memory.chroma_client import ChromaMemory
from tools.telegram_tools import alert_eod_report
from config.settings import TIMEZONE, GROQ_API_KEY, GROQ_MODEL

IST = ZoneInfo(TIMEZONE)


def run_eod_job():
    """
    Main EOD job. Call after market close.
    Sends Telegram summary + stores outcomes in ChromaDB for ML-style learning.
    """
    state  = TradeStateManager()
    chroma = ChromaMemory()

    now   = datetime.now(IST)
    today = now.date().isoformat()

    print(f"\n{'='*60}")
    print(f"  EOD Learning Job — {today}")
    print(f"{'='*60}\n")

    # ── 1. Get today's closed trades ──────────────────────────────────────────
    today_trades = state.get_today_trades()
    closed       = [t for t in today_trades if t.status != "open"]

    if not closed:
        print("No closed trades today — nothing to store.")
        _send_empty_eod(today)
        return

    print(f"Processing {len(closed)} closed trades...\n")

    # ── 2. Store each outcome in ChromaDB ────────────────────────────────────
    stored = 0
    for trade in closed:
        try:
            outcome = (
                "hit_target" if trade.status == "closed_win"
                else "hit_sl"  if trade.status == "closed_loss"
                else "expired"
            )
            # Fix #14 — prefer the persisted regime; fall back to substring
            # parsing only for legacy rows that pre-date the column.
            regime = (trade.regime or _extract_regime(trade.entry_reason or ""))

            chroma.store_signal_outcome(
                symbol=trade.symbol,
                setup_type=trade.setup_type or "unknown",
                regime=regime,
                score=trade.score or 0.0,
                grade=trade.grade or "C",
                entry=trade.entry_price or 0.0,
                sl=trade.stop_loss or 0.0,
                target=trade.target_price or 0.0,
                outcome=outcome,
                pnl_r=trade.pnl_r or 0.0,
            )
            stored += 1
            win_emoji = "✅" if outcome == "hit_target" else "❌"
            print(
                f"  {win_emoji} {trade.symbol:12} "
                f"{(trade.setup_type or ''):20} "
                f"{trade.grade or '-':4} "
                f"{outcome:12} "
                f"{trade.pnl_r:+.2f}R  "
                f"₹{trade.pnl:+,.0f}"
            )
        except Exception as e:
            print(f"  ⚠ {trade.symbol} — storage error: {e}")

    # ── 3. Console summary ───────────────────────────────────────────────────
    wins      = [t for t in closed if t.status == "closed_win"]
    losses    = [t for t in closed if t.status == "closed_loss"]
    today_pnl = state.get_today_pnl()
    win_rate  = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_r     = round(
        sum(t.pnl_r for t in closed if t.pnl_r) / len(closed), 2
    ) if closed else 0

    print(f"\n{'─'*60}")
    print(f"  📊 Today's Results — {today}")
    print(f"  Trades:    {len(closed)}")
    print(f"  Wins:      {len(wins)}  |  Losses: {len(losses)}")
    print(f"  Win rate:  {win_rate}%")
    print(f"  P&L:       ₹{today_pnl:+,.0f}")
    print(f"  Avg R:     {avg_r:+.2f}R")
    print(f"\n  Stored {stored}/{len(closed)} outcomes in ChromaDB")
    print(f"{'─'*60}")

    # Fix #42 (D4) — LLM self-critique pass on today's closed trades
    try:
        _run_self_critique(closed, chroma)
    except Exception as e:
        print(f"[EOD] self-critique outer error (non-fatal): {e}")

    # ── 4. Setup breakdown ───────────────────────────────────────────────────
    by_setup = state.get_win_rate_by_setup()
    if by_setup:
        print(f"\n  📈 All-time win rate by setup:")
        for setup, stats in sorted(
            by_setup.items(), key=lambda x: x[1]["win_rate"], reverse=True
        ):
            bar = "█" * int(stats["win_rate"] / 10)
            print(
                f"  {setup:22} {bar:<10} "
                f"{stats['win_rate']:5.1f}%  "
                f"({stats['total']} trades  avg {stats['avg_r']:+.2f}R)"
            )

    # ── 5. Telegram EOD alert ────────────────────────────────────────────────
    try:
        best_trade  = max((t.pnl or 0) for t in closed) if closed else 0
        worst_trade = min((t.pnl or 0) for t in closed) if closed else 0

        # Best setup by win rate (only if ≥ 2 trades)
        best_setup = "n/a"
        if by_setup:
            eligible = {k: v for k, v in by_setup.items() if v["total"] >= 2}
            if eligible:
                best_setup = max(eligible, key=lambda k: eligible[k]["win_rate"])

        # Try to get today's regime from the first trade's reason
        regime_today = "unknown"
        if closed:
            regime_today = closed[0].regime or _extract_regime(closed[0].entry_reason or "")

        alert_eod_report(
            total_trades=len(closed),
            wins=len(wins),
            losses=len(losses),
            total_pnl=today_pnl,
            best_trade=best_trade,
            worst_trade=worst_trade,
            best_setup=best_setup,
            regime_of_day=regime_today,
        )
        print("\n  📱 Telegram EOD report sent!")
    except Exception as e:
        print(f"\n  ⚠ Telegram send failed: {e}")

    # ── 6. Weekly scorecard (Fridays only) ──────────────────────────────────
    if now.weekday() == 4:   # Friday
        _print_weekly_scorecard(state)

    # ── 7. Phase 3.0.1 — Monthly negative-R review ───────────────────────────
    # On the last trading day of each calendar month, if MONTHLY_NEG_R_REVIEW
    # is enabled, compute mean R across this month's closed trades. If
    # negative, flag for retrospective. Informational only — does NOT pause
    # the system. The pause decision is a human one.
    try:
        from config.settings import MONTHLY_NEG_R_REVIEW
    except ImportError:
        MONTHLY_NEG_R_REVIEW = True
    if MONTHLY_NEG_R_REVIEW and _is_last_trading_day_of_month(now):
        try:
            avg_r, n = state.get_month_avg_r()
        except Exception as e:
            print(f"[EOD] month_avg_r query failed (non-fatal): {e}")
            avg_r, n = (None, 0)
        if avg_r is not None and n > 0:
            print(f"\n{'─'*60}")
            print(f"  📅 MONTH-END R REVIEW — {now.strftime('%B %Y')}")
            print(f"  Trades:   {n}")
            print(f"  Mean R:   {avg_r:+.3f}R")
            if avg_r < 0:
                print(f"  🔴 NEGATIVE-R MONTH — retrospective review recommended")
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🔴 <b>MONTH-END NEGATIVE R</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📅 {now.strftime('%B %Y')}\n"
                        f"📊 Trades: {n}\n"
                        f"📉 Mean R: {avg_r:+.3f}R\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Retrospective review recommended. System NOT paused."
                    )
                except Exception:
                    pass
            else:
                print(f"  🟢 Positive-R month — continue.")
            print(f"{'─'*60}")

    print(f"\n{'='*60}")
    print(f"  EOD job complete — system learned from today's {len(stored)} trades.")
    print(f"{'='*60}\n")


def _is_last_trading_day_of_month(now) -> bool:
    """
    Returns True if `now` is the last trading day (Mon-Fri) of its calendar
    month. We approximate the last trading day as the last weekday of the
    month — doesn't account for NSE holidays. A holiday on the final weekday
    means the previous trading day was technically the last, and our check
    misses it. Acceptable tradeoff for an informational flag.
    """
    from datetime import timedelta as _td
    # Walk forward from `now` to month-end; if every remaining day is Sat/Sun,
    # then `now` is the last weekday of the month.
    if now.weekday() >= 5:    # Saturday or Sunday — definitely not
        return False
    today = now.date()
    cursor = today + _td(days=1)
    while cursor.month == today.month:
        if cursor.weekday() < 5:   # Mon-Fri
            return False
        cursor += _td(days=1)
    return True


def _run_self_critique(closed_trades, chroma):
    """
    Fix #42 (D4) — LLM-graded process review of today's closed trades.
    Single batched Groq call; failure is non-fatal (rest of EOD runs).

    Process grade evaluates DECISION QUALITY independent of outcome.
    The 2×2 (process × outcome) tag is the highest-information learning artefact:
      good_trade_good_outcome  → reinforce
      good_trade_bad_outcome   → KEEP — bad luck, not bad process
      bad_trade_good_outcome   → DO NOT reinforce — lucky win, bad pattern
      bad_trade_bad_outcome    → flag for blacklist
    """
    if not closed_trades:
        return
    if not GROQ_API_KEY:
        print("[EOD] Self-critique skipped — no GROQ_API_KEY")
        return

    # Cap the batch to control tokens (~100 tokens per row × cap = bounded)
    batch = closed_trades[:30]
    rows = []
    for t in batch:
        rows.append({
            "id":     t.id,
            "sym":    t.symbol,
            "setup":  t.setup_type,
            "grade":  t.grade or "?",
            "score":  round(t.score or 0, 2),
            "regime": t.regime or "unknown",
            "pnl_r":  round(t.pnl_r or 0, 2),
            "exit":   t.exit_reason or "",
            "outcome": "WIN" if t.status == "closed_win" else "LOSS",
        })

    prompt = (
        "You are an intraday trading process auditor. For each trade, evaluate "
        "DECISION QUALITY independent of outcome. Process grade considers: "
        "setup quality, regime fit, exit cleanliness — NOT just P&L.\n\n"
        "Return ONLY this JSON shape:\n"
        '{"trades":[{"id":N,"process_grade":"A|B|C|D|F",'
        '"tag":"good_trade_good_outcome|good_trade_bad_outcome|'
        'bad_trade_good_outcome|bad_trade_bad_outcome",'
        '"would_take_again":true|false,"improvement":"<=12 words"}]}\n\n'
        f"Trades:\n{json.dumps(rows)}"
    )

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
            response_format={"type": "json_object"},
            timeout=30,
        )
        content = resp.choices[0].message.content.strip()
        data = json.loads(content)
    except Exception as e:
        print(f"[EOD] Self-critique Groq call failed (non-fatal): {e}")
        return

    critiques = data.get("trades", []) if isinstance(data, dict) else []
    print(f"\n[EOD] 🧠 Got {len(critiques)} self-critiques from LLM")

    tag_counts = {}
    for c in critiques:
        try:
            chroma.store_trade_critique(
                trade_id        = c.get("id"),
                process_grade   = c.get("process_grade", "C"),
                tag             = c.get("tag", "unknown"),
                would_take_again= bool(c.get("would_take_again", True)),
                improvement     = c.get("improvement", ""),
            )
            tag_counts[c.get("tag", "unknown")] = tag_counts.get(c.get("tag", "unknown"), 0) + 1
        except Exception as e:
            print(f"[EOD] critique save error for trade {c.get('id')}: {e}")

    if tag_counts:
        print("[EOD] Critique tag distribution:")
        for tag, n in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {tag:30s} {n}")


def _send_empty_eod(today: str):
    """Send a brief Telegram message on days with no trades."""
    try:
        alert_eod_report(
            total_trades=0,
            wins=0,
            losses=0,
            total_pnl=0,
            best_trade=0,
            worst_trade=0,
            best_setup="n/a",
            regime_of_day="n/a",
        )
    except Exception:
        pass


def _extract_regime(reason: str) -> str:
    """Extract regime label from trade reason string."""
    if not reason:
        return "unknown"
    rl = reason.lower()
    for regime in ["trending", "recovering", "choppy", "event"]:
        if regime in rl:
            return regime
    return "unknown"


def _print_weekly_scorecard(state: TradeStateManager):
    """Print a weekly summary — called on Fridays."""
    print(f"\n{'═'*60}")
    print(f"  📅 WEEKLY SCORECARD")
    print(f"{'═'*60}")

    summary   = state.get_summary()
    by_setup  = state.get_win_rate_by_setup()
    by_grade  = state.get_win_rate_by_grade()
    by_hour   = state.get_win_rate_by_hour()
    best_stk  = state.get_best_stocks(top_n=5)

    print(f"\n  All-time performance:")
    print(f"  Total:    {summary['total']} trades")
    print(f"  Win rate: {summary['win_rate']}%")
    print(f"  Avg R:    {summary['avg_r']:+.2f}R")
    print(f"  P&L:      ₹{summary['total_pnl']:+,.0f}")

    if by_grade:
        print(f"\n  By grade:")
        for grade in ["A++", "A+", "A", "B", "C"]:
            if grade in by_grade:
                g = by_grade[grade]
                print(f"    {grade:4} {g['win_rate']:5.1f}% "
                      f"({g['total']} trades  {g['avg_r']:+.2f}R)")

    if by_hour:
        best_hour  = max(by_hour, key=lambda h: by_hour[h]["win_rate"])
        worst_hour = min(by_hour, key=lambda h: by_hour[h]["win_rate"])
        print(f"\n  Best entry hour:  {best_hour}  ({by_hour[best_hour]['win_rate']}% WR)")
        print(f"  Worst entry hour: {worst_hour}  ({by_hour[worst_hour]['win_rate']}% WR)")

    if best_stk:
        print(f"\n  Top 5 stocks by cumulative P&L:")
        for s in best_stk:
            print(f"    {s['symbol']:12} ₹{s['total_pnl']:+,.0f}")

    print(f"{'═'*60}\n")


if __name__ == "__main__":
    run_eod_job()
