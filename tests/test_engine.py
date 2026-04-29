"""
Test the scoring engine in complete isolation.
No Kite, no APIs, no internet needed.
Run: python -m pytest tests/test_engine.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from scoring.engine import (
    ScoringEngine, RawSignal, VolumeData, MarketContext,
    RelativeStrengthData, NewsData,
    SetupType, RegimeType, Grade, SignalDirection,
)

engine = ScoringEngine()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_signal(
    symbol="HDFCBANK",
    setup_type=SetupType.VWAP_RECLAIM,
    direction=SignalDirection.LONG,
    entry=1742.0,
    sl=1727.0,
    target=1764.0,
    current=1743.0,
    body_ratio=0.75,
    close_pos=0.85,
    sector="BANKING",
) -> RawSignal:
    return RawSignal(
        symbol=symbol, setup_type=setup_type, direction=direction,
        entry_price=entry, stop_loss=sl, target_price=target,
        current_price=current, candle_body_ratio=body_ratio,
        close_position=close_pos, sector=sector,
    )


def make_volume(ratio=2.1, spread=0.05, liquidity=True) -> VolumeData:
    avg = 100_000
    return VolumeData(
        symbol="HDFCBANK",
        current_volume=avg * ratio,
        avg_volume_20=avg,
        volume_ratio=ratio,
        bid_ask_spread=spread,
        liquidity_pass=liquidity,
    )


def make_context(
    regime=RegimeType.RECOVERING,
    nifty_above=True,
    bnf_above=True,
    nifty_min=30,
    trend_aligned=True,
    breadth=0.65,
) -> MarketContext:
    return MarketContext(
        regime=regime,
        regime_confidence=0.85,
        nifty_above_vwap=nifty_above,
        banknifty_above_vwap=bnf_above,
        nifty_vwap_minutes=nifty_min,
        market_trend_aligned=trend_aligned,
        breadth_score=breadth,
    )


def make_rs(stock_chg=0.9, nifty_chg=0.2) -> RelativeStrengthData:
    delta = stock_chg - nifty_chg
    return RelativeStrengthData(
        symbol="HDFCBANK",
        stock_change_pct=stock_chg,
        nifty_change_pct=nifty_chg,
        rs_delta=delta,
        outperforming=delta > 0.5,
    )


def make_news(has=True, sentiment=0.8, catalyst="earnings", headline="HDFC Bank Q3 beats") -> NewsData:
    return NewsData(
        symbol="HDFCBANK",
        has_news=has,
        sentiment=sentiment,
        catalyst_type=catalyst,
        headline=headline,
        llm_score=sentiment,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_perfect_setup_gets_A_plus_plus():
    """Best possible inputs should score A++ (9+)."""
    result = engine.calculate(
        signal=make_signal(body_ratio=0.85, close_pos=0.90),
        volume=make_volume(ratio=2.8),
        context=make_context(regime=RegimeType.RECOVERING),
        rs=make_rs(stock_chg=1.2, nifty_chg=0.2),
        news=make_news(sentiment=0.9),
    )
    print(f"\n[A++] final={result.components.final_score} grade={result.components.grade}")
    print(f"      reason: {result.reason}")
    assert result.components.grade == Grade.A_PLUS_PLUS
    assert result.components.final_score >= 9.0
    assert result.is_valid


def test_choppy_regime_kills_breakout():
    """A breakout that would score A in trending should drop to B or C in choppy."""
    result_trending = engine.calculate(
        signal=make_signal(setup_type=SetupType.MOMENTUM_BREAKOUT),
        volume=make_volume(ratio=1.8),
        context=make_context(regime=RegimeType.TRENDING),
        rs=make_rs(0.6, 0.1),
        news=make_news(has=False),
    )
    result_choppy = engine.calculate(
        signal=make_signal(setup_type=SetupType.MOMENTUM_BREAKOUT),
        volume=make_volume(ratio=1.8),
        context=make_context(regime=RegimeType.CHOPPY),
        rs=make_rs(0.6, 0.1),
        news=make_news(has=False),
    )
    print(f"\n[Regime] trending={result_trending.components.final_score} choppy={result_choppy.components.final_score}")
    assert result_choppy.components.final_score < result_trending.components.final_score
    # breakout in choppy must be penalised significantly
    assert result_choppy.components.regime_multiplier == 0.6


def test_recovering_regime_boosts_vwap_reclaim():
    """VWAP reclaim in Recovering regime gets ×1.4 multiplier."""
    result = engine.calculate(
        signal=make_signal(setup_type=SetupType.VWAP_RECLAIM),
        volume=make_volume(ratio=1.6),
        context=make_context(regime=RegimeType.RECOVERING),
        rs=make_rs(0.7, 0.1),
        news=make_news(has=False),
    )
    print(f"\n[Recovery boost] mult={result.components.regime_multiplier} final={result.components.final_score}")
    assert result.components.regime_multiplier == 1.4


def test_no_liquidity_is_hard_reject():
    """Signal with failed liquidity check must be rejected regardless of setup quality."""
    result = engine.calculate(
        signal=make_signal(body_ratio=0.9, close_pos=0.95),
        volume=make_volume(ratio=3.0, liquidity=False),
        context=make_context(),
        rs=make_rs(1.5, 0.2),
        news=make_news(sentiment=1.0),
    )
    print(f"\n[Liquidity reject] valid={result.is_valid} reason={result.reason}")
    assert result.is_valid is False
    assert "liquidity" in result.reason.lower()


def test_price_ran_too_far_proximity_fail():
    """If price moved >0.7% from entry, proximity check should fail."""
    result = engine.calculate(
        signal=make_signal(entry=1742.0, current=1760.0),  # ~1.03% drift
        volume=make_volume(ratio=2.0),
        context=make_context(),
        rs=make_rs(0.8, 0.2),
        news=make_news(has=False),
    )
    print(f"\n[Proximity] ok={result.proximity_ok} valid={result.is_valid}")
    assert result.proximity_ok is False
    assert result.is_valid is False


def test_negative_news_applies_penalty():
    """Negative news should reduce score vs neutral."""
    result_neutral = engine.calculate(
        signal=make_signal(),
        volume=make_volume(ratio=1.8),
        context=make_context(),
        rs=make_rs(0.6, 0.1),
        news=make_news(has=False),
    )
    result_negative = engine.calculate(
        signal=make_signal(),
        volume=make_volume(ratio=1.8),
        context=make_context(),
        rs=make_rs(0.6, 0.1),
        news=make_news(has=True, sentiment=0.1, catalyst="news", headline="HDFC Bank under RBI scrutiny"),
    )
    print(f"\n[News] neutral_raw={result_neutral.components.raw_score} negative_raw={result_negative.components.raw_score}")
    assert result_negative.components.raw_score < result_neutral.components.raw_score


def test_wick_breakout_low_confidence():
    """A wick breakout (low body ratio, close near bottom of candle) = low confidence."""
    result = engine.calculate(
        signal=make_signal(body_ratio=0.15, close_pos=0.25),
        volume=make_volume(ratio=1.6),
        context=make_context(),
        rs=make_rs(0.5, 0.1),
        news=make_news(has=False),
    )
    print(f"\n[Wick] confidence={result.confidence} setup_quality={result.components.setup_quality}")
    assert result.confidence < 0.5
    assert result.components.setup_quality < 1.5


def test_grade_thresholds():
    """Verify each grade bucket is working correctly."""
    cases = [
        (9.5, Grade.A_PLUS_PLUS),
        (8.5, Grade.A_PLUS),
        (7.5, Grade.A),
        (6.0, Grade.B),
        (4.0, Grade.C),
    ]
    for score, expected_grade in cases:
        grade = engine._get_grade(score)
        print(f"  score={score} → {grade.value} (expected {expected_grade.value})")
        assert grade == expected_grade


def test_event_regime_reduces_all_setups():
    """Event/expiry day must reduce all setup scores by ×0.7."""
    for setup in SetupType:
        mult = engine._get_regime_multiplier(RegimeType.EVENT, setup)
        assert mult == 0.7, f"{setup.value} should be 0.7 on event day, got {mult}"
    print("\n[Event] all setups correctly ×0.7")


def test_score_capped_at_10():
    """Final score must never exceed 10."""
    result = engine.calculate(
        signal=make_signal(body_ratio=1.0, close_pos=1.0),
        volume=make_volume(ratio=5.0),
        context=make_context(regime=RegimeType.RECOVERING),
        rs=make_rs(3.0, 0.1),
        news=make_news(sentiment=1.0, catalyst="earnings"),
    )
    print(f"\n[Cap] final={result.components.final_score}")
    assert result.components.final_score <= 10.0


def test_trend_pullback_in_event_regime_is_throttled():
    """EVENT regime must throttle TREND_PULLBACK to 0.7× like every other setup."""
    mult = engine._get_regime_multiplier(RegimeType.EVENT, SetupType.TREND_PULLBACK)
    assert mult == 0.7, f"TREND_PULLBACK in EVENT should be 0.7, got {mult}"


def test_trend_pullback_in_trending_regime_gets_boost():
    """TREND_PULLBACK is meant to fire in trending markets — must get >= 1.2 multiplier."""
    mult = engine._get_regime_multiplier(RegimeType.TRENDING, SetupType.TREND_PULLBACK)
    assert mult >= 1.2, f"TREND_PULLBACK in TRENDING should boost ≥1.2, got {mult}"


def test_trend_pullback_in_choppy_regime_is_penalised():
    """Counter-trend in chop must be penalised (multiplier < 1.0)."""
    mult = engine._get_regime_multiplier(RegimeType.CHOPPY, SetupType.TREND_PULLBACK)
    assert mult < 1.0, f"TREND_PULLBACK in CHOPPY should be penalised <1.0, got {mult}"


def test_all_setups_have_all_regimes():
    """Every SetupType must have a multiplier in every RegimeType — KeyError-safe."""
    for regime in RegimeType:
        for setup in SetupType:
            mult = engine._get_regime_multiplier(regime, setup)
            assert isinstance(mult, (int, float)), \
                f"{regime.value}/{setup.value} missing multiplier"


def test_underperforming_stock_gets_zero_rs_score():
    """Stock underperforming index by >0.5% should get 0 RS score."""
    rs = make_rs(stock_chg=0.2, nifty_chg=0.9)   # delta = -0.7%
    score = engine._score_relative_strength(rs)
    print(f"\n[RS] delta={rs.rs_delta:.2f} → rs_score={score}")
    assert score == 0.0


# ─── Run all ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_perfect_setup_gets_A_plus_plus,
        test_choppy_regime_kills_breakout,
        test_recovering_regime_boosts_vwap_reclaim,
        test_no_liquidity_is_hard_reject,
        test_price_ran_too_far_proximity_fail,
        test_negative_news_applies_penalty,
        test_wick_breakout_low_confidence,
        test_grade_thresholds,
        test_event_regime_reduces_all_setups,
        test_score_capped_at_10,
        test_underperforming_stock_gets_zero_rs_score,
        test_trend_pullback_in_event_regime_is_throttled,
        test_trend_pullback_in_trending_regime_gets_boost,
        test_trend_pullback_in_choppy_regime_is_penalised,
        test_all_setups_have_all_regimes,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__} — {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} — UNEXPECTED: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed == 0:
        print("All tests passed. Scoring engine is solid.")
    else:
        print("Fix failing tests before building agents.")
