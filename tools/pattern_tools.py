from langchain.tools import tool
import json
import pandas as pd
from data.kite_client import KiteDataClient
from scoring.engine import SetupType
from config.universe import get_sector

_kite = None
def get_kite():
    global _kite
    if _kite is None: _kite = KiteDataClient()
    return _kite

def _candle_quality(c):
    r = c["high"] - c["low"]
    if r == 0: return 0.0, 0.5
    return round(abs(c["close"]-c["open"])/r, 3), round((c["close"]-c["low"])/r, 3)

def _atr(df, p=10):
    h,l,c = df["high"].tail(p), df["low"].tail(p), df["close"].tail(p)
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.mean()

def _sl_target(entry, atr, r=1.5):
    dist = max(atr*0.8, entry*0.007)
    return round(entry-dist,2), round(entry+dist*r,2)

def _make(sym, stype, entry, sl, tgt, curr, br, cp, reason):
    return {"symbol":sym,"setup_type":stype,"direction":"long","entry_price":entry,
            "stop_loss":sl,"target_price":tgt,"current_price":curr,
            "candle_body_ratio":br,"close_position":cp,
            "candle_quality":round((br+cp)/2,3),"sector":get_sector(sym),"reason":reason}

def _detect(df, vwap, curr, sym):
    if df is None or len(df)<8 or vwap is None: return None
    last,prev = df.iloc[-1],df.iloc[-2]
    br,cp = _candle_quality(last)
    atr = _atr(df)
    # Recovery
    below = sum(1 for i in range(-6,-2) if df.iloc[i]["close"]<vwap)
    if below>=3 and last["close"]>vwap and last["close"]>last["open"] and br>=0.5:
        sl,tgt = _sl_target(last["close"], atr)
        return _make(sym,"recovery_setup",round(last["close"],2),sl,tgt,curr,br,cp,
                     f"Recovery: was below VWAP {below} candles, now reclaiming {vwap:.2f}")
    # VWAP reclaim
    if prev["close"]<vwap and last["close"]>vwap and last["close"]>last["open"] and br>=0.45:
        sl,tgt = _sl_target(round(vwap*1.001,2), atr)
        return _make(sym,"vwap_reclaim",round(vwap*1.001,2),sl,tgt,curr,br,cp,
                     f"VWAP reclaim at {vwap:.2f}")
    # Momentum breakout
    rh = df["high"].iloc[-7:-1].max()
    if last["close"]>rh and last["close"]>vwap and br>=0.4 and cp>=0.6:
        sl,tgt = _sl_target(round(last["close"],2), atr)
        return _make(sym,"momentum_breakout",round(last["close"],2),sl,tgt,curr,br,cp,
                     f"Broke recent high {rh:.2f} above VWAP")
    # VWAP pullback
    above = sum(1 for i in range(-6,-2) if df.iloc[i]["close"]>vwap)
    if above>=3 and prev["low"]<=vwap*1.002 and last["close"]>vwap and br>=0.4:
        sl,tgt = _sl_target(round(last["close"],2), atr)
        return _make(sym,"vwap_pullback",round(last["close"],2),sl,tgt,curr,br,cp,
                     f"VWAP pullback reclaim after {above} candles above")
    # Range breakout
    rc = df.iloc[-9:-1]
    rng_h,rng_l = rc["high"].max(),rc["low"].min()
    rng_pct = (rng_h-rng_l)/rng_l*100 if rng_l>0 else 99
    if rng_pct<2.0 and last["close"]>rng_h and last["close"]>vwap and br>=0.4:
        sl,tgt = _sl_target(round(last["close"],2), atr)
        return _make(sym,"range_breakout",round(last["close"],2),sl,tgt,curr,br,cp,
                     f"Range breakout above {rng_h:.2f}")
    return None

@tool("Detect intraday setup for one NSE stock")
def detect_setup(symbol: str) -> str:
    """Scan one stock for trading setups. Returns setup details or null."""
    df,vwap = get_kite().get_vwap_with_candles(symbol)
    curr = get_kite().get_quotes([symbol]).get(symbol,{}).get("last_price", 0)
    result = _detect(df, vwap, curr, symbol)
    return json.dumps(result or {"symbol":symbol,"setup_type":None,"reason":"No setup detected"})

@tool("Scan multiple NSE stocks for setups")
def scan_all_setups(symbols: str) -> str:
    """Scan comma-separated symbols for setups. Returns only valid ones."""
    results = []
    for sym in [s.strip() for s in symbols.split(",")]:
        try:
            df,vwap = get_kite().get_vwap_with_candles(sym)
            curr = get_kite().get_quotes([sym]).get(sym,{}).get("last_price",0)
            r = _detect(df, vwap, curr, sym)
            if r: results.append(r)
        except: continue
    results.sort(key=lambda x: x.get("candle_quality",0), reverse=True)
    return json.dumps(results, default=str)

PATTERN_TOOLS = [detect_setup, scan_all_setups]
