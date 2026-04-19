"""
Score Tools — LangChain tool wrappers around ScoringEngine + TradeStateManager + Kite.
Handles: signal scoring, position entry/exit, watchlist, position queries.
"""
import json
from math import floor
from langchain.tools import tool

from scoring.engine import (
    ScoringEngine, RawSignal, VolumeData, MarketContext,
    RelativeStrengthData, NewsData, SetupType, RegimeType, SignalDirection,
)
from memory.trade_state import TradeStateManager, WatchlistItem
from data.kite_client import KiteDataClient
from config.universe import get_sector
from config.settings import (
    CAPITAL, RISK_PER_TRADE_PCT, MAX_POSITIONS, MAX_SAME_SECTOR_POSITIONS,
    MAX_CONSECUTIVE_LOSSES, CONSERVATIVE_SIZE_PCT, TARGET_R1, TARGET_R2,
)
from datetime import datetime

_engine = ScoringEngine()
_state: TradeStateManager = None
_kite:  KiteDataClient    = None


def get_state() -> TradeStateManager:
    global _state
    if _state is None:
        _state = TradeStateManager()
    return _state


def get_kite() -> KiteDataClient:
    global _kite
    if _kite is None:
        _kite = KiteDataClient()
    return _kite


def _calc_tp(entry: float, sl: float, r: float) -> float:
    return round(entry + (entry - sl) * r, 2)


def _calc_quantity(entry_price: float, stop_loss: float, conservative: bool = False) -> int:
    """
    Position sizing: risk 1% of capital per trade.
    Returns 0 if SL is invalid or capital is insufficient.
    """
    dist = entry_price - stop_loss
    if dist <= 0:
        return 0
    multiplier  = CONSERVATIVE_SIZE_PCT if conservative else 1.0
    risk_amount = CAPITAL * RISK_PER_TRADE_PCT * multiplier
    qty         = floor(risk_amount / dist)
    # Cap at what available capital can buy
    available   = get_state().get_available_capital()
    qty         = min(qty, floor(available / entry_price))
    return max(0, qty)


# ─── Score a signal ───────────────────────────────────────────────────────────

@tool("Score a trading signal using the scoring engine")
def score_signal(
    symbol: str, setup_type: str, direction: str,
    entry_price: float, stop_loss: float, target_price: float, current_price: float,
    candle_body_ratio: float, close_position_in_candle: float, sector: str,
    volume_ratio: float, bid_ask_spread: float, liquidity_pass: bool,
    nifty_above_vwap: bool, banknifty_above_vwap: bool,
    nifty_vwap_minutes: int, market_trend_aligned: bool, breadth_score: float,
    regime: str, stock_change_pct: float, nifty_change_pct: float,
    has_news: bool, news_llm_score: float, catalyst_type: str,
    news_headline: str = "",
) -> str:
    """
    Score a raw signal using all agent inputs.
    Returns final_score, grade, breakdown, and trade validity.
    """
    try:
        sig = RawSignal(
            symbol=symbol,
            setup_type=SetupType(setup_type),
            direction=SignalDirection(direction),
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            current_price=current_price,
            candle_body_ratio=candle_body_ratio,
            close_position=close_position_in_candle,
            sector=sector,
        )
        vol = VolumeData(
            symbol=symbol, current_volume=0, avg_volume_20=0,
            volume_ratio=volume_ratio, bid_ask_spread=bid_ask_spread,
            liquidity_pass=liquidity_pass,
        )
        ctx = MarketContext(
            regime=RegimeType(regime),
            regime_confidence=0.8,
            nifty_above_vwap=nifty_above_vwap,
            banknifty_above_vwap=banknifty_above_vwap,
            nifty_vwap_minutes=nifty_vwap_minutes,
            market_trend_aligned=market_trend_aligned,
            breadth_score=breadth_score,
        )
        rs = RelativeStrengthData(
            symbol=symbol,
            stock_change_pct=stock_change_pct,
            nifty_change_pct=nifty_change_pct,
            rs_delta=round(stock_change_pct - nifty_change_pct, 3),
            outperforming=(stock_change_pct - nifty_change_pct) > 0.5,
        )
        nws = NewsData(
            symbol=symbol, has_news=has_news, sentiment=news_llm_score,
            catalyst_type=catalyst_type, headline=news_headline,
            llm_score=news_llm_score,
        )
        r = _engine.calculate(sig, vol, ctx, rs, nws)
        c = r.components

        return json.dumps({
            "symbol":       symbol,
            "setup_type":   setup_type,
            "final_score":  c.final_score,
            "grade":        c.grade.value,
            "is_valid":     r.is_valid,
            "proximity_ok": r.proximity_ok,
            "confidence":   r.confidence,
            "breakdown": {
                "setup_quality":    c.setup_quality,
                "volume_strength":  c.volume_strength,
                "market_alignment": c.market_alignment,
                "relative_strength": c.relative_strength,
                "news_sentiment":   c.news_sentiment,
                "raw_score":        c.raw_score,
                "regime_multiplier": c.regime_multiplier,
            },
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "tp1_price":   _calc_tp(entry_price, stop_loss, TARGET_R1),
            "tp2_price":   _calc_tp(entry_price, stop_loss, TARGET_R2),
            "reason":      r.reason,
            "skip_reason": c.skip_reason,
        })
    except Exception as e:
        return json.dumps({"error": str(e), "symbol": symbol, "is_valid": False})


# ─── Entry validation ─────────────────────────────────────────────────────────

@tool("Check if we can enter a trade")
def can_enter_trade(symbol: str, sector: str, entry_price: float, stop_loss: float) -> str:
    """
    Validate entry: max positions, sector cap, cooldown, capital, consecutive losses.
    Always call this before entering a trade.
    """
    state = get_state()
    open_pos = state.get_open_positions()

    # Already in this stock
    if any(p.symbol == symbol for p in open_pos):
        return json.dumps({"can_enter": False, "reason": f"{symbol} already open"})

    # Max positions
    if len(open_pos) >= MAX_POSITIONS:
        return json.dumps({"can_enter": False,
                           "reason": f"Max {MAX_POSITIONS} positions reached"})

    # Cooldown
    if state.is_in_cooldown(symbol, 30):
        return json.dumps({"can_enter": False,
                           "reason": f"{symbol} in 30-min cooldown after last exit"})

    # Sector cap
    sector_count = sum(1 for p in open_pos if get_sector(p.symbol) == sector)
    if sector_count >= MAX_SAME_SECTOR_POSITIONS:
        return json.dumps({"can_enter": False,
                           "reason": f"Sector {sector} already has {sector_count} positions"})

    # SL validity
    dist = entry_price - stop_loss
    if dist <= 0:
        return json.dumps({"can_enter": False, "reason": "Stop loss must be below entry"})

    # Position sizing with consecutive-loss adjustment
    consec  = state.get_consecutive_losses()
    conservative = consec >= MAX_CONSECUTIVE_LOSSES
    qty     = _calc_quantity(entry_price, stop_loss, conservative)

    if qty < 1:
        return json.dumps({
            "can_enter": False,
            "reason":    "Not enough capital for even 1 share at current risk parameters",
        })

    return json.dumps({
        "can_enter":        True,
        "reason":           "ok",
        "quantity":         qty,
        "capital_available": round(state.get_available_capital(), 2),
        "deployment_pct":   round(state.get_deployment_pct(), 1),
        "open_positions":   len(open_pos),
        "consecutive_losses": consec,
        "conservative_mode": conservative,
    })


# ─── Open position ────────────────────────────────────────────────────────────

@tool("Open a new position")
def open_position(
    symbol: str, setup_type: str, direction: str,
    grade: str, score: float, confidence: float,
    entry_price: float, stop_loss: float,
    quantity: int, reason: str,
    score_breakdown: str = "{}",
) -> str:
    """
    Record a new position in DB and place paper/live order via Kite.
    tp1 and tp2 are auto-calculated from entry/SL using TARGET_R1/R2.
    """
    try:
        state = get_state()
        tp1   = _calc_tp(entry_price, stop_loss, TARGET_R1)
        tp2   = _calc_tp(entry_price, stop_loss, TARGET_R2)
        bd    = json.loads(score_breakdown) if isinstance(score_breakdown, str) else score_breakdown

        pos_id = state.open_position(
            symbol=symbol,
            setup_type=setup_type,
            grade=grade,
            score=score,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1_price=tp1,
            tp2_price=tp2,
            quantity=quantity,
            entry_reason=reason,
            score_breakdown=bd,
            direction=direction,
        )

        tx       = "BUY" if direction == "long" else "SELL"
        order_id = get_kite().place_order(symbol, tx, quantity)

        return json.dumps({
            "success":     True,
            "position_id": pos_id,
            "symbol":      symbol,
            "quantity":    quantity,
            "entry":       entry_price,
            "sl":          stop_loss,
            "tp1":         tp1,
            "tp2":         tp2,
            "grade":       grade,
            "score":       score,
            "order_id":    order_id,
        })
    except Exception as e:
        return json.dumps({"success": False, "reason": str(e), "symbol": symbol})


# ─── Partial exit at TP1 ──────────────────────────────────────────────────────

@tool("Execute partial exit at TP1 — 50% of position")
def partial_exit_tp1(position_id: int) -> str:
    """
    Exit 50% of position at TP1. Moves SL to breakeven.
    Call when current_price >= tp1_price and tp1_hit is False.
    """
    try:
        state = get_state()
        pos   = state.get_position(position_id)
        if not pos:
            return json.dumps({"success": False, "reason": "Position not found"})
        if pos.tp1_hit:
            return json.dumps({"success": False, "reason": "TP1 already hit"})

        exit_price    = get_kite().get_quotes([pos.symbol]).get(
            pos.symbol, {}).get("last_price", pos.tp1_price)
        qty_exit      = floor(pos.quantity_remaining / 2)
        qty_remaining = pos.quantity_remaining - qty_exit

        partial_pnl = (exit_price - pos.entry_price) * qty_exit
        new_sl      = pos.entry_price   # breakeven

        # Update state
        state.mark_tp1_hit(position_id, qty_remaining, partial_pnl)
        state.update_stop_loss(position_id, new_sl)

        # Place partial exit order
        tx       = "SELL" if pos.direction == "long" else "BUY"
        order_id = get_kite().place_order(pos.symbol, tx, qty_exit)

        return json.dumps({
            "success":       True,
            "position_id":   position_id,
            "symbol":        pos.symbol,
            "qty_exited":    qty_exit,
            "qty_remaining": qty_remaining,
            "exit_price":    round(exit_price, 2),
            "partial_pnl":   round(partial_pnl, 2),
            "new_sl":        new_sl,
            "order_id":      order_id,
        })
    except Exception as e:
        return json.dumps({"success": False, "reason": str(e)})


# ─── Full exit ────────────────────────────────────────────────────────────────

@tool("Close an open position fully")
def close_position(position_id: int, exit_reason: str) -> str:
    """
    Close remaining position. Updates DB and places exit order.
    exit_reason: 'sl_hit' | 'tp2_hit' | 'eod_exit' | 'stalled' | 'manual'
    """
    try:
        state = get_state()
        pos   = state.get_position(position_id)
        if not pos:
            return json.dumps({"success": False, "reason": "Position not found"})

        exit_price = get_kite().get_quotes([pos.symbol]).get(
            pos.symbol, {}).get("last_price", pos.entry_price)

        qty       = pos.quantity_remaining
        sl_dist   = abs(pos.entry_price - pos.initial_sl)

        if pos.direction == "long":
            trade_pnl = (exit_price - pos.entry_price) * qty
        else:
            trade_pnl = (pos.entry_price - exit_price) * qty

        total_pnl = round(pos.pnl + trade_pnl, 2)   # includes partial TP1 pnl
        pnl_r = round(
            total_pnl / (sl_dist * pos.quantity), 2
        ) if sl_dist > 0 and pos.quantity > 0 else 0

        status   = "closed_win" if total_pnl > 0 else "closed_loss"
        state.close_position(position_id, exit_price, total_pnl, pnl_r, status, exit_reason)

        tx       = "SELL" if pos.direction == "long" else "BUY"
        order_id = get_kite().place_order(pos.symbol, tx, qty)

        return json.dumps({
            "success":     True,
            "position_id": position_id,
            "symbol":      pos.symbol,
            "exit_price":  round(exit_price, 2),
            "pnl":         total_pnl,
            "pnl_r":       pnl_r,
            "status":      status,
            "exit_reason": exit_reason,
            "order_id":    order_id,
        })
    except Exception as e:
        return json.dumps({"success": False, "reason": str(e)})


# ─── Update SL ────────────────────────────────────────────────────────────────

@tool("Update stop loss for a position (trailing SL)")
def update_stop_loss(position_id: int, new_sl: float) -> str:
    """Move stop loss up for trailing SL management. Only moves SL higher (tighter)."""
    try:
        state = get_state()
        pos   = state.get_position(position_id)
        if not pos:
            return json.dumps({"success": False, "reason": "Position not found"})
        if new_sl <= pos.stop_loss:
            return json.dumps({"success": False, "reason": "New SL not better than current"})
        state.update_stop_loss(position_id, new_sl)
        return json.dumps({"success": True, "old_sl": pos.stop_loss, "new_sl": new_sl})
    except Exception as e:
        return json.dumps({"success": False, "reason": str(e)})


# ─── Queries ──────────────────────────────────────────────────────────────────

@tool("Get all open positions with live prices")
def get_open_positions(query: str = "all") -> str:
    """Get current open positions with unrealized P&L and position details."""
    state     = get_state()
    positions = state.get_open_positions()
    result    = []

    for p in positions:
        try:
            quotes  = get_kite().get_quotes([p.symbol])
            current = quotes.get(p.symbol, {}).get("last_price", p.entry_price)
        except Exception:
            current = p.entry_price

        sl_dist  = abs(p.entry_price - p.initial_sl) or 1
        unreal   = (current - p.entry_price) * p.quantity_remaining \
                   if p.direction == "long" \
                   else (p.entry_price - current) * p.quantity_remaining
        pnl_r    = round(unreal / (sl_dist * p.quantity), 2) if sl_dist > 0 and p.quantity > 0 else 0

        result.append({
            "id":            p.id,
            "symbol":        p.symbol,
            "direction":     p.direction,
            "grade":         p.grade,
            "score":         p.score,
            "entry_price":   p.entry_price,
            "stop_loss":     p.stop_loss,
            "initial_sl":    p.initial_sl,
            "tp1_price":     p.tp1_price,
            "tp2_price":     p.tp2_price,
            "tp1_hit":       p.tp1_hit,
            "quantity":      p.quantity,
            "qty_remaining": p.quantity_remaining,
            "current_price": round(current, 2),
            "unrealized_pnl": round(unreal, 2),
            "pnl_r":         pnl_r,
            "entry_time":    p.entry_time,
            "setup_type":    p.setup_type,
            "entry_reason":  p.entry_reason,
        })

    return json.dumps({
        "open_count":    len(result),
        "positions":     result,
        "today_pnl":     round(state.get_today_pnl(), 2),
        "deployed_pct":  round(state.get_deployment_pct(), 1),
        "capital_avail": round(state.get_available_capital(), 2),
    })


@tool("Add signal to watchlist")
def add_to_watchlist(
    symbol: str, setup_type: str, score: float,
    entry_price: float, stop_loss: float, reason: str,
) -> str:
    """Watchlist a B-grade signal or one where capital is full. Monitored for next opportunity."""
    try:
        from datetime import datetime
        tp1 = _calc_tp(entry_price, stop_loss, TARGET_R1)
        tp2 = _calc_tp(entry_price, stop_loss, TARGET_R2)
        item = WatchlistItem(
            symbol=symbol, setup_type=setup_type, score=score,
            entry_price=entry_price, stop_loss=stop_loss,
            tp1_price=tp1, tp2_price=tp2, reason=reason,
            added_at=datetime.now().isoformat(),
        )
        get_state().add_to_watchlist(item)
        return json.dumps({"watchlisted": True, "symbol": symbol,
                           "score": score, "tp1": tp1, "tp2": tp2})
    except Exception as e:
        return json.dumps({"watchlisted": False, "error": str(e)})


# ─── Exported tool list ───────────────────────────────────────────────────────

SCORE_TOOLS = [
    score_signal,
    can_enter_trade,
    open_position,
    partial_exit_tp1,
    close_position,
    update_stop_loss,
    get_open_positions,
    add_to_watchlist,
]
