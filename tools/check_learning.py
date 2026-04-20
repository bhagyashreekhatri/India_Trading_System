"""
check_learning.py — Show everything the agent has stored and learned.

Run on server:
    cd /root/india_trading
    python tools/check_learning.py

Shows:
  1. All trades in SQLite (today + all-time summary)
  2. ChromaDB — what trade patterns are stored in vector memory
  3. Win/loss breakdown by setup type
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.trade_state import TradeStateManager
from memory.chroma_client import ChromaMemory
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

SEP = "─" * 60

def banner(title):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


# ── 1. SQLite — Trade State ───────────────────────────────────────────────────

banner("🗃  SQLite Trade Database")

state = TradeStateManager()

# All-time summary
summary = state.get_summary()
section("📊 All-Time Summary")
print(f"  Total trades   : {summary['total']}")
print(f"  Wins           : {summary['wins']}")
print(f"  Losses         : {summary['losses']}")
print(f"  Win rate       : {summary['win_rate']}%")
print(f"  Avg R          : {summary['avg_r']:+.2f}R")
print(f"  Total P&L      : ₹{summary['total_pnl']:+,.0f}")
print(f"  Best trade     : ₹{summary['best_trade']:+,.0f}")
print(f"  Worst trade    : ₹{summary['worst_trade']:+,.0f}")

# Open positions
open_pos = state.get_open_positions()
section(f"📂 Open Positions ({len(open_pos)})")
if open_pos:
    for p in open_pos:
        print(f"  {p.symbol:12} | {p.grade} {p.score:.1f} | entry ₹{p.entry_price:.2f} "
              f"| SL ₹{p.stop_loss:.2f} | qty {p.quantity} | {p.setup_type}")
else:
    print("  None")

# Today's trades
today_trades = state.get_today_trades()
section(f"📅 Today's Trades ({len(today_trades)})")
if today_trades:
    for t in today_trades:
        status_icon = "🟢" if t.status == "closed_win" else "🔴" if t.status == "closed_loss" else "🔵"
        pnl_str = f"₹{t.pnl:+,.0f}" if t.pnl else "open"
        print(f"  {status_icon} {t.symbol:12} | {t.grade or '-'} {(t.score or 0):.1f} "
              f"| {(t.setup_type or '').replace('_',' '):20} | {pnl_str}")
else:
    print("  No trades today yet")

# All closed trades
closed = state.get_all_closed_trades()
section(f"📋 All Closed Trades ({len(closed)})")
if closed:
    for t in sorted(closed, key=lambda x: x.exit_time or "", reverse=True)[:20]:
        icon = "🟢" if t.status == "closed_win" else "🔴"
        print(f"  {icon} {t.symbol:12} | {t.grade or '-'} | "
              f"₹{t.pnl:+,.0f} ({t.pnl_r:+.2f}R) | "
              f"{(t.exit_reason or '').replace('_',' '):20} | "
              f"{(t.exit_time or '')[:16]}")
    if len(closed) > 20:
        print(f"  ... and {len(closed)-20} more")
else:
    print("  No closed trades yet")

# Setup performance
section("🎯 Win Rate by Setup")
setup_stats = state.get_win_rate_by_setup()
if setup_stats:
    for setup, v in sorted(setup_stats.items(), key=lambda x: -x[1]['win_rate']):
        bar = "█" * int(v['win_rate'] / 10)
        print(f"  {setup.replace('_',' '):25} | {v['total']:2} trades | "
              f"{v['win_rate']:5.1f}% {bar} | avg {v['avg_r']:+.2f}R | ₹{v['total_pnl']:+,.0f}")
else:
    print("  No data yet")

# Grade performance
section("🏆 Win Rate by Grade")
grade_stats = state.get_win_rate_by_grade()
if grade_stats:
    for grade in ["A++", "A+", "A", "B", "C"]:
        if grade in grade_stats:
            v = grade_stats[grade]
            print(f"  {grade:4} | {v['total']:2} trades | {v['win_rate']:5.1f}% | avg {v['avg_r']:+.2f}R")
else:
    print("  No data yet")


# ── 2. ChromaDB — Vector Memory ───────────────────────────────────────────────

banner("🧠  ChromaDB Vector Memory (What Agent Learned)")

try:
    chroma = ChromaMemory()

    # Check each collection
    collections = {
        "trade_patterns":   "Trade patterns (setups that worked/failed)",
        "market_regimes":   "Market regime snapshots",
        "stock_profiles":   "Per-stock performance profiles",
    }

    for col_name, description in collections.items():
        section(f"📦 {col_name} — {description}")
        try:
            col = chroma.client.get_collection(col_name)
            count = col.count()
            print(f"  Records stored: {count}")

            if count > 0:
                # Peek at recent records
                results = col.peek(limit=5)
                docs = results.get("documents", [])
                metas = results.get("metadatas", [])
                for i, (doc, meta) in enumerate(zip(docs, metas)):
                    print(f"\n  [{i+1}] {doc[:120]}...")
                    if meta:
                        key_fields = {k: v for k, v in meta.items()
                                      if k in ['symbol', 'setup_type', 'grade', 'outcome',
                                               'pnl', 'regime', 'timestamp']}
                        print(f"      Meta: {key_fields}")
            else:
                print("  (empty — agent needs more trades to build memory)")
        except Exception as e:
            print(f"  Collection not found or empty: {e}")

except Exception as e:
    print(f"\n  ChromaDB error: {e}")
    print("  (ChromaDB may not have any data yet if no EOD job has run)")


# ── 3. Hour-of-day analysis ───────────────────────────────────────────────────

banner("⏰  Best Trading Hours (so far)")
hour_stats = state.get_win_rate_by_hour()
if hour_stats:
    for hour, v in sorted(hour_stats.items()):
        bar_w = "█" * int(v['win_rate'] / 10)
        bar_l = "░" * (10 - int(v['win_rate'] / 10))
        print(f"  {hour}:00  {v['total']:2} trades | {v['win_rate']:5.1f}% {bar_w}{bar_l} | "
              f"avg ₹{v['avg_pnl']:+,.0f}")
else:
    print("  Not enough data yet (need closed trades)")

print(f"\n{'═'*60}")
print(f"  ✅ Done — {len(closed)} closed trades in DB")
print(f"     Dashboard Learning Lab: http://SERVER_IP:8501 → 🎓 Learning Lab tab")
print(f"{'═'*60}\n")
