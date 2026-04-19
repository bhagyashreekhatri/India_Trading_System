from langchain.tools import tool
import json
from data.kite_client import KiteDataClient

_kite = None
def get_kite() -> KiteDataClient:
    global _kite
    if _kite is None:
        _kite = KiteDataClient()
    return _kite

@tool("Get live quotes for NSE stocks")
def get_quotes(symbols: str) -> str:
    """Get live quotes for comma-separated NSE symbols. Returns price, volume, change_pct."""
    symbol_list = [s.strip() for s in symbols.split(",")]
    return json.dumps(get_kite().get_quotes(symbol_list), default=str)

@tool("Get OHLCV candles for an NSE stock")
def get_candles(symbol: str) -> str:
    """Get last 20 five-minute candles for a stock."""
    df = get_kite().get_candles(symbol, interval="5minute", days=1)
    if df is None:
        return json.dumps({"error": f"No data for {symbol}"})
    return df.tail(20).to_json(orient="records", date_format="iso")

@tool("Get VWAP for an NSE stock")
def get_vwap(symbol: str) -> str:
    """Get current VWAP and price position relative to it."""
    df, vwap = get_kite().get_vwap_with_candles(symbol)
    if df is None or vwap is None:
        return json.dumps({"error": f"No VWAP data for {symbol}"})
    current = df["close"].iloc[-1]
    return json.dumps({"symbol": symbol, "vwap": vwap, "current_price": round(current,2),
                       "above_vwap": current > vwap,
                       "distance_pct": round((current-vwap)/vwap*100, 3)})

@tool("Get volume ratio for an NSE stock")
def get_volume_ratio(symbol: str) -> str:
    """Get volume ratio vs 20-period average. >1.5 = strong."""
    ratio = get_kite().get_volume_ratio(symbol)
    if ratio is None:
        return json.dumps({"error": f"No data for {symbol}"})
    return json.dumps({"symbol": symbol, "volume_ratio": ratio,
                       "strength": "strong" if ratio>=1.5 else "weak" if ratio<1.2 else "moderate"})

@tool("Get Nifty and BankNifty data")
def get_nifty_data(query: str = "nifty") -> str:
    """Get Nifty50 and BankNifty price, change% and VWAP position."""
    return json.dumps({"nifty": get_kite().get_nifty_data(),
                       "banknifty": get_kite().get_banknifty_data()}, default=str)

@tool("Get bid-ask spread for an NSE stock")
def get_spread(symbol: str) -> str:
    """Get spread as %. >0.15% = illiquid, reject signal."""
    spread = get_kite().get_spread_pct(symbol)
    return json.dumps({"symbol": symbol, "spread_pct": spread, "liquidity_ok": spread < 0.15})

KITE_TOOLS = [get_quotes, get_candles, get_vwap, get_volume_ratio, get_nifty_data, get_spread]
