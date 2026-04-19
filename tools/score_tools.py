from langchain.tools import tool
import json
from datetime import datetime
from scoring.engine import (ScoringEngine, RawSignal, VolumeData, MarketContext,
                             RelativeStrengthData, NewsData, SetupType, RegimeType, SignalDirection)
from memory.trade_state import TradeStateManager
from data.kite_client import KiteDataClient

_engine = ScoringEngine()
_state = None
_kite  = None
def get_state():
    global _state
    if _state is None: _state = TradeStateManager()
    return _state
def get_kite():
    global _kite
    if _kite is None: _kite = KiteDataClient()
    return _kite

@tool("Score a trading signal using the scoring engine")
def score_signal(symbol:str, setup_type:str, direction:str, entry_price:float,
                 stop_loss:float, target_price:float, current_price:float,
                 candle_body_ratio:float, close_position:float, sector:str,
                 volume_ratio:float, bid_ask_spread:float, liquidity_pass:bool,
                 nifty_above_vwap:bool, banknifty_above_vwap:bool,
                 nifty_vwap_minutes:int, market_trend_aligned:bool, breadth_score:float,
                 regime:str, stock_change_pct:float, nifty_change_pct:float,
                 has_news:bool, news_sentiment:float, catalyst_type:str,
                 news_headline:str="") -> str:
    """Score a raw signal using all agent inputs. Returns final_score, grade, breakdown."""
    try:
        sig = RawSignal(symbol=symbol,setup_type=SetupType(setup_type),
                        direction=SignalDirection(direction),entry_price=entry_price,
                        stop_loss=stop_loss,target_price=target_price,
                        current_price=current_price,candle_body_ratio=candle_body_ratio,
                        close_position=close_position,sector=sector)
        vol = VolumeData(symbol=symbol,current_volume=0,avg_volume_20=0,
                         volume_ratio=volume_ratio,bid_ask_spread=bid_ask_spread,
                         liquidity_pass=liquidity_pass)
        ctx = MarketContext(regime=RegimeType(regime),regime_confidence=0.8,
                            nifty_above_vwap=nifty_above_vwap,banknifty_above_vwap=banknifty_above_vwap,
                            nifty_vwap_minutes=nifty_vwap_minutes,market_trend_aligned=market_trend_aligned,
                            breadth_score=breadth_score)
        rs  = RelativeStrengthData(symbol=symbol,stock_change_pct=stock_change_pct,
                                   nifty_change_pct=nifty_change_pct,
                                   rs_delta=stock_change_pct-nifty_change_pct,
                                   outperforming=(stock_change_pct-nifty_change_pct)>0.5)
        nws = NewsData(symbol=symbol,has_news=has_news,sentiment=news_sentiment,
                       catalyst_type=catalyst_type,headline=news_headline,llm_score=news_sentiment)
        r   = _engine.calculate(sig,vol,ctx,rs,nws)
        c   = r.components
        return json.dumps({"symbol":symbol,"setup_type":setup_type,"final_score":c.final_score,
                           "grade":c.grade.value,"is_valid":r.is_valid,"proximity_ok":r.proximity_ok,
                           "confidence":r.confidence,
                           "breakdown":{"setup_quality":c.setup_quality,"volume_strength":c.volume_strength,
                                        "market_alignment":c.market_alignment,"relative_strength":c.relative_strength,
                                        "news_sentiment":c.news_sentiment,"raw_score":c.raw_score,
                                        "regime_multiplier":c.regime_multiplier},
                           "entry_price":entry_price,"stop_loss":stop_loss,"target_price":target_price,
                           "reason":r.reason,"skip_reason":c.skip_reason})
    except Exception as e:
        return json.dumps({"error": str(e), "symbol": symbol})

@tool("Check if we can enter a trade")
def can_enter_trade(symbol: str, sector: str, entry_price: float, stop_loss: float) -> str:
    """Validate entry: max positions, sector cap, cooldown, capital. Always call before entering."""
    can,reason = get_state().can_enter(symbol,sector,entry_price,stop_loss)
    qty = get_state().calculate_position_size(entry_price,stop_loss) if can else 0
    return json.dumps({"can_enter":can,"reason":reason,"quantity":qty,
                       "capital_available":round(get_state().get_available_capital(),2),
                       "deployment_pct":round(get_state().get_deployment_pct(),1),
                       "open_positions":get_state().get_open_count()})

@tool("Open a new position")
def open_position(symbol:str, setup_type:str, direction:str, grade:str, score:float,
                  confidence:float, entry_price:float, stop_loss:float, target_price:float,
                  sector:str, reason:str) -> str:
    """Record new position in DB and place order via Kite."""
    pos = get_state().open_position(symbol=symbol,setup_type=setup_type,direction=direction,
                                     grade=grade,score=score,confidence=confidence,
                                     entry_price=entry_price,stop_loss=stop_loss,
                                     target_price=target_price,sector=sector,reason=reason)
    if not pos:
        return json.dumps({"success":False,"reason":"Position size = 0"})
    tx = "BUY" if direction=="long" else "SELL"
    order_id = get_kite().place_order(symbol,tx,pos.quantity)
    return json.dumps({"success":True,"position_id":pos.id,"symbol":symbol,
                       "quantity":pos.quantity,"entry":entry_price,"sl":stop_loss,
                       "target":target_price,"grade":grade,"score":score,"order_id":order_id})

@tool("Get all open positions with live prices")
def get_open_positions(query: str = "all") -> str:
    """Get current open positions with unrealized P&L."""
    positions = get_state().get_open_positions()
    result = []
    for p in positions:
        quotes  = get_kite().get_quotes([p.symbol])
        current = quotes.get(p.symbol,{}).get("last_price", p.entry_price)
        sl_dist = abs(p.entry_price-p.stop_loss)
        unreal  = (current-p.entry_price)*p.quantity if p.direction=="long" else (p.entry_price-current)*p.quantity
        pnl_r   = round(unreal/(sl_dist*p.quantity),2) if sl_dist>0 else 0
        result.append({"id":p.id,"symbol":p.symbol,"direction":p.direction,"grade":p.grade,
                        "score":p.score,"entry_price":p.entry_price,"stop_loss":p.stop_loss,
                        "target_price":p.target_price,"quantity":p.quantity,
                        "current_price":round(current,2),"unrealized_pnl":round(unreal,2),
                        "pnl_r":pnl_r,"entry_time":p.entry_time,"setup_type":p.setup_type})
    return json.dumps({"open_count":len(result),"positions":result,
                       "today_pnl":round(get_state().get_today_pnl(),2),
                       "deployed_pct":round(get_state().get_deployment_pct(),1)})

@tool("Close an open position")
def close_position(position_id: int, exit_reason: str) -> str:
    """Close position by ID — updates DB and places exit order."""
    pos = get_state().get_position_by_id(position_id)
    if not pos:
        return json.dumps({"success":False,"reason":"Position not found"})
    exit_price = get_kite().get_quotes([pos.symbol]).get(pos.symbol,{}).get("last_price",pos.entry_price)
    closed = get_state().close_position(position_id,exit_price,exit_reason)
    if not closed:
        return json.dumps({"success":False,"reason":"Could not close"})
    tx = "SELL" if pos.direction=="long" else "BUY"
    order_id = get_kite().place_order(pos.symbol,tx,pos.quantity)
    return json.dumps({"success":True,"position_id":position_id,"symbol":pos.symbol,
                       "exit_price":exit_price,"pnl":closed.pnl,"pnl_r":closed.pnl_r,
                       "status":closed.status,"exit_reason":exit_reason,"order_id":order_id})

@tool("Add signal to watchlist")
def add_to_watchlist(symbol:str, setup_type:str, score:float, grade:str,
                     entry_zone:float, stop_loss:float, target:float, reason:str) -> str:
    """Watchlist a B-grade signal or one where capital is currently full."""
    get_state().add_to_watchlist(symbol=symbol,setup_type=setup_type,score=score,grade=grade,
                                  entry_zone=entry_zone,stop_loss=stop_loss,target=target,reason=reason)
    return json.dumps({"watchlisted":True,"symbol":symbol,"score":score})

SCORE_TOOLS = [score_signal, can_enter_trade, open_position, get_open_positions,
               close_position, add_to_watchlist]
