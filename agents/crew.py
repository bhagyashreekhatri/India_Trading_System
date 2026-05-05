"""
TradingCrew — pure Python orchestrator.
No CrewAI, no LLM except Groq for news sentiment only.

Architecture (8 logical agents):
  1. MarketScanner      — filters 150 stocks to active candidates
  2. RegimeDetector     — TRENDING/CHOPPY/RECOVERING/EVENT
  3. BreadthAnalyzer    — market breadth + sector strength
  4. SetupDetector      — 7 setup types (ORB, VWAP, breakout, etc.)
  5. VolumeRSAnalyzer   — volume + relative strength confirmation
  6. NewsSentimentAgent — NewsAPI + Groq LLM (only LLM call)
  7. ScoringAgent       — ScoringEngine → grade + score
  8. PositionManager    — TP1/TP2/trailing SL/EOD exits + Telegram

Run: TradingCrew().run_tick()
"""
import json
from math import floor
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

STATUS_FILE = Path("./system_status.json")

from data.kite_client import KiteDataClient
from data.news_client import NewsClient
from memory.trade_state import TradeStateManager, WatchlistItem
from memory.chroma_client import ChromaMemory

from scoring.engine import (
    ScoringEngine, RawSignal, VolumeData, MarketContext,
    RelativeStrengthData, NewsData,
    SetupType, RegimeType, SignalDirection,
    _round_to_tick, _round_down_tick, _round_up_tick,
)

from tools.pattern_tools import _detect_setups_multi
from tools.volume_tools   import _compute_breadth, _compute_sector_strength
from tools.telegram_tools import (
    alert_trade_entry, alert_tp1_hit, alert_trade_exit,
    alert_trailing_sl_moved, alert_consecutive_losses,
    alert_market_breadth, alert_eod_report, alert_system_start,
)

from config.universe import FULL_UNIVERSE, get_sector
from config.settings import (
    CAPITAL, RISK_PER_TRADE_PCT, MAX_POSITIONS, MAX_SAME_SECTOR_POSITIONS,
    MAX_CONSECUTIVE_LOSSES, CONSERVATIVE_SIZE_PCT, MAX_POSITION_VALUE_PCT,
    TARGET_R1, TARGET_R2, TIMEZONE,
    TRAILING_SL_ENABLED, TRAILING_ATR_MULTIPLIER,
    BREADTH_BULLISH, BREADTH_BEARISH, MOMENTUM_BO_MIN_RVOL, SCORE_SIZE_TIERS,
    HOUR_GATE_NUDGES,
    MIN_SCORE_ENTRY, MIN_SCORE_ENTRY_CONSERVATIVE, MIN_SCORE_WATCHLIST,
    NO_ENTRY_BEFORE_MIN, NO_NEW_ENTRY_AFTER, EOD_CLOSE_TIME,
    MIDDAY_AVOID_START, MIDDAY_AVOID_END,
    PROXIMITY_MAX_PCT, LEADER_PROXIMITY_MAX_PCT, LEADER_DAY_CHG_PCT, LEADER_RS_DELTA_PCT,
    DAILY_LOSS_KILL_PCT,
    CONFLUENCE_MULTIPLIER_2, CONFLUENCE_MULTIPLIER_3, SCAN_MIN_TURNOVER,
    TICK_SIZE,
    MIN_RISK_PER_TRADE_PCT, MIN_POSITION_VALUE_PCT,
    DAILY_PROFIT_LOCKOUT_PCT, DAILY_PROFIT_TIGHTEN_PCT,
    PAPER_TRADING, PAPER_SLIPPAGE_ENTRY_BPS, PAPER_SLIPPAGE_STOP_BPS,
    PAPER_SLIPPAGE_TARGET_BPS,
)

IST = ZoneInfo(TIMEZONE)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_ist() -> datetime:
    return datetime.now(IST)


def _entry_dt_aware(entry_time: str) -> datetime:
    """
    Convert a stored entry_time ISO string into a TZ-aware IST datetime.

    Why this exists: state.open_position() historically wrote
    datetime.now().isoformat() with no tzinfo. The wall-clock value depends on
    the host TZ — UTC on a default DigitalOcean droplet, IST on a Mac. Earlier
    code did `entry_dt.replace(tzinfo=IST)` which silently mislabels UTC values
    as IST, adding 5h30 to apparent age and tripping the 45-min stall threshold
    on the first tick.

    Handles both legacy naive ISO and new aware ISO transparently:
      - aware  → just astimezone(IST)
      - naive  → attach host's local tz (from time.localtime), then convert
    """
    import time as _t
    from datetime import timezone, timedelta
    parsed = datetime.fromisoformat(entry_time)
    if parsed.tzinfo is not None:
        return parsed.astimezone(IST)
    host_offset_sec = _t.localtime().tm_gmtoff
    host_tz = timezone(timedelta(seconds=host_offset_sec))
    return parsed.replace(tzinfo=host_tz).astimezone(IST)


def _parse_time(t: str) -> dtime:
    """'HH:MM' → time object."""
    h, m = t.split(":")
    return dtime(int(h), int(m))


def _calc_tp(entry: float, sl: float, r: float) -> float:
    """entry + (entry - sl) * R, tick-aligned (Fix #7)."""
    return _round_up_tick(entry + (entry - sl) * r, TICK_SIZE)


def _apply_paper_slippage(price: float, side: str, kind: str) -> float:
    """
    Worsen a paper fill price to simulate real broker execution (Fix #16).
      side: 'buy' = entry-LONG / exit-SHORT  → fill HIGHER than LTP (worse for buyer)
            'sell'= entry-SHORT / exit-LONG → fill LOWER than LTP (worse for seller)
      kind: 'entry' / 'stop' / 'target' picks the bps from settings.
    No-op in live mode (real broker → real slippage).
    """
    if not PAPER_TRADING or price <= 0:
        return price
    if kind == "stop":
        bps = PAPER_SLIPPAGE_STOP_BPS
    elif kind == "target":
        bps = PAPER_SLIPPAGE_TARGET_BPS
    else:
        bps = PAPER_SLIPPAGE_ENTRY_BPS
    factor = (1 + bps / 10000.0) if side == "buy" else (1 - bps / 10000.0)
    return _round_to_tick(price * factor, TICK_SIZE)


def _calc_atr_from_df(df) -> float:
    """Quick ATR from a DataFrame tail."""
    import pandas as pd
    df_t = df.tail(11)
    high, low, prev_c = df_t["high"], df_t["low"], df_t["close"].shift(1)
    tr = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return float(tr.iloc[1:].mean())


def _parse_json(text) -> dict | list:
    """Best-effort JSON parse — handles wrapped strings."""
    if isinstance(text, (dict, list)):
        return text
    text = str(text).strip()
    for s, e in [("[", "]"), ("{", "}")]:
        i, j = text.find(s), text.rfind(e)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    return {}


# ─── TradingCrew ──────────────────────────────────────────────────────────────

class TradingCrew:
    """
    Main trading loop. Call run_tick() every SCAN_INTERVAL_MIN minutes.
    Manages full lifecycle: scan → regime → breadth → setups → score → enter → manage.
    """

    def __init__(self):
        self.kite    = KiteDataClient()
        self.news    = NewsClient()
        self.state   = TradeStateManager()
        self.chroma  = ChromaMemory()
        self.engine  = ScoringEngine()
        self._tick   = 0
        self._breadth_cache: dict = {}    # refreshed every ~15 min
        self._regime_cache:  dict = {}
        self._breadth_tick   = -99
        self._regime_tick    = -99
        # Per-tick VWAP cache — populated by _detect_setups, read by
        # _detect_breadth so breadth uses real VWAP (Fix #8) instead of the
        # change_pct proxy. Cleared at the start of every tick.
        self._vwap_cache: dict[str, float] = {}
        # Clear yesterday's watchlist so dashboard shows only today's signals
        self.state.clear_old_watchlist()
        print("[Crew] Initialized — scanning 150 stocks, TP1+TP2+trailing SL active")
        alert_system_start()

    # ── Main entry point ──────────────────────────────────────────────────────

    def run_tick(self, min_score: float = None) -> dict:
        self._tick += 1
        self._vwap_cache.clear()   # Fix #8 — fresh VWAPs per tick
        now = _now_ist()
        print(f"\n{'='*60}")
        print(f"[Crew] TICK #{self._tick} — {now.strftime('%H:%M:%S IST')}")
        print(f"{'='*60}")

        # 1. Always manage open positions first (SL/TP/trailing/EOD)
        self._manage_positions()

        # 2. Time gate — no new entries in certain windows
        if not self._ok_to_trade(now):
            print(f"[Crew] Time gate: no new entries at {now.strftime('%H:%M')}")
            return self._tick_summary(0, 0, 0)

        # 3. Regime + breadth (cached, refresh every 5 ticks ~15 min)
        if self._tick - self._regime_tick >= 5:
            self._regime_cache = self._detect_regime()
            self._regime_tick  = self._tick

        if self._tick - self._breadth_tick >= 5:
            self._breadth_cache = self._detect_breadth()
            self._breadth_tick  = self._tick

        breadth_score = self._breadth_cache.get("breadth_score", 0.6)
        breadth_label = self._breadth_cache.get("breadth_label", "NEUTRAL")

        # Breadth gate — avoid new longs in bad breadth
        if breadth_score <= BREADTH_BEARISH:
            print(f"[Crew] Breadth BEARISH ({breadth_score:.0%}) — no new entries")
            return self._tick_summary(0, 0, 0)

        # 4. Scan active stocks
        active = self._scan_market()
        if not active:
            return self._tick_summary(0, 0, 0)

        # Sector rotation: promote stocks from top sectors
        top_sectors = self._breadth_cache.get("top_sectors", [])
        active = self._reorder_by_sector(active, top_sectors)

        # 5. Detect setups (parallel-friendly loop)
        setups = self._detect_setups(active)
        if not setups:
            return self._tick_summary(len(active), 0, 0)

        # 6. Score signals
        scored = self._score_signals(setups, self._regime_cache, self._breadth_cache, min_score=min_score)

        # 7. Allocate capital
        self._allocate(scored)

        return self._tick_summary(len(active), len(setups), len(scored))

    # ── Time gate ─────────────────────────────────────────────────────────────

    def _ok_to_trade(self, now: datetime) -> bool:
        t = now.time()
        market_open = dtime(9, 15 + NO_ENTRY_BEFORE_MIN)   # 9:20
        no_entry    = _parse_time(NO_NEW_ENTRY_AFTER)       # 14:45
        mid_start   = _parse_time(MIDDAY_AVOID_START)       # 13:00
        mid_end     = _parse_time(MIDDAY_AVOID_END)         # 14:00

        if t < market_open:
            return False
        if t >= no_entry:
            return False
        if mid_start <= t < mid_end:
            print(f"[Crew] Midday lull ({MIDDAY_AVOID_START}–{MIDDAY_AVOID_END}) — selective only")
            # Still allow, but min_score is raised in _score_signals
        return True

    def _is_midday(self) -> bool:
        t = _now_ist().time()
        return _parse_time(MIDDAY_AVOID_START) <= t < _parse_time(MIDDAY_AVOID_END)

    # ── Agent 1: Market Scanner ───────────────────────────────────────────────

    def _scan_market(self) -> list[str]:
        print(f"[Scanner] Scanning {len(FULL_UNIVERSE)} stocks...")
        try:
            # Batch fetch quotes for all stocks (single round-trip)
            quotes = self.kite.get_quotes(FULL_UNIVERSE)
            active = []
            for sym, q in quotes.items():
                chg   = abs(q.get("change_pct", 0))
                vol   = q.get("volume", 0)
                price = q.get("last_price", 0)
                turnover = price * vol   # ₹ traded today so far
                # Filter: meaningful move + real liquidity
                # (Fix #5: turnover-based, not raw share count — fixes the
                # bug where ₹50 stocks and ₹5,000 stocks cleared the same gate)
                if chg >= 0.3 and turnover >= SCAN_MIN_TURNOVER:
                    active.append((sym, chg, turnover))

            # Sort by absolute change, take top 60
            active.sort(key=lambda x: x[1], reverse=True)
            result = [s[0] for s in active[:60]]
            print(f"[Scanner] {len(result)} active stocks (of {len(FULL_UNIVERSE)} scanned, "
                  f"turnover floor ₹{SCAN_MIN_TURNOVER/1e5:.0f}L)")
            return result
        except Exception as e:
            print(f"[Scanner] Error: {e} — using top 30 universe")
            return FULL_UNIVERSE[:30]

    def _reorder_by_sector(self, symbols: list[str], top_sectors: list[str]) -> list[str]:
        """Promote stocks from strong sectors to front of the list."""
        if not top_sectors:
            return symbols
        priority = [s for s in symbols if get_sector(s) in top_sectors]
        rest     = [s for s in symbols if s not in priority]
        return priority + rest

    # ── Agent 2: Regime Detector ─────────────────────────────────────────────

    def _detect_regime(self) -> dict:
        print("[Regime] Detecting market regime...")
        try:
            nifty      = self.kite.get_nifty_data()
            banknifty  = self.kite.get_banknifty_data()
            n_chg      = nifty.get("change_pct", 0)
            n_above    = nifty.get("above_vwap", True)
            bn_above   = banknifty.get("above_vwap", True)

            # Regime logic
            if abs(n_chg) > 1.5:
                regime = "event"
            elif n_above and abs(n_chg) > 0.4:
                regime = "trending"
            elif not n_above:
                regime = "recovering"
            else:
                regime = "choppy"

            # Regime confidence
            confidence = 0.9 if abs(n_chg) > 0.8 else 0.7

            result = {
                "regime":               regime,
                "regime_confidence":    confidence,
                "nifty_above_vwap":     n_above,
                "banknifty_above_vwap": bn_above,
                "nifty_vwap_minutes":   20 if n_above else -20,
                "market_trend_aligned": n_above,
                "nifty_change_pct":     n_chg,
                "banknifty_change_pct": banknifty.get("change_pct", 0),
            }
            print(f"[Regime] {regime.upper()} | Nifty {n_chg:+.2f}% | above_vwap={n_above}")
            return result
        except Exception as e:
            print(f"[Regime] Error: {e} — defaulting to CHOPPY")
            return {
                "regime": "choppy", "regime_confidence": 0.5,
                "nifty_above_vwap": True, "banknifty_above_vwap": True,
                "nifty_vwap_minutes": 0, "market_trend_aligned": True,
                "nifty_change_pct": 0, "banknifty_change_pct": 0,
            }

    # ── Agent 3: Breadth Analyzer ─────────────────────────────────────────────

    def _detect_breadth(self) -> dict:
        print("[Breadth] Computing market breadth...")
        try:
            # Fix #8 — pass the per-tick VWAP cache so breadth uses real VWAP
            # for active stocks; falls back to last>open proxy otherwise.
            breadth  = _compute_breadth(vwap_cache=self._vwap_cache)
            sectors  = _compute_sector_strength(vwap_cache=self._vwap_cache)
            top3     = [s["sector"] for s in sectors[:3]]
            bottom3  = [s["sector"] for s in sectors[-3:]]

            bs = breadth["breadth_score"]
            label = breadth["breadth_label"]
            real_n = breadth.get("used_real_vwap", 0)
            print(f"[Breadth] {bs:.0%} above VWAP → {label} | Top: {top3} | "
                  f"real_vwap_hits={real_n}/{breadth.get('stocks_checked', 0)}")

            # Send Telegram alert periodically (every ~15 min via tick filter)
            alert_market_breadth(breadth["breadth_pct"], label)

            return {
                **breadth,
                "top_sectors":   top3,
                "weak_sectors":  bottom3,
                "all_sectors":   sectors,
            }
        except Exception as e:
            print(f"[Breadth] Error: {e}")
            return {
                "breadth_score": 0.6, "breadth_pct": 60.0,
                "breadth_label": "NEUTRAL",
                "top_sectors":   [], "weak_sectors": [], "all_sectors": [],
            }

    # ── Agent 4: Setup Detector ───────────────────────────────────────────────

    def _detect_setups(self, active: list[str]) -> list[dict]:
        """
        Returns the PRIMARY setup per active stock, with confluence_count and
        confluence_setups attached so the scorer can apply the multiplier.
        Multi-detect (Fix #5) — each stock now reveals all matching setups,
        not just the first hit.
        """
        print(f"[Setup] Detecting setups in {len(active)} stocks...")
        setups       = []
        no_data      = 0
        few_candles  = 0
        below_vwap_count = 0
        weak_body    = 0
        confluence_n = 0   # count of stocks where 2+ setups fired

        for sym in active:
            try:
                df, vwap = self.kite.get_vwap_with_candles(sym)
                if df is None:
                    no_data += 1
                    continue
                if len(df) < 8:
                    few_candles += 1
                    continue

                # Fix #8 — share the freshly-computed VWAP with the breadth /
                # sector functions so they don't have to re-fetch candles.
                if vwap:
                    self._vwap_cache[sym] = vwap

                quotes   = self.kite.get_quotes([sym])
                curr     = quotes.get(sym, {}).get("last_price", 0.0)

                last = df.iloc[-1]
                br   = abs(last["close"] - last["open"]) / (last["high"] - last["low"]) \
                       if (last["high"] - last["low"]) > 0 else 0
                if last["close"] < vwap:
                    below_vwap_count += 1
                if br < 0.4:
                    weak_body += 1

                matches = _detect_setups_multi(df, vwap, curr, sym)
                if matches:
                    primary = matches[0]   # priority-highest match
                    if primary.get("confluence_count", 1) >= 2:
                        confluence_n += 1
                        print(f"[Setup] ⚡ CONFLUENCE x{primary['confluence_count']} on {sym}: "
                              f"{primary['confluence_setups']}")
                    setups.append(primary)
            except Exception:
                continue

        setups.sort(key=lambda x: x.get("candle_quality", 0), reverse=True)
        print(
            f"[Setup] Found {len(setups)} setups ({confluence_n} with confluence) | "
            f"no_data={no_data} few_candles={few_candles} | "
            f"below_vwap={below_vwap_count} weak_body={weak_body} (of {len(active)})"
        )
        return setups

    # ── Agent 5+6: Volume + RS + News ────────────────────────────────────────

    def _get_volume_rs(self, sym: str, nifty_chg: float) -> tuple[float, float, float, bool]:
        """Returns (volume_ratio, spread_pct, rs_delta, liquidity_pass).

        liquidity_pass = spread is acceptable (stock is tradeable).
        Volume ratio is NOT part of liquidity_pass — it is scored separately
        via volume_strength in the engine. This means:
          - Wide spread (>0.5%) → hard reject (can't trade — entry/exit costs eat profit)
          - Low volume (ratio < 1.2) → volume_strength = 0.0 → lower score → harder to reach 7.0
          - High volume → volume_strength up to 2.0 → boosts score
        This way a perfect setup on a liquid stock is never hard-blocked just because
        the current 5-min candle hasn't printed 1.2x average volume yet.
        """
        try:
            ratio     = self.kite.get_volume_ratio(sym) or 0.0
            spread    = self.kite.get_spread_pct(sym)
            quotes    = self.kite.get_quotes([sym])
            stock_chg = quotes.get(sym, {}).get("change_pct", 0.0)
            delta     = round(stock_chg - nifty_chg, 3)

            # spread=999.0 means Kite depth data unavailable — treat as pass
            spread_ok = True if spread >= 999.0 else (spread < 0.5)

            # Liquidity = can I trade this stock (spread-based only)
            # Volume quality is captured in volume_strength via ratio
            liq = spread_ok

            print(f"[VolumeRS] {sym}: ratio={ratio:.2f} spread={'N/A' if spread >= 999.0 else f'{spread:.3f}%'} liq={liq}")
            return ratio, spread, delta, liq
        except Exception as e:
            print(f"[VolumeRS] {sym}: error — {e}")
            return 0.0, 999.0, 0.0, True   # on error, pass liquidity — don't block on missing data

    def _get_news(self, sym: str) -> tuple[bool, float, str, str]:
        """Returns (has_news, llm_score, catalyst_type, headline)."""
        try:
            nd = self.news.get_news_for_symbol(sym)
            if nd.has_news and nd.headline:
                try:
                    self.chroma.store_news(sym, nd.headline, nd.sentiment,
                                          nd.llm_score, nd.catalyst_type)
                except Exception:
                    pass
            return nd.has_news, nd.llm_score, nd.catalyst_type, nd.headline or ""
        except Exception:
            return False, 0.5, "none", ""

    # ── Agent 7: Scoring ──────────────────────────────────────────────────────

    def _score_signals(
        self,
        setups:      list[dict],
        regime_data: dict,
        breadth_data: dict,
        min_score:   float = None,
    ) -> list[dict]:
        print(f"[Scorer] Scoring {len(setups)} setups...")
        scored  = []
        regime  = regime_data.get("regime", "choppy")
        nchg    = regime_data.get("nifty_change_pct", 0.0)
        bs      = breadth_data.get("breadth_score", 0.6)

        # Base threshold: use dashboard value if provided, else midday/default logic
        if min_score is None:
            min_score = MIN_SCORE_ENTRY_CONSERVATIVE if self._is_midday() else MIN_SCORE_ENTRY
        else:
            # Midday: never go below conservative threshold even if dashboard says lower
            if self._is_midday():
                min_score = max(min_score, MIN_SCORE_ENTRY_CONSERVATIVE)

        # Also raise threshold if consecutive losses ≥ 3
        consec = self.state.get_consecutive_losses()
        if consec >= MAX_CONSECUTIVE_LOSSES:
            min_score = max(min_score, MIN_SCORE_ENTRY_CONSERVATIVE)
            print(f"[Scorer] Conservative mode — {consec} consecutive losses, threshold={min_score}")

        # ── Time-of-day nudge (Fix #24 / A5) ─────────────────────────────────
        # Adjust the gate by hour-of-day per the 151-trade analysis. 9 & 10 IST
        # raise the bar (noisy / losing); 12 IST lowers it (best hour).
        cur_hour = _now_ist().hour
        hour_nudge = HOUR_GATE_NUDGES.get(cur_hour, 0.0)
        if hour_nudge != 0.0:
            min_score = max(0.0, min_score + hour_nudge)
            print(f"[Scorer] Hour {cur_hour:02d} IST nudge {hour_nudge:+.1f} → threshold {min_score:.1f}")

        # Write effective threshold to status file so dashboard can display it
        conservative = consec >= MAX_CONSECUTIVE_LOSSES or self._is_midday()
        try:
            STATUS_FILE.write_text(json.dumps({
                "effective_threshold": round(min_score, 1),
                "conservative_mode":   conservative,
                "consecutive_losses":  consec,
                "midday_mode":         self._is_midday(),
                "regime":              regime_data.get("regime", "unknown"),
                "breadth_label":       breadth_data.get("breadth_label", "NEUTRAL"),
                "last_tick":           _now_ist().strftime("%H:%M:%S"),
            }, indent=2))
        except Exception:
            pass

        for s in setups:
            sym = s["symbol"]
            try:
                # Volume + RS
                vol_ratio, spread, rs_delta, liq = self._get_volume_rs(sym, nchg)

                # ── A1 / Fix #22 — momentum_breakout volume hard-veto ───────
                # Real breakouts come on volume. Reject momentum_breakout if
                # RVOL < 2.0 — kills the #1 fakeout class (file 04 analysis).
                if (s.get("setup_type") == "momentum_breakout"
                        and vol_ratio < MOMENTUM_BO_MIN_RVOL):
                    print(f"[Scorer] {sym} momentum_breakout RVOL={vol_ratio:.2f} "
                          f"< {MOMENTUM_BO_MIN_RVOL} — fakeout risk, skip")
                    continue

                # News (Groq LLM — this is the ONLY LLM call)
                has_news, news_score, catalyst, headline = self._get_news(sym)

                # Quotes for current price
                quotes  = self.kite.get_quotes([sym])
                stock_chg = quotes.get(sym, {}).get("change_pct", 0.0)

                # Build scoring objects
                signal = RawSignal(
                    symbol=sym,
                    setup_type=SetupType(s["setup_type"]),
                    direction=SignalDirection(s.get("direction", "long")),
                    entry_price=s["entry_price"],
                    stop_loss=s["stop_loss"],
                    target_price=s.get("tp2_price", s.get("target_price", s["entry_price"])),
                    current_price=s.get("current_price", s["entry_price"]),
                    candle_body_ratio=s.get("candle_body_ratio", 0.5),
                    close_position=s.get("close_position", 0.6),
                    sector=s.get("sector", get_sector(sym)),
                )
                volume = VolumeData(
                    symbol=sym, current_volume=0, avg_volume_20=0,
                    volume_ratio=vol_ratio, bid_ask_spread=spread,
                    liquidity_pass=liq,
                )
                context = MarketContext(
                    regime=RegimeType(regime),
                    regime_confidence=regime_data.get("regime_confidence", 0.8),
                    nifty_above_vwap=regime_data.get("nifty_above_vwap", True),
                    banknifty_above_vwap=regime_data.get("banknifty_above_vwap", True),
                    nifty_vwap_minutes=regime_data.get("nifty_vwap_minutes", 0),
                    market_trend_aligned=regime_data.get("market_trend_aligned", True),
                    breadth_score=bs,
                )
                rs = RelativeStrengthData(
                    symbol=sym,
                    stock_change_pct=stock_chg,
                    nifty_change_pct=nchg,
                    rs_delta=rs_delta,
                    outperforming=rs_delta > 0.5,
                )
                news = NewsData(
                    symbol=sym, has_news=has_news, sentiment=news_score,
                    catalyst_type=catalyst, headline=headline, llm_score=news_score,
                )

                result = self.engine.calculate(signal, volume, context, rs, news)
                comp   = result.components

                # ── Confluence multiplier (Fix #5) ───────────────────────────
                # Apply BEFORE the per-setup floor and final_score cap. The
                # engine's final_score is already raw × regime_multiplier; we
                # additionally multiply for confluence and re-cap at 10.
                conf_n = s.get("confluence_count", 1)
                if conf_n >= 3:
                    conf_mult = CONFLUENCE_MULTIPLIER_3
                elif conf_n == 2:
                    conf_mult = CONFLUENCE_MULTIPLIER_2
                else:
                    conf_mult = 1.0
                if conf_mult > 1.0:
                    boosted = round(min(10.0, comp.final_score * conf_mult), 2)
                    comp.final_score = boosted
                    # Refresh grade so dashboard / DB write are consistent
                    from scoring.engine import Grade
                    if boosted >= 9.0:   comp.grade = Grade.A_PLUS_PLUS
                    elif boosted >= 8.0: comp.grade = Grade.A_PLUS
                    elif boosted >= 7.0: comp.grade = Grade.A
                    elif boosted >= 5.0: comp.grade = Grade.B
                    else:                comp.grade = Grade.C

                # ── PDH break bonus (Fix #17) ────────────────────────────────
                # Previous day's high is a major magnet level. An entry above
                # PDH on volume is a much higher-probability long than the
                # same setup mid-range. PDL break for shorts (system is
                # long-only today; PDL nudge dormant until SHORT-01).
                pdh_nudge = 0.0
                pdh_pdl = None
                try:
                    pdh_pdl = self.kite.get_pdh_pdl(sym)
                except Exception:
                    pdh_pdl = None
                if pdh_pdl:
                    pdh, _pdl = pdh_pdl
                    if s.get("direction", "long") == "long" and s["entry_price"] > pdh:
                        pdh_nudge = 0.3

                # ── Sector flow nudge (Fix #15) ───────────────────────────────
                # Trade WITH the day's flow. Top-3 sectors get a small boost,
                # bottom-3 get a penalty (more likely to fall below the gate).
                # Uses already-computed top_sectors / weak_sectors from breadth.
                top_secs  = breadth_data.get("top_sectors", []) or []
                weak_secs = breadth_data.get("weak_sectors", []) or []
                sym_sector = s.get("sector", get_sector(sym))
                sector_nudge = 0.0
                if sym_sector in top_secs:
                    sector_nudge = 0.3
                elif sym_sector in weak_secs:
                    sector_nudge = -0.5
                # Combine PDH + sector nudges in a single score update so we
                # don't recompute grade twice.
                total_nudge = sector_nudge + pdh_nudge
                if total_nudge != 0.0:
                    new_score = max(0.0, min(10.0, comp.final_score + total_nudge))
                    comp.final_score = new_score
                    from scoring.engine import Grade
                    if new_score >= 9.0:   comp.grade = Grade.A_PLUS_PLUS
                    elif new_score >= 8.0: comp.grade = Grade.A_PLUS
                    elif new_score >= 7.0: comp.grade = Grade.A
                    elif new_score >= 5.0: comp.grade = Grade.B
                    else:                  comp.grade = Grade.C

                # Per-setup score overrides — raise bar for underperforming setups
                SETUP_MIN_SCORES = {
                    "failed_breakdown": 7.5,   # 33% WR in 151-trade dataset
                }
                setup_min    = SETUP_MIN_SCORES.get(s.get("setup_type", ""), 0)
                effective_min = max(min_score, setup_min)

                will_enter = result.is_valid and comp.final_score >= effective_min
                # Always log score so we can see what's happening
                print(
                    f"[Scorer] {sym:12} {s['setup_type']:20} "
                    f"score={comp.final_score:.1f} "
                    f"(sq={comp.setup_quality:.1f} vol={comp.volume_strength:.1f} "
                    f"mkt={comp.market_alignment:.1f} rs={comp.relative_strength:.1f} "
                    f"news={comp.news_sentiment:.1f}) "
                    f"{'✅ ENTER' if will_enter else '❌ skip'}"
                )

                if will_enter:
                    scored_item = {
                        **s,
                        "final_score": comp.final_score,
                        "grade":       comp.grade.value,
                        "confidence":  result.confidence,
                        "reason":      result.reason,
                        "score_breakdown": {
                            "setup_quality":    comp.setup_quality,
                            "volume_strength":  comp.volume_strength,
                            "market_alignment": comp.market_alignment,
                            "relative_strength": comp.relative_strength,
                            "news_sentiment":   comp.news_sentiment,
                            "confluence_count": s.get("confluence_count", 1),
                            "confluence_mult":  conf_mult,
                            "sector_nudge":     sector_nudge,
                            "pdh_nudge":        pdh_nudge,
                        },
                        "rs_delta":    rs_delta,
                        "news_headline": headline,
                    }
                    scored.append(scored_item)

                elif comp.final_score >= MIN_SCORE_WATCHLIST:
                    # B-grade — add to watchlist
                    self._add_watchlist(sym, s, comp.final_score, result.reason)

            except Exception as e:
                print(f"[Scorer] Error on {sym}: {e}")

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        print(f"[Scorer] {len(scored)} signals above threshold {min_score}")
        return scored

    def _add_watchlist(self, sym: str, s: dict, score: float, reason: str):
        try:
            tp1 = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R1)
            tp2 = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R2)
            item = WatchlistItem(
                symbol=sym, setup_type=s["setup_type"], score=score,
                entry_price=s["entry_price"], stop_loss=s["stop_loss"],
                tp1_price=tp1, tp2_price=tp2, reason=reason[:200],
                added_at=datetime.now().isoformat(),
            )
            self.state.add_to_watchlist(item)
        except Exception:
            pass

    # ── Agent 8a: Capital Allocator ───────────────────────────────────────────

    def _allocate(self, scored: list[dict]):
        """Enter trades for top-scored signals that pass all filters."""
        open_pos = self.state.get_open_positions()
        consec   = self.state.get_consecutive_losses()

        # ── Daily-profit lockout (Fix #11) ───────────────────────────────────
        # Mirror of the kill-switch on the upside. Once today_pnl crosses the
        # lockout ceiling (+3% of CAPITAL), no new entries — protect the day's
        # gains. Existing positions still managed. Auto-resets at next session.
        today_pnl       = self.state.get_today_pnl()
        lockout_ceiling = CAPITAL * DAILY_PROFIT_LOCKOUT_PCT
        tighten_ceiling = CAPITAL * DAILY_PROFIT_TIGHTEN_PCT

        if today_pnl >= lockout_ceiling:
            print(f"[Allocator] 🟢 DAILY-PROFIT LOCKOUT — "
                  f"today P&L ₹{today_pnl:+,.0f} ≥ ceiling ₹{lockout_ceiling:+,.0f} "
                  f"({DAILY_PROFIT_LOCKOUT_PCT*100:.1f}% of ₹{CAPITAL:,}). "
                  f"Done for the day — no new entries.")
            if not getattr(self, "_profit_lock_alerted_today", False):
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🟢 <b>DAILY-PROFIT LOCKOUT</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Today P&L: ₹{today_pnl:+,.0f}\n"
                        f"🎯 Ceiling: ₹{lockout_ceiling:+,.0f} "
                        f"({DAILY_PROFIT_LOCKOUT_PCT*100:.1f}% of capital)\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Profitable day locked in. Open positions still managed."
                    )
                except Exception:
                    pass
                self._profit_lock_alerted_today = True
            return

        # ── Daily-loss kill switch ───────────────────────────────────────────
        # Hard floor: if today_pnl drops below -DAILY_LOSS_KILL_PCT × CAPITAL,
        # block ALL new entries for the rest of the session. Existing positions
        # continue to be managed (SL/TP/trail/EOD). Auto-resets at next session.
        kill_floor   = -CAPITAL * DAILY_LOSS_KILL_PCT
        if today_pnl <= kill_floor:
            print(f"[Allocator] 🛑 DAILY-LOSS KILL SWITCH — "
                  f"today P&L ₹{today_pnl:+,.0f} ≤ floor ₹{kill_floor:+,.0f} "
                  f"({DAILY_LOSS_KILL_PCT*100:.1f}% of ₹{CAPITAL:,}). "
                  f"Blocking new entries for rest of session.")
            # Telegram alert (idempotent — once-per-session)
            if not getattr(self, "_kill_switch_alerted_today", False):
                try:
                    from tools.telegram_tools import _send
                    _send(
                        f"🛑 <b>DAILY-LOSS KILL SWITCH ACTIVATED</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📉 Today P&L: ₹{today_pnl:+,.0f}\n"
                        f"🚫 Floor: ₹{kill_floor:+,.0f} "
                        f"({DAILY_LOSS_KILL_PCT*100:.1f}% of ₹{CAPITAL:,})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"No new entries today. Open positions still managed."
                    )
                except Exception:
                    pass
                self._kill_switch_alerted_today = True
            return

        # ── Tighten gate at +2R (Fix #11) — ride existing winners only ───────
        # Filter scored candidates to A+/A++ (≥8.0) once today_pnl crosses +2%.
        # Continues to take A+ trades but rejects marginal A-grades from here.
        if today_pnl >= tighten_ceiling:
            pre_count = len(scored)
            scored = [s for s in scored if s.get("final_score", 0) >= 8.0]
            if pre_count != len(scored):
                print(f"[Allocator] 🟡 +2R PROFIT — tightened gate to 8.0; "
                      f"{pre_count} → {len(scored)} candidates remain")

        for s in scored:
            sym    = s["symbol"]
            sector = s.get("sector", get_sector(sym))

            # Max positions
            if len(open_pos) >= MAX_POSITIONS:
                print(f"[Allocator] Max positions reached")
                break

            # Already in this stock
            if any(p.symbol == sym for p in open_pos):
                continue

            # ── Symbol auto-blacklist (Fix #27 / D2) ─────────────────────────
            # Skip systematically-bad names (≥3 trades, <30% WR rolling-30).
            if self.state.is_symbol_blacklisted(sym):
                print(f"[Allocator] {sym} auto-blacklisted (poor rolling-30 WR) — skip")
                continue

            # ── Cooldown + smart re-entry (Fix #26 / C1) ────────────────────
            # Hard cap: max 2 trades per stock per day.
            strikes_today = self.state.count_today_trades_on(sym)
            if strikes_today >= 2:
                print(f"[Allocator] {sym} 2 strikes used today — skip")
                continue
            if self.state.is_in_cooldown(sym, 30):
                print(f"[Allocator] {sym} in 30-min cooldown — skip")
                continue
            # Track for sizing (second strike → half size)
            second_strike = (strikes_today == 1)

            # Sector cap
            sec_count = sum(1 for p in open_pos if get_sector(p.symbol) == sector)
            if sec_count >= MAX_SAME_SECTOR_POSITIONS:
                print(f"[Allocator] {sym} sector {sector} full — skip")
                continue

            # ── Fix #13 — fetch FRESH LTP at order time ───────────────────
            # The signal price (s["entry_price"]) is the close of the bar that
            # produced the setup, which may be 3–25 minutes stale by the time
            # we get here. Stamping that as the fill price overstates paper
            # P&L and won't match live execution. Refetch live LTP, validate
            # proximity against it, then USE THE LIVE LTP as the actual fill.
            try:
                live_q = self.kite.get_quotes([sym])
                live_ltp = float(live_q.get(sym, {}).get("last_price", 0) or 0)
            except Exception as e:
                print(f"[Allocator] {sym} live quote failed ({e}) — skip")
                continue
            if live_ltp <= 0:
                print(f"[Allocator] {sym} no live LTP — skip")
                continue

            signal_px = float(s["entry_price"])
            drift = abs(live_ltp - signal_px) / signal_px if signal_px > 0 else 1.0

            # Fix #19 — leaders (strong movers with positive RS) get a relaxed
            # proximity ceiling so we don't keep rejecting trending stocks for
            # the very thing that makes them tradeable.
            is_leader = False
            try:
                live_chg = float(live_q.get(sym, {}).get("change_pct", 0) or 0)
                rs_d     = float(s.get("rs_delta", 0) or 0)
                if live_chg >= LEADER_DAY_CHG_PCT and rs_d >= LEADER_RS_DELTA_PCT:
                    is_leader = True
            except Exception:
                pass
            prox_max = LEADER_PROXIMITY_MAX_PCT if is_leader else PROXIMITY_MAX_PCT

            if drift > prox_max:
                tag = " LEADER" if is_leader else ""
                print(f"[Allocator] {sym} drifted {drift*100:.2f}% > {prox_max*100:.2f}%{tag} "
                      f"— signal ₹{signal_px:.2f} → live ₹{live_ltp:.2f} — skip")
                continue
            if is_leader and drift > PROXIMITY_MAX_PCT:
                print(f"[Allocator] ⚡ LEADER {sym} drift {drift*100:.2f}% allowed "
                      f"(chg={live_chg:.1f}% RS={rs_d:+.1f}%)")

            # ── 15-min HTF trend filter (Fix #20) ─────────────────────────────
            # Reject counter-trend scalps — these are the highest-failure
            # category in the trade-log analysis. Only veto LONGs when the
            # higher timeframe is firmly DOWN.
            try:
                htf = self.kite.get_htf_trend(sym)
            except Exception:
                htf = "neutral"
            if s.get("direction", "long") == "long" and htf == "down":
                print(f"[Allocator] {sym} 15m HTF trend is DOWN — counter-trend, skip")
                continue

            # Overwrite with the actual fill price; recompute TPs from it.
            # SL stays — it's a technical level, not a price-relative offset.
            # Fix #16 — apply paper slippage so paper P&L reflects realistic
            # entry-fill quality (no-op in live mode).
            entry_side = "buy" if s.get("direction", "long") == "long" else "sell"
            s["entry_price"] = _apply_paper_slippage(live_ltp, entry_side, "entry")
            s["tp1_price"]   = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R1)
            s["tp2_price"]   = _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R2)

            # Position sizing (uses the corrected entry)
            dist  = s["entry_price"] - s["stop_loss"]
            if dist <= 0:
                print(f"[Allocator] {sym} live LTP ≤ SL — skip")
                continue

            conservative = consec >= MAX_CONSECUTIVE_LOSSES
            multiplier   = CONSERVATIVE_SIZE_PCT if conservative else 1.0
            # Fix #23 (A6) — score-based sizing tier (combines multiplicatively
            # with conservative-mode dampener). A++ full, A+ 75%, A 50%, B 25%.
            grade_tier   = SCORE_SIZE_TIERS.get(s.get("grade", ""), 0.5)
            # Fix #26 (C1) — second strike on same stock today → half size
            second_dampen = 0.5 if second_strike else 1.0
            risk_amount  = CAPITAL * RISK_PER_TRADE_PCT * multiplier * grade_tier * second_dampen
            if second_strike:
                print(f"[Allocator] {sym} 2nd strike today — sizing dampened ×0.5")
            qty          = floor(risk_amount / dist)
            # Cap 1: max 20% of capital per position (prevents 1 trade using all capital)
            max_pos_val  = CAPITAL * MAX_POSITION_VALUE_PCT
            qty          = min(qty, floor(max_pos_val / s["entry_price"]))
            # Cap 2: can't exceed available capital
            qty          = min(qty, floor(self.state.get_available_capital() / s["entry_price"]))
            qty          = max(0, qty)

            if qty < 1:
                print(f"[Allocator] {sym} qty=0 — insufficient capital")
                continue

            # ── Sizing floor (Fix #9) — no qty=1 token trades ─────────────────
            # When capital is mostly deployed, the 3rd cap above can push qty
            # down to 1-2 shares. A 1-share trade can't earn the ₹1500-3000
            # net target — the cost stack alone (~₹40-200/leg) leaves nothing.
            # Reject below thresholds and watchlist instead.
            risk_taken = qty * dist
            position_val = qty * s["entry_price"]
            min_risk = CAPITAL * MIN_RISK_PER_TRADE_PCT
            min_pos  = CAPITAL * MIN_POSITION_VALUE_PCT
            if risk_taken < min_risk or position_val < min_pos:
                reason_skip = (f"qty={qty} risk=₹{risk_taken:.0f} pos=₹{position_val:.0f} — "
                               f"below floor (need risk≥₹{min_risk:.0f} pos≥₹{min_pos:.0f}) — watchlist")
                print(f"[Allocator] {sym} {reason_skip}")
                self._add_watchlist(sym, s, s.get("final_score", 0), s.get("reason", ""))
                continue

            # Enter!
            tp1 = s.get("tp1_price") or _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R1)
            tp2 = s.get("tp2_price") or _calc_tp(s["entry_price"], s["stop_loss"], TARGET_R2)

            pos_id = self.state.open_position(
                symbol=sym,
                setup_type=s["setup_type"],
                grade=s["grade"],
                score=s["final_score"],
                confidence=s["confidence"],
                entry_price=s["entry_price"],
                stop_loss=s["stop_loss"],
                tp1_price=tp1,
                tp2_price=tp2,
                quantity=qty,
                entry_reason=s.get("reason", ""),
                score_breakdown=s.get("score_breakdown"),
                direction=s.get("direction", "long"),
                sector=sector,
                regime=self._regime_cache.get("regime", ""),  # Fix #14
            )

            tx = "BUY" if s.get("direction", "long") == "long" else "SELL"
            self.kite.place_order(sym, tx, qty)

            # Broker-side SL-M (Fix #6) — opposite side, trigger at the stop
            sl_tx = "SELL" if s.get("direction", "long") == "long" else "BUY"
            sl_oid = self.kite.place_sl_order(
                symbol=sym, transaction=sl_tx, quantity=qty,
                trigger=s["stop_loss"], price=s["stop_loss"],
            )
            if sl_oid:
                self.state.update_sl_order_id(pos_id, sl_oid)
                print(f"[Allocator] 🛑 SL-M placed {sym} trigger={s['stop_loss']} id={sl_oid}")

            # Telegram entry alert
            try:
                alert_trade_entry(
                    symbol=sym,
                    setup_type=s["setup_type"],
                    grade=s["grade"],
                    score=s["final_score"],
                    confidence=s["confidence"],
                    entry_price=s["entry_price"],
                    stop_loss=s["stop_loss"],
                    tp1_price=tp1,
                    tp2_price=tp2,
                    quantity=qty,
                    reason=s.get("reason", ""),
                    score_breakdown=s.get("score_breakdown"),
                )
            except Exception:
                pass

            print(f"[Allocator] ✅ ENTERED {sym} qty={qty} grade={s['grade']} "
                  f"score={s['final_score']:.1f} entry={s['entry_price']}")

            # Refresh open_pos after each entry
            open_pos = self.state.get_open_positions()

        # Alert if consecutive losses triggered conservative mode
        if consec >= MAX_CONSECUTIVE_LOSSES:
            try:
                alert_consecutive_losses(consec, MIN_SCORE_ENTRY_CONSERVATIVE)
            except Exception:
                pass

    # ── Agent 8b: Position Manager ────────────────────────────────────────────

    def _manage_positions(self):
        """
        For every open position:
          • Position is from a prior session → force-close (overnight veto)
          • Hit SL → full exit (initial = sl_hit, post-trail = sl_trail_hit)
          • Hit TP1 → 50% exit, SL → breakeven, start trailing
          • Hit TP2 (or tp1+trailing hit) → full exit (closed_win)
          • Stalled (>45 min, <0.15R move) → close
          • EOD at 15:00 → close all
        """
        open_pos = self.state.get_open_positions()
        if not open_pos:
            return

        now = _now_ist()
        eod = _parse_time(EOD_CLOSE_TIME)   # 15:00
        print(f"[PosMgr] Managing {len(open_pos)} open positions")

        # Batch quotes for all open positions
        syms = [p.symbol for p in open_pos]
        try:
            quotes = self.kite.get_quotes(syms)
        except Exception:
            quotes = {}

        today_ist = now.date()

        for p in open_pos:
            curr = quotes.get(p.symbol, {}).get("last_price", p.entry_price)

            # ── Overnight veto ────────────────────────────────────────────────
            # Any position with entry_time on a prior session must NEVER survive
            # into today. Root cause of the ASIANPAINT 19.85h paper hold:
            # 15:00 EOD force-close didn't fire on 2026-04-20. Belt-and-braces:
            # at every tick, if a position's entry date != today (IST), close it
            # immediately at LTP and tag as overnight_exit.
            if p.entry_time:
                try:
                    entry_dt_ist = _entry_dt_aware(p.entry_time)
                    if entry_dt_ist.date() != today_ist:
                        print(f"[PosMgr] ⚠ OVERNIGHT VETO {p.symbol} — "
                              f"entered {entry_dt_ist.date()}, today is {today_ist}")
                        self._full_exit(p, curr, "overnight_exit")
                        continue
                except Exception:
                    pass

            # ── EOD: close everything ──────────────────────────────────────────
            if now.time() >= eod:
                self._full_exit(p, curr, "eod_exit")
                continue

            # ── SL hit (distinguish initial from trailed) ────────────────────
            if curr <= p.stop_loss:
                # If stop has been moved above initial_sl, it's a trailing exit
                # (price ran in our favour, we tightened, then it pulled back).
                # That should NOT be analytics-classified as a loss like an
                # initial-SL hit; the P&L is often positive.
                trailed = p.tp1_hit or (p.initial_sl and p.stop_loss > p.initial_sl + 1e-6)
                reason = "sl_trail_hit" if trailed else "sl_hit"
                self._full_exit(p, curr, reason)
                continue

            # ── TP2 hit (after TP1 already taken) ─────────────────────────────
            if p.tp1_hit and curr >= p.tp2_price:
                self._full_exit(p, curr, "tp2_hit")
                continue

            # ── TP1 hit (first time) ──────────────────────────────────────────
            if not p.tp1_hit and curr >= p.tp1_price:
                self._partial_exit_tp1(p, curr)
                # After TP1, move SL to breakeven and continue
                continue

            # ── Trailing SL (only after TP1 hit) ─────────────────────────────
            if p.tp1_hit and TRAILING_SL_ENABLED:
                self._try_trail_sl(p, curr)

            # ── Stall detection: >45 min, <0.15R move, not tp1 ───────────────
            # Give trades enough time to breathe — 3 min ticks mean we check
            # every 3 min, so 45 min = 15 ticks before declaring stall.
            # Threshold 0.15R: only exit if truly stuck, not just slow.
            if not p.tp1_hit and p.entry_time:
                try:
                    # entry_time is stored naive by datetime.now().isoformat() in
                    # state.open_position(). On a UTC-host server this is UTC; on
                    # an IST-host server it's IST. Use _entry_dt_aware() to detect
                    # and normalise to IST so elapsed math is correct on either host.
                    entry_dt = _entry_dt_aware(p.entry_time)
                    elapsed  = (now - entry_dt).total_seconds() / 60
                    sl_dist  = abs(p.entry_price - p.initial_sl) or 0.01
                    pnl_r    = (curr - p.entry_price) / sl_dist if p.direction == "long" \
                               else (p.entry_price - curr) / sl_dist
                    if elapsed >= 45 and abs(pnl_r) <= 0.15:
                        self._full_exit(p, curr, "stalled_no_movement")
                        continue
                except Exception:
                    pass

            print(f"[PosMgr] HOLD {p.symbol} @ {curr:.2f} | "
                  f"SL={p.stop_loss:.2f} TP1={p.tp1_price:.2f} TP2={p.tp2_price:.2f} "
                  f"tp1_hit={p.tp1_hit}")

    def _partial_exit_tp1(self, p, curr: float):
        """Exit 50% at TP1. Move SL to breakeven (broker-side SL-M replaced)."""
        from math import floor
        # Fix #13 — refetch live LTP for honest fill price (curr from
        # _manage_positions can be a few hundred ms stale)
        try:
            fq = self.kite.get_quotes([p.symbol])
            fresh = float(fq.get(p.symbol, {}).get("last_price", 0) or 0)
            if fresh > 0:
                curr = fresh
        except Exception:
            pass
        # Fix #16 — paper-mode target slippage (limit order, small drag)
        exit_side = "sell" if p.direction == "long" else "buy"
        curr = _apply_paper_slippage(curr, exit_side, "target")

        qty_exit      = floor(p.quantity_remaining / 2)
        qty_remaining = p.quantity_remaining - qty_exit
        if qty_exit < 1:
            return

        partial_pnl = (curr - p.entry_price) * qty_exit
        new_sl      = p.entry_price   # breakeven

        self.state.mark_tp1_hit(p.id, qty_remaining, partial_pnl)
        self.state.update_stop_loss(p.id, new_sl)

        tx = "SELL" if p.direction == "long" else "BUY"
        self.kite.place_order(p.symbol, tx, qty_exit)

        # Replace broker-side SL-M: cancel old (was on full qty at initial_sl),
        # place new on remaining qty at breakeven (Fix #6).
        if getattr(p, "sl_order_id", ""):
            self.kite.cancel_order(p.sl_order_id)
        sl_tx = "SELL" if p.direction == "long" else "BUY"
        new_sl_oid = self.kite.place_sl_order(
            symbol=p.symbol, transaction=sl_tx, quantity=qty_remaining,
            trigger=new_sl, price=new_sl,
        )
        if new_sl_oid:
            self.state.update_sl_order_id(p.id, new_sl_oid)

        print(f"[PosMgr] 🎯 TP1 HIT {p.symbol} — exited {qty_exit} @ {curr:.2f} "
              f"partial_pnl=₹{partial_pnl:+,.0f} | SL→breakeven {new_sl:.2f}")

        try:
            alert_tp1_hit(
                symbol=p.symbol,
                tp1_price=curr,
                partial_pnl=partial_pnl,
                qty_exited=qty_exit,
                qty_remaining=qty_remaining,
                new_sl=new_sl,
            )
        except Exception:
            pass

    def _try_trail_sl(self, p, curr: float):
        """Trail SL using ATR after TP1 hit. Replaces broker-side SL-M (Fix #6).
        Fix #25 (B2) — volatility-adaptive multiplier: tighter in chop, looser
        on hot trades.
        """
        try:
            df, _ = self.kite.get_vwap_with_candles(p.symbol)
            if df is None:
                return
            atr     = _calc_atr_from_df(df)

            # Adaptive multiplier — default 0.5×ATR, tighter (0.7) in chop,
            # looser (0.4) on hot-volume trades. Lower mult = tighter trail.
            mult = TRAILING_ATR_MULTIPLIER
            try:
                if self._regime_cache.get("regime") == "choppy":
                    mult = 0.7    # tighter — chop reverses fast
                else:
                    vr = self.kite.get_volume_ratio(p.symbol) or 0.0
                    if vr >= 2.0:
                        mult = 0.4   # looser — let hot trades run
            except Exception:
                pass

            new_sl  = _round_down_tick(curr - atr * mult, TICK_SIZE)

            if new_sl > p.stop_loss:
                self.state.update_stop_loss(p.id, new_sl)
                # Replace broker-side SL-M to track the trail
                if getattr(p, "sl_order_id", ""):
                    self.kite.cancel_order(p.sl_order_id)
                sl_tx = "SELL" if p.direction == "long" else "BUY"
                new_oid = self.kite.place_sl_order(
                    symbol=p.symbol, transaction=sl_tx,
                    quantity=p.quantity_remaining,
                    trigger=new_sl, price=new_sl,
                )
                if new_oid:
                    self.state.update_sl_order_id(p.id, new_oid)
                print(f"[PosMgr] 🔄 Trail SL {p.symbol}: "
                      f"{p.stop_loss:.2f} → {new_sl:.2f} "
                      f"(ATR={atr:.2f}, mult={mult:.2f})")
                try:
                    alert_trailing_sl_moved(p.symbol, p.stop_loss, new_sl, curr)
                except Exception:
                    pass
        except Exception:
            pass


    def _full_exit(self, p, curr: float, reason: str):
        """Close full remaining position. Cancel SL-M first to avoid double sell."""
        # Fix #13 — refetch live LTP for honest exit-fill price
        try:
            fq = self.kite.get_quotes([p.symbol])
            fresh = float(fq.get(p.symbol, {}).get("last_price", 0) or 0)
            if fresh > 0:
                curr = fresh
        except Exception:
            pass

        # Fix #16 — paper-mode slippage (worse for stops, lighter for targets/EOD)
        exit_side = "sell" if p.direction == "long" else "buy"
        if reason in ("sl_hit", "sl_trail_hit"):
            curr = _apply_paper_slippage(curr, exit_side, "stop")
        else:
            curr = _apply_paper_slippage(curr, exit_side, "target")

        qty      = p.quantity_remaining
        sl_dist  = abs(p.entry_price - p.initial_sl) or 0.01

        if p.direction == "long":
            trade_pnl = (curr - p.entry_price) * qty
        else:
            trade_pnl = (p.entry_price - curr) * qty

        total_pnl = round(p.pnl + trade_pnl, 2)
        pnl_r = round(total_pnl / (sl_dist * p.quantity), 2) \
                if p.quantity > 0 else 0

        status = "closed_win" if total_pnl > 0 else "closed_loss"
        self.state.close_position(p.id, curr, total_pnl, pnl_r, status, reason)

        # Cancel any pending broker-side SL-M before placing the MARKET exit
        # (Fix #6) — prevents the "polling sees SL hit + broker SL-M also fires"
        # double-sell race in live mode. Safe no-op in paper.
        if getattr(p, "sl_order_id", "") and reason not in ("sl_hit", "sl_trail_hit"):
            self.kite.cancel_order(p.sl_order_id)
        # If reason IS sl_hit/sl_trail_hit, the broker stop may have just filled;
        # cancel is still attempted but failure is benign (already filled).
        elif getattr(p, "sl_order_id", ""):
            self.kite.cancel_order(p.sl_order_id)

        tx = "SELL" if p.direction == "long" else "BUY"
        self.kite.place_order(p.symbol, tx, qty)

        emoji = "✅" if total_pnl > 0 else "❌"
        print(f"[PosMgr] {emoji} CLOSED {p.symbol} @ {curr:.2f} | "
              f"P&L=₹{total_pnl:+,.0f} ({pnl_r:+.2f}R) | {reason}")

        # Telegram exit alert
        try:
            entry_dt  = datetime.fromisoformat(p.entry_time) if p.entry_time else datetime.now()
            hold_mins = int((datetime.now() - entry_dt).total_seconds() / 60)
            alert_trade_exit(
                symbol=p.symbol,
                setup_type=p.setup_type or "",
                exit_price=curr,
                entry_price=p.entry_price,
                pnl=total_pnl,
                pnl_r=pnl_r,
                exit_reason=reason,
                hold_minutes=hold_mins,
            )
        except Exception:
            pass

        # ChromaDB — store outcome immediately so learning is live, not just at EOD
        try:
            outcome = "hit_target" if reason in ("tp1_hit", "tp2_hit") else \
                      "hit_sl"     if reason == "sl_hit" else "expired"
            self.chroma.store_signal_outcome(
                symbol=p.symbol,
                setup_type=p.setup_type or "unknown",
                regime=(p.regime or self._regime_cache.get("regime", "unknown")),  # Fix #14 — entry-time regime first
                score=p.score or 0.0,
                grade=p.grade or "B",
                entry=p.entry_price,
                sl=p.initial_sl or p.stop_loss,
                target=p.tp2_price or p.tp1_price,
                outcome=outcome,
                pnl_r=pnl_r,
            )
            print(f"[ChromaDB] 📚 Stored {p.symbol} → {outcome} ({pnl_r:+.2f}R)")
        except Exception as e:
            print(f"[ChromaDB] Write error: {e}")

    # ── EOD Report ────────────────────────────────────────────────────────────

    def send_eod_report(self):
        """Call this at EOD to send daily summary via Telegram."""
        try:
            summary = self.state.get_summary()
            wins    = summary.get("wins", 0)
            losses  = summary.get("losses", 0)
            total   = summary.get("total", 0)

            # Best setup (by win rate)
            setup_stats = self.state.get_win_rate_by_setup()
            best_setup  = max(setup_stats, key=lambda k: setup_stats[k]["win_rate"]) \
                          if setup_stats else "n/a"

            regime_cache = self._regime_cache.get("regime", "unknown")

            alert_eod_report(
                total_trades=total,
                wins=wins,
                losses=losses,
                total_pnl=summary.get("total_pnl", 0),
                best_trade=summary.get("best_trade", 0),
                worst_trade=summary.get("worst_trade", 0),
                best_setup=best_setup,
                regime_of_day=regime_cache,
            )
        except Exception as e:
            print(f"[EOD] Error sending report: {e}")

    # ── Utility ───────────────────────────────────────────────────────────────

    def _tick_summary(self, active: int, setups: int, scored: int) -> dict:
        now      = _now_ist()
        open_pos = self.state.get_open_positions()

        # Best open position by unrealised P&L
        best_sym    = ""
        best_unreal = 0.0
        if open_pos:
            try:
                syms   = [p.symbol for p in open_pos]
                quotes = self.kite.get_quotes(syms)
                for p in open_pos:
                    curr   = quotes.get(p.symbol, {}).get("last_price", p.entry_price)
                    unreal = (curr - p.entry_price) * p.quantity_remaining \
                             if p.direction == "long" \
                             else (p.entry_price - curr) * p.quantity_remaining
                    if abs(unreal) > abs(best_unreal):
                        best_unreal = unreal
                        best_sym    = p.symbol
            except Exception:
                pass

        s = {
            "tick":           self._tick,
            "time":           now.strftime("%H:%M:%S"),
            "active_stocks":  active,
            "setups_found":   setups,
            "signals_scored": scored,
            "open_positions": len(open_pos),
            "today_pnl":      round(self.state.get_today_pnl(), 2),
            "best_open_sym":  best_sym,
            "best_open_pnl":  round(best_unreal, 2),
        }

        best_str = f" | best open: {best_sym} ₹{best_unreal:+,.0f}" if best_sym else ""
        print(f"[Crew] Tick #{self._tick} done: {setups} setups | "
              f"{scored} entries | "
              f"{s['open_positions']} open | "
              f"P&L ₹{s['today_pnl']:+,.0f}{best_str}")
        return s
