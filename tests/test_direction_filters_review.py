"""Tests for direction-aware hard gate (BUG2), scanner ranking (BUG5), and oversold reversal playbook (BUG4)."""

import pytest
from market_features import hard_gate


def test_hard_gate_directional_vetoes_and_universal_failures():
    # Base valid market features
    base_features = {
        "fresh": True,
        "spread_pct": 0.1,
        "funding_rate": 0.0001,
        "atr_to_friction": 5.0,
        "fibonacci": {
            "valid": True,
            "zone": "MID_RETRACEMENT",
            "retracement_ratio": 0.50,
            "is_dump_extended": False,
            "is_long_fomo_danger": False,
        },
    }

    # 1. Base passes both SHORT and LONG
    ok_short, reasons_short = hard_gate(base_features, direction="SHORT")
    assert ok_short is True
    assert reasons_short == []

    ok_long, reasons_long = hard_gate(base_features, direction="LONG")
    assert ok_long is True
    assert reasons_long == []

    # 2. Extended dump: vetoes SHORT, but NOT LONG
    dump_features = {
        **base_features,
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.85,
            "is_dump_extended": True,
            "is_long_fomo_danger": False,
        },
    }
    ok_dump_short, reasons_dump_short = hard_gate(dump_features, direction="SHORT")
    assert ok_dump_short is False
    assert "dump_already_extended" in reasons_dump_short

    ok_dump_long, reasons_dump_long = hard_gate(dump_features, direction="LONG")
    assert ok_dump_long is True
    assert "dump_already_extended" not in reasons_dump_long

    # 3. Negative funding squeeze: vetoes SHORT, but NOT LONG
    squeeze_features = {
        **base_features,
        "funding_rate": -0.008,
    }
    ok_sq_short, reasons_sq_short = hard_gate(squeeze_features, direction="SHORT")
    assert ok_sq_short is False
    assert "crowded_short_squeeze_risk" in reasons_sq_short

    ok_sq_long, reasons_sq_long = hard_gate(squeeze_features, direction="LONG")
    assert ok_sq_long is True
    assert "crowded_short_squeeze_risk" not in reasons_sq_long

    # 4. Long FOMO danger: vetoes LONG, but NOT SHORT
    fomo_features = {
        **base_features,
        "fibonacci": {
            "valid": True,
            "zone": "PEAK_EXHAUSTION",
            "retracement_ratio": 0.02,
            "is_dump_extended": False,
            "is_long_fomo_danger": True,
        },
    }
    ok_fomo_long, reasons_fomo_long = hard_gate(fomo_features, direction="LONG")
    assert ok_fomo_long is False
    assert "long_fomo_danger" in reasons_fomo_long

    ok_fomo_short, reasons_fomo_short = hard_gate(fomo_features, direction="SHORT")
    assert ok_fomo_short is True
    assert "long_fomo_danger" not in reasons_fomo_short

    # 5. Universal failures apply to both directions
    stale_features = {**base_features, "fresh": False}
    assert hard_gate(stale_features, direction="SHORT")[0] is False
    assert "stale_data" in hard_gate(stale_features, direction="SHORT")[1]
    assert hard_gate(stale_features, direction="LONG")[0] is False
    assert "stale_data" in hard_gate(stale_features, direction="LONG")[1]

    wide_spread = {**base_features, "spread_pct": 0.50}
    assert hard_gate(wide_spread, direction="SHORT")[0] is False
    assert "spread_too_wide" in hard_gate(wide_spread, direction="SHORT")[1]
    assert hard_gate(wide_spread, direction="LONG")[0] is False
    assert "spread_too_wide" in hard_gate(wide_spread, direction="LONG")[1]


def test_hard_gate_both_mode_eligibility():
    base_features = {
        "fresh": True,
        "spread_pct": 0.1,
        "funding_rate": 0.0001,
        "atr_to_friction": 5.0,
        "fibonacci": {
            "valid": True,
            "zone": "MID_RETRACEMENT",
            "retracement_ratio": 0.50,
            "is_dump_extended": False,
            "is_long_fomo_danger": False,
        },
    }

    # 1. Base passes in BOTH mode
    ok, reasons = hard_gate(base_features, direction="BOTH")
    assert ok is True
    assert reasons == []

    # 2. Extended dump: SHORT vetoed, but LONG eligible -> BOTH succeeds!
    dump_features = {
        **base_features,
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.85,
            "is_dump_extended": True,
            "is_long_fomo_danger": False,
        },
    }
    ok_dump, reasons_dump = hard_gate(dump_features, direction="BOTH")
    assert ok_dump is True
    assert reasons_dump == []

    # 3. FOMO danger: LONG vetoed, but SHORT eligible -> BOTH succeeds!
    fomo_features = {
        **base_features,
        "fibonacci": {
            "valid": True,
            "zone": "PEAK_EXHAUSTION",
            "retracement_ratio": 0.02,
            "is_dump_extended": False,
            "is_long_fomo_danger": True,
        },
    }
    ok_fomo, reasons_fomo = hard_gate(fomo_features, direction="BOTH")
    assert ok_fomo is True
    assert reasons_fomo == []

    # 4. Both directions vetoed: SHORT fails (dump) AND LONG fails (fomo) -> BOTH fails!
    double_veto = {
        **base_features,
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.85,
            "is_dump_extended": True,
            "is_long_fomo_danger": True,
        },
    }
    ok_both_veto, reasons_both_veto = hard_gate(double_veto, direction="BOTH")
    assert ok_both_veto is False
    assert "dump_already_extended" in reasons_both_veto
    assert "long_fomo_danger" in reasons_both_veto

    # 5. Universal failure vetoes BOTH even if setups are clean
    stale_both = {**base_features, "fresh": False}
    ok_stale, reasons_stale = hard_gate(stale_both, direction="BOTH")
    assert ok_stale is False
    assert "stale_data" in reasons_stale


def test_scanner_long_ranking_favors_pullbacks_not_biggest_losers(mocker):
    from scanner import MarketScanner
    from client import BingXClient
    from config import AppConfig

    config = AppConfig(
        api_key="mock",
        secret_key="mock",
        universe_mode="PUMP_GAINERS",
        min_volume_24h_usdt=10000.0,
        max_spread_pct=0.25,
    )
    client = BingXClient(config)
    scanner = MarketScanner(client, config)

    mocker.patch.object(scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(client, "get_contracts", return_value=[
        {"symbol": "PULLBACK-DIP-USDT", "apiStateOpen": "true"},
        {"symbol": "PULLBACK-MILD-USDT", "apiStateOpen": "true"},
        {"symbol": "DUMP-COIN-USDT", "apiStateOpen": "true"},
        {"symbol": "PUMP-PEAK-USDT", "apiStateOpen": "true"},
        {"symbol": "CRASH-COIN-USDT", "apiStateOpen": "true"},  # Below -20% -> filter threshold
    ])
    mocker.patch.object(client, "get_tickers", return_value=[
        {"symbol": "PULLBACK-DIP-USDT", "lastPrice": "1.0", "priceChangePercent": "-3.0", "volume": "100000", "bidPrice": "0.999", "askPrice": "1.001"},
        {"symbol": "PULLBACK-MILD-USDT", "lastPrice": "2.0", "priceChangePercent": "1.5", "volume": "100000", "bidPrice": "1.999", "askPrice": "2.001"},
        {"symbol": "DUMP-COIN-USDT", "lastPrice": "0.5", "priceChangePercent": "-18.5", "volume": "100000", "bidPrice": "0.499", "askPrice": "0.501"},
        {"symbol": "PUMP-PEAK-USDT", "lastPrice": "5.0", "priceChangePercent": "38.0", "volume": "100000", "bidPrice": "4.995", "askPrice": "5.005"},
        {"symbol": "CRASH-COIN-USDT", "lastPrice": "0.1", "priceChangePercent": "-26.0", "volume": "100000", "bidPrice": "0.099", "askPrice": "0.101"},
    ])

    candidates = scanner.scan_universe(direction="LONG", limit_candidates=3)
    symbols = [c.symbol for c in candidates]

    # CRASH-COIN (-26%) must be filtered out by retained LONG threshold (-20% to +40%)
    assert "CRASH-COIN-USDT" not in symbols

    # Pullback candidates must rank at the top, NOT the unconditional biggest loser (-18.5%)
    assert symbols[0] in ("PULLBACK-MILD-USDT", "PULLBACK-DIP-USDT")
    assert symbols[1] in ("PULLBACK-MILD-USDT", "PULLBACK-DIP-USDT")
    # DUMP-COIN (-18.5%) must NOT be top 1
    assert symbols[0] != "DUMP-COIN-USDT"


def test_scanner_both_mode_balanced_discovery_deduped(mocker):
    from scanner import MarketScanner
    from client import BingXClient
    from config import AppConfig

    config = AppConfig(
        api_key="mock",
        secret_key="mock",
        universe_mode="PUMP_GAINERS",
        min_volume_24h_usdt=10000.0,
        max_spread_pct=0.25,
    )
    client = BingXClient(config)
    scanner = MarketScanner(client, config)

    mocker.patch.object(scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(client, "get_contracts", return_value=[
        {"symbol": "PUMP-1-USDT", "apiStateOpen": "true"},
        {"symbol": "PUMP-2-USDT", "apiStateOpen": "true"},
        {"symbol": "PUMP-3-USDT", "apiStateOpen": "true"},
        {"symbol": "DIP-1-USDT", "apiStateOpen": "true"},
        {"symbol": "DIP-2-USDT", "apiStateOpen": "true"},
        {"symbol": "DIP-3-USDT", "apiStateOpen": "true"},
    ])
    mocker.patch.object(client, "get_tickers", return_value=[
        {"symbol": "PUMP-1-USDT", "lastPrice": "10.0", "priceChangePercent": "50.0", "volume": "200000", "bidPrice": "9.999", "askPrice": "10.001"},
        {"symbol": "PUMP-2-USDT", "lastPrice": "5.0", "priceChangePercent": "30.0", "volume": "150000", "bidPrice": "4.999", "askPrice": "5.001"},
        {"symbol": "PUMP-3-USDT", "lastPrice": "2.0", "priceChangePercent": "20.0", "volume": "100000", "bidPrice": "1.999", "askPrice": "2.001"},
        {"symbol": "DIP-1-USDT", "lastPrice": "1.0", "priceChangePercent": "1.0", "volume": "200000", "bidPrice": "0.999", "askPrice": "1.001"},
        {"symbol": "DIP-2-USDT", "lastPrice": "3.0", "priceChangePercent": "-2.5", "volume": "150000", "bidPrice": "2.999", "askPrice": "3.001"},
        {"symbol": "DIP-3-USDT", "lastPrice": "4.0", "priceChangePercent": "-4.0", "volume": "100000", "bidPrice": "3.999", "askPrice": "4.001"},
    ])

    candidates = scanner.scan_universe(direction="BOTH", limit_candidates=4)
    symbols = [c.symbol for c in candidates]

    assert len(candidates) == 4
    # Unique symbols (deduped)
    assert len(set(symbols)) == 4

    # Balanced allocation: BOTH must include pumpers and pullbacks, NOT 100% pumpers
    pumpers = [s for s in symbols if "PUMP" in s]
    dips = [s for s in symbols if "DIP" in s]
    assert len(pumpers) == 2, f"Expected 2 pumpers, got {len(pumpers)} ({pumpers})"
    assert len(dips) == 2, f"Expected 2 dips, got {len(dips)} ({dips})"


def test_playbook_type_contracts_has_oversold_reversal():
    from contracts import PlaybookType
    assert hasattr(PlaybookType, "OVERSOLD_REVERSAL")
    assert PlaybookType.OVERSOLD_REVERSAL.value == "OVERSOLD_REVERSAL"


def test_playbook_rejects_long_on_mere_rsi_low():
    """No LONG entry should be triggered on mere RSI low without divergence and confirmation."""
    from strategy_playbook import evaluate_playbooks
    from contracts import PlaybookType

    # Deeply oversold, but crashing: NO bullish divergence, NO wick rejection, DOWN candle
    market_features = {
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.90,
            "is_golden_pullback": False,
            "is_dump_extended": True,
            "is_long_breakdown_danger": True,
            "swing_low": 10.0,
        },
        "rsi": {
            "valid": True,
            "rsi_15m": 18.0,
            "rsi_1h": 22.0,
            "is_oversold": True,
            "divergence": "NONE",  # No divergence!
        },
        "impulse_wave": {
            "valid": True,
            "consecutive_bull_bars": 0,
            "lower_wick_15m": 0.05,  # No lower wick rejection
            "lower_wick_1h": 0.05,
            "confluent_lower_rejection": False,
        },
        "bollinger": {
            "valid": True,
            "percent_b": -0.10,
            "is_overextended_lower": True,
        },
        "ema_trend": {
            "trend": "STRONG_DOWNTREND",
        },
        "timeframes": {
            "15m": {"last_direction": "DOWN"}
        }
    }

    match = evaluate_playbooks(
        symbol="FALLING-KNIFE-USDT",
        price=9.5,
        change_24h=-18.0,
        spread_pct=0.001,
        market_features=market_features,
    )

    # Must NOT trigger OVERSOLD_REVERSAL or SUPPORT_PULLBACK
    assert match.playbook != "OVERSOLD_REVERSAL"
    assert match.playbook != PlaybookType.SUPPORT_PULLBACK.value


def test_playbook_rejects_oversold_without_bullish_confirmation():
    """Oversold + Bullish Divergence is still not enough without candle confirmation/reclaim."""
    from strategy_playbook import evaluate_playbooks

    market_features = {
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.88,
            "is_golden_pullback": False,
            "is_dump_extended": True,
            "swing_low": 10.0,
        },
        "rsi": {
            "valid": True,
            "rsi_15m": 25.0,
            "is_oversold": True,
            "divergence": "BULLISH_DIV",  # Has divergence
        },
        "impulse_wave": {
            "valid": True,
            "consecutive_bull_bars": 0,
            "lower_wick_15m": 0.08,  # But NO lower wick rejection
            "lower_wick_1h": 0.05,
            "confluent_lower_rejection": False,
        },
        "bollinger": {
            "valid": True,
            "percent_b": -0.05,
        },
        "ema_trend": {
            "trend": "STRONG_DOWNTREND",
        },
        "timeframes": {
            "15m": {"last_direction": "DOWN"}
        }
    }

    match = evaluate_playbooks(
        symbol="UNCONFIRMED-DIP-USDT",
        price=9.8,
        change_24h=-14.0,
        spread_pct=0.001,
        market_features=market_features,
    )

    assert match.playbook != "OVERSOLD_REVERSAL"


def test_playbook_matches_oversold_reversal_on_full_conjunction():
    """Full conjunction: Oversold + Bullish Divergence + Bullish Confirmation/Support Reclaim."""
    from strategy_playbook import evaluate_playbooks
    from contracts import PlaybookType, DirectionMode

    market_features = {
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.80,
            "is_golden_pullback": False,
            "swing_low": 10.0,
        },
        "rsi": {
            "valid": True,
            "rsi_15m": 26.5,
            "rsi_1h": 28.0,
            "is_oversold": True,
            "divergence": "BULLISH_DIV",  # 1. Divergence
        },
        "impulse_wave": {
            "valid": True,
            "consecutive_bull_bars": 1,
            "lower_wick_15m": 0.38,  # 2. Strong lower wick rejection
            "lower_wick_1h": 0.25,
            "confluent_lower_rejection": True,
        },
        "bollinger": {
            "valid": True,
            "percent_b": 0.12,  # 3. Reclaimed inside lower band
            "is_overextended_lower": False,
        },
        "ema_trend": {
            "trend": "MILD_DOWNTREND",
        },
        "timeframes": {
            "15m": {"last_direction": "UP"}  # Reversal bar
        }
    }

    match = evaluate_playbooks(
        symbol="REVERSAL-COIN-USDT",
        price=10.2,  # Reclaimed above swing_low (10.0)
        change_24h=-10.0,
        spread_pct=0.001,
        market_features=market_features,
    )

    assert match.playbook == PlaybookType.OVERSOLD_REVERSAL.value
    assert match.direction == DirectionMode.LONG.value
    assert match.score >= 50
    assert len(match.matched_signals) >= 3
    assert any("divergence" in s.lower() or "divergensi" in s.lower() for s in match.matched_signals)


