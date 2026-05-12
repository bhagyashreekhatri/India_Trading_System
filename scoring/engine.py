"""
Trading data types and enums.

NOTE — Phase 0 rebuild (2026-05-11): The original ScoringEngine class (multi-input
0-10 score with regime multipliers) was deleted. 30-month NIFTY validation showed
the score system was anti-predictive — A++ trades returned -0.095R while A trades
returned +0.092R across 280 trades. See docs/12_Audit_1Month_Validation_2026-05-11.md
and docs/16_30Month_Final_Analysis_2026-05-11.md for the full evidence.

The new entry-decision flow uses agents/conviction_engine.py, which combines
the 10:15 IST macro state with the first-hour-high (FHH) break to produce a
binary tier (S/A/B/SKIP). That mechanism was validated at 97-100% precision
on 44 STRONG_GREEN+FHH events across 30 months.

This file is preserved as the home for the trading data types so existing
imports across the codebase keep working without disruption during the
gradual cutover.

Tick-rounding helpers were extracted to tools/tick_utils.py — import from there.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime

# Tick-rounding helpers moved to tools/tick_utils.py — re-export here for
# backward compatibility during the cutover. New code should import from
# tools.tick_utils directly.
from tools.tick_utils import _round_to_tick, _round_down_tick, _round_up_tick  # noqa: F401


# ─── Enums ────────────────────────────────────────────────────────────────────

class SetupType(str, Enum):
    """
    Active setups after Phase 0 rebuild:
      - MOMENTUM_BREAKOUT — only setup with gross+net edge in 280-trade audit
      - FHH_BREAK         — first-hour-high break (30-month-validated at 97-100% w/ macro)

    Other setup-type members are retained ONLY because the trade history database
    has rows referring to them. The detectors that produced these setups have
    been disarmed and will be deleted from pattern_tools.py.
    """
    MOMENTUM_BREAKOUT  = "momentum_breakout"
    FHH_BREAK          = "fhh_break"          # NEW — Phase 0 rebuild
    # Below: retained for DB-compat / legacy reading only. Detectors disarmed.
    VWAP_PULLBACK      = "vwap_pullback"
    VWAP_RECLAIM       = "vwap_reclaim"
    FAILED_BREAKDOWN   = "failed_breakdown"
    RANGE_BREAKOUT     = "range_breakout"
    RECOVERY_SETUP     = "recovery_setup"
    TREND_PULLBACK     = "trend_pullback"
    INSIDE_BAR_BREAK   = "inside_bar_break"


class RegimeType(str, Enum):
    TRENDING   = "trending"
    CHOPPY     = "choppy"
    RECOVERING = "recovering"
    EVENT      = "event"


class Grade(str, Enum):
    """
    NOTE: Grade-based decisions are being phased out. The conviction_engine
    produces tier S/A/B/SKIP based on macro+FHH state, not grades. Grades are
    retained for telemetry display and historical critique only.
    """
    A_PLUS_PLUS = "A++"
    A_PLUS      = "A+"
    A           = "A"
    B           = "B"
    C           = "C"


class SignalDirection(str, Enum):
    LONG  = "long"
    SHORT = "short"


# ─── Input dataclasses ────────────────────────────────────────────────────────

@dataclass
class RawSignal:
    """A trading signal from a setup detector — unscored."""
    symbol:            str
    setup_type:        SetupType
    direction:         SignalDirection
    entry_price:       float
    stop_loss:         float
    target_price:      float
    current_price:     float
    candle_body_ratio: float       # body / total candle range (0–1)
    close_position:    float       # where close sits in candle range (0=low, 1=high)
    detected_at:       datetime    = field(default_factory=datetime.now)
    sector:            str         = "OTHER"


@dataclass
class VolumeData:
    """Volume + spread + liquidity summary for a symbol."""
    symbol:           str
    current_volume:   float
    avg_volume_20:    float        # 20-period average volume
    volume_ratio:     float        # current / avg
    bid_ask_spread:   float        # as % of price
    liquidity_pass:   bool         # spread < 0.1% and volume > 1.2x


@dataclass
class MarketContext:
    """Market regime and breadth context."""
    regime:                   RegimeType
    regime_confidence:        float          # 0–1
    nifty_above_vwap:         bool
    banknifty_above_vwap:     bool
    nifty_vwap_minutes:       int            # minutes above (positive) or below (negative)
    market_trend_aligned:     bool           # True if index trending with signal direction
    breadth_score:            float          # 0–1, % of stocks above VWAP


@dataclass
class RelativeStrengthData:
    """Stock vs index relative-strength snapshot."""
    symbol:                str
    stock_change_pct:      float
    nifty_change_pct:      float
    rs_delta:              float        # stock_change - nifty_change
    outperforming:         bool         # rs_delta > 0.5%


@dataclass
class NewsData:
    """News sentiment snapshot for a symbol (used at premarket / EOD cold paths)."""
    symbol:          str
    has_news:        bool
    sentiment:       float        # -1.0 to +1.0
    catalyst_type:   str          # "earnings" | "split" | "news" | "none"
    headline:        str          = ""
    llm_score:       float        = 0.5


# ─── Telemetry-only types (retained for dashboard / RAG storage) ─────────────

@dataclass
class ScoreComponents:
    """
    Telemetry-only score breakdown.

    Phase 0 NOTE: This was the old scoring engine's output. It's retained as a
    debug telemetry struct so existing rows in trade_state.db remain readable.
    The conviction_engine does NOT produce ScoreComponents — it produces a tier
    (S/A/B/SKIP).
    """
    setup_quality:      float = 0.0
    volume_strength:    float = 0.0
    market_alignment:   float = 0.0
    relative_strength:  float = 0.0
    news_sentiment:     float = 0.0
    raw_score:          float = 0.0
    regime_multiplier:  float = 1.0
    final_score:        float = 0.0
    grade:              Grade  = Grade.C
    skip_reason:        str    = ""


@dataclass
class ScoredSignal:
    """
    A signal with telemetry attached. The 'is_valid' flag is now set by the
    conviction_engine path, not the deleted ScoringEngine.
    """
    signal:       RawSignal
    components:   ScoreComponents
    confidence:   float
    reason:       str
    is_valid:     bool
    proximity_ok: bool


# ─── ScoringEngine stub (Phase 0 rebuild — DEPRECATED) ──────────────────────
#
# The original ScoringEngine was deleted (it was the 0-10 score system with
# multiplicative regime/news/sector nudges that was empirically anti-predictive).
# This stub remains because crew.py's legacy `_score_signals` path still
# instantiates `ScoringEngine()` and calls `.calculate(...)` to produce a
# ScoreComponents object for telemetry display.
#
# The conviction_engine (agents/conviction_engine.py) is the actual entry
# authority. This stub returns NEUTRAL components (raw_score = 5.0, grade = B)
# so the legacy path keeps booting; conviction_engine gates real decisions.

class ScoringEngine:
    """
    DEPRECATED stub. Returns neutral telemetry-only ScoreComponents.

    The real entry authority is agents/conviction_engine.py.

    Kept so crew.py's legacy `_score_signals` keeps booting during the
    feature-flagged rollout. After conviction_engine forward-validates, the
    legacy `_score_signals` body should be deleted and this stub removed.
    """

    def calculate(
        self,
        signal:  RawSignal,
        volume:  VolumeData,
        context: MarketContext,
        rs:      RelativeStrengthData,
        news:    NewsData,
    ) -> ScoredSignal:
        """
        Returns a neutral ScoredSignal. The conviction engine in crew.py
        runs AFTER this and is what actually decides whether to enter.

        Setup-quality is naively scored from the candle body ratio (0-3).
        Everything else defaults to 0. raw_score lands ~3-6; multiplier 1.0;
        grade derived from final_score buckets.

        This is JUST telemetry — the conviction engine is the real gate.
        """
        # Naive setup quality from candle body ratio (0-3 scale)
        setup_quality = max(0.0, min(3.0, signal.candle_body_ratio * 3.0))

        # Volume strength based on volume_ratio (0-2 scale)
        vol_strength = max(0.0, min(2.0, (volume.volume_ratio - 0.8) * 1.5))

        # Market alignment based on trend alignment + breadth (0-2)
        mkt_align = (1.0 if context.market_trend_aligned else 0.5) + \
                    max(0.0, min(1.0, context.breadth_score - 0.4))

        # Relative strength (0-2)
        rs_score = 2.0 if rs.outperforming else max(0.0, min(2.0, 1.0 + rs.rs_delta * 0.3))

        # News (0-1) — kept for backward compat, but news_score from caller is
        # mostly 0.5 (default) since news is moved to cold-path only.
        news_score = max(0.0, min(1.0, 0.5 + news.sentiment * 0.5))

        raw = setup_quality + vol_strength + mkt_align + rs_score + news_score
        raw = round(min(10.0, max(0.0, raw)), 2)

        # No regime multiplier — that was the broken part of the old engine.
        final = raw

        # Grade buckets (telemetry only — does not gate entries)
        if   final >= 9.0: grade = Grade.A_PLUS_PLUS
        elif final >= 8.0: grade = Grade.A_PLUS
        elif final >= 7.0: grade = Grade.A
        elif final >= 5.0: grade = Grade.B
        else:              grade = Grade.C

        comp = ScoreComponents(
            setup_quality=round(setup_quality, 2),
            volume_strength=round(vol_strength, 2),
            market_alignment=round(mkt_align, 2),
            relative_strength=round(rs_score, 2),
            news_sentiment=round(news_score, 2),
            raw_score=raw,
            regime_multiplier=1.0,
            final_score=final,
            grade=grade,
            skip_reason="",
        )

        return ScoredSignal(
            signal=signal,
            components=comp,
            confidence=max(0.0, min(1.0, signal.close_position)),
            reason=f"telemetry-only score {final:.1f} ({grade.value}); conviction_engine is the real gate",
            is_valid=(final >= 5.0),
            proximity_ok=True,   # conviction_engine handles proximity now
        )
