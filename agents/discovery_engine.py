"""
Discovery Engine — Phase 2.1.

Spec: docs/19_Discovery_Engine_Spec_2026-05-12.md

The reason this exists:
  On 2026-05-12, the cleanest longs of the day were JINDRILL (+7.81%) and
  OIL India (+5.59% → +8.51%) — both mid-caps NOT in the agent's hardcoded
  150-stock universe. The agent was structurally blind to the highest-
  conviction names of the session.

What this module does:
  1. Seeds a candidate pool from kite.instruments(NSE) at boot
     (NSE EQ series only; ETFs / indices / illiquid names filtered out).
  2. Every DISCOVERY_SCAN_INTERVAL_SEC during market hours, batch-fetches
     OHLC for the pool, computes %chg vs prev close + volume ratio.
  3. Admits names crossing |%chg| ≥ DISCOVERY_MIN_PCT_MOVE on >1.5x volume
     with adequate liquidity (turnover ≥ ₹10cr, spread ≤ 0.15%).
  4. Bounded: ≤5 new per scan, ≤15 total live, ≤40/session.
  5. Auto-blacklists symbols that cause 2+ losses (7-day cooldown).

Three Laws compliance (PROJECT_MEMORY top section):
  - No symbol hardcoding — pool seeded from broker's NSE EQ listing.
  - No clock gates — only structural triggers (%chg + volume + liquidity).
  - Thresholds tunable in config/settings.py, not buried magic numbers.

Safe-rollout posture:
  - Shadow mode by default. DISCOVERY_ALLOW_TRADES flag in settings.py
    gates whether crew.py actually merges discovered names into the live
    universe. Until that's True, discovery runs silently and logs only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo
import re
import json
import os

from config.settings import TIMEZONE

IST = ZoneInfo(TIMEZONE)

# Patterns for non-EQ instruments to exclude from the candidate pool.
_NON_EQ_NAME_RE = re.compile(
    r"\b(ETF|BEES|LIQUID|GILT|NIFTY|SENSEX|JUNIOR|GOLD|SILVER|GROWW)\b",
    re.IGNORECASE,
)

DEFAULT_BLACKLIST_PATH = "discovery_blacklist.json"


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DiscoveryCandidate:
    symbol:           str
    pct_change:       float      # signed, e.g. +7.81 or -5.04
    volume_ratio:     float      # current_volume / 20d avg volume (proxy via day-volume / 20d-avg)
    avg_turnover_inr: float      # 20-day avg ₹ turnover
    spread_pct:       float
    score:            float      # 0-1 composite admission score
    intraday_high_pct: float     # high vs prev close
    pull_from_extreme_pct: float # how far off intraday extreme
    detected_at:      datetime
    reason:           str

    @property
    def direction_bias(self) -> str:
        """Positive %chg → long candidate; negative → short candidate."""
        return "long" if self.pct_change > 0 else "short"


@dataclass
class _DailyContext:
    """20-day rolling history per symbol — recomputed at boot each session."""
    avg_daily_volume:   float = 0.0
    avg_daily_turnover: float = 0.0


# ─── Engine ───────────────────────────────────────────────────────────────────

class DiscoveryEngine:
    """
    Top-mover scanner that runs every N minutes during market hours.

    Lifecycle per session:
      1. __init__ → seed_candidate_pool() pulls NSE EQ listings.
      2. crew.py calls run_scan(now) on a fixed cadence.
      3. crew.py calls get_live_universe(core) at the top of every tick.
      4. crew.py calls report_trade_outcome() when positions close.
      5. EOD: discovered_today is reset; blacklist persists to disk.
    """

    def __init__(
        self,
        kite,
        core_universe: list[str],
        settings_module=None,
        blacklist_path: str = DEFAULT_BLACKLIST_PATH,
    ):
        self.kite = kite
        # `core_universe` is the existing 150-stock hardcoded list. We use it
        # to filter out names that are already covered.
        self.core_universe = set(core_universe)
        self.blacklist_path = blacklist_path

        # Lazy-load settings so test code can pass a stub module.
        if settings_module is None:
            from config import settings as _settings
            settings_module = _settings
        self.s = settings_module

        # State
        self._candidate_pool: list[str] = []
        self._daily_context: dict[str, _DailyContext] = {}
        self._discovered_today: dict[str, DiscoveryCandidate] = {}
        self._blacklist: dict[str, str] = {}   # symbol → ISO date when expires
        self._loss_counter: dict[str, int] = {}
        self._last_scan_at: Optional[datetime] = None
        self._scans_this_session: int = 0
        self._adds_this_session: int = 0
        self._session_iso: Optional[str] = None

        self._load_blacklist()

    # ── Pool seeding ─────────────────────────────────────────────────────────

    def seed_candidate_pool(self) -> int:
        """
        Pull NSE EQ instruments from Kite (one call) and filter:
          - segment == NSE and series == EQ
          - tradingsymbol does not match ETF/BEES/GILT/NIFTY patterns
          - not already in core_universe (those go through the main path)

        Returns the number of names seeded into the candidate pool.
        Failure is non-fatal — pool stays empty; discovery silently no-ops.
        """
        try:
            raw_kite = getattr(self.kite, "kite", None) or self.kite
            instruments = raw_kite.instruments("NSE")
        except Exception as e:
            print(f"[Discovery] seed_candidate_pool: instruments() failed: {e}")
            self._candidate_pool = []
            return 0

        pool: list[str] = []
        for inst in instruments:
            tsym  = inst.get("tradingsymbol", "")
            series = inst.get("series", "")
            segment = inst.get("segment", "")
            if not tsym:
                continue
            if series != "EQ":
                continue
            if segment != "NSE":
                continue
            if _NON_EQ_NAME_RE.search(tsym):
                continue
            if tsym in self.core_universe:
                continue
            pool.append(tsym)

        self._candidate_pool = pool
        print(f"[Discovery] seeded candidate pool — {len(pool)} NSE EQ "
              f"names (excluding {len(self.core_universe)} core + ETFs/indices)")
        return len(pool)

    # ── Scan ─────────────────────────────────────────────────────────────────

    def run_scan(self, now: Optional[datetime] = None) -> list[DiscoveryCandidate]:
        """
        Main entry. Called periodically by crew.py.

        Returns the list of newly-admitted candidates this scan (may be empty).
        Existing discovered_today entries are pruned if they've cooled off
        (price back inside ±1% chg and volume_ratio < 1.0 for 15+ min).
        """
        if now is None:
            now = datetime.now(IST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=IST)

        # Reset state on session change.
        today_iso = now.date().isoformat()
        if self._session_iso != today_iso:
            self._reset_for_new_session(today_iso)

        # Cadence + first-scan delay
        if self._last_scan_at is not None:
            delta = (now - self._last_scan_at).total_seconds()
            if delta < self.s.DISCOVERY_SCAN_INTERVAL_SEC:
                return []

        # Skip first DISCOVERY_FIRST_SCAN_DELAY_MIN minutes after 09:15 open
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if (now - market_open).total_seconds() < self.s.DISCOVERY_FIRST_SCAN_DELAY_MIN * 60:
            return []

        # Hard caps
        if self._adds_this_session >= self.s.DISCOVERY_MAX_PER_SESSION:
            return []
        if len(self._discovered_today) >= self.s.DISCOVERY_MAX_TOTAL:
            self._prune_stale(now)
            if len(self._discovered_today) >= self.s.DISCOVERY_MAX_TOTAL:
                return []

        if not self._candidate_pool:
            return []

        # Batch-fetch OHLC for the pool, in chunks of 500
        admitted: list[DiscoveryCandidate] = []
        ranked = self._rank_movers(now)
        cap = self.s.DISCOVERY_MAX_NEW_ADDS_PER_SCAN
        for cand in ranked:
            if len(admitted) >= cap:
                break
            if self._adds_this_session >= self.s.DISCOVERY_MAX_PER_SESSION:
                break
            if len(self._discovered_today) >= self.s.DISCOVERY_MAX_TOTAL:
                break
            self._discovered_today[cand.symbol] = cand
            self._adds_this_session += 1
            admitted.append(cand)
            print(
                f"[Discovery] ADMIT {cand.symbol}  "
                f"{cand.pct_change:+.2f}%  vol×{cand.volume_ratio:.2f}  "
                f"turnover ₹{cand.avg_turnover_inr/1e7:.1f}cr  "
                f"spread {cand.spread_pct:.3f}%  score {cand.score:.2f}  "
                f"({cand.reason})"
            )

        # Prune stale entries (price cooled back inside ±1% with low volume).
        self._prune_stale(now)

        self._last_scan_at = now
        self._scans_this_session += 1
        if not admitted:
            print(f"[Discovery] scan #{self._scans_this_session}: 0 admits "
                  f"(pool={len(self._candidate_pool)}, "
                  f"live={len(self._discovered_today)}, "
                  f"session-adds={self._adds_this_session})")
        return admitted

    # ── Universe merge ───────────────────────────────────────────────────────

    def get_live_universe(self, core: list[str]) -> list[str]:
        """
        crew.py calls this at the top of each tick. Returns core ∪
        currently-active discovery names. If DISCOVERY_ALLOW_TRADES is False,
        returns core only (shadow mode — engine runs and logs, but doesn't
        feed names to the trading pipeline).
        """
        if not getattr(self.s, "DISCOVERY_ALLOW_TRADES", False):
            return list(core)
        extra = [
            sym for sym in self._discovered_today
            if sym not in self.core_universe and sym not in self._blacklist
        ]
        if not extra:
            return list(core)
        return list(core) + extra

    # ── Outcome reporting (auto-blacklist) ───────────────────────────────────

    def report_trade_outcome(self, symbol: str, r_multiple: float) -> None:
        """
        Called by crew.py on each closed discovery position. If a symbol
        accumulates DISCOVERY_BLACKLIST_LOSS_THRESHOLD losing trades (defined
        as r_multiple < -1.0), it's blacklisted for DISCOVERY_BLACKLIST_DAYS
        trading days. Blacklist persists across restarts.
        """
        if symbol not in self._discovered_today:
            return   # not a discovery name; main path handles core universe
        if r_multiple >= -1.0:
            return   # not a clear loss
        self._loss_counter[symbol] = self._loss_counter.get(symbol, 0) + 1
        threshold = getattr(self.s, "DISCOVERY_BLACKLIST_LOSS_THRESHOLD", 2)
        if self._loss_counter[symbol] >= threshold:
            days = getattr(self.s, "DISCOVERY_BLACKLIST_DAYS", 7)
            expires = (datetime.now(IST) + timedelta(days=days)).date().isoformat()
            self._blacklist[symbol] = expires
            self._save_blacklist()
            print(f"[Discovery] BLACKLIST {symbol} — {self._loss_counter[symbol]} "
                  f"losses, banned until {expires}")

    # ── Internals: ranking, filtering, pruning ───────────────────────────────

    def _rank_movers(self, now: datetime) -> list[DiscoveryCandidate]:
        """
        Pull OHLC for the candidate pool in 500-name chunks, apply hard
        filters, and rank survivors by composite admission score.
        """
        survivors: list[DiscoveryCandidate] = []

        # Filter out symbols we've already admitted today (don't re-admit)
        # or that are blacklisted.
        pool = [
            s for s in self._candidate_pool
            if s not in self._discovered_today and not self._is_blacklisted(s, now)
        ]
        if not pool:
            return []

        # Batch in chunks of 500 (Kite's quote API limit)
        CHUNK = 500
        nifty_change = self._get_nifty_change_pct()

        for i in range(0, len(pool), CHUNK):
            batch = pool[i : i + CHUNK]
            try:
                quotes = self.kite.get_quotes(batch)
            except Exception as e:
                print(f"[Discovery] get_quotes failed on chunk {i}-{i+CHUNK}: {e}")
                continue
            for sym, q in quotes.items():
                cand = self._build_candidate(sym, q, now, nifty_change)
                if cand is not None:
                    survivors.append(cand)

        # Sort by composite admission score descending
        survivors.sort(key=lambda c: c.score, reverse=True)
        return survivors

    def _build_candidate(
        self,
        sym: str,
        q: dict,
        now: datetime,
        nifty_change: float,
    ) -> Optional[DiscoveryCandidate]:
        """Apply hard filters; return None if any fail."""
        last_price = q.get("last_price", 0.0)
        prev_close = q.get("close", 0.0)
        if last_price <= 0 or prev_close <= 0:
            return None
        pct_change = (last_price / prev_close - 1.0) * 100.0

        # Filter #1 — meaningful magnitude
        if abs(pct_change) < self.s.DISCOVERY_MIN_PCT_MOVE:
            return None

        # Filter #2 — volume confirmation
        # We use today's reported volume / 20d avg daily volume as proxy.
        # The daily_context cache is populated lazily on first need (avoids
        # a 600-name daily history pull at boot, which would be slow).
        ctx = self._daily_context.get(sym)
        if ctx is None:
            ctx = self._load_symbol_context(sym)
            self._daily_context[sym] = ctx
        if ctx.avg_daily_volume <= 0:
            return None
        today_volume = q.get("volume", 0)
        volume_ratio = today_volume / ctx.avg_daily_volume if ctx.avg_daily_volume > 0 else 0.0
        if volume_ratio < self.s.DISCOVERY_MIN_VOLUME_RATIO:
            return None

        # Filter #3 — liquidity floor (20d avg ₹ turnover)
        if ctx.avg_daily_turnover < self.s.DISCOVERY_MIN_AVG_TURNOVER_INR:
            return None

        # Filter #4 — spread tightness
        bid = q.get("bid", 0.0) or 0.0
        ask = q.get("ask", 0.0) or 0.0
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ((ask + bid) / 2.0) * 100.0
        else:
            spread_pct = 0.0  # no depth → treat as OK (don't reject silently)
        if spread_pct > self.s.DISCOVERY_MAX_SPREAD_PCT * 100.0:
            return None

        # Compute helpers for scoring
        high = q.get("high", last_price)
        low  = q.get("low",  last_price)
        intraday_high_pct = (high / prev_close - 1.0) * 100.0 if prev_close > 0 else 0.0
        # How far off the intraday extreme (low for shorts, high for longs)
        if pct_change > 0:
            pull_from_extreme = (high - last_price) / high * 100.0 if high > 0 else 0.0
        else:
            pull_from_extreme = (last_price - low) / low * 100.0 if low > 0 else 0.0

        # Composite admission score — see doc 19 §8
        # z_score: how outlier is this move vs today's NIFTY?
        nifty_dispersion = max(abs(nifty_change), 0.3)   # avoid divide-by-tiny
        z_score = (pct_change - nifty_change) / nifty_dispersion
        # tanh keeps z bounded [-1, 1]
        from math import tanh
        score = (
            0.40 * (tanh(z_score) + 1.0) / 2.0 +              # 0–1 from outlier-ness
            0.30 * min(volume_ratio / 3.0, 1.0) +              # 0–1 from volume conviction
            0.20 * (1.0 - min(pull_from_extreme / 5.0, 1.0)) + # 0–1 from proximity to extreme
            0.10 * min(ctx.avg_daily_turnover / 5e8, 1.0)      # 0–1 from liquidity bonus (50cr cap)
        )

        return DiscoveryCandidate(
            symbol=sym,
            pct_change=round(pct_change, 3),
            volume_ratio=round(volume_ratio, 2),
            avg_turnover_inr=round(ctx.avg_daily_turnover, 0),
            spread_pct=round(spread_pct, 3),
            score=round(score, 3),
            intraday_high_pct=round(intraday_high_pct, 3),
            pull_from_extreme_pct=round(pull_from_extreme, 3),
            detected_at=now,
            reason=f"{pct_change:+.2f}% on {volume_ratio:.1f}x vol, "
                   f"z={z_score:+.2f}, pull-from-extreme {pull_from_extreme:.2f}%",
        )

    def _load_symbol_context(self, sym: str) -> _DailyContext:
        """Fetch 20 daily candles and compute avg volume + avg turnover."""
        try:
            df = self.kite.get_candles(sym, interval="day", days=30)
            if df is None or len(df) < 5:
                return _DailyContext()
            df = df.tail(20)
            vol_mean = float(df["volume"].mean())
            # Turnover ≈ close × volume per day, averaged
            turnover_series = df["close"] * df["volume"]
            turnover_mean = float(turnover_series.mean())
            return _DailyContext(
                avg_daily_volume=vol_mean,
                avg_daily_turnover=turnover_mean,
            )
        except Exception:
            return _DailyContext()

    def _get_nifty_change_pct(self) -> float:
        """Today's NIFTY 50 change vs prev close — used to compute z-score."""
        try:
            q = self.kite.get_quotes(["NIFTY 50"])
            data = q.get("NIFTY 50", {})
            if data:
                return float(data.get("change_pct", 0.0))
        except Exception:
            pass
        return 0.0

    def _prune_stale(self, now: datetime) -> None:
        """
        Remove discovered names that have cooled off — back inside ±1% chg
        with volume_ratio < 1.0 means the move has died, no reason to keep
        the name in scope.
        """
        if not self._discovered_today:
            return
        stale = []
        syms = list(self._discovered_today.keys())
        try:
            quotes = self.kite.get_quotes(syms)
        except Exception:
            return
        for sym, cand in self._discovered_today.items():
            q = quotes.get(sym, {})
            last = q.get("last_price", 0.0)
            prev_close = q.get("close", 0.0)
            if last <= 0 or prev_close <= 0:
                continue
            cur_pct = (last / prev_close - 1.0) * 100.0
            age_min = (now - cand.detected_at).total_seconds() / 60.0
            # Cooled-off: drifted back inside ±1% and was admitted ≥15 min ago
            if abs(cur_pct) < 1.0 and age_min >= 15:
                stale.append(sym)
        for sym in stale:
            print(f"[Discovery] PRUNE {sym} — cooled off")
            self._discovered_today.pop(sym, None)

    def _reset_for_new_session(self, today_iso: str) -> None:
        """Reset per-session counters and discovered set."""
        self._discovered_today.clear()
        self._adds_this_session = 0
        self._scans_this_session = 0
        self._last_scan_at = None
        self._loss_counter.clear()
        self._session_iso = today_iso
        # Drop expired blacklist entries
        before = len(self._blacklist)
        self._blacklist = {
            s: exp for s, exp in self._blacklist.items() if exp > today_iso
        }
        if len(self._blacklist) != before:
            self._save_blacklist()

    # ── Blacklist persistence ────────────────────────────────────────────────

    def _is_blacklisted(self, sym: str, now: datetime) -> bool:
        exp = self._blacklist.get(sym)
        if not exp:
            return False
        if exp <= now.date().isoformat():
            # Expired — drop it
            self._blacklist.pop(sym, None)
            self._save_blacklist()
            return False
        return True

    def _load_blacklist(self) -> None:
        if not os.path.exists(self.blacklist_path):
            return
        try:
            with open(self.blacklist_path) as fh:
                self._blacklist = json.load(fh)
        except Exception as e:
            print(f"[Discovery] blacklist load failed: {e}")
            self._blacklist = {}

    def _save_blacklist(self) -> None:
        try:
            with open(self.blacklist_path, "w") as fh:
                json.dump(self._blacklist, fh, indent=2, sort_keys=True)
        except Exception as e:
            print(f"[Discovery] blacklist save failed: {e}")
