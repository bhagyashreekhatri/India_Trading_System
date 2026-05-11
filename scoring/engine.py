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
