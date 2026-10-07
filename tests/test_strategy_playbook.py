"""Unit tests for Phase 3: Autonomous Multi-Strategy Playbooks.

Validates:
1. Autonomous classification into PUMP_EXHAUSTION, SUPPORT_PULLBACK, BREAKDOWN_RETEST, FUNDING_SQUEEZE.
2. Safe fallback to PlaybookType.NONE when market conditions are ambiguous.
3. Adaptive Risk:Reward (R:R) recommendation matching each playbook profile.
4. Senior-friendly narrative explanations generation in Indonesian.
5. End-to-end integration into Orchestrator cycle sizing.
"""

import pytest
from contracts import PlaybookType, DirectionMode
from strategy_playbook import evaluate_playbooks, PlaybookMatch
from plain_explainer import humanize_ai_decision
from sizing import SizingCalculator


def test_playbook_pump_exhaustion_detection():
    market_features = {
        "fibonacci": {
            "zone": "PEAK_EXHAUSTION",
            "is_peak_exhaustion": True,
            "retracement_ratio": 0.05
        },
        "rsi": {
            "valid": True,
            "rsi_15m": 76.5,
            "is_overbought": True,
            "divergence": "BEARISH_DIV"
        },
        "bollinger": {
            "valid": True,
            "percent_b": 1.05,
            "is_overextended_upper": True
        },
        "impulse_wave": {
            "exhaustion_score": 85,
            "confluent_rejection": True,
            "wick_15m": 0.35,
            "volume_fade": True
        },
        "ema_trend": {
            "trend": "STRONG_UPTREND"
        }
    }

    match = evaluate_playbooks(
        symbol="PEPE-USDT",
        price=0.000012,
        change_24h=18.5,
        spread_pct=0.0004,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.PUMP_EXHAUSTION.value
    assert match.direction == DirectionMode.SHORT.value
    assert match.score >= 70
    assert match.recommended_rr == 2.5
    assert "Puncak" in match.title_id or "Pump" in match.title_id
    assert len(match.matched_signals) >= 3


def test_playbook_support_pullback_detection():
    market_features = {
        "fibonacci": {
            "zone": "GOLDEN_POCKET_SUPPORT",
            "is_golden_pullback": True,
            "retracement_ratio": 0.50,
            "is_dump_extended": False,
            "is_long_breakdown_danger": False
        },
        "rsi": {
            "valid": True,
            "rsi_15m": 42.0,
            "is_oversold": False,
            "divergence": "BULLISH_DIV"
        },
        "bollinger": {
            "valid": True,
            "percent_b": 0.20,
            "is_overextended_lower": True
        },
        "ema_trend": {
            "trend": "STRONG_UPTREND"
        },
        "impulse_wave": {
            "exhaustion_score": 20
        }
    }

    match = evaluate_playbooks(
        symbol="SOL-USDT",
        price=180.0,
        change_24h=4.2,
        spread_pct=0.0002,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.SUPPORT_PULLBACK.value
    assert match.direction == DirectionMode.LONG.value
    assert match.score >= 60
    assert match.recommended_rr == 2.0
    assert "Pantulan" in match.title_id or "Support" in match.title_id


def test_playbook_breakdown_retest_detection():
    market_features = {
        "fibonacci": {
            "zone": "EXTENDED_DUMP",
            "is_dump_extended": True,
            "retracement_ratio": 0.75
        },
        "rsi": {
            "valid": True,
            "rsi_15m": 38.0,
            "divergence": "NONE"
        },
        "impulse_wave": {
            "wick_15m": 0.28
        },
        "ema_trend": {
            "trend": "STRONG_DOWNTREND"
        }
    }

    match = evaluate_playbooks(
        symbol="DOGE-USDT",
        price=0.14,
        change_24h=-8.5,
        spread_pct=0.0003,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.BREAKDOWN_RETEST.value
    assert match.direction == DirectionMode.SHORT.value
    assert match.score >= 50
    assert match.recommended_rr == 2.0
    assert "Jebol" in match.title_id or "Breakdown" in match.title_id


def test_playbook_funding_squeeze_detection():
    market_features = {
        "funding_rate": 0.0012,
        "funding_sentiment": "EXTREME_LONG_CROWD",
        "fibonacci": {
            "is_peak_exhaustion": True
        },
        "rsi": {
            "rsi_15m": 65.0
        },
        "impulse_wave": {
            "volume_fade": True
        }
    }

    match = evaluate_playbooks(
        symbol="SHIB-USDT",
        price=0.000025,
        change_24h=6.0,
        spread_pct=0.0004,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.FUNDING_SQUEEZE.value
    assert match.direction == DirectionMode.SHORT.value
    assert match.score >= 60
    assert match.recommended_rr == 2.0
    assert "Funding" in match.title_id or "Biaya" in match.title_id


def test_playbook_fallback_none_when_unclear():
    market_features = {
        "fibonacci": {
            "zone": "MID_RANGE_CHOP",
            "is_peak_exhaustion": False,
            "is_golden_pullback": False
        },
        "rsi": {
            "rsi_15m": 51.0,
            "divergence": "NONE"
        },
        "bollinger": {
            "percent_b": 0.50
        },
        "ema_trend": {
            "trend": "NEUTRAL"
        }
    }

    match = evaluate_playbooks(
        symbol="BTC-USDT",
        price=65000.0,
        change_24h=0.4,
        spread_pct=0.0001,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.NONE.value
    assert match.score == 0
    assert "Konservatif" in match.title_id or "Pemantauan" in match.title_id


def test_plain_explainer_with_playbook():
    playbook_data = {
        "playbook": "PUMP_EXHAUSTION",
        "direction": "SHORT",
        "score": 85,
        "title_id": "Strategi Jual di Pucuk (Pump Exhaustion)",
        "explanation_id": "Harga koin mengalami kenaikan tajam namun momentum pembeli telah habis.",
        "recommended_rr": 2.5
    }

    narrative = humanize_ai_decision(
        symbol="PEPE-USDT",
        decision="ENTER_SHORT",
        confidence=88,
        evidence="Exhaustion at 1.618 Fib, Bearish RSI divergence",
        risk_factors="none",
        price=0.000015,
        change_24h=14.2,
        spread_pct=0.0003,
        playbook=playbook_data
    )

    assert narrative["playbook_title"] == "Strategi Jual di Pucuk (Pump Exhaustion)"
    assert narrative["playbook_score"] == 85
    assert any("Strategi Otonom Terpilih" in note for note in narrative["market_notes"])


def test_sizing_with_playbook_recommended_rr():
    contract_info = {
        "tradeMinQuantity": 1.0,
        "stepSize": 1.0,
        "quantityPrecision": 0,
        "pricePrecision": 4,
        "minNotional": 5.0
    }

    # Playbook recommends 2.5 R:R for Pump Exhaustion
    sizing = SizingCalculator.calculate_lot(
        symbol="DOGE-USDT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=0.2000,
        contract_info=contract_info,
        direction="SHORT",
        atr=0.0040,  # 2% ATR -> SL = 1.5 * ATR = 0.0060 (3%), TP = 2.5 * SL = 0.0150 (7.5%)
        target_rr=2.5
    )

    assert sizing.is_valid is True
    assert sizing.stop_loss_price is not None
    assert sizing.take_profit_price is not None
    # For SHORT at 0.2000:
    # SL distance = 0.0060 -> SL price = 0.2060 (+3.0%)
    # TP distance = 0.0150 -> TP price = 0.1850 (-7.5%)
    assert sizing.stop_loss_price == 0.2060
    assert sizing.take_profit_price == 0.1850
    assert sizing.sl_percent == 3.0
    assert sizing.tp_percent == 7.5
