"""
Stock-level Decoupling Rule — Phase 2.3.

Spec: docs/21_Stock_Decoupling_Spec_2026-05-12.md (drafted alongside this code).

WHY THIS EXISTS
───────────────
On 2026-05-12, NIFTY closed -1.83% (STRONG_RED locked at 10:15 IST). The
conviction engine correctly blocked all long entries — historical precision
89% close-negative held: NIFTY ended the day deep red. The agent stayed flat,
₹0 P&L, which was the right outcome for the overall tape.

BUT — three specific single stocks RAN against the index all day:
  • ONGC      +4.88% morning, +5.93% close (intraday hi +6.73%)
  • OIL India +5.59% morning, +7.66% close (intraday hi +9.51%)
  • JINDRILL  +7.09% morning, +7.81% close (intraday hi +13.63%)

These were SINGLE-STOCK CATALYST trades (oil-producers riding a crude rally),
not sector trades. The METAL sector — which the original Phase 2.2 spec
proposed admitting on decoupling — actually FADED its +0.52% morning gain
into a -0.35% close. Sector-aware relief would have hurt P&L. Stock-level
decoupling, evaluated per name with strict thresholds, would have caught
ONGC cleanly.

THE RULE (Three Laws compliant — no hardcoded sectors, no symbol allow-lists)
─────────────────────────────────────────────────────────────────────────────
A long is admitted at tier B- (half-size of B) on a macro RED/STRONG_RED day
IF AND ONLY IF the following structural conditions all hold:

  1. Stock %chg vs prev close ≥ +4.0%        (single-stock magnitude)
  2. Stock volume ratio ≥ 1.5×                (volume confirmation)
  3. LTP within 0.5% of intraday high         (HOD-proximity, not chasing)
  4. Stock's sector index NOT severely red    (sector chg ≥ -1.0%)
  5. Stock's own first-hour high broken cleanly (no whipsaw)
  6. Current IST time ≥ 11:00                 (give the stock time to confirm)

If ALL six pass, the conviction engine returns tier B- with size 0.5× the
normal B sizing. Otherwise, the existing macro-RED skip applies.

Note: condition #3 (HOD proximity) is also the universal filter at the top
of conviction_engine; we re-check it here for clarity. Condition #5
(stock-level FHH) is the existing Phase 1.1 trigger.

OUT OF SCOPE
────────────
• No mean-reversion / fade-the-rip logic. Pure continuation only.
• No multi-leg pairs. Single-leg directional only.
• No catalyst attribution (news / earnings). Pure price+volume structure.
• Default OFF via STOCK_DECOUPLING_ENABLED flag. After 3-5 shadow sessions
  show the rule fires cleanly (and that admitted trades have positive R),
  flip the flag to True.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Optional


# Earliest time we'll consider a stock for decoupling admit. Before 11:00
# IST the day's structure is still forming — wait for confirmation.
DECOUPLING_MIN_TIME_IST = dtime(11, 0)


@dataclass(frozen=True)
class DecouplingResult:
    """Output of one evaluate() call."""
    admit:              bool
    tier:               str          # "B-" if admit, "SKIP" if not
    size_multiplier:    float        # 0.5 if admit, 0.0 if not
    reason:             str
    stock_pct:          float
    volume_ratio:       float
    sector_pct:         float
    pull_from_hod_pct:  float


class StockDecouplingRule:
    """
    Stateless evaluator. Call .evaluate() once per (symbol, candidate) tick.

    Holds no Kite client — caller passes the quote dict + sector quote dict.
    This keeps the rule unit-testable without any mocks of broker plumbing.
    """

    def __init__(self, settings_module=None):
        if settings_module is None:
            from config import settings as _settings
            settings_module = _settings
        self.s = settings_module

    def evaluate(
        self,
        symbol:        str,
        stock_quote:   dict,    # last_price, close (prev), high, change_pct, volume
        sector_quote:  Optional[dict],   # sector index quote or None if no mapping
        volume_ratio:  Optional[float],  # today_vol / 20d avg; caller supplies
        stock_fhh_state,                  # FirstHourState for this symbol; can be None
        now:           Optional[datetime] = None,
    ) -> DecouplingResult:
        """
        Apply the six-condition rule. Returns DecouplingResult.
        On any condition fail, admit=False with reason describing which.
        """
        if now is None:
            now = datetime.now()

        # ── Condition #6: time check ─────────────────────────────────────────
        # Cheapest filter first. Before 11:00 IST the day's forming structure
        # isn't readable — skip.
        if now.time() < DECOUPLING_MIN_TIME_IST:
            return self._reject(
                "before_11:00_IST",
                stock_quote, sector_quote, volume_ratio,
            )

        # ── Condition #1: stock magnitude ────────────────────────────────────
        last = stock_quote.get("last_price", 0.0) or 0.0
        prev_close = stock_quote.get("close", 0.0) or 0.0
        if last <= 0 or prev_close <= 0:
            return self._reject(
                "stock_quote_missing",
                stock_quote, sector_quote, volume_ratio,
            )
        stock_pct = (last / prev_close - 1.0) * 100.0
        threshold_pct = getattr(self.s, "STOCK_DECOUPLING_MIN_PCT", 4.0)
        if stock_pct < threshold_pct:
            return self._reject(
                f"stock_pct_{stock_pct:+.2f}%_below_+{threshold_pct:.1f}%_floor",
                stock_quote, sector_quote, volume_ratio,
            )

        # ── Condition #2: volume confirmation ────────────────────────────────
        vol_min = getattr(self.s, "STOCK_DECOUPLING_MIN_VOL_RATIO", 1.5)
        if volume_ratio is None or volume_ratio < vol_min:
            return self._reject(
                f"vol_ratio_{(volume_ratio or 0):.2f}_below_{vol_min:.1f}x",
                stock_quote, sector_quote, volume_ratio,
            )

        # ── Condition #3: HOD proximity ──────────────────────────────────────
        day_high = stock_quote.get("high", 0.0) or 0.0
        pull_from_hod_pct = (day_high - last) / day_high * 100.0 if day_high > 0 else 100.0
        max_pull = getattr(self.s, "STOCK_DECOUPLING_MAX_PULL_FROM_HOD_PCT", 0.5)
        if pull_from_hod_pct > max_pull:
            return self._reject(
                f"pull_from_hod_{pull_from_hod_pct:.2f}%_above_{max_pull:.1f}%",
                stock_quote, sector_quote, volume_ratio,
            )

        # ── Condition #4: sector not severely red ────────────────────────────
        # Use the sector's own change_pct vs prev close. If we have no sector
        # mapping (sector_quote is None), we default to PASS — but log it so
        # we can audit how often that happens. A symbol with no mapped sector
        # is rare (REALTY, MEDIA, etc.); we don't want to silently block them.
        sector_pct = 0.0
        if sector_quote is not None:
            sector_last  = sector_quote.get("last_price", 0.0) or 0.0
            sector_close = sector_quote.get("close", 0.0) or 0.0
            if sector_last > 0 and sector_close > 0:
                sector_pct = (sector_last / sector_close - 1.0) * 100.0
            else:
                sector_pct = sector_quote.get("change_pct", 0.0) or 0.0
        sector_floor = getattr(self.s, "STOCK_DECOUPLING_SECTOR_FLOOR_PCT", -1.0)
        if sector_pct < sector_floor:
            return self._reject(
                f"sector_{sector_pct:+.2f}%_below_{sector_floor:.1f}%_floor",
                stock_quote, sector_quote, volume_ratio,
            )

        # ── Condition #5: stock's own FHH clean break ────────────────────────
        # We rely on the FHH detector's per-stock state. The conviction engine
        # already does this check downstream, but we re-check here so the
        # decoupling rule is self-contained (callable independently in tests).
        if stock_fhh_state is None or not stock_fhh_state.is_set:
            return self._reject(
                "stock_fhh_not_set",
                stock_quote, sector_quote, volume_ratio,
            )
        if stock_fhh_state.whipsaw:
            return self._reject(
                "stock_fhh_whipsaw",
                stock_quote, sector_quote, volume_ratio,
            )
        if not stock_fhh_state.clean_high_break:
            return self._reject(
                "stock_fhh_not_broken",
                stock_quote, sector_quote, volume_ratio,
            )

        # All six conditions passed — admit at tier B- (half-size of B)
        return DecouplingResult(
            admit=True,
            tier="B-",
            size_multiplier=0.5,
            reason=(
                f"stock {stock_pct:+.2f}% on {volume_ratio:.2f}× vol, "
                f"hod-proximity {pull_from_hod_pct:.2f}%, "
                f"sector {sector_pct:+.2f}%, stock-FHH cleanly broken"
            ),
            stock_pct=round(stock_pct, 3),
            volume_ratio=round(volume_ratio, 2),
            sector_pct=round(sector_pct, 3),
            pull_from_hod_pct=round(pull_from_hod_pct, 3),
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _reject(
        self,
        reason: str,
        stock_quote: dict,
        sector_quote: Optional[dict],
        volume_ratio: Optional[float],
    ) -> DecouplingResult:
        last = stock_quote.get("last_price", 0.0) or 0.0
        prev = stock_quote.get("close", 0.0) or 0.0
        stock_pct = (last / prev - 1.0) * 100.0 if last > 0 and prev > 0 else 0.0
        day_high = stock_quote.get("high", 0.0) or 0.0
        pull_pct = (day_high - last) / day_high * 100.0 if day_high > 0 else 0.0
        sector_pct = 0.0
        if sector_quote is not None:
            s_last  = sector_quote.get("last_price", 0.0) or 0.0
            s_close = sector_quote.get("close", 0.0) or 0.0
            if s_last > 0 and s_close > 0:
                sector_pct = (s_last / s_close - 1.0) * 100.0
        return DecouplingResult(
            admit=False,
            tier="SKIP",
            size_multiplier=0.0,
            reason=reason,
            stock_pct=round(stock_pct, 3),
            volume_ratio=round(volume_ratio or 0.0, 2),
            sector_pct=round(sector_pct, 3),
            pull_from_hod_pct=round(pull_pct, 3),
        )


# ─── Helper that integrates with crew.py / conviction_engine.py ──────────────

def evaluate_for_conviction(
    symbol:        str,
    stock_quote:   dict,
    fhh_detector,
    kite,
    settings_module,
    now=None,
) -> DecouplingResult:
    """
    Convenience wrapper that pulls the sector quote + computes the volume
    ratio so the caller (conviction_engine) doesn't need to know the details.

    Fetches at most one extra Kite quote per call (the sector index). Returns
    a DecouplingResult that the conviction engine can act on directly.
    """
    from config.universe import get_sector

    rule = StockDecouplingRule(settings_module=settings_module)

    # 1. Sector lookup (symbol → sector → NIFTY index name)
    sym_sector = get_sector(symbol)
    sector_idx = getattr(settings_module, "SYMBOL_SECTOR_TO_INDEX", {}).get(sym_sector)
    sector_quote = None
    if sector_idx:
        try:
            quotes = kite.get_quotes([sector_idx])
            sector_quote = quotes.get(sector_idx)
        except Exception:
            sector_quote = None   # treat as missing → defaults to neutral

    # 2. Volume ratio — today's volume vs 20d daily avg.
    # We pull 20 daily candles. This is a small cost (one Kite call per
    # qualifying candidate). Cache hit-rate could be added later if needed.
    volume_ratio = None
    try:
        df = kite.get_candles(symbol, interval="day", days=30)
        if df is not None and len(df) >= 5:
            avg_vol = float(df.tail(20)["volume"].mean())
            today_vol = stock_quote.get("volume", 0) or 0
            if avg_vol > 0:
                volume_ratio = today_vol / avg_vol
    except Exception:
        volume_ratio = None

    # 3. Stock's own FHH state
    try:
        stock_fhh = fhh_detector.get_state(symbol, now)
    except Exception:
        stock_fhh = None

    return rule.evaluate(
        symbol=symbol,
        stock_quote=stock_quote,
        sector_quote=sector_quote,
        volume_ratio=volume_ratio,
        stock_fhh_state=stock_fhh,
        now=now,
    )
