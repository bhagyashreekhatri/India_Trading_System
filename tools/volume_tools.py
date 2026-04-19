from langchain.tools import tool
import json
from data.kite_client import KiteDataClient

_kite = None
def get_kite() -> KiteDataClient:
    global _kite
    if _kite is None:
        _kite = KiteDataClient()
    return _kite

def _vol_score(ratio, liq):
    if not liq: return 0.0
    if ratio >= 2.5: return 2.0
    elif ratio >= 1.5: return round(1.0 + (ratio-1.5)/1.0, 2)
    elif ratio >= 1.2: return 1.0
    return 0.0

def _rs_score(delta):
    if delta >= 1.0: return 2.0
    elif delta >= 0.5: return 1.5
    elif delta >= 0.0: return 1.0
    elif delta >= -0.5: return 0.5
    return 0.0

@tool("Analyze volume strength for an NSE stock")
def analyze_volume(symbol: str) -> str:
    """Get volume ratio, spread, liquidity pass/fail and volume_score 0-2."""
    ratio  = get_kite().get_volume_ratio(symbol) or 0.0
    spread = get_kite().get_spread_pct(symbol)
    liq    = (ratio >= 1.2) and (spread < 0.15)
    return json.dumps({"symbol": symbol, "volume_ratio": ratio, "bid_ask_spread": spread,
                       "liquidity_pass": liq, "volume_score": _vol_score(ratio, liq)})

@tool("Get relative strength vs Nifty")
def get_relative_strength(symbol: str) -> str:
    """Compare stock vs Nifty change%. Positive delta = outperforming."""
    quotes    = get_kite().get_quotes([symbol])
    nifty     = get_kite().get_nifty_data()
    stock_chg = quotes.get(symbol, {}).get("change_pct", 0.0)
    nifty_chg = nifty.get("change_pct", 0.0)
    delta     = round(stock_chg - nifty_chg, 3)
    return json.dumps({"symbol": symbol, "stock_change_pct": stock_chg,
                       "nifty_change_pct": nifty_chg, "rs_delta": delta,
                       "outperforming": delta > 0.5, "rs_score": _rs_score(delta)})

@tool("Batch volume and RS analysis for multiple stocks")
def batch_volume_rs(symbols: str) -> str:
    """Analyze volume + RS for comma-separated symbols. Returns ranked list."""
    symbol_list = [s.strip() for s in symbols.split(",")]
    quotes    = get_kite().get_quotes(symbol_list)
    nifty_chg = get_kite().get_nifty_data().get("change_pct", 0.0)
    results   = []
    for sym in symbol_list:
        ratio  = get_kite().get_volume_ratio(sym) or 0.0
        spread = get_kite().get_spread_pct(sym)
        liq    = (ratio >= 1.2) and (spread < 0.15)
        delta  = round(quotes.get(sym, {}).get("change_pct", 0.0) - nifty_chg, 3)
        results.append({"symbol": sym, "volume_ratio": ratio, "spread_pct": spread,
                        "liquidity_pass": liq, "rs_delta": delta,
                        "volume_score": _vol_score(ratio, liq), "rs_score": _rs_score(delta)})
    results.sort(key=lambda x: x["volume_score"]+x["rs_score"], reverse=True)
    return json.dumps(results)

VOLUME_TOOLS = [analyze_volume, get_relative_strength, batch_volume_rs]
