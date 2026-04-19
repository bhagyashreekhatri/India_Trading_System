"""
Telegram Alerts — sends real-time trade notifications.
Entry, Exit, TP1 hit, SL hit, EOD report, consecutive loss warning.
"""
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TIMEZONE

IST = ZoneInfo(TIMEZONE)


def _send(message: str) -> bool:
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram] Token/ChatID missing — skipping alert")
        return False
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        print(f"[Telegram] Failed to send: {e}")
        return False


def alert_trade_entry(
    symbol:       str,
    setup_type:   str,
    grade:        str,
    score:        float,
    confidence:   float,
    entry_price:  float,
    stop_loss:    float,
    tp1_price:    float,
    tp2_price:    float,
    quantity:     int,
    reason:       str,
    score_breakdown: dict = None,
):
    now      = datetime.now(IST).strftime("%H:%M IST")
    sl_pct   = abs(entry_price - stop_loss) / entry_price * 100
    tp1_pct  = abs(tp1_price - entry_price) / entry_price * 100
    tp2_pct  = abs(tp2_price - entry_price) / entry_price * 100
    bd       = score_breakdown or {}

    msg = (
        f"✅ <b>TRADE ENTRY</b> — {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b> | {setup_type.replace('_',' ').title()}\n"
        f"🏆 Grade: <b>{grade}</b> | Score: <b>{score:.1f}/10</b> | Confidence: {confidence*100:.0f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Entry:  ₹{entry_price:,.2f}\n"
        f"🛑 SL:     ₹{stop_loss:,.2f}  (-{sl_pct:.2f}%)\n"
        f"🎯 TP1:   ₹{tp1_price:,.2f}  (+{tp1_pct:.2f}%)  → exit 50%\n"
        f"🚀 TP2:   ₹{tp2_price:,.2f}  (+{tp2_pct:.2f}%)  → exit 50%\n"
        f"📦 Qty:   {quantity} shares\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    if bd:
        msg += (
            f"📊 Score breakdown:\n"
            f"  Setup: {bd.get('setup_quality',0):.1f}/3 | "
            f"Vol: {bd.get('volume_strength',0):.1f}/2 | "
            f"Mkt: {bd.get('market_alignment',0):.1f}/2\n"
            f"  RS: {bd.get('relative_strength',0):.1f}/2 | "
            f"News: {bd.get('news_sentiment',0):.1f}/1\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
    msg += f"💡 <i>{reason[:120]}</i>"
    _send(msg)


def alert_tp1_hit(
    symbol:      str,
    tp1_price:   float,
    partial_pnl: float,
    qty_exited:  int,
    qty_remaining: int,
    new_sl:      float,
):
    now = datetime.now(IST).strftime("%H:%M IST")
    msg = (
        f"🎯 <b>TP1 HIT</b> — {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"✅ Exited {qty_exited} shares @ ₹{tp1_price:,.2f}\n"
        f"💰 Partial P&L: <b>₹{partial_pnl:+,.0f}</b>\n"
        f"📦 Remaining: {qty_remaining} shares still open\n"
        f"🛑 SL moved to breakeven: ₹{new_sl:,.2f}\n"
        f"🚀 Riding to TP2 — risk free now!"
    )
    _send(msg)


def alert_trade_exit(
    symbol:      str,
    setup_type:  str,
    exit_price:  float,
    entry_price: float,
    pnl:         float,
    pnl_r:       float,
    exit_reason: str,
    hold_minutes: int,
):
    now    = datetime.now(IST).strftime("%H:%M IST")
    emoji  = "🟢" if pnl > 0 else "🔴"
    outcome = "WIN" if pnl > 0 else "LOSS"
    msg = (
        f"{emoji} <b>TRADE EXIT — {outcome}</b> — {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b> | {setup_type.replace('_',' ').title()}\n"
        f"💰 P&L: <b>₹{pnl:+,.0f}</b> ({pnl_r:+.2f}R)\n"
        f"📈 Entry: ₹{entry_price:,.2f} → Exit: ₹{exit_price:,.2f}\n"
        f"⏱ Held: {hold_minutes} minutes\n"
        f"📋 Reason: <i>{exit_reason}</i>"
    )
    _send(msg)


def alert_trailing_sl_moved(symbol: str, old_sl: float, new_sl: float, current_price: float):
    now = datetime.now(IST).strftime("%H:%M IST")
    msg = (
        f"🔄 <b>TRAILING SL MOVED</b> — {now}\n"
        f"📌 <b>{symbol}</b>\n"
        f"📈 Current: ₹{current_price:,.2f}\n"
        f"🛑 SL: ₹{old_sl:,.2f} → ₹{new_sl:,.2f}"
    )
    _send(msg)


def alert_consecutive_losses(count: int, new_threshold: float):
    now = datetime.now(IST).strftime("%H:%M IST")
    msg = (
        f"⚠️ <b>CONSECUTIVE LOSS ALERT</b> — {now}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 {count} consecutive losses detected\n"
        f"🛡 Going CONSERVATIVE mode:\n"
        f"  • Min score raised to {new_threshold}\n"
        f"  • Position size reduced 50%\n"
        f"💡 Market may not suit current setups today"
    )
    _send(msg)


def alert_market_breadth(breadth_pct: float, regime: str):
    now   = datetime.now(IST).strftime("%H:%M IST")
    emoji = "🟢" if breadth_pct > 65 else "🔴" if breadth_pct < 40 else "🟡"
    msg = (
        f"{emoji} <b>MARKET BREADTH UPDATE</b> — {now}\n"
        f"📊 {breadth_pct:.0f}% stocks above VWAP\n"
        f"🌐 Regime: <b>{regime}</b>"
    )
    _send(msg)


def alert_eod_report(
    total_trades: int,
    wins: int,
    losses: int,
    total_pnl: float,
    best_trade: float,
    worst_trade: float,
    best_setup: str,
    regime_of_day: str,
):
    now      = datetime.now(IST).strftime("%d %b %Y")
    win_rate = round(wins / total_trades * 100, 1) if total_trades > 0 else 0
    emoji    = "🟢" if total_pnl > 0 else "🔴"
    msg = (
        f"{emoji} <b>EOD REPORT — {now}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Trades:   {total_trades} ({wins}W / {losses}L)\n"
        f"🎯 Win Rate: {win_rate}%\n"
        f"💰 Total P&L: <b>₹{total_pnl:+,.0f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Best trade:  ₹{best_trade:+,.0f}\n"
        f"📉 Worst trade: ₹{worst_trade:+,.0f}\n"
        f"🔥 Best setup: {best_setup.replace('_',' ').title()}\n"
        f"🌐 Market regime today: {regime_of_day}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 System running on server — see you tomorrow!"
    )
    _send(msg)


def alert_system_start():
    now = datetime.now(IST).strftime("%d %b %Y %H:%M IST")
    msg = (
        f"🚀 <b>NSE TRADING SYSTEM STARTED</b>\n"
        f"⏰ {now}\n"
        f"📈 Paper trading mode — scanning 150 stocks\n"
        f"⚡ Scan interval: 3 minutes"
    )
    _send(msg)


def alert_kill_switch(activated: bool):
    now    = datetime.now(IST).strftime("%H:%M IST")
    status = "ACTIVATED 🛑" if activated else "DEACTIVATED ✅"
    msg    = f"🔴 <b>KILL SWITCH {status}</b> — {now}"
    _send(msg)
