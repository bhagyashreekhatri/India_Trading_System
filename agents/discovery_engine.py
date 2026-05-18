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
#
# 2026-05-18 v2: Kite's bulk instruments(NSE) returns ~9780 rows ALL tagged
# with instrument_type="EQ", but most are actually:
#   • Indices: "NIFTY50 PR 2X LEV", "INDIA VIX" (have spaces)
#   • Debt: "115VCCL31A-N0", "785TCHFL29-N0" (start with digits, -N\d suffix)
#   • SME / TT segment: "SIMCA-ST" (-ST suffix)
#   • ETFs / sovereign gold bonds: SBIETFNIF50, GOLDBEES etc.
# The first filter rejected only 98 names — pool came out at 9,538 (10× too many).
# This expanded set targets ~1500 actual NSE cash-equity names.

# SUBSTRING markers — these in ANY position mean non-EQ. ETF and BEES are
# unambiguous (no real NSE EQ name contains them).
_NON_EQ_SUBSTR_RE = re.compile(r"(ETF|BEES)", re.IGNORECASE)

# PREFIX markers — name STARTS with one of these. Cannot use substring on
# these because real EQ names exist with these letters elsewhere (e.g.
# INDIAMART, BHARATFORG, GOLDIAM). The leading-anchored regex avoids that.
#
# We do NOT include GOLD/SILVER/LIQUID/JUNIOR/GROWW/INDIA/BHARAT as prefixes
# because (a) the BEES/ETF substring catches the ones we care about and (b)
# real EQ names start with most of these strings.
_NON_EQ_PREFIX_RE = re.compile(
    r"^(NIFTY|SENSEX|VIX|SGB|TBILL|GS\d|GOI|CGB|CPSE|BHARAT22)",
    re.IGNORECASE,
)

# Combined "non-EQ name" check exposed for the filter pipeline.
def _is_non_eq_name(tsym: str) -> bool:
    return bool(_NON_EQ_SUBSTR_RE.search(tsym) or _NON_EQ_PREFIX_RE.match(tsym))

# Reject names ending in known non-EQ-cash suffixes:
#   -ST     : SME segment trade-to-trade
#   -SM     : SME segment (small-cap — illiquid, ineligible for intraday)
#   -N\d    : NCDs / debt notes        (e.g. 115VCCL31A-N0)
#   -SG/-GS : government securities suffix variants
#   -BE     : "Book Entry" — trade-to-trade equity (no intraday)
#   -BZ     : Surveillance segment T2T
#   -RT     : Rights
#   -RR     : REIT / Rights Renounce  (e.g. BIRET-RR, BAGMANE-RR)
#   -IV     : InvIT (Infrastructure Investment Trust)  (e.g. INTERISE-IV, PGINVIT-IV)
#   -NG     : ZC-NCD category G       (e.g. IIFLZC28-NG)
#   -Y\d    : debt note category Y    (e.g. ICICM58-Y1)
#   -IT     : trust segment           (e.g. BDR-IT)
#   -BL     : Block deal
# 2026-05-18 v3 expanded suffix list — pool was at 2,982 after v2; sample
# still leaked SME (-SM), REIT (-RR), InvIT (-IV), debt (-NG / -Y\d), trust
# (-IT). Target after v3: ~1500-1800 names (≤3 quote chunks → fewer
# Cloudflare strikes on the /quote endpoint).
_NON_EQ_SUFFIX_RE = re.compile(
    r"-(ST|SM|SF|N\d|SG|GS|RT|RR|IV|NG|Y\d|IT|BL|R\d|YL|YB|BC|BE|BZ|MF|ZC|ME|ML)\d*$"
)

# Real NSE EQ tradingsymbols match this shape:
#   start with letter, then alpha+digit+&, optional -ALPHANUM segment suffix.
# Rejects "INDIA VIX" (space), "115VCCL31A-N0" (leading digit).
_EQ_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9&]*(-[A-Z0-9]+)?$")

DEFAULT_BLACKLIST_PATH = "discovery_blacklist.json"
DEFAULT_DAILY_CTX_PATH = "discovery_daily_ctx.json"
DEFAULT_ADMITS_LOG_PATH = "discovery_admits.jsonl"   # append-only audit trail


def _str(v) -> str:
    """Coerce Kite SDK field to str. Older Kite SDK versions returned
    instrument field values as bytes; newer returns str. Defensive."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return str(v)


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
        daily_ctx_path: str = DEFAULT_DAILY_CTX_PATH,
        admits_log_path: str = DEFAULT_ADMITS_LOG_PATH,
    ):
        self.kite = kite
        # `core_universe` is the existing 150-stock hardcoded list. We use it
        # to filter out names that are already covered.
        self.core_universe = set(core_universe)
        self.blacklist_path = blacklist_path
        self.daily_ctx_path = daily_ctx_path
        self.admits_log_path = admits_log_path

        # Injected by crew.py after construction. Phase 2.1.2 — when present,
        # each admit is enriched with a NewsAPI+Groq catalyst headline on a
        # cold path (best-effort, never blocks scan). Default None so unit
        # tests don't need to mock the news client.
        self.news_client = None

        # Lazy-load settings so test code can pass a stub module.
        if settings_module is None:
            from config import settings as _settings
            settings_module = _settings
        self.s = settings_module

        # State
        self._candidate_pool: list[str] = []
        # Daily context is now persisted to disk keyed by (symbol, date) so it
        # survives restarts and Kite rate-limit pauses. Loaded at boot.
        self._daily_context: dict[str, _DailyContext] = {}
        self._daily_context_date: Optional[str] = None    # ISO date of cached data
        self._discovered_today: dict[str, DiscoveryCandidate] = {}
        self._blacklist: dict[str, str] = {}   # symbol → ISO date when expires
        self._loss_counter: dict[str, int] = {}
        self._last_scan_at: Optional[datetime] = None
        self._scans_this_session: int = 0
        self._adds_this_session: int = 0
        self._session_iso: Optional[str] = None
        # Phase 2.1.1 — per-scan budget so a fresh boot doesn't fire 100+
        # daily-history fetches in seconds and trip Kite's 10 req/s rate limit.
        # Reset at the start of every scan.
        self._ctx_fetches_this_scan: int = 0

        self._load_blacklist()
        self._load_daily_context()

    # ── Pool seeding ─────────────────────────────────────────────────────────

    def seed_candidate_pool(self) -> int:
        """
        Pull NSE EQ instruments from Kite (one call) and filter:
          - instrument_type == EQ  (excludes FUT/CE/PE/NSEIDX etc.)
          - tradingsymbol does not match ETF/BEES/GILT/NIFTY patterns
          - not already in core_universe (those go through the main path)

        The exchange filter is enforced by the `instruments("NSE")` call
        itself — no need to re-check segment field.

        2026-05-18 fix: was using `series` field which the Kite SDK's bulk
        `instruments()` endpoint does NOT return (that field is only in
        `search_instruments` responses). The correct field for cash-equity
        identification in the bulk feed is `instrument_type` (EQ/FUT/CE/PE).
        Boot log showed "non-EQ-series=9780" rejecting every row.

        Returns the number of names seeded into the candidate pool.
        Failure is non-fatal — pool stays empty; discovery silently no-ops.
        """
        # Resolve the underlying KiteConnect handle. KiteDataClient stores it
        # at `self.kite.kite`; bare KiteConnect (in tests) is the object itself.
        # Use explicit truthy check so None or missing attribute falls back.
        raw_kite = getattr(self.kite, "kite", None)
        if raw_kite is None:
            raw_kite = self.kite

        # Sanity — confirm we have a callable instruments() method
        if not hasattr(raw_kite, "instruments"):
            print(f"[Discovery] seed_candidate_pool: kite handle {type(raw_kite).__name__} "
                  f"has no .instruments() method — pool stays empty")
            self._candidate_pool = []
            return 0

        try:
            instruments = raw_kite.instruments("NSE")
        except Exception as e:
            print(f"[Discovery] seed_candidate_pool: instruments() raised: "
                  f"{type(e).__name__}: {e}")
            self._candidate_pool = []
            return 0

        if not instruments:
            print(f"[Discovery] seed_candidate_pool: instruments() returned EMPTY "
                  f"(type={type(instruments).__name__}). Kite rate limit or stale "
                  f"token? Pool stays empty.")
            self._candidate_pool = []
            return 0

        # Diagnostic counters — let us see exactly which filter rejected what
        # the next time pool size looks wrong.
        n_raw = len(instruments)
        n_no_tsym = 0
        n_non_eq_type = 0
        n_etf_pattern = 0
        n_bad_segment = 0
        n_bad_shape = 0       # leading digit / space / non-ASCII (debt / indices)
        n_bad_suffix = 0      # -ST / -N\d (SME / debt notes)
        n_in_core = 0
        pool: list[str] = []

        for inst in instruments:
            # Tolerate dict-of-bytes (older SDK) and dict-of-str alike.
            tsym = _str(inst.get("tradingsymbol", ""))
            itype = _str(inst.get("instrument_type", ""))
            seg = _str(inst.get("segment", ""))
            if not tsym:
                n_no_tsym += 1
                continue
            if itype != "EQ":
                n_non_eq_type += 1
                continue
            # Segment must be exactly "NSE" (cash equity). Excludes NSE-INDEX,
            # NSEINDEX, NSE-SME, NSE-DEBT, NSE-RIGHTS etc.
            if seg and seg != "NSE":
                n_bad_segment += 1
                continue
            # Shape: ASCII alpha+digit+&, optional -ALPHANUM segment suffix.
            # Rejects "INDIA VIX" (space), "115VCCL31A-N0" (leading digit).
            if not _EQ_SHAPE_RE.match(tsym):
                n_bad_shape += 1
                continue
            # Suffix: reject SME (-ST), debt notes (-N0..-N9), trading-restricted (-BE/-BZ),
            # rights/partly-paid/etc.
            if _NON_EQ_SUFFIX_RE.search(tsym):
                n_bad_suffix += 1
                continue
            # Name pattern: reject indices/ETFs/sovereign-bond instruments.
            # Uses substring match for ETF/BEES and prefix match for NIFTY/
            # SENSEX/SGB/TBILL/etc. See _is_non_eq_name docstring.
            if _is_non_eq_name(tsym):
                n_etf_pattern += 1
                continue
            if tsym in self.core_universe:
                n_in_core += 1
                continue
            pool.append(tsym)

        self._candidate_pool = pool
        print(
            f"[Discovery] seeded candidate pool — {len(pool)} names "
            f"(raw={n_raw}, no-tsym={n_no_tsym}, non-EQ-type={n_non_eq_type}, "
            f"bad-segment={n_bad_segment}, bad-shape={n_bad_shape}, "
            f"bad-suffix={n_bad_suffix}, ETF-pattern={n_etf_pattern}, "
            f"in-core={n_in_core})"
        )
        # Sample a few names so we can eyeball the result in logs
        if pool:
            sample = pool[:5] + ["..."] + pool[-3:] if len(pool) > 10 else pool
            print(f"[Discovery] sample: {sample}")
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

            # Phase 2.1.2 — cold-path news enrichment + audit log.
            # Best-effort: if NewsClient unreachable / Groq 429 / etc, we log
            # the admit without catalyst rather than block the scan.
            self._enrich_and_log_admit(cand)

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

        # Reset per-scan call budget so each scan gets a fresh allowance
        # for new daily-history fetches (cap is DISCOVERY_MAX_NEW_CONTEXT_
        # FETCHES_PER_SCAN, default 10).
        self._ctx_fetches_this_scan = 0

        # Filter out symbols we've already admitted today (don't re-admit)
        # or that are blacklisted.
        pool = [
            s for s in self._candidate_pool
            if s not in self._discovered_today and not self._is_blacklisted(s, now)
        ]
        if not pool:
            return []

        # Batch in chunks of 500 (Kite's quote API hard limit), with a 0.6s
        # sleep between chunks. Phase 2.1.3: Cloudflare started 403'ing the
        # /quote endpoint with a "Just a moment..." challenge page when 6+
        # 500-name chunks fired back-to-back at ~50ms intervals — the URL
        # length and request burst together looked bot-like. A sub-second
        # space between chunks lets each request fully drain and avoids
        # the burst signature without slowing total scan time meaningfully
        # (3 chunks × 0.6s = 1.8s overhead on a 30-60s scan).
        CHUNK = 500
        SLEEP_BETWEEN_CHUNKS_SEC = 0.6
        nifty_change = self._get_nifty_change_pct()

        # If two consecutive chunks come back empty, abort the rest of the
        # scan — almost certainly Cloudflare is blocking everything now and
        # further calls just dig the hole deeper.
        consecutive_empty = 0
        import time

        chunks = list(range(0, len(pool), CHUNK))
        for chunk_idx, i in enumerate(chunks):
            batch = pool[i : i + CHUNK]
            try:
                quotes = self.kite.get_quotes(batch)
            except Exception as e:
                print(f"[Discovery] get_quotes failed on chunk {i}-{i+CHUNK}: {e}")
                quotes = {}

            if not quotes:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    print(f"[Discovery] aborting scan — 2 consecutive empty "
                          f"chunks (Cloudflare block likely). "
                          f"Scanned {chunk_idx}/{len(chunks)} chunks.")
                    break
            else:
                consecutive_empty = 0
                for sym, q in quotes.items():
                    cand = self._build_candidate(sym, q, now, nifty_change)
                    if cand is not None:
                        survivors.append(cand)

            # Throttle between chunks. Skip the sleep after the final chunk
            # so we don't add latency to the last quote → first-candidate gap.
            if chunk_idx < len(chunks) - 1:
                time.sleep(SLEEP_BETWEEN_CHUNKS_SEC)

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
        # Cache lookup first — populated lazily on first need from
        # _load_symbol_context. Cache persists across restarts (disk-backed).
        ctx = self._daily_context.get(sym)
        if ctx is None or ctx.avg_daily_volume <= 0:
            # Respect per-scan call budget (avoid rate-limit on first scan)
            budget = getattr(self.s, "DISCOVERY_MAX_NEW_CONTEXT_FETCHES_PER_SCAN", 10)
            if self._ctx_fetches_this_scan >= budget:
                # Defer this candidate to next scan. Don't pollute the cache
                # with a failed empty result — let the symbol retry next time.
                return None
            self._ctx_fetches_this_scan += 1
            ctx = self._load_symbol_context(sym)
            if ctx.avg_daily_volume <= 0:
                # Fetch failed (Kite rate limit, no history, etc.) — do NOT
                # cache the empty result. Symbol gets another shot next scan.
                return None
            # Successful fetch — cache it and persist to disk.
            self._daily_context[sym] = ctx
            self._save_daily_context()
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

    # ── Daily-context persistence (Phase 2.1.1 rate-limit fix) ───────────────
    # 20-day avg volume / turnover changes once per day. We persist it to
    # disk so a restart doesn't trigger a 100+ Kite call storm. File format:
    #   { "date": "2026-05-18", "ctx": { "SYMBOL": {avg_vol, avg_turn}, ... } }
    # If the on-disk date matches today, we load it. Otherwise we treat it
    # as stale (yesterday's volumes are close enough but let's be precise)
    # and start fresh; the per-scan budget protects us from a storm.

    def _load_daily_context(self) -> None:
        if not os.path.exists(self.daily_ctx_path):
            return
        try:
            with open(self.daily_ctx_path) as fh:
                payload = json.load(fh)
            disk_date = payload.get("date", "")
            from datetime import date as _date
            today_iso = _date.today().isoformat()
            if disk_date != today_iso:
                # Stale — yesterday's context. Keep it loaded as a sane
                # starting estimate; will be overwritten as today's fetches
                # land. Avoids a full storm even on a stale cache file.
                self._daily_context_date = disk_date
            else:
                self._daily_context_date = today_iso
            for sym, fields in payload.get("ctx", {}).items():
                self._daily_context[sym] = _DailyContext(
                    avg_daily_volume=float(fields.get("avg_vol", 0)),
                    avg_daily_turnover=float(fields.get("avg_turn", 0)),
                )
            print(f"[Discovery] daily context cache: {len(self._daily_context)} "
                  f"symbols loaded ({'today' if self._daily_context_date == today_iso else 'stale: ' + (disk_date or 'unknown')})")
        except Exception as e:
            print(f"[Discovery] daily_context load failed (non-fatal): {e}")
            self._daily_context = {}

    def _save_daily_context(self) -> None:
        try:
            from datetime import date as _date
            payload = {
                "date": _date.today().isoformat(),
                "ctx": {
                    sym: {
                        "avg_vol":  ctx.avg_daily_volume,
                        "avg_turn": ctx.avg_daily_turnover,
                    }
                    for sym, ctx in self._daily_context.items()
                    if ctx.avg_daily_volume > 0    # never persist failed fetches
                },
            }
            with open(self.daily_ctx_path, "w") as fh:
                json.dump(payload, fh)
        except Exception as e:
            print(f"[Discovery] daily_context save failed (non-fatal): {e}")

    # ── Cold-path news enrichment + admit audit log ──────────────────────────

    def _enrich_and_log_admit(self, cand: DiscoveryCandidate) -> None:
        """
        Fire NewsAPI+Groq catalyst lookup for the newly-admitted candidate
        (cold path — never blocks the scan). Logs [DiscoveryNews] line and
        appends a JSONL record to discovery_admits.jsonl for offline
        recurring-pattern analysis.

        Why this matters: 2026-05-12 and 2026-05-18 both had JINDRILL +7-8%
        as the top discovery candidate. Same name, same direction, two weeks
        apart. The hypothesis is "oil services riding a crude rally" — but
        we should let the data tell us, not assume. NewsClient's daily cache
        means at most one Groq call per (symbol, day).
        """
        headline = ""
        sentiment = 0.5
        catalyst_type = ""

        nc = self.news_client
        if nc is not None:
            try:
                news = nc.get_news_for_symbol(cand.symbol)
                if news and getattr(news, "has_news", False):
                    headline = getattr(news, "headline", "") or ""
                    sentiment = float(getattr(news, "sentiment", 0.5) or 0.5)
                    catalyst_type = getattr(news, "catalyst_type", "") or ""
                    print(
                        f"[DiscoveryNews] {cand.symbol}: "
                        f"\"{headline[:80]}{'...' if len(headline) > 80 else ''}\"  "
                        f"sentiment={sentiment:.2f}  catalyst={catalyst_type or 'unknown'}"
                    )
            except Exception as e:
                print(f"[DiscoveryNews] {cand.symbol} enrich failed (non-fatal): "
                      f"{type(e).__name__}: {e}")

        # Append audit-log entry regardless of news availability so we can
        # mine the JSONL later for recurring patterns even if NewsAPI was
        # rate-limited.
        try:
            from datetime import datetime as _dt
            rec = {
                "ts": _dt.now().isoformat(),
                "symbol": cand.symbol,
                "pct_change": cand.pct_change,
                "volume_ratio": cand.volume_ratio,
                "turnover_inr": cand.avg_turnover_inr,
                "spread_pct": cand.spread_pct,
                "score": cand.score,
                "direction": cand.direction_bias,
                "headline": headline,
                "sentiment": sentiment,
                "catalyst_type": catalyst_type,
                "reason": cand.reason,
            }
            with open(self.admits_log_path, "a") as fh:
                fh.write(json.dumps(rec) + "\n")
        except Exception as e:
            # Audit-log failure should never break a scan — but log it once
            # so we know to fix the disk path / permissions.
            print(f"[Discovery] admits_log write failed (non-fatal): {e}")
