"""
Trading Crew — plain Python orchestrator.
No CrewAI. Just Groq + Python. Clean and fast.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from groq import Groq
from config.settings import GROQ_API_KEY, GROQ_MODEL, TIMEZONE

IST = ZoneInfo(TIMEZONE)
client = Groq(api_key=GROQ_API_KEY)

def ask_groq(system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
        temperature=0.1,
        max_tokens=4000,
    )
    return resp.choices[0].message.content.strip()

def parse_json(text: str):
    text = str(text).strip()
    for s,e in [("[","]"),("{","}")]:
        i,j = text.find(s), text.rfind(e)
        if i!=-1 and j!=-1 and j>i:
            try: return json.loads(text[i:j+1])
            except: continue
    return []

from tools.kite_tools import get_quotes, get_volume_ratio, get_nifty_data, get_vwap, get_spread
from tools.volume_tools import batch_volume_rs
from tools.pattern_tools import scan_all_setups
from tools.news_tools import get_batch_news
from tools.chroma_tools import query_similar_signals
from tools.score_tools import can_enter_trade, open_position, get_open_positions, close_position, add_to_watchlist
from scoring.engine import ScoringEngine, RawSignal, VolumeData, MarketContext, RelativeStrengthData, NewsData, SetupType, RegimeType, SignalDirection
from config.universe import FULL_UNIVERSE, get_sector
from config.settings import MIN_SCORE_ENTRY
engine = ScoringEngine()

class TradingCrew:
    def __init__(self):
        self._tick = 0
        print("[Crew] Initialized with Groq + plain Python")

    def run_tick(self) -> dict:
        self._tick += 1
        now = datetime.now(IST)
        print(f"\n{'='*55}")
        print(f"[Crew] TICK #{self._tick} — {now.strftime('%H:%M:%S IST')}")
        print(f"{'='*55}")

        # Step 1: Manage open positions
        self._manage_positions()

        # Step 2: Scan market
        active = self._scan_market()
        if not active:
            print("[Crew] No active stocks found")
            return {"tick":self._tick,"active_stocks":0,"setups_found":0,"signals_scored":0}

        # Step 3: Detect regime
        regime_data = self._detect_regime()

        # Step 4: Detect setups
        setups = self._detect_setups(active)
        if not setups:
            print("[Crew] No setups detected")
            return {"tick":self._tick,"active_stocks":len(active),"setups_found":0,"signals_scored":0}

        # Step 5: Score signals
        scored = self._score_signals(setups, regime_data)

        # Step 6: Allocate capital
        self._allocate(scored)

        summary = {"tick":self._tick,"time":now.strftime("%H:%M:%S"),
                   "active_stocks":len(active),"setups_found":len(setups),"signals_scored":len(scored)}
        print(f"[Crew] Tick done: {summary}")
        return summary

    def _scan_market(self) -> list:
        print("[Scanner] Scanning market...")
        try:
            raw = parse_json(get_quotes(",".join(FULL_UNIVERSE[:50])))
            active = []
            for sym, data in (raw.items() if isinstance(raw,dict) else {}.items()):
                if abs(data.get("change_pct",0)) >= 0.3:
                    active.append(sym)
            print(f"[Scanner] {len(active)} active stocks")
            return active[:60]
        except Exception as e:
            print(f"[Scanner] Error: {e}")
            return FULL_UNIVERSE[:30]

    def _detect_regime(self) -> dict:
        print("[Regime] Detecting regime...")
        try:
            nifty = parse_json(get_nifty_data("nifty"))
            n = nifty.get("nifty", {})
            above = n.get("above_vwap", True)
            chg   = n.get("change_pct", 0)
            if abs(chg) > 1.5:   regime = "event"
            elif abs(chg) > 0.4 and above: regime = "trending"
            elif not above:      regime = "recovering"
            else:                regime = "choppy"
            print(f"[Regime] {regime} | Nifty {chg:+.2f}% | above_vwap={above}")
            return {"regime":regime,"nifty_above_vwap":above,
                    "banknifty_above_vwap":above,"nifty_vwap_minutes":20,
                    "market_trend_aligned":above,"breadth_score":0.6,
                    "nifty_change_pct":chg}
        except Exception as e:
            print(f"[Regime] Error: {e}, defaulting to trending")
            return {"regime":"trending","nifty_above_vwap":True,
                    "banknifty_above_vwap":True,"nifty_vwap_minutes":20,
                    "market_trend_aligned":True,"breadth_score":0.6,"nifty_change_pct":0}

    def _detect_setups(self, active: list) -> list:
        print(f"[Setup] Scanning {len(active)} stocks...")
        try:
            result = parse_json(scan_all_setups(",".join(active)))
            setups = result if isinstance(result, list) else []
            print(f"[Setup] Found {len(setups)} setups")
            return setups
        except Exception as e:
            print(f"[Setup] Error: {e}")
            return []

    def _score_signals(self, setups: list, regime_data: dict) -> list:
        print(f"[Scorer] Scoring {len(setups)} setups...")
        scored = []
        regime = regime_data.get("regime","trending")

        # Get quotes for all setup symbols
        symbols = [s["symbol"] for s in setups]
        try:
            quotes_raw = parse_json(get_quotes(",".join(symbols)))
            quotes = quotes_raw if isinstance(quotes_raw, dict) else {}
        except:
            quotes = {}

        # Get news batch
        try:
            news_raw = parse_json(get_batch_news(",".join(symbols)))
            news_map = news_raw if isinstance(news_raw, dict) else {}
        except:
            news_map = {}

        for s in setups:
            try:
                sym = s["symbol"]
                q   = quotes.get(sym, {})

                # Volume data
                vol_ratio = float(parse_json(get_volume_ratio(sym)).get("volume_ratio", 1.0))
                spread    = float(parse_json(get_spread(sym)).get("spread_pct", 0.1))
                liq       = vol_ratio >= 1.2 and spread < 0.15

                # RS
                stock_chg = q.get("change_pct", 0.0)
                nifty_chg = regime_data.get("nifty_change_pct", 0.0)

                # News
                nd        = news_map.get(sym, {})
                has_news  = nd.get("has_news", False)
                news_score = nd.get("llm_score", 0.5)
                catalyst  = nd.get("catalyst_type", "none")
                headline  = nd.get("headline", "")

                # Build scoring objects
                signal = RawSignal(
                    symbol=sym,
                    setup_type=SetupType(s["setup_type"]),
                    direction=SignalDirection(s.get("direction","long")),
                    entry_price=s["entry_price"],
                    stop_loss=s["stop_loss"],
                    target_price=s["target_price"],
                    current_price=s.get("current_price", s["entry_price"]),
                    candle_body_ratio=s.get("candle_body_ratio", 0.5),
                    close_position=s.get("close_position", 0.7),
                    sector=s.get("sector", get_sector(sym)),
                )
                volume = VolumeData(sym,0,0,vol_ratio,spread,liq)
                context = MarketContext(
                    regime=RegimeType(regime),
                    regime_confidence=0.8,
                    nifty_above_vwap=regime_data.get("nifty_above_vwap",True),
                    banknifty_above_vwap=regime_data.get("banknifty_above_vwap",True),
                    nifty_vwap_minutes=regime_data.get("nifty_vwap_minutes",20),
                    market_trend_aligned=regime_data.get("market_trend_aligned",True),
                    breadth_score=regime_data.get("breadth_score",0.6),
                )
                rs   = RelativeStrengthData(sym,stock_chg,nifty_chg,stock_chg-nifty_chg,(stock_chg-nifty_chg)>0.5)
                news = NewsData(sym,has_news,news_score,catalyst,headline,news_score)

                result = engine.calculate(signal,volume,context,rs,news)
                comp   = result.components

                if comp.final_score >= MIN_SCORE_ENTRY and result.is_valid:
                    scored.append({**s,
                        "final_score": comp.final_score,
                        "grade":       comp.grade.value,
                        "confidence":  result.confidence,
                        "reason":      result.reason,
                    })
                    print(f"[Scorer] {sym} → {comp.final_score:.1f} {comp.grade.value}")
                elif comp.final_score >= 5.0:
                    add_to_watchlist(sym,s["setup_type"],comp.final_score,comp.grade.value,
                                     s["entry_price"],s["stop_loss"],s["target_price"],result.reason)

            except Exception as e:
                print(f"[Scorer] Error on {s.get('symbol','?')}: {e}")

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        print(f"[Scorer] {len(scored)} signals above threshold")
        return scored

    def _allocate(self, scored: list):
        for s in scored:
            try:
                sym    = s["symbol"]
                sector = s.get("sector", get_sector(sym))
                result = parse_json(can_enter_trade(sym,sector,s["entry_price"],s["stop_loss"]))
                if not result.get("can_enter"):
                    print(f"[Allocator] {sym} SKIP — {result.get('reason')}")
                    continue
                # Proximity check
                current = s.get("current_price", s["entry_price"])
                drift   = abs(current - s["entry_price"]) / s["entry_price"]
                if drift > 0.007:
                    print(f"[Allocator] {sym} SKIP — price ran {drift*100:.2f}%")
                    continue
                res = parse_json(open_position(
                    sym, s["setup_type"], s.get("direction","long"),
                    s["grade"], s["final_score"], s["confidence"],
                    s["entry_price"], s["stop_loss"], s["target_price"],
                    sector, s["reason"]
                ))
                if res.get("success"):
                    print(f"[Allocator] {sym} ENTERED — qty={res.get('quantity')} grade={s['grade']}")
            except Exception as e:
                print(f"[Allocator] Error: {e}")

    def _manage_positions(self):
        try:
            pos_data = parse_json(get_open_positions("all"))
            positions = pos_data.get("positions", []) if isinstance(pos_data,dict) else []
            if not positions:
                return
            now = datetime.now(IST)
            print(f"[PosMgr] Managing {len(positions)} open positions")
            for p in positions:
                pid     = p["id"]
                sym     = p["symbol"]
                pnl_r   = p.get("pnl_r", 0)
                current = p.get("current_price", p["entry_price"])
                sl      = p["stop_loss"]
                target  = p["target_price"]
                entry_t = datetime.fromisoformat(p["entry_time"])
                minutes = (now - entry_t.replace(tzinfo=IST)).seconds // 60

                reason = None
                if current <= sl:
                    reason = "stop_loss_hit"
                elif current >= target:
                    reason = "target_hit"
                elif minutes >= 20 and abs(pnl_r) <= 0.2:
                    reason = "stalled_no_movement"
                elif now.hour >= 15:
                    reason = "eod_exit"

                if reason:
                    res = parse_json(close_position(pid, reason))
                    print(f"[PosMgr] {sym} CLOSED — {reason} pnl={res.get('pnl_r',0):.1f}R")
                else:
                    print(f"[PosMgr] {sym} HOLD — {pnl_r:+.1f}R")
        except Exception as e:
            print(f"[PosMgr] Error: {e}")
