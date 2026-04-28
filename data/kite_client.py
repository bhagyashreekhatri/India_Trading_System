"""
Kite Connect wrapper.
Handles: live quotes, historical OHLCV, VWAP calculation, order placement (paper).
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dt_time
from typing import Optional
from zoneinfo import ZoneInfo
from kiteconnect import KiteConnect

from config.settings import (
    KITE_API_KEY, KITE_ACCESS_TOKEN, PAPER_TRADING, TIMEZONE
)
from config.universe import FULL_UNIVERSE, INDEX_INSTRUMENTS

IST = ZoneInfo(TIMEZONE)   # Asia/Kolkata — server is UTC, Kite needs IST


class KiteDataClient:

    EXCHANGE = "NSE"
    INDEX_EXCHANGE = "NSE"

    def __init__(self):
        self.kite = KiteConnect(api_key=KITE_API_KEY)
        self.kite.set_access_token(KITE_ACCESS_TOKEN)
        self._instrument_cache: dict = {}
        self._load_instruments()

    def _load_instruments(self):
        """Cache instrument tokens for quick lookup."""
        try:
            instruments = self.kite.instruments("NSE")
            for inst in instruments:
                self._instrument_cache[inst["tradingsymbol"]] = inst["instrument_token"]
            print(f"[Kite] Loaded {len(self._instrument_cache)} instruments")
        except Exception as e:
            print(f"[Kite] Warning: could not load instruments: {e}")

    def get_token(self, symbol: str) -> Optional[int]:
        return self._instrument_cache.get(symbol)

    # ── Live quotes ───────────────────────────────────────────────────────────

    def get_quotes(self, symbols: list[str]) -> dict:
        """
        Batch quote fetch.
        Returns dict: symbol → {last_price, volume, open, high, low, close, change_pct}
        """
        instrument_keys = [f"{self.EXCHANGE}:{s}" for s in symbols]
        try:
            raw = self.kite.quote(instrument_keys)
            result = {}
            for symbol in symbols:
                key = f"{self.EXCHANGE}:{symbol}"
                if key in raw:
                    q = raw[key]
                    ohlc = q.get("ohlc", {})
                    last = q.get("last_price", 0)
                    close_prev = ohlc.get("close", last)
                    change_pct = ((last - close_prev) / close_prev * 100) if close_prev else 0
                    result[symbol] = {
                        "last_price":  last,
                        "volume":      q.get("volume", 0),
                        "open":        ohlc.get("open", 0),
                        "high":        ohlc.get("high", 0),
                        "low":         ohlc.get("low", 0),
                        "close":       close_prev,
                        "change_pct":  round(change_pct, 3),
                        "bid":         q.get("depth", {}).get("buy", [{}])[0].get("price", 0),
                        "ask":         q.get("depth", {}).get("sell", [{}])[0].get("price", 0),
                    }
            return result
        except Exception as e:
            print(f"[Kite] Quote error: {e}")
            return {}

    # ── Historical candles ─────────────────────────────────────────────────────

    def get_candles(
        self,
        symbol:   str,
        interval: str = "5minute",
        days:     int = 1,
        retries:  int = 3,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles with auto-retry on transient Kite API errors.
        Returns DataFrame with columns: date, open, high, low, close, volume.
        Retries up to 3 times with 1s delay — handles 'kt-common' API blips.
        """
        import time as _time

        token = self.get_token(symbol)
        if not token:
            return None

        # Use IST — server is UTC, naive datetime.now() would give wrong date range
        to_date   = datetime.now(IST).replace(tzinfo=None)
        from_date = to_date - timedelta(days=days)

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                data = self.kite.historical_data(
                    instrument_token=token,
                    from_date=from_date,
                    to_date=to_date,
                    interval=interval,
                )
                if not data:
                    return None
                df = pd.DataFrame(data)
                df.columns = ["date", "open", "high", "low", "close", "volume"]
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df
            except Exception as e:
                last_error = e
                if attempt < retries:
                    _time.sleep(1.0 * attempt)   # 1s, 2s backoff
                    continue

        print(f"[Kite] Historical data failed for {symbol} after {retries} attempts: {last_error}")
        return None

    # ── VWAP calculation ──────────────────────────────────────────────────────

    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """
        Standard VWAP: cumulative (typical_price × volume) / cumulative volume.
        Resets each day automatically since we pass intraday data.
        """
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        tp_vol        = typical_price * df["volume"]
        vwap          = tp_vol.cumsum() / df["volume"].cumsum()
        return vwap

    def get_vwap(self, symbol: str) -> Optional[float]:
        """Current VWAP for a symbol."""
        df = self.get_candles(symbol, interval="5minute", days=1)
        if df is None or df.empty:
            return None
        vwap_series = self.calculate_vwap(df)
        return round(vwap_series.iloc[-1], 2)

    def get_vwap_with_candles(self, symbol: str) -> tuple[Optional[pd.DataFrame], Optional[float]]:
        """Returns (df_with_vwap_column, current_vwap)."""
        df = self.get_candles(symbol, interval="5minute", days=1)
        if df is None or df.empty:
            return None, None
        df["vwap"] = self.calculate_vwap(df)
        return df, round(df["vwap"].iloc[-1], 2)

    # ── Volume analysis ───────────────────────────────────────────────────────

    def get_avg_volume(self, symbol: str, periods: int = 20) -> Optional[float]:
        """20-period average volume from 5-min candles."""
        df = self.get_candles(symbol, interval="5minute", days=3)
        if df is None or len(df) < periods:
            return None
        return df["volume"].tail(periods).mean()

    def get_volume_ratio(self, symbol: str) -> Optional[float]:
        """
        Last COMPLETED candle volume / 20-period average.

        Uses iloc[-2] (last fully closed 5-min candle), NOT iloc[-1].
        Kite always appends the currently-forming candle as the last row.
        At 10:45:34 IST the 10:45–10:50 candle has only 34s of volume
        out of 300s — giving ratio 0.01–0.15 even on active stocks.
        iloc[-2] is the last candle that closed with its full volume.
        """
        df = self.get_candles(symbol, interval="5minute", days=3)
        if df is None or len(df) < 22:   # 20 avg + 1 complete + 1 forming
            return None
        avg     = df["volume"].iloc[-22:-2].mean()   # 20 completed candles
        current = df["volume"].iloc[-2]               # last completed candle
        return round(current / avg, 2) if avg > 0 else None

    # ── Bid-ask spread ────────────────────────────────────────────────────────

    def get_spread_pct(self, symbol: str) -> float:
        """Bid-ask spread as % of mid price."""
        quotes = self.get_quotes([symbol])
        if symbol not in quotes:
            return 999.0
        q   = quotes[symbol]
        bid = q.get("bid", 0)
        ask = q.get("ask", 0)
        if bid <= 0 or ask <= 0:
            return 999.0
        mid = (bid + ask) / 2
        return round((ask - bid) / mid * 100, 4)

    # ── Index data ────────────────────────────────────────────────────────────

    def get_nifty_data(self) -> dict:
        """Nifty 50 live quote and VWAP."""
        quotes = self.get_quotes(["NIFTY 50"])
        vwap   = self.get_vwap("NIFTY 50")
        q      = quotes.get("NIFTY 50", {})
        return {
            "last_price": q.get("last_price", 0),
            "change_pct": q.get("change_pct", 0),
            "vwap":       vwap,
            "above_vwap": (q.get("last_price", 0) > vwap) if vwap else False,
        }

    def get_banknifty_data(self) -> dict:
        quotes = self.get_quotes(["NIFTY BANK"])
        vwap   = self.get_vwap("NIFTY BANK")
        q      = quotes.get("NIFTY BANK", {})
        return {
            "last_price": q.get("last_price", 0),
            "change_pct": q.get("change_pct", 0),
            "vwap":       vwap,
            "above_vwap": (q.get("last_price", 0) > vwap) if vwap else False,
        }

    # ── Order placement (paper only for now) ─────────────────────────────────

    def place_order(
        self,
        symbol:        str,
        transaction:   str,   # "BUY" or "SELL"
        quantity:      int,
        order_type:    str = "MARKET",
        price:         float = 0,
    ) -> Optional[str]:
        if PAPER_TRADING:
            order_id = f"PAPER_{symbol}_{datetime.now().strftime('%H%M%S')}"
            print(f"[Kite PAPER] {transaction} {quantity} {symbol} @ {'MARKET' if not price else price} → {order_id}")
            return order_id

        try:
            order_id = self.kite.place_order(
                variety=KiteConnect.VARIETY_REGULAR,
                exchange=self.EXCHANGE,
                tradingsymbol=symbol,
                transaction_type=transaction,
                quantity=quantity,
                order_type=order_type,
                product=KiteConnect.PRODUCT_MIS,   # intraday
                price=price if order_type == "LIMIT" else None,
            )
            print(f"[Kite LIVE] {transaction} {quantity} {symbol} → order_id={order_id}")
            return str(order_id)
        except Exception as e:
            print(f"[Kite] Order error: {e}")
            return None

    def cancel_order(self, order_id: Optional[str]) -> bool:
        """
        Cancel a pending order (used to replace SL-M when stop is updated).
        Paper: no-op (returns True). Live: calls Kite REGULAR cancel.
        """
        if not order_id:
            return False
        if PAPER_TRADING or order_id.startswith("PAPER_"):
            print(f"[Kite PAPER] cancel {order_id}")
            return True
        try:
            self.kite.cancel_order(
                variety=KiteConnect.VARIETY_REGULAR,
                order_id=order_id,
            )
            print(f"[Kite LIVE] cancelled {order_id}")
            return True
        except Exception as e:
            # Most common cause: order already filled (broker stop fired).
            # Caller treats this as benign and reconciles via position state.
            print(f"[Kite] cancel failed for {order_id} (may already be filled): {e}")
            return False

    def place_sl_order(
        self,
        symbol:     str,
        transaction: str,
        quantity:   int,
        trigger:    float,
        price:      float,
    ) -> Optional[str]:
        """Place SL-M order."""
        if PAPER_TRADING:
            order_id = f"PAPER_SL_{symbol}_{datetime.now().strftime('%H%M%S')}"
            print(f"[Kite PAPER] SL {transaction} {quantity} {symbol} trigger={trigger} → {order_id}")
            return order_id
        try:
            order_id = self.kite.place_order(
                variety=KiteConnect.VARIETY_REGULAR,
                exchange=self.EXCHANGE,
                tradingsymbol=symbol,
                transaction_type=transaction,
                quantity=quantity,
                order_type=KiteConnect.ORDER_TYPE_SLM,
                product=KiteConnect.PRODUCT_MIS,
                trigger_price=trigger,
                price=price,
            )
            return str(order_id)
        except Exception as e:
            print(f"[Kite] SL order error: {e}")
            return None
