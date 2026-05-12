"""
Conviction Engine — the new entry-decision module.

Replaces the deleted ScoringEngine. Instead of a 0-10 floating-point score
with multiplicative regime / sector / hour / breadth / news nudges (which
30 months of data proved was anti-predictive — A++ trades returned -0.095R
while A trades returned +0.092R), the conviction engine produces a binary
tier: S, A, B, or SKIP.

The tier is derived from two empirically-validated signals:

  1. 10:15 IST macro state (agents/market_state.py)
     - STRONG_GREEN / GREEN / YELLOW / RED / STRONG_RED / WAITING

  2. First-Hour-High (FHH) break state (agents/fhh_break_detector.py)
     - clean_high_break  → 100% / 97% / 88% bullish (S / A / B tiers)
     - whipsaw           → 70% chop, SKIP
     - inside_first_hour → too early, SKIP

Plus universal pre-entry filters that survived the audit:
  - Stock day_pct > 0   (don't long bouncing-from-low names)
  - Order book bid/sell ratio ≥ 1.5 (5-level aggregate, not top-of-book)
  - Spread ≤ 0.10%
  - Not RAG-vetoed (proven loser)
  - Not on symbol blacklist

Each tier maps to a fixed risk/reward sizing per config/settings.py:
  Tier S — full size, top conviction (STRONG_GREEN + FHH)
  Tier A — full size, high conviction (GREEN + FHH)
  Tier B — HALF size, medium conviction (YELLOW + FHH + high-grade setup)
  SKIP   — no entry

See docs/16_30Month_Final_Analysis_2026-05-11.md and
    docs/17_Rebuild_Plan_2026-05-11.md.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional


ConvictionTier = Literal["S", "A", "B", "SKIP"]


@dataclass
class ConvictionResult:
    """The output of the conviction engine for one (symbol, setup) candidate."""
    tier:                 ConvictionTier
    size_multiplier:      float    # 0.0 (SKIP), 0.5 (B), 1.0 (S/A)
    risk_inr:             float    # max acceptable loss in ₹
    target_inr:           float    # target profit in ₹
    reasoning:            str
    macro_state:          str
    fhh_state:            str
    failed_filters:       list[str]


class ConvictionEngine:
    """
    Decides whether to take a trade and at what size.

    Usage in crew.py:
        engine = ConvictionEngine(market_state_agent, fhh_detector)
        result = engine.evaluate(symbol, setup, stock_quote, order_book)
        if result.tier == "SKIP":
            self._rej(result.reasoning)
            continue
        qty = self._size_position(result, ltp, stop_loss)
        ...
    """

    NIFTY_FOR_FHH = "NIFTY 50"   # use NIFTY's FHH state as the macro break read

    def __init__(self, market_state_agent, fhh_detector):
        self.market_state = market_state_agent
        self.fhh_detector = fhh_detector
        # Phase 1.5/1.6/1.7 — injected by crew.py after construction.
        # Default None so tests using just market+fhh keep working.
        self.day_type = None
        self.vol_state = None

    def evaluate(
        self,
        symbol:      str,
        setup,                # RawSignal-like object with .grade etc., or None
        stock_quote: dict,    # {"last_price", "open", "high", "low", "close", "change_pct", ...}
        order_book:  Optional[dict] = None,  # full depth dict from kite_client
        now=None,
    ) -> ConvictionResult:
        """
        Returns a ConvictionResult. Universal filters fire FIRST (cheapest skips),
        then macro state, then FHH state, then tier mapping.

        Phase 1.1 enhancement (2026-05-11): Added stock-level FHH break check
        and HOD proximity gate. The NIFTY-level FHH state still acts as macro
        confirmation; the stock's OWN FHH break is the entry trigger; HOD
        proximity ensures we're not chasing extended moves.
        """
        from config.settings import (
            ORDER_BOOK_RATIO_MIN,
            SPREAD_MAX_PCT,
            CONVICTION_RISK_INR,
            CONVICTION_TARGET_INR,
            STOCK_HOD_PROXIMITY_PCT,
        )

        failed = []

        # ── Universal pre-entry filters ─────────────────────────────────────
        # 1. Stock must be up on the day (don't long bouncing-from-low stocks)
        if stock_quote.get("change_pct", 0.0) < 0.0:
            return _skip(
                "stock_negative_day",
                macro_state="-", fhh_state="-",
                failed=["stock_change_pct<0"],
            )

        # 1b. Stock must be near today's high — don't chase extended moves.
        # Validated 30-month finding: structural entry should be at or near
        # the fresh HOD. If LTP is >0.5% below the day high, the move has
        # already happened.
        ltp_pre = stock_quote.get("last_price", 0.0)
        day_high = stock_quote.get("high", 0.0)
        if ltp_pre > 0 and day_high > 0:
            below_hod_pct = (day_high - ltp_pre) / day_high
            if below_hod_pct > STOCK_HOD_PROXIMITY_PCT:
                return _skip(
                    f"stock_extended_off_hod_{below_hod_pct*100:.2f}%",
                    macro_state="-", fhh_state="-",
                    failed=[f"LTP {below_hod_pct*100:.2f}% below day high (max {STOCK_HOD_PROXIMITY_PCT*100:.1f}%)"],
                )

        # 2. Spread filter
        bid = stock_quote.get("bid", 0.0)
        ask = stock_quote.get("ask", 0.0)
        ltp = stock_quote.get("last_price", 0.0)
        if bid > 0 and ask > 0 and ltp > 0:
            spread_pct = (ask - bid) / ltp
            if spread_pct > SPREAD_MAX_PCT:
                return _skip(
                    f"spread_too_wide_{spread_pct*100:.2f}%",
                    macro_state="-", fhh_state="-",
                    failed=[f"spread {spread_pct*100:.3f}% > {SPREAD_MAX_PCT*100:.3f}%"],
                )

        # 3. 5-level order-book depth ratio (replaces top-of-book naive read)
        if order_book is not None:
            ob_ratio = _compute_5level_depth_ratio(order_book)
            if ob_ratio < ORDER_BOOK_RATIO_MIN:
                return _skip(
                    f"weak_order_book_ratio_{ob_ratio:.2f}",
                    macro_state="-", fhh_state="-",
                    failed=[f"5-level bid/sell {ob_ratio:.2f} < {ORDER_BOOK_RATIO_MIN}"],
                )

        # ── Macro state filter (validated on 584 sessions) ──────────────────
        macro_snap = self.market_state.get_state(now)

        if macro_snap.state == "WAITING":
            return _skip(
                "macro_waiting_pre_1015",
                macro_state="WAITING", fhh_state="-",
                failed=["before 10:15 IST"],
            )

        if macro_snap.state in ("STRONG_RED", "RED"):
            # Phase 2.3 — stock-level decoupling override. On adversarial macro
            # days, a single stock that meets the six-condition rule (large
            # magnitude + volume + HOD proximity + sector-not-severely-red +
            # own-FHH-clean-break + after 11:00 IST) may still be admitted at
            # tier B- (half-size). Catches the 2026-05-12 ONGC +5.93% case
            # that the binary macro gate blocked.
            #
            # Default-OFF via STOCK_DECOUPLING_ENABLED. When OFF the rule still
            # evaluates and logs admits (shadow mode), but returns the same
            # SKIP as before — so we collect evidence without trading on it.
            from config.settings import STOCK_DECOUPLING_ENABLED
            try:
                from agents.stock_decoupling import evaluate_for_conviction
                import config.settings as _settings_mod
                # The decoupling rule needs the Kite client. Conviction engine
                # was originally pure (no Kite); we get it via the FHH
                # detector's reference. This is a thin coupling — acceptable
                # for one feature, and easily refactored later.
                kite_ref = getattr(self.fhh_detector, "kite", None)
                if kite_ref is not None:
                    dec_res = evaluate_for_conviction(
                        symbol=symbol,
                        stock_quote=stock_quote,
                        fhh_detector=self.fhh_detector,
                        kite=kite_ref,
                        settings_module=_settings_mod,
                        now=now,
                    )
                    if dec_res.admit:
                        marker = "ENABLED" if STOCK_DECOUPLING_ENABLED else "SHADOW"
                        print(
                            f"[Decoupling] {symbol} ADMIT-{marker} on macro "
                            f"{macro_snap.state} — {dec_res.reason}"
                        )
                        if STOCK_DECOUPLING_ENABLED:
                            # Build a tier-B-equivalent result with half-size.
                            from config.settings import CONVICTION_RISK_INR, CONVICTION_TARGET_INR
                            return ConvictionResult(
                                tier="B",
                                size_multiplier=0.5 * dec_res.size_multiplier * 2,  # 0.5 net
                                risk_inr=CONVICTION_RISK_INR.get("B", 750) * 0.5,
                                target_inr=CONVICTION_TARGET_INR.get("B", 1500) * 0.5,
                                reasoning=f"decoupling-override-on-{macro_snap.state}: {dec_res.reason}",
                                macro_state=macro_snap.state,
                                fhh_state="decoupling_override",
                                failed_filters=[],
                            )
                        # Shadow mode — fall through to skip below
                    elif dec_res.stock_pct >= 2.0:
                        # Only log near-misses (stock at least up 2%) to keep
                        # log volume manageable on a 60-symbol scan.
                        print(
                            f"[Decoupling] {symbol} would-skip — "
                            f"{dec_res.reason} "
                            f"(stock {dec_res.stock_pct:+.2f}%, "
                            f"vol×{dec_res.volume_ratio:.2f}, "
                            f"sector {dec_res.sector_pct:+.2f}%)"
                        )
            except Exception as e:
                print(f"[Decoupling] evaluator error (non-fatal): {e}")

            # Normal RED / STRONG_RED skip path (unchanged behaviour by default)
            if macro_snap.state == "STRONG_RED":
                return _skip(
                    f"macro_strong_red ({macro_snap.reasoning})",
                    macro_state="STRONG_RED", fhh_state="-",
                    failed=["macro STRONG_RED — 89% of these days close negative"],
                )
            return _skip(
                f"macro_red ({macro_snap.reasoning})",
                macro_state="RED", fhh_state="-",
                failed=["macro RED — 74% of these days close negative"],
            )

        # ── First-Hour break state (NIFTY level — macro signal) ─────────────
        from config.settings import (
            REQUIRE_STOCK_FHH_BREAK, WHIPSAW_FREEZE_ENABLED,
        )
        fhh_state = self.fhh_detector.get_state(self.NIFTY_FOR_FHH, now)

        if not fhh_state.is_set:
            return _skip(
                "fhh_not_yet_set",
                macro_state=macro_snap.state, fhh_state="not_set",
                failed=["first hour not yet captured"],
            )

        # ── Whipsaw freeze (Phase 1.3) ──────────────────────────────────────
        # 30-month evidence: NIFTY whipsaw (both FHH and FHL broken) →
        # 70% of those days close flat. Freeze all entries when detected.
        if WHIPSAW_FREEZE_ENABLED and fhh_state.whipsaw:
            return _skip(
                "whipsaw_freeze_nifty",
                macro_state=macro_snap.state, fhh_state="whipsaw",
                failed=["NIFTY whipsaw (both FHH+FHL broken) — 70% historical chop"],
            )

        # NIFTY FHH break = market-wide bullish confirmation
        if not fhh_state.clean_high_break:
            return _skip(
                "nifty_fhh_not_broken",
                macro_state=macro_snap.state, fhh_state="inside_or_below",
                failed=["NIFTY FHH not yet broken — no macro continuation signal"],
            )

        # ── Stock-level FHH break (Phase 1.1 — the entry trigger) ───────────
        # The 30-month research validated NIFTY's FHH break as the macro
        # signal. For an individual STOCK entry, we additionally require the
        # stock's OWN first-hour-high to be broken. This is the "stock is
        # structurally breaking out, AND macro confirms it" combo.
        if REQUIRE_STOCK_FHH_BREAK:
            stock_fhh = self.fhh_detector.get_state(symbol, now)
            if not stock_fhh.is_set:
                return _skip(
                    f"stock_fhh_not_set_{symbol}",
                    macro_state=macro_snap.state, fhh_state="nifty_ok_stock_pending",
                    failed=[f"{symbol} first hour not yet captured"],
                )
            if stock_fhh.whipsaw:
                return _skip(
                    f"stock_whipsaw_{symbol}",
                    macro_state=macro_snap.state, fhh_state="nifty_ok_stock_whipsaw",
                    failed=[f"{symbol} both FHH+FHL broken — stock-level chop"],
                )
            if not stock_fhh.clean_high_break:
                return _skip(
                    f"stock_fhh_not_broken_{symbol}",
                    macro_state=macro_snap.state, fhh_state="nifty_ok_stock_inside",
                    failed=[f"{symbol} FHH not yet broken"],
                )

        # ── Day-type classifier (Phase 1.5 — refine routing) ───────────────
        # By 11:00 IST the day's forming structure is readable. We skip the
        # most adverse class — TREND_FORMING_DN — because long-only entries
        # in a clearly down-trending tape have very low success.
        # RANGE_FORMING days don't favor momentum_breakout (the only active
        # setup) — momentum needs expansion, not compression.
        if self.day_type is not None:
            try:
                dt_snap = self.day_type.get_snapshot(now)
                if dt_snap.type == "TREND_FORMING_DN":
                    return _skip(
                        f"day_type_trend_down ({dt_snap.reasoning})",
                        macro_state=macro_snap.state, fhh_state="ok_but_day_down",
                        failed=[dt_snap.reasoning],
                    )
                if dt_snap.type == "RANGE_FORMING":
                    return _skip(
                        f"day_type_range_compression ({dt_snap.reasoning})",
                        macro_state=macro_snap.state, fhh_state="ok_but_day_compressed",
                        failed=[dt_snap.reasoning],
                    )
                # TREND_FORMING_UP / BALANCED / WAITING → proceed (BALANCED
                # is fine — the conviction tier handles caution sizing).
            except Exception as e:
                print(f"[Conviction] day_type read error (proceeding): {e}")

        # ── Volatility state read (Phase 1.7 — adaptive size mult) ─────────
        # The size multiplier is applied DOWNSTREAM in crew.py when computing
        # qty. We just read the state here so the conviction result can
        # surface it (e.g., via reasoning text) and crew.py can apply it.
        vol_size_mult = 1.0
        vol_note = ""
        if self.vol_state is not None:
            try:
                vs = self.vol_state.get_state(now)
                if vs is not None:
                    vol_size_mult = vs.size_multiplier
                    if vs.is_nr7:
                        vol_note = " (post-NR7 expansion expected)"
                    if vs.regime != "NORMAL":
                        vol_note = f" (vol {vs.regime.lower()}, size ×{vs.size_multiplier:.1f}){vol_note}"
            except Exception as e:
                print(f"[Conviction] vol_state read error (proceeding): {e}")

        # ── Tier mapping ────────────────────────────────────────────────────
        # All gates passed. Map (macro_state, fhh_state) to tier.

        if macro_snap.state == "STRONG_GREEN":
            return ConvictionResult(
                tier="S",
                size_multiplier=1.0 * vol_size_mult,
                risk_inr=CONVICTION_RISK_INR["S"] * vol_size_mult,
                target_inr=CONVICTION_TARGET_INR["S"],
                reasoning=f"TIER_S — STRONG_GREEN macro + NIFTY FHH + {symbol} FHH + stock at HOD{vol_note}",
                macro_state="STRONG_GREEN",
                fhh_state="triple_confluence_break",
                failed_filters=[],
            )

        if macro_snap.state == "GREEN":
            return ConvictionResult(
                tier="A",
                size_multiplier=1.0 * vol_size_mult,
                risk_inr=CONVICTION_RISK_INR["A"] * vol_size_mult,
                target_inr=CONVICTION_TARGET_INR["A"],
                reasoning=f"TIER_A — GREEN macro + NIFTY FHH + {symbol} FHH + stock at HOD{vol_note}",
                macro_state="GREEN",
                fhh_state="triple_confluence_break",
                failed_filters=[],
            )

        if macro_snap.state == "YELLOW":
            # Tier B requires high-quality setup grade in addition to FHH break
            grade = getattr(setup, "grade", None)
            grade_str = grade.value if hasattr(grade, "value") else str(grade) if grade else ""
            if grade_str not in ("A++", "A+"):
                return _skip(
                    "yellow_macro_requires_high_grade",
                    macro_state="YELLOW", fhh_state="clean_high_break",
                    failed=[f"YELLOW + FHH requires setup grade A+/A++; got {grade_str or '(none)'}"],
                )
            return ConvictionResult(
                tier="B",
                size_multiplier=0.5 * vol_size_mult,
                risk_inr=CONVICTION_RISK_INR["B"] * vol_size_mult,
                target_inr=CONVICTION_TARGET_INR["B"],
                reasoning=f"TIER_B — YELLOW + FHH + {grade_str} grade — HALF SIZE{vol_note}",
                macro_state="YELLOW",
                fhh_state="clean_high_break",
                failed_filters=[],
            )

        # Should not reach here.
        return _skip(
            "unexpected_macro_state",
            macro_state=macro_snap.state, fhh_state=str(fhh_state.clean_high_break),
            failed=[f"unexpected macro state: {macro_snap.state}"],
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _skip(reason: str, macro_state: str, fhh_state: str, failed: list[str]) -> ConvictionResult:
    return ConvictionResult(
        tier="SKIP",
        size_multiplier=0.0,
        risk_inr=0.0,
        target_inr=0.0,
        reasoning=reason,
        macro_state=macro_state,
        fhh_state=fhh_state,
        failed_filters=failed,
    )


def _compute_5level_depth_ratio(order_book: dict) -> float:
    """
    Sum bid_qty across top-5 levels / sum sell_qty across top-5 levels.

    Validated finding from 18-month research: top-of-book ratio is easily
    spoofed by a single large order. 5-level aggregate is more robust.

    Returns 99.0 if there's no sell side (degenerate book → permissive).
    """
    try:
        buy = order_book.get("buy", []) or order_book.get("depth", {}).get("buy", [])
        sell = order_book.get("sell", []) or order_book.get("depth", {}).get("sell", [])
        buy_total = sum(float(lv.get("quantity", 0)) for lv in buy[:5])
        sell_total = sum(float(lv.get("quantity", 0)) for lv in sell[:5])
        if sell_total <= 0:
            return 99.0
        return buy_total / sell_total
    except Exception:
        return 1.0  # safe default — neutral
