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
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from data.kite_client import KiteDataClient
from data.news_client import NewsClient
from memory.trade_state import TradeStateManager, WatchlistItem
from memory.chroma_client import ChromaMemory

from scoring.engine import (
    ScoringEngine, RawSignal, VolumeData, MarketContext,
    RelativeStrengthData, NewsData,
    SetupType, RegimeType, SignalDirection,
)

from tools.pattern_tools import _detect_all_setups
from tools.volume_tools   import _compute_breadth, _compute_sector_strength
from tools.telegram_tools import (
    alert_trade_entry, alert_tp1_hit, alert_trade_exit,
    alert_trailing_sl_moved, alert_consecutive_losses,
    alert_market_breadth, alert_eod_report, alert_system_start,
)

from config.universe import FULL_UNIVERSE, get_sector
from config.settings import (
    CAPITAL, RISK_PER_TRADE_PCT, MAX_POSITIONS, MAX_SAME_SECTOR_POSITIONS,
    MAX_CONSECUTIVE_LOSSES, CONSERVATIVE_SIZE_PCT,
    TARGET_R1, TARGET_R2, TIMEZONE,
    TRAILING_SL_ENABLED, TRAILING_ATR_MULTIPLIER,
    BREADTH_BULLISH, BREADTH_BEARISH,
    MIN_SCORE_ENTRY, MIN_SCORE_ENTRY_CONSERVATIVE, MIN_SCORE_WATCHLIST,
    NO_ENTRY_BEFORE_MIN, NO_NEW_ENTRY_AFTER, EOD_CLOSE_TIME,
    MIDDAY_AVOID_START, MIDDAY_AVOID_END,
    PROXIMITY_MAX_PCT,
)

IST = ZoneInfo(TIMEZONE)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_ist() -> datetime:
    return datetime.now(IST)


def _parse_time(t: str) -> dtime:
    """'HH:MM' → time object."""
    h, m = t.split(":")
    return dtime(int(h), int(m))


def _calc_tp(entry: float, sl: float, r: float) -> float:
    return round(entry + (entry - sl) * r, 2)


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
        print("[Crew] Initialized — scanning 150 stocks, TP1+TP2+trailing SL active")
        alert_system_start()

    # ── Main entry point ──────────────────────────────────────────────────────

    def run_tick(self) -> dict:
        self._tick += 1
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
        scored = self._score_signals(setups, self._regime_cache, self._breadth_cache)

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
            # Batch fetch quotes for all 150 stocks
            quotes = self.kite.get_quotes(FULL_UNIVERSE)
            active = []
            for sym, q in quotes.items():
                chg = abs(q.get("change_pct", 0))
                vol = q.get("volume", 0)
                # Filter: meaningful move + some volume
                if chg >= 0.3 and vol >= 10_000:
                    active.append((sym, chg))

            # Sort by absolute change, take top 60
            active.sort(key=lambda x: x[1], reverse=True)
            result = [s[0] for s in active[:60]]
            print(f"[Scanner] {len(result)} active stocks (of {len(FULL_UNIVERSE)} scanned)")
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
            breadth  = _compute_breadth()
            sectors  = _compute_sector_strength()
            top3     = [s["sector"] for s in sectors[:3]]
            bottom3  = [s["sector"] for s in sectors[-3:]]

            bs = breadth["breadth_score"]
            label = breadth["breadth_label"]
            print(f"[Breadth] {bs:.0%} above VWAP → {label} | Top: {top3}")

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
        print(f"[Setup] Detecting setups in {len(active)} stocks...")
        setups       = []
        no_data      = 0
        few_candles  = 0
        below_vwap_count = 0
        weak_body    = 0

        for sym in active:
            try:
                df, vwap = self.kite.get_vwap_with_candles(sym)
                if df is None:
                    no_data += 1
                    continue
                if len(df) < 8:
                    few_candles += 1
                    continue

                quotes   = self.kite.get_quotes([sym])
                curr     = quotes.get(sym, {}).get("last_price", 0.0)

                # Quick diagnostic: count common blockers
                last = df.iloc[-1]
                br   = abs(last["close"] - last["open"]) / (last["high"] - last["low"]) \
                       if (last["high"] - last["low"]) > 0 else 0
                if last["close"] < vwap:
                    below_vwap_count += 1
                if br < 0.4:
                    weak_body += 1

                result = _detect_all_setups(df, vwap, curr, sym)
                if result:
                    setups.append(result)
            except Exception:
                continue

        setups.sort(key=lambda x: x.get("candle_quality", 0), reverse=True)
        print(
            f"[Setup] Found {len(setups)} setups | "
            f"no_data={no_data} few_candles={few_candles} | "
            f"below_vwap={below_vwap_count} weak_body={weak_body} (of {len(active)})"
        )
        return setups

    # ── Agent 5+6: Volume + RS + News ────────────────────────────────────────

    def _get_volume_rs(self, sym: str, nifty_chg: float) -> tuple[float, float, float, bool]:
        """Returns (volume_ratio, spread_pct, rs_delta, liquidity_pass)."""
        try:
            ratio  = self.kite.get_volume_ratio(sym) or 0.0
            spread = self.kite.get_spread_pct(sym)
            quotes = self.kite.get_quotes([sym])
            stock_chg = quotes.get(sym, {}).get("change_pct", 0.0)
            delta  = round(stock_chg - nifty_chg, 3)
            liq    = (ratio >= 1.2) and (spread < 0.15)
            return ratio, spread, delta, liq
        except Exception:
            return 0.0, 0.5, 0.0, False

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
    ) -> list[dict]:
        print(f"[Scorer] Scoring {len(setups)} setups...")
        scored  = []
        regime  = regime_data.get("regime", "choppy")
        nchg    = regime_data.get("nifty_change_pct", 0.0)
        bs      = breadth_data.get("breadth_score", 0.6)

        # Raise score threshold during midday
        min_score = MIN_SCORE_ENTRY_CONSERVATIVE if self._is_midday() else MIN_SCORE_ENTRY

        # Also raise threshold if consecutive losses ≥ 3
        consec = self.state.get_consecutive_losses()
        if consec >= MAX_CONSECUTIVE_LOSSES:
            min_score = max(min_score, MIN_SCORE_ENTRY_CONSERVATIVE)
            print(f"[Scorer] Conservative mode — {consec} consecutive losses, threshold={min_score}")

        for s in setups:
            sym = s["symbol"]
            try:
                # Volume + RS
                vol_ratio, spread, rs_delta, liq = self._get_volume_rs(sym, nchg)

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

                if result.is_valid and comp.final_score >= min_score:
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
                        },
                        "rs_delta":    rs_delta,
                        "news_headline": headline,
                    }
                    scored.append(scored_item)
                    print(f"[Scorer] ✅ {sym} → {comp.final_score:.1f} {comp.grade.value} | {s['setup_type']}")

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

            # Cooldown
            if self.state.is_in_cooldown(sym, 30):
                print(f"[Allocator] {sym} in cooldown — skip")
                continue

            # Sector cap
            sec_count = sum(1 for p in open_pos if get_sector(p.symbol) == sector)
            if sec_count >= MAX_SAME_SECTOR_POSITIONS:
                print(f"[Allocator] {sym} sector {sector} full — skip")
                continue

            # Proximity check (price ran from entry)
            curr  = s.get("current_price", s["entry_price"])
            drift = abs(curr - s["entry_price"]) / s["entry_price"]
            if drift > PROXIMITY_MAX_PCT:
                print(f"[Allocator] {sym} price ran {drift*100:.2f}% — skip")
                continue

            # Position sizing
            dist  = s["entry_price"] - s["stop_loss"]
            if dist <= 0:
                continue

            conservative = consec >= MAX_CONSECUTIVE_LOSSES
            multiplier   = CONSERVATIVE_SIZE_PCT if conservative else 1.0
            risk_amount  = CAPITAL * RISK_PER_TRADE_PCT * multiplier
            qty          = floor(risk_amount / dist)
            qty          = min(qty, floor(self.state.get_available_capital() / s["entry_price"]))
            qty          = max(0, qty)

            if qty < 1:
                print(f"[Allocator] {sym} qty=0 — insufficient capital")
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
            )

            tx = "BUY" if s.get("direction", "long") == "long" else "SELL"
            self.kite.place_order(sym, tx, qty)

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
          • Hit SL → full exit (closed_loss)
          • Hit TP1 → 50% exit, SL → breakeven, start trailing
          • Hit TP2 (or tp1+trailing hit) → full exit (closed_win)
          • Stalled (>20 min, <0.2R move) → close
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

        for p in open_pos:
            curr = quotes.get(p.symbol, {}).get("last_price", p.entry_price)

            # ── EOD: close everything ──────────────────────────────────────────
            if now.time() >= eod:
                self._full_exit(p, curr, "eod_exit")
                continue

            # ── SL hit ────────────────────────────────────────────────────────
            if curr <= p.stop_loss:
                self._full_exit(p, curr, "sl_hit")
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

            # ── Stall detection: >20 min, <0.2R move, not tp1 ─────────────────
            if not p.tp1_hit and p.entry_time:
                try:
                    entry_dt = datetime.fromisoformat(p.entry_time)
                    elapsed  = (now - entry_dt.replace(tzinfo=IST)).total_seconds() / 60
                    sl_dist  = abs(p.entry_price - p.initial_sl) or 0.01
                    pnl_r    = (curr - p.entry_price) / sl_dist if p.direction == "long" \
                               else (p.entry_price - curr) / sl_dist
                    if elapsed >= 20 and abs(pnl_r) <= 0.2:
                        self._full_exit(p, curr, "stalled_no_movement")
                        continue
                except Exception:
                    pass

            print(f"[PosMgr] HOLD {p.symbol} @ {curr:.2f} | "
                  f"SL={p.stop_loss:.2f} TP1={p.tp1_price:.2f} TP2={p.tp2_price:.2f} "
                  f"tp1_hit={p.tp1_hit}")

    def _partial_exit_tp1(self, p, curr: float):
        """Exit 50% at TP1. Move SL to breakeven. Telegram alert."""
        from math import floor
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
        """Trail SL using ATR after TP1 hit."""
        try:
            df, _ = self.kite.get_vwap_with_candles(p.symbol)
            if df is None:
                return
            atr     = _calc_atr_from_df(df)
            new_sl  = round(curr - atr * TRAILING_ATR_MULTIPLIER, 2)

            if new_sl > p.stop_loss:
                self.state.update_stop_loss(p.id, new_sl)
                print(f"[PosMgr] 🔄 Trail SL {p.symbol}: "
                      f"{p.stop_loss:.2f} → {new_sl:.2f} (ATR={atr:.2f})")
                try:
                    alert_trailing_sl_moved(p.symbol, p.stop_loss, new_sl, curr)
                except Exception:
                    pass
        except Exception:
            pass

    def _full_exit(self, p, curr: float, reason: str):
        """Close full remaining position. Telegram exit alert."""
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
