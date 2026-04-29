from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
from math import floor, ceil


# ─── Tick-size helpers (Fix #7) ───────────────────────────────────────────────
# NSE equities trade in ₹0.05 ticks. Live orders with non-tick prices reject.
# Use _round_to_tick for nominal rounding; _round_down/_up for direction-aware
# stop / target placement (always conservative — never widen risk).

_DEFAULT_TICK = 0.05

def _round_to_tick(price: float, tick: float = _DEFAULT_TICK) -> float:
    """Round to nearest valid tick. For entry prices and similar."""
    if price <= 0 or tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 2)

def _round_down_tick(price: float, tick: float = _DEFAULT_TICK) -> float:
    """Round DOWN to a valid tick. Use for LONG stop loss (gives the stop
    breathing room — never tighter than intended)."""
    if price <= 0 or tick <= 0:
        return round(price, 2)
    return round(floor(price / tick) * tick, 2)

def _round_up_tick(price: float, tick: float = _DEFAULT_TICK) -> float:
    """Round UP to a valid tick. Use for LONG entry / TP (asks for slightly
    more, never less)."""
    if price <= 0 or tick <= 0:
        return round(price, 2)
    return round(ceil(price / tick) * tick, 2)


# ─── Enums ────────────────────────────────────────────────────────────────────

class SetupType(str, Enum):
    MOMENTUM_BREAKOUT  = "momentum_breakout"
    VWAP_PULLBACK      = "vwap_pullback"
    VWAP_RECLAIM       = "vwap_reclaim"
    FAILED_BREAKDOWN   = "failed_breakdown"
    RANGE_BREAKOUT     = "range_breakout"
    RECOVERY_SETUP     = "recovery_setup"
    TREND_PULLBACK     = "trend_pullback"   # Fix #10 — strong-mover second-leg entry


class RegimeType(str, Enum):
    TRENDING   = "trending"
    CHOPPY     = "choppy"
    RECOVERING = "recovering"
    EVENT      = "event"


class Grade(str, Enum):
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
    """Output from Setup Detection Agent — unscored."""
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
    """Output from Volume + RS Agent."""
    symbol:           str
    current_volume:   float
    avg_volume_20:    float        # 20-period average volume
    volume_ratio:     float        # current / avg
    bid_ask_spread:   float        # as % of price
    liquidity_pass:   bool         # spread < 0.1% and volume > 1.2x


@dataclass
class MarketContext:
    """Output from Regime Detector Agent."""
    regime:                   RegimeType
    regime_confidence:        float          # 0–1
    nifty_above_vwap:         bool
    banknifty_above_vwap:     bool
    nifty_vwap_minutes:       int            # minutes above (positive) or below (negative)
    market_trend_aligned:     bool           # True if index trending with signal direction
    breadth_score:            float          # 0–1, % of stocks above VWAP


@dataclass
class RelativeStrengthData:
    """Part of Volume + RS Agent output."""
    symbol:                str
    stock_change_pct:      float
    nifty_change_pct:      float
    rs_delta:              float        # stock_change - nifty_change
    outperforming:         bool         # rs_delta > 0.5%


@dataclass
class NewsData:
    """Output from News Sentiment Agent."""
    symbol:          str
    has_news:        bool
    sentiment:       float        # -1.0 to +1.0
    catalyst_type:   str          # "earnings" | "split" | "news" | "none"
    headline:        str          = ""
    llm_score:       float        = 0.5


# ─── Score components (transparent breakdown) ─────────────────────────────────

@dataclass
class ScoreComponents:
    setup_quality:      float = 0.0    # 0–3
    volume_strength:    float = 0.0    # 0–2
    market_alignment:   float = 0.0    # 0–2
    relative_strength:  float = 0.0    # 0–2
    news_sentiment:     float = 0.0    # 0–1 (or −0.5 penalty)
    raw_score:          float = 0.0    # sum (0–10)
    regime_multiplier:  float = 1.0
    final_score:        float = 0.0    # raw × multiplier, capped at 10
    grade:              Grade  = Grade.C
    skip_reason:        str    = ""    # why it was skipped if applicable


# ─── Final output ─────────────────────────────────────────────────────────────

@dataclass
class ScoredSignal:
    signal:       RawSignal
    components:   ScoreComponents
    confidence:   float            # 0–1, candle quality confidence
    reason:       str              # human-readable explanation
    is_valid:     bool             # passed all filters
    proximity_ok: bool             # price not too far from entry


# ─── Scoring Engine ───────────────────────────────────────────────────────────

class ScoringEngine:
    """
    Pure scoring logic. No API calls. No side effects.
    Feed it data, get a ScoredSignal back.
    """

    REGIME_MULTIPLIERS: dict = {
        RegimeType.TRENDING: {
            SetupType.MOMENTUM_BREAKOUT: 1.2,
            SetupType.VWAP_PULLBACK:     1.0,
            SetupType.VWAP_RECLAIM:      1.0,
            SetupType.FAILED_BREAKDOWN:  1.0,
            SetupType.RANGE_BREAKOUT:    1.1,
            SetupType.RECOVERY_SETUP:    0.8,
            SetupType.TREND_PULLBACK:    1.3,   # Fix #10 — best fit: trending regime + strong mover pullback
        },
        RegimeType.CHOPPY: {
            SetupType.MOMENTUM_BREAKOUT: 0.6,
            SetupType.VWAP_PULLBACK:     1.2,
            SetupType.VWAP_RECLAIM:      1.1,
            SetupType.FAILED_BREAKDOWN:  1.1,
            SetupType.RANGE_BREAKOUT:    0.7,
            SetupType.RECOVERY_SETUP:    0.8,
            SetupType.TREND_PULLBACK:    0.7,   # counter-trend in chop — penalise
        },
        RegimeType.RECOVERING: {
            SetupType.MOMENTUM_BREAKOUT: 1.1,   # was 1.0 — momentum_breakout is the engine (84% WR, +96k in 6 days)
            SetupType.VWAP_PULLBACK:     1.0,
            SetupType.VWAP_RECLAIM:      1.4,
            SetupType.FAILED_BREAKDOWN:  0.8,   # was 1.1 — 33% WR; positive only because of one ADANIGREEN outlier
            SetupType.RANGE_BREAKOUT:    0.9,
            SetupType.RECOVERY_SETUP:    1.0,   # was 1.3 — 42% WR, -7k loss, lowest profit factor (0.63)
            SetupType.TREND_PULLBACK:    1.1,   # mild boost — recovering market with strong relative-strength names
        },
        RegimeType.EVENT: {
            SetupType.MOMENTUM_BREAKOUT: 0.7,
            SetupType.VWAP_PULLBACK:     0.7,
            SetupType.VWAP_RECLAIM:      0.7,
            SetupType.FAILED_BREAKDOWN:  0.7,
            SetupType.RANGE_BREAKOUT:    0.7,
            SetupType.RECOVERY_SETUP:    0.7,
            SetupType.TREND_PULLBACK:    0.7,
        },
    }

    # ── Component scorers ─────────────────────────────────────────────────────

    def _score_setup_quality(self, signal: RawSignal) -> tuple[float, float]:
        """
        Returns (setup_score 0-3, confidence 0-1).
        Confidence = how clean the candle was.
        """
        score = 0.0
        confidence_factors = []

        body_ratio = signal.candle_body_ratio
        close_pos  = signal.close_position

        # Body quality (strong close = high body ratio)
        if body_ratio >= 0.7:
            score += 1.5
            confidence_factors.append(1.0)
        elif body_ratio >= 0.5:
            score += 1.0
            confidence_factors.append(0.7)
        elif body_ratio >= 0.3:
            score += 0.5
            confidence_factors.append(0.4)
        else:
            confidence_factors.append(0.1)   # wick breakout, very weak

        # Close position in candle (for bullish: closed near top = good)
        if signal.direction == SignalDirection.LONG:
            if close_pos >= 0.75:
                score += 1.5
                confidence_factors.append(1.0)
            elif close_pos >= 0.55:
                score += 1.0
                confidence_factors.append(0.7)
            elif close_pos >= 0.4:
                score += 0.5
                confidence_factors.append(0.4)
            else:
                confidence_factors.append(0.1)
        else:
            # For short: closed near bottom = good
            inverted = 1.0 - close_pos
            if inverted >= 0.75:
                score += 1.5
                confidence_factors.append(1.0)
            elif inverted >= 0.55:
                score += 1.0
                confidence_factors.append(0.7)
            elif inverted >= 0.4:
                score += 0.5
                confidence_factors.append(0.4)
            else:
                confidence_factors.append(0.1)

        capped_score = min(score, 3.0)
        confidence   = sum(confidence_factors) / len(confidence_factors)
        return capped_score, confidence

    def _score_volume(self, vol: VolumeData) -> float:
        """Volume strength: 0–2 points."""
        if not vol.liquidity_pass:
            return 0.0      # reject — spread too wide or no volume
        ratio = vol.volume_ratio
        if ratio >= 2.5:
            return 2.0
        elif ratio >= 1.5:
            # linear interpolation between 1.5 and 2.5
            return 1.0 + (ratio - 1.5) / 1.0
        elif ratio >= 1.2:
            return 1.0
        else:
            return 0.0

    def _score_market_alignment(self, ctx: MarketContext, signal: RawSignal) -> float:
        """Market alignment: 0–2 points."""
        score = 0.0
        is_long = signal.direction == SignalDirection.LONG

        # Nifty alignment
        nifty_aligned = (is_long and ctx.nifty_above_vwap) or \
                        (not is_long and not ctx.nifty_above_vwap)
        if nifty_aligned:
            score += 1.0

        # Trend alignment (trend_aligned checks if index is trending with our direction)
        if ctx.market_trend_aligned:
            score += 1.0
        elif ctx.breadth_score >= 0.6 and is_long:
            score += 0.5      # broad market healthy even if not perfectly trending

        # Choppy regime penalty
        if ctx.regime == RegimeType.CHOPPY:
            score = max(0.0, score - 0.5)

        return min(score, 2.0)

    def _score_relative_strength(self, rs: RelativeStrengthData) -> float:
        """Relative strength vs index: 0–2 points."""
        delta = rs.rs_delta   # stock % change - nifty % change

        if delta >= 1.0:
            return 2.0
        elif delta >= 0.5:
            return 1.5
        elif delta >= 0.0:
            return 1.0
        elif delta >= -0.5:
            return 0.5
        else:
            return 0.0     # underperforming by more than 0.5% = no score

    def _score_news(self, news: NewsData) -> float:
        """
        News / sentiment: -0.5 to +1.0 points.

        Rebased 2026-04-28: no-news now returns 0.0 (was 0.5). The old +0.5
        baseline meant every newsless stock got a free half-point added to Raw,
        which was the dominant driver of A++ score inflation in the first 151
        trades (file 04 calibration analysis). Real positive sentiment must now
        be earned, not assumed.
        """
        if not news.has_news:
            return 0.0     # was 0.5 — no free credit for absence of news

        sentiment = news.llm_score   # 0–1 from LLM

        if news.catalyst_type == "earnings" and sentiment >= 0.7:
            return 1.0
        elif sentiment >= 0.7:
            return 1.0
        elif sentiment >= 0.5:
            return 0.7
        elif sentiment >= 0.3:
            return 0.4
        else:
            return -0.5    # negative news → penalty

    def _get_regime_multiplier(
        self,
        regime:     RegimeType,
        setup_type: SetupType,
    ) -> float:
        return self.REGIME_MULTIPLIERS[regime][setup_type]

    def _get_grade(self, score: float) -> Grade:
        if score >= 9.0:
            return Grade.A_PLUS_PLUS
        elif score >= 8.0:
            return Grade.A_PLUS
        elif score >= 7.0:
            return Grade.A
        elif score >= 5.0:
            return Grade.B
        else:
            return Grade.C

    def _check_proximity(
        self,
        signal:       RawSignal,
        max_drift_pct: float = 0.007,
    ) -> tuple[bool, float]:
        """
        Returns (is_ok, drift_pct).
        If current price has drifted >0.7% from entry, R:R is broken.
        """
        drift = abs(signal.current_price - signal.entry_price) / signal.entry_price
        return drift <= max_drift_pct, round(drift * 100, 3)

    def _build_reason(
        self,
        signal:     RawSignal,
        components: ScoreComponents,
        ctx:        MarketContext,
        news:       NewsData,
    ) -> str:
        parts = [
            f"{signal.setup_type.value.replace('_', ' ').title()} on {signal.symbol}",
            f"regime={ctx.regime.value}",
            f"setup={components.setup_quality:.1f}/3",
            f"vol={components.volume_strength:.1f}/2",
            f"mkt={components.market_alignment:.1f}/2",
            f"rs={components.relative_strength:.1f}/2",
            f"news={components.news_sentiment:.1f}/1",
            f"raw={components.raw_score:.1f}",
            f"×{components.regime_multiplier}",
            f"→ {components.final_score:.1f} [{components.grade.value}]",
        ]
        if news.has_news and news.headline:
            parts.append(f'| "{news.headline[:50]}"')
        return " | ".join(parts)

    # ── Main calculate method ──────────────────────────────────────────────────

    def calculate(
        self,
        signal:  RawSignal,
        volume:  VolumeData,
        context: MarketContext,
        rs:      RelativeStrengthData,
        news:    NewsData,
        proximity_max_pct: float = 0.007,
    ) -> ScoredSignal:
        """
        Main entry point. Feed all agent outputs, get a ScoredSignal back.
        """
        comp = ScoreComponents()

        # Hard reject: no liquidity
        if not volume.liquidity_pass:
            comp.skip_reason = "Rejected — liquidity fail (spread too wide or volume too low)"
            return ScoredSignal(
                signal=signal, components=comp,
                confidence=0.0, reason=comp.skip_reason,
                is_valid=False, proximity_ok=False,
            )

        # Score each component
        comp.setup_quality,   confidence  = self._score_setup_quality(signal)
        comp.volume_strength              = self._score_volume(volume)
        comp.market_alignment             = self._score_market_alignment(context, signal)
        comp.relative_strength            = self._score_relative_strength(rs)
        comp.news_sentiment               = self._score_news(news)

        # Raw score
        comp.raw_score = (
            comp.setup_quality +
            comp.volume_strength +
            comp.market_alignment +
            comp.relative_strength +
            comp.news_sentiment
        )
        comp.raw_score = round(max(0.0, min(10.0, comp.raw_score)), 2)

        # Regime multiplier
        comp.regime_multiplier = self._get_regime_multiplier(
            context.regime, signal.setup_type
        )

        # Final score
        comp.final_score = round(
            min(10.0, comp.raw_score * comp.regime_multiplier), 2
        )
        comp.grade = self._get_grade(comp.final_score)

        # Proximity check
        proximity_ok, drift_pct = self._check_proximity(signal, proximity_max_pct)
        if not proximity_ok:
            comp.skip_reason = f"Skipped — price ran {drift_pct}% from entry (R:R broken)"

        # Is valid for entry?
        is_valid = (
            proximity_ok and
            comp.final_score >= 5.0 and
            volume.liquidity_pass
        )

        reason = self._build_reason(signal, comp, context, news)

        return ScoredSignal(
            signal=signal,
            components=comp,
            confidence=round(confidence, 2),
            reason=reason,
            is_valid=is_valid,
            proximity_ok=proximity_ok,
        )
