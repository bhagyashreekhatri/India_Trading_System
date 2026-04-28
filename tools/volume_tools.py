"""
Volume, Relative Strength, Market Breadth, and Sector Strength Tools.
All pure Python — zero LLM calls.

Tools:
  analyze_volume        — volume ratio + spread + liquidity for one stock
  get_relative_strength — RS delta vs Nifty for one stock
  batch_volume_rs       — volume + RS for a list of stocks
  get_market_breadth    — % of top 50 stocks above VWAP (breadth score 0-1)
  get_sector_strength   — per-sector average RS delta + breadth
  get_breadth_regime    — BULLISH/NEUTRAL/BEARISH from breadth + Nifty trend
"""
import json
from collections import defaultdict
from langchain.tools import tool

from data.kite_client import KiteDataClient
from config.universe import (
    FULL_UNIVERSE, SECTOR_MAP, get_sector, get_top_liquid_stocks,
)
from config.settings import (
    BREADTH_BULLISH, BREADTH_BEARISH, BREADTH_SAMPLE_SIZE,
    VOLUME_MIN_RATIO, VOLUME_STRONG_RATIO, VOLUME_VERY_STRONG,
    SECTOR_LEADERS,
)

# ─── Singleton Kite client ────────────────────────────────────────────────────
_kite: KiteDataClient = None

def _get_kite() -> KiteDataClient:
    global _kite
    if _kite is None:
        _kite = KiteDataClient()
    return _kite


# ─── Scoring helpers ─────────────────────────────────────────────────────────

def _vol_score(ratio: float, liq: bool) -> float:
    """Volume strength: 0–2."""
    if not liq:
        return 0.0
    if ratio >= VOLUME_VERY_STRONG:
        return 2.0
    elif ratio >= VOLUME_STRONG_RATIO:
        return round(1.0 + (ratio - VOLUME_STRONG_RATIO) / 1.0, 2)
    elif ratio >= VOLUME_MIN_RATIO:
        return 1.0
    return 0.0


def _rs_score(delta: float) -> float:
    """Relative strength score: 0–2."""
    if delta >= 1.0:    return 2.0
    elif delta >= 0.5:  return 1.5
    elif delta >= 0.0:  return 1.0
    elif delta >= -0.5: return 0.5
    return 0.0


# ─── Single-stock tools ───────────────────────────────────────────────────────

@tool("Analyze volume strength for an NSE stock")
def analyze_volume(symbol: str) -> str:
    """
    Get volume ratio, bid-ask spread, liquidity pass/fail, volume_score for one stock.
    liquidity_pass = volume_ratio >= 1.2 AND spread < 0.15%
    Returns JSON.
    """
    try:
        kite   = _get_kite()
        ratio  = kite.get_volume_ratio(symbol) or 0.0
        spread = kite.get_spread_pct(symbol)
        # spread=999.0 means Kite depth data unavailable — don't penalize that
        spread_ok = True if spread >= 999.0 else (spread < 0.5)
        liq    = (ratio >= VOLUME_MIN_RATIO) and spread_ok
        return json.dumps({
            "symbol":        symbol,
            "volume_ratio":  round(ratio, 3),
            "bid_ask_spread": round(spread, 4),
            "liquidity_pass": liq,
            "volume_score":  _vol_score(ratio, liq),
        })
    except Exception as e:
        return json.dumps({"symbol": symbol, "error": str(e), "liquidity_pass": False})


@tool("Get relative strength vs Nifty for one stock")
def get_relative_strength(symbol: str) -> str:
    """
    Compare stock % change vs Nifty % change.
    Positive rs_delta = outperforming Nifty.
    Returns JSON with rs_delta, outperforming bool, rs_score 0-2.
    """
    try:
        kite      = _get_kite()
        quotes    = kite.get_quotes([symbol])
        nifty     = kite.get_nifty_data()
        stock_chg = quotes.get(symbol, {}).get("change_pct", 0.0)
        nifty_chg = nifty.get("change_pct", 0.0)
        delta     = round(stock_chg - nifty_chg, 3)
        return json.dumps({
            "symbol":           symbol,
            "stock_change_pct": round(stock_chg, 3),
            "nifty_change_pct": round(nifty_chg, 3),
            "rs_delta":         delta,
            "outperforming":    delta > 0.5,
            "rs_score":         _rs_score(delta),
        })
    except Exception as e:
        return json.dumps({"symbol": symbol, "error": str(e), "rs_delta": 0.0})


@tool("Batch volume and RS analysis for multiple stocks")
def batch_volume_rs(symbols: str) -> str:
    """
    Analyze volume + RS for comma-separated NSE symbols.
    Returns list sorted by combined score (volume + RS) descending.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    kite = _get_kite()
    try:
        quotes    = kite.get_quotes(symbol_list)
        nifty_chg = kite.get_nifty_data().get("change_pct", 0.0)
    except Exception:
        quotes, nifty_chg = {}, 0.0

    results = []
    for sym in symbol_list:
        try:
            ratio  = kite.get_volume_ratio(sym) or 0.0
            spread = kite.get_spread_pct(sym)
            # spread=999.0 means Kite depth unavailable — don't penalize
            spread_ok = True if spread >= 999.0 else (spread < 0.5)
            liq    = (ratio >= VOLUME_MIN_RATIO) and spread_ok
            delta  = round(quotes.get(sym, {}).get("change_pct", 0.0) - nifty_chg, 3)
            results.append({
                "symbol":       sym,
                "volume_ratio": round(ratio, 3),
                "spread_pct":   round(spread, 4),
                "liquidity_pass": liq,
                "rs_delta":     delta,
                "volume_score": _vol_score(ratio, liq),
                "rs_score":     _rs_score(delta),
                "combined_score": round(_vol_score(ratio, liq) + _rs_score(delta), 2),
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["combined_score"], reverse=True)
    return json.dumps(results)


# ─── Market Breadth ───────────────────────────────────────────────────────────

def _compute_breadth(vwap_cache: dict | None = None) -> dict:
    """
    Sample BREADTH_SAMPLE_SIZE most liquid stocks.

    Fix #8 — accuracy ladder for the "above VWAP" check:
      1. If `vwap_cache` has a real VWAP for the symbol (populated by the
         setup-detection pass earlier in the same tick), compare last_price
         to that. This is the true measurement.
      2. Otherwise fall back to `last_price > today_open` — a much stronger
         proxy than the old `change_pct >= 0`. Correctly catches "gap down
         + recovery" (above own open, still negative on the day) and rejects
         "gap up + fade" (below own open, still positive on the day).
      3. Last-resort: `change_pct >= 0` if open price unavailable.
    """
    kite   = _get_kite()
    sample = get_top_liquid_stocks(BREADTH_SAMPLE_SIZE)
    try:
        quotes = kite.get_quotes(sample)   # 1 batch call — no rate limit hit
    except Exception:
        quotes = {}

    above_vwap = 0
    checked    = 0
    used_real  = 0   # how many used real VWAP vs proxy

    for sym in sample:
        q = quotes.get(sym)
        if not q:
            continue
        last  = q.get("last_price", 0)
        open_ = q.get("open", 0)

        is_above = False
        if vwap_cache and sym in vwap_cache and vwap_cache[sym] and last > 0:
            is_above = last > vwap_cache[sym]
            used_real += 1
        elif last > 0 and open_ > 0:
            # Stronger proxy: above today's own open, not yesterday's close
            is_above = last > open_
        else:
            is_above = q.get("change_pct", 0) >= 0   # last-resort

        if is_above:
            above_vwap += 1
        checked += 1

    breadth_score = round(above_vwap / checked, 3) if checked > 0 else 0.5
    breadth_pct   = round(breadth_score * 100, 1)

    if breadth_score >= BREADTH_BULLISH:
        breadth_label = "BULLISH"
    elif breadth_score <= BREADTH_BEARISH:
        breadth_label = "BEARISH"
    else:
        breadth_label = "NEUTRAL"

    return {
        "stocks_checked":    checked,
        "stocks_above_vwap": above_vwap,
        "breadth_score":     breadth_score,
        "breadth_pct":       breadth_pct,
        "breadth_label":     breadth_label,
        "used_real_vwap":    used_real,   # telemetry — how much of the sample had real VWAP
    }


@tool("Get market breadth — % of stocks above VWAP")
def get_market_breadth(query: str = "") -> str:
    """
    Samples the top 50 NSE liquid stocks and counts how many are above VWAP.
    Returns breadth_score (0–1), breadth_pct, breadth_label (BULLISH/NEUTRAL/BEARISH).
    Pass any string or empty string as argument.
    """
    try:
        result = _compute_breadth()
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"breadth_score": 0.5, "breadth_label": "NEUTRAL",
                           "error": str(e)})


# ─── Sector Strength ─────────────────────────────────────────────────────────

def _compute_sector_strength(vwap_cache: dict | None = None) -> list[dict]:
    """
    Per-sector RS + breadth.

    Fix #8: same accuracy ladder as `_compute_breadth` — real VWAP from
    setup-detection cache → fallback `last_price > today_open` → last-resort
    `change_pct >= 0`.
    """
    kite = _get_kite()

    try:
        nifty_chg = kite.get_nifty_data().get("change_pct", 0.0)
    except Exception:
        nifty_chg = 0.0

    all_leaders = list({sym for leaders in SECTOR_LEADERS.values() for sym in leaders})
    try:
        all_quotes = kite.get_quotes(all_leaders)
    except Exception:
        all_quotes = {}

    sector_results = []

    for sector, leaders in SECTOR_LEADERS.items():
        rs_deltas   = []
        above_vwap  = 0
        valid_count = 0

        for sym in leaders:
            q = all_quotes.get(sym)
            if not q:
                continue
            stock_chg = q.get("change_pct", 0.0)
            last      = q.get("last_price", 0)
            open_     = q.get("open", 0)
            delta     = round(stock_chg - nifty_chg, 3)
            rs_deltas.append(delta)

            is_above = False
            if vwap_cache and sym in vwap_cache and vwap_cache[sym] and last > 0:
                is_above = last > vwap_cache[sym]
            elif last > 0 and open_ > 0:
                is_above = last > open_
            else:
                is_above = stock_chg >= 0
            if is_above:
                above_vwap += 1
            valid_count += 1

        if valid_count == 0:
            continue

        avg_rs      = round(sum(rs_deltas) / len(rs_deltas), 3) if rs_deltas else 0.0
        breadth_pct = round(above_vwap / valid_count * 100, 1)

        # Sector score: RS contribution + breadth contribution (0–4 scale)
        sector_score = round(
            _rs_score(avg_rs) + (breadth_pct / 100) * 2.0,
            2,
        )
        sector_results.append({
            "sector":          sector,
            "avg_rs_delta":    avg_rs,
            "breadth_pct":     breadth_pct,
            "leaders_checked": valid_count,
            "sector_score":    sector_score,
            "trending":        sector_score >= 3.0,
        })

    sector_results.sort(key=lambda x: x["sector_score"], reverse=True)
    return sector_results


@tool("Get sector strength ranking for NSE sectors")
def get_sector_strength(query: str = "") -> str:
    """
    Ranks NSE sectors by average RS delta and % leaders above VWAP.
    Returns list sorted from strongest to weakest sector.
    Pass any string or empty string as argument.
    """
    try:
        results = _compute_sector_strength()
        return json.dumps(results)
    except Exception as e:
        return json.dumps({"error": str(e), "results": []})


@tool("Get breadth regime label for market condition")
def get_breadth_regime(query: str = "") -> str:
    """
    Combines market breadth and Nifty trend to give a regime label:
    BULLISH_BREADTH / NEUTRAL_BREADTH / BEARISH_BREADTH
    Also returns top 3 and bottom 3 sectors.
    Pass any string or empty string as argument.
    """
    try:
        kite = _get_kite()

        breadth = _compute_breadth()
        sectors = _compute_sector_strength()

        nifty_data = kite.get_nifty_data()
        nifty_above_vwap = nifty_data.get("above_vwap", False)

        top3    = [s["sector"] for s in sectors[:3]]
        bottom3 = [s["sector"] for s in sectors[-3:]]

        # Final breadth regime
        bs = breadth["breadth_score"]
        if bs >= BREADTH_BULLISH and nifty_above_vwap:
            regime = "BULLISH_BREADTH"
        elif bs <= BREADTH_BEARISH or not nifty_above_vwap:
            regime = "BEARISH_BREADTH"
        else:
            regime = "NEUTRAL_BREADTH"

        return json.dumps({
            "breadth_score":     breadth["breadth_score"],
            "breadth_pct":       breadth["breadth_pct"],
            "breadth_label":     breadth["breadth_label"],
            "nifty_above_vwap":  nifty_above_vwap,
            "breadth_regime":    regime,
            "top_sectors":       top3,
            "weak_sectors":      bottom3,
            "all_sectors":       sectors,
        })
    except Exception as e:
        return json.dumps({"breadth_regime": "NEUTRAL_BREADTH", "error": str(e)})


# ─── Exported tool list ───────────────────────────────────────────────────────

VOLUME_TOOLS = [
    analyze_volume,
    get_relative_strength,
    batch_volume_rs,
    get_market_breadth,
    get_sector_strength,
    get_breadth_regime,
]
