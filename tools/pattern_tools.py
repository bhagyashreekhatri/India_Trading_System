"""
Pattern Detection Tools — pure Python, zero LLM calls.
Detects 7 intraday setups:
  1. Momentum Breakout
  2. VWAP Pullback
  3. VWAP Reclaim
  4. Recovery Setup
  5. Range Breakout
  6. ORB (Opening Range Breakout — 15-min)   ← NEW
  7. Failed Breakdown                          ← NEW
Plus gap analysis at open.
"""
import json
import pandas as pd
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from langchain.tools import tool

from data.kite_client import KiteDataClient
from scoring.engine import (
    SetupType, SignalDirection,
    _round_to_tick, _round_down_tick, _round_up_tick,
)
from config.universe import get_sector
from config.settings import (
    ORB_MINUTES, ORB_MIN_RANGE_PCT, ORB_MAX_RANGE_PCT,
    TARGET_R1, TARGET_R2, TIMEZONE, TICK_SIZE,
)

IST = ZoneInfo(TIMEZONE)

# ─── Singleton Kite client ────────────────────────────────────────────────────
_kite: KiteDataClient = None

def _get_kite() -> KiteDataClient:
    global _kite
    if _kite is None:
        _kite = KiteDataClient()
    return _kite


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _candle_quality(c: dict) -> tuple[float, float]:
    """Returns (body_ratio, close_position) for a candle dict."""
    rng = c["high"] - c["low"]
    if rng == 0:
        return 0.0, 0.5
    body = abs(c["close"] - c["open"]) / rng
    close_pos = (c["close"] - c["low"]) / rng
    return round(body, 3), round(close_pos, 3)


def _atr(df: pd.DataFrame, periods: int = 10) -> float:
    """Average True Range over last N periods."""
    df_tail = df.tail(periods + 1)
    high = df_tail["high"]
    low  = df_tail["low"]
    prev_close = df_tail["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.iloc[1:].mean())   # skip first NaN row


def _calc_tp(entry: float, sl: float, r: float) -> float:
    """entry + (entry - sl) * R, rounded UP to a valid NSE tick (Fix #7)."""
    return _round_up_tick(entry + (entry - sl) * r, TICK_SIZE)


def _sl_from_atr(entry: float, atr: float, min_pct: float = 0.007) -> float:
    """SL = entry - max(ATR×0.8, entry×min_pct), rounded DOWN to a tick.
    Rounding down for LONG stops gives the stop slightly more breathing
    room — never tighter than intended (Fix #7)."""
    dist = max(atr * 0.8, entry * min_pct)
    return _round_down_tick(entry - dist, TICK_SIZE)


def _make_signal(
    symbol:     str,
    setup_type: str,
    direction:  str,
    entry:      float,
    sl:         float,
    atr:        float,
    current:    float,
    body_ratio: float,
    close_pos:  float,
    reason:     str,
) -> dict:
    # Tick-align all four prices (Fix #7).
    # Entry: nearest tick (we want to fill at signal level).
    # SL: rounded DOWN for longs to give breathing room (never tighter).
    # TP1/TP2: derived from tick-aligned entry+sl, then up-rounded by _calc_tp.
    entry_t = _round_to_tick(entry, TICK_SIZE)
    sl_t    = _round_down_tick(sl, TICK_SIZE)
    tp1     = _calc_tp(entry_t, sl_t, TARGET_R1)
    tp2     = _calc_tp(entry_t, sl_t, TARGET_R2)
    return {
        "symbol":           symbol,
        "setup_type":       setup_type,
        "direction":        direction,
        "entry_price":      entry_t,
        "stop_loss":        sl_t,
        "tp1_price":        tp1,
        "tp2_price":        tp2,
        "target_price":     tp2,
        "current_price":    current,
        "candle_body_ratio": body_ratio,
        "close_position":   close_pos,
        "candle_quality":   round((body_ratio + close_pos) / 2, 3),
        "sector":           get_sector(symbol),
        "reason":           reason,
        "atr":              round(atr, 2),
    }


# ─── ORB (Opening Range Breakout) ─────────────────────────────────────────────

def _get_orb_levels(symbol: str) -> dict | None:
    """
    Fetch 1-min candles for the first ORB_MINUTES of the session (9:15–9:30).
    Returns {"orb_high": x, "orb_low": x, "range_pct": x} or None if no data.
    """
    try:
        kite = _get_kite()
        df_1min = kite.get_candles(symbol, interval="minute", days=1)
        if df_1min is None or df_1min.empty:
            return None

        # filter to 9:15–9:30
        df_1min["dt"] = pd.to_datetime(df_1min.index if df_1min.index.name == "date"
                                       else df_1min.get("date", df_1min.index))
        open_time  = dtime(9, 15)
        close_time = dtime(9, 15 + ORB_MINUTES)  # 9:30 for 15-min ORB

        orb_candles = df_1min[
            df_1min["dt"].apply(lambda x: open_time <= x.time() < close_time)
        ]
        if orb_candles.empty:
            return None

        orb_high  = float(orb_candles["high"].max())
        orb_low   = float(orb_candles["low"].min())
        range_pct = (orb_high - orb_low) / orb_low * 100

        return {
            "orb_high":  round(orb_high, 2),
            "orb_low":   round(orb_low, 2),
            "range_pct": round(range_pct, 3),
        }
    except Exception:
        return None


def _detect_orb_breakout(
    symbol:  str,
    df:      pd.DataFrame,
    current: float,
    atr:     float,
) -> dict | None:
    """
    Detect ORB breakout AFTER 9:30 IST.
    Bullish: last close > orb_high with body near top.
    Returns signal dict or None.
    """
    now_ist = datetime.now(IST).time()
    # ORB breakout only valid 9:30 onwards
    if now_ist < dtime(9, 30):
        return None

    orb = _get_orb_levels(symbol)
    if not orb:
        return None

    range_pct = orb["range_pct"]
    # Skip if range too tight or too wild
    if range_pct < ORB_MIN_RANGE_PCT or range_pct > ORB_MAX_RANGE_PCT:
        return None

    last = df.iloc[-1]
    br, cp = _candle_quality(last.to_dict())

    # Bullish ORB breakout
    if (last["close"] > orb["orb_high"]
            and last["close"] > last["open"]
            and br >= 0.4
            and cp >= 0.55):
        entry = round(orb["orb_high"] * 1.0005, 2)   # small buffer above ORB high
        sl    = round(orb["orb_low"], 2)              # SL = ORB low
        reason = (
            f"ORB Breakout: {ORB_MINUTES}-min range ₹{orb['orb_low']:.2f}–"
            f"₹{orb['orb_high']:.2f} ({range_pct:.2f}%). "
            f"Close {last['close']:.2f} > ORB high"
        )
        return _make_signal(symbol, SetupType.MOMENTUM_BREAKOUT, "long",
                            entry, sl, atr, current, br, cp, reason)
    return None


# ─── Failed Breakdown ─────────────────────────────────────────────────────────

def _detect_failed_breakdown(
    df:      pd.DataFrame,
    vwap:    float,
    current: float,
    symbol:  str,
    atr:     float,
) -> dict | None:
    """
    Failed Breakdown: price pierced below a key support (prior session low, or
    range low) but closed back above it — trapping shorts.
    Pattern: prev candle low < support, current close > support, bullish body.
    Support proxy: VWAP or the 8-candle range low.
    """
    if df is None or len(df) < 5:
        return None

    last   = df.iloc[-1]
    prev   = df.iloc[-2]
    br, cp = _candle_quality(last.to_dict())

    # Use range low of the last 8 candles (excluding current) as support
    support = float(df.iloc[-9:-1]["low"].min()) if len(df) >= 9 else vwap

    # Key conditions:
    # 1. Previous candle (or current candle's wick) dipped below support
    # 2. Current close is back ABOVE support (failed the breakdown)
    # 3. Bullish close with reasonable body
    dipped_below = (prev["low"] < support * 1.001) or (last["low"] < support * 1.001)
    closed_above = last["close"] > support

    if (dipped_below
            and closed_above
            and last["close"] > last["open"]
            and br >= 0.45
            and cp >= 0.5):
        # SL = below the failed breakdown wick
        sl  = round(min(prev["low"], last["low"]) * 0.998, 2)
        reason = (
            f"Failed Breakdown: price dipped to {min(prev['low'], last['low']):.2f} "
            f"below support {support:.2f}, recovered to {last['close']:.2f}. "
            f"Shorts trapped — bullish reversal"
        )
        return _make_signal(symbol, SetupType.FAILED_BREAKDOWN, "long",
                            round(last["close"], 2), sl, atr,
                            current, br, cp, reason)
    return None


# ─── Gap Analysis ─────────────────────────────────────────────────────────────

def _gap_analysis(symbol: str) -> dict:
    """
    Compare today's open vs yesterday's close.
    Returns gap_pct, gap_type, tradeable (bool), and a plain reason string.
    """
    try:
        kite = _get_kite()
        df   = kite.get_candles(symbol, interval="day", days=3)
        if df is None or len(df) < 2:
            return {"symbol": symbol, "gap_pct": 0.0, "gap_type": "none",
                    "tradeable": False, "reason": "Not enough history"}

        # Today's open — last row; yesterday's close — second to last
        today_open     = float(df.iloc[-1]["open"])
        yesterday_close = float(df.iloc[-2]["close"])
        gap_pct = (today_open - yesterday_close) / yesterday_close * 100

        if gap_pct > 1.5:
            gap_type = "gap_up"
            tradeable = gap_pct < 5.0   # too big a gap = skip (earnings, news)
            reason = f"Gap UP {gap_pct:.2f}% from ₹{yesterday_close:.2f} to open ₹{today_open:.2f}"
        elif gap_pct < -1.5:
            gap_type = "gap_down"
            tradeable = gap_pct > -5.0
            reason = f"Gap DOWN {gap_pct:.2f}% from ₹{yesterday_close:.2f} to open ₹{today_open:.2f}"
        elif abs(gap_pct) < 0.3:
            gap_type = "flat"
            tradeable = True
            reason = f"Flat open (gap {gap_pct:.2f}%), prior close ₹{yesterday_close:.2f}"
        else:
            gap_type = "minor"
            tradeable = True
            reason = f"Minor gap {gap_pct:.2f}% from ₹{yesterday_close:.2f}"

        return {
            "symbol":         symbol,
            "today_open":     round(today_open, 2),
            "yesterday_close": round(yesterday_close, 2),
            "gap_pct":        round(gap_pct, 3),
            "gap_type":       gap_type,
            "tradeable":      tradeable,
            "reason":         reason,
        }
    except Exception as e:
        return {"symbol": symbol, "gap_pct": 0.0, "gap_type": "none",
                "tradeable": False, "reason": str(e)}


# ─── Main setup detector ──────────────────────────────────────────────────────

def _detect_setups_multi(
    df:      pd.DataFrame,
    vwap:    float,
    current: float,
    symbol:  str,
) -> list[dict]:
    """
    Detect ALL setups that fire for the given bar — not just the first match.
    Order in the returned list is priority-descending; same as the legacy
    `_detect_all_setups` priority chain. The crew picks element [0] as the
    primary signal and uses len(list) for confluence scoring.

    Returns list of signal dicts; empty list if no setup detected.
    """
    matches: list[dict] = []

    if df is None or len(df) < 8 or vwap is None:
        return matches

    last = df.iloc[-1]
    prev = df.iloc[-2]
    br, cp = _candle_quality(last.to_dict())
    atr = _atr(df)

    # ── 1. ORB breakout ──────────────────────────────────────────────────────
    orb = _detect_orb_breakout(symbol, df, current, atr)
    if orb:
        matches.append(orb)

    # ── 2. Failed Breakdown ──────────────────────────────────────────────────
    fb = _detect_failed_breakdown(df, vwap, current, symbol, atr)
    if fb:
        matches.append(fb)

    # ── 3. Recovery setup ────────────────────────────────────────────────────
    below = sum(1 for i in range(-6, -2) if df.iloc[i]["close"] < vwap)
    if (below >= 3
            and last["close"] > vwap
            and last["close"] > last["open"]
            and br >= 0.5):
        sl = _sl_from_atr(last["close"], atr)
        matches.append(_make_signal(symbol, SetupType.RECOVERY_SETUP, "long",
                            round(last["close"], 2), sl, atr, current, br, cp,
                            f"Recovery: was below VWAP {below} candles, now reclaiming {vwap:.2f}"))

    # ── 4. VWAP Reclaim ──────────────────────────────────────────────────────
    if (prev["close"] < vwap
            and last["close"] > vwap
            and last["close"] > last["open"]
            and br >= 0.45):
        entry = round(vwap * 1.001, 2)
        sl    = _sl_from_atr(entry, atr)
        matches.append(_make_signal(symbol, SetupType.VWAP_RECLAIM, "long",
                            entry, sl, atr, current, br, cp,
                            f"VWAP reclaim at {vwap:.2f}"))

    # ── 5. VWAP Pullback ─────────────────────────────────────────────────────
    above = sum(1 for i in range(-6, -2) if df.iloc[i]["close"] > vwap)
    if (above >= 3
            and prev["low"] <= vwap * 1.002
            and last["close"] > vwap
            and br >= 0.4):
        sl = _sl_from_atr(round(last["close"], 2), atr)
        matches.append(_make_signal(symbol, SetupType.VWAP_PULLBACK, "long",
                            round(last["close"], 2), sl, atr, current, br, cp,
                            f"VWAP pullback reclaim after {above} candles above VWAP"))

    # ── 6. Momentum Breakout ─────────────────────────────────────────────────
    recent_high = float(df["high"].iloc[-7:-1].max())
    if (last["close"] > recent_high
            and last["close"] > vwap
            and br >= 0.4
            and cp >= 0.6):
        sl = _sl_from_atr(round(last["close"], 2), atr)
        matches.append(_make_signal(symbol, SetupType.MOMENTUM_BREAKOUT, "long",
                            round(last["close"], 2), sl, atr, current, br, cp,
                            f"Momentum breakout above recent high {recent_high:.2f} and VWAP"))

    # ── 7. Range Breakout ────────────────────────────────────────────────────
    rc      = df.iloc[-9:-1]
    rng_h   = float(rc["high"].max())
    rng_l   = float(rc["low"].min())
    rng_pct = (rng_h - rng_l) / rng_l * 100 if rng_l > 0 else 99.0
    if (rng_pct < 2.0
            and last["close"] > rng_h
            and last["close"] > vwap
            and br >= 0.4):
        sl = _sl_from_atr(round(last["close"], 2), atr)
        matches.append(_make_signal(symbol, SetupType.RANGE_BREAKOUT, "long",
                            round(last["close"], 2), sl, atr, current, br, cp,
                            f"Range breakout: {rng_pct:.2f}% tight range, broke {rng_h:.2f}"))

    # Tag confluence count on every match — the primary (matches[0]) is what
    # the scorer entries on; confluence is a multiplier applied to its score.
    n = len(matches)
    for m in matches:
        m["confluence_count"] = n
        m["confluence_setups"] = [x.get("setup_type", "") for x in matches]
    return matches


def _detect_all_setups(
    df:      pd.DataFrame,
    vwap:    float,
    current: float,
    symbol:  str,
) -> dict | None:
    """
    Backward-compatible wrapper: returns the first (highest-priority) match,
    or None if nothing fires. The new multi-detect API is _detect_setups_multi.
    """
    matches = _detect_setups_multi(df, vwap, current, symbol)
    return matches[0] if matches else None


# ─── LangChain Tools ──────────────────────────────────────────────────────────

@tool("Detect intraday setup for one NSE stock")
def detect_setup(symbol: str) -> str:
    """
    Scan one NSE stock for the best intraday setup.
    Returns JSON with setup_type, entry, SL, TP1, TP2, reason or null.
    """
    try:
        kite    = _get_kite()
        df, vwap = kite.get_vwap_with_candles(symbol)
        curr    = kite.get_quotes([symbol]).get(symbol, {}).get("last_price", 0.0)
        result  = _detect_all_setups(df, vwap, curr, symbol)
        return json.dumps(
            result or {"symbol": symbol, "setup_type": None, "reason": "No setup detected"},
            default=str,
        )
    except Exception as e:
        return json.dumps({"symbol": symbol, "setup_type": None, "reason": str(e)})


@tool("Scan multiple NSE stocks for setups")
def scan_all_setups(symbols: str) -> str:
    """
    Scan comma-separated NSE symbols for intraday setups.
    Returns JSON array of only the stocks with valid setups, sorted by candle quality.
    """
    results = []
    for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        try:
            kite     = _get_kite()
            df, vwap = kite.get_vwap_with_candles(sym)
            curr     = kite.get_quotes([sym]).get(sym, {}).get("last_price", 0.0)
            r        = _detect_all_setups(df, vwap, curr, sym)
            if r:
                results.append(r)
        except Exception:
            continue

    results.sort(key=lambda x: x.get("candle_quality", 0), reverse=True)
    return json.dumps(results, default=str)


@tool("Get gap analysis for an NSE stock")
def get_gap_analysis(symbol: str) -> str:
    """
    Compares today's open vs yesterday's close.
    Returns gap_pct, gap_type (gap_up/gap_down/flat/minor), tradeable bool.
    """
    return json.dumps(_gap_analysis(symbol), default=str)


@tool("Get gap analysis for multiple NSE stocks")
def batch_gap_analysis(symbols: str) -> str:
    """
    Run gap analysis for comma-separated NSE symbols.
    Returns list of gap results sorted by abs(gap_pct) descending.
    """
    results = []
    for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        try:
            results.append(_gap_analysis(sym))
        except Exception:
            continue
    results.sort(key=lambda x: abs(x.get("gap_pct", 0)), reverse=True)
    return json.dumps(results, default=str)


@tool("Get ORB levels for a stock")
def get_orb_levels(symbol: str) -> str:
    """
    Returns the Opening Range Breakout high/low/range_pct for today.
    Based on first 15 minutes (9:15–9:30 IST).
    """
    orb = _get_orb_levels(symbol)
    if not orb:
        return json.dumps({"symbol": symbol, "error": "ORB data unavailable"})
    orb["symbol"] = symbol
    orb["valid"]  = ORB_MIN_RANGE_PCT <= orb["range_pct"] <= ORB_MAX_RANGE_PCT
    return json.dumps(orb, default=str)


# ─── Exported tool list ───────────────────────────────────────────────────────

PATTERN_TOOLS = [
    detect_setup,
    scan_all_setups,
    get_gap_analysis,
    batch_gap_analysis,
    get_orb_levels,
]
