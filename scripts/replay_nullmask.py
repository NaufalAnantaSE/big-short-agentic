#!/usr/bin/env python3
"""Replay Script for NULLMASK candidate.

Verifies:
1. Scenario 1 (Controlled Spread < 0.35%):
   - hard_gate(features, direction="LONG") -> ALLOWED (previously rejected by dump_already_extended)
   - evaluate_playbooks(...) -> matches OVERSOLD_REVERSAL (Direction: LONG)
2. Scenario 2 (Original Spread 0.378%):
   - hard_gate(features, direction="LONG") -> REJECTED
   - Universal gate works properly: rejection reason is strictly 'spread_too_wide', NOT 'dump_already_extended'
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_features import hard_gate
from strategy_playbook import evaluate_playbooks
from contracts import PlaybookType, DirectionMode


def build_nullmask_features(spread_pct: float) -> dict:
    return {
        "symbol": "NULLMASK-USDT",
        "price": 0.018480,
        "fresh": True,
        "spread_pct": spread_pct,
        "funding_rate": -0.015,  # Negative funding (crowded shorts)
        "funding_sentiment": "MODERATE_SHORT_CROWD",
        "atr_to_friction": 4.5,
        "fibonacci": {
            "valid": True,
            "zone": "EXTENDED_DUMP",
            "retracement_ratio": 0.848,
            "swing_high": 0.1215,
            "swing_low": 0.0180,
            "is_peak_exhaustion": False,
            "is_dump_extended": True,
            "is_golden_pullback": False,
            "is_long_fomo_danger": False,
            "is_long_breakdown_danger": True
        },
        "rsi": {
            "rsi_15m": 21.0,
            "rsi_1h": 26.5,
            "divergence": "BULLISH_DIV",
            "is_oversold": True,
            "is_overbought": False
        },
        "bollinger": {
            "is_overextended_lower": True,
            "is_overextended_upper": False,
            "percent_b": 0.08
        },
        "impulse_wave": {
            "valid": True,
            "lower_wick_15m": 0.32,
            "lower_wick_1h": 0.25,
            "confluent_lower_rejection": True,
            "volume_fade": False,
            "consecutive_bull_bars": 1
        },
        "timeframes": {
            "15m": {"last_direction": "UP", "change_pct": -84.8},
            "1h": {"last_direction": "DOWN", "change_pct": -84.8}
        },
        "ema_trend": {
            "regime": "DOWNTREND"
        }
    }


def main():
    print("=" * 70)
    print("REPLAY AUDIT: NULLMASK (RSI 21, Bullish Div, Fib 84.8%, Funding -0.015)")
    print("=" * 70)

    # -------------------------------------------------------------
    # Scenario 1: Controlled Liquidity (spread = 0.20% < 0.35%)
    # -------------------------------------------------------------
    feat_s1 = build_nullmask_features(spread_pct=0.20)
    allowed_s1, reasons_s1 = hard_gate(feat_s1, max_spread_pct=0.35, direction="LONG")
    playbook_s1 = evaluate_playbooks(
        symbol="NULLMASK-USDT",
        price=feat_s1["price"],
        change_24h=-84.8,
        spread_pct=feat_s1["spread_pct"],
        market_features=feat_s1
    )

    print("\n[SKENARIO 1: Spread Terkontrol 0.20% (< 0.35%)]")
    print(f"- hard_gate(direction='LONG') Result : {'ALLOWED' if allowed_s1 else 'REJECTED'}")
    print(f"- Rejection Reasons                   : {reasons_s1 if reasons_s1 else 'None (Passed)'}")
    print(f"- Matched Playbook                    : {playbook_s1.playbook}")
    print(f"- Playbook Direction                  : {playbook_s1.direction}")
    print(f"- Playbook Score                      : {playbook_s1.score}/100")
    print(f"- Playbook Matched Signals            : {playbook_s1.matched_signals}")

    assert allowed_s1 is True, f"Expected allowed_s1 to be True, got False with reasons: {reasons_s1}"
    assert playbook_s1.playbook == PlaybookType.OVERSOLD_REVERSAL.value, f"Expected OVERSOLD_REVERSAL, got {playbook_s1.playbook}"
    assert playbook_s1.direction == DirectionMode.LONG.value, f"Expected LONG, got {playbook_s1.direction}"
    print("-> ASSERT SKENARIO 1: [PASSED] (Koin lolos gate LONG & match OVERSOLD_REVERSAL)")

    # -------------------------------------------------------------
    # Scenario 2: Original Spread (spread = 0.378% > 0.35%)
    # -------------------------------------------------------------
    feat_s2 = build_nullmask_features(spread_pct=0.378)
    allowed_s2, reasons_s2 = hard_gate(feat_s2, max_spread_pct=0.35, direction="LONG")

    print("\n[SKENARIO 2: Spread Asli 0.378% (> 0.35%)]")
    print(f"- hard_gate(direction='LONG') Result : {'ALLOWED' if allowed_s2 else 'REJECTED'}")
    print(f"- Rejection Reasons                   : {reasons_s2}")

    assert allowed_s2 is False, "Expected allowed_s2 to be False"
    assert "spread_too_wide" in reasons_s2, f"Expected spread_too_wide in reasons, got {reasons_s2}"
    assert "dump_already_extended" not in reasons_s2, f"dump_already_extended should NOT be present for LONG, got {reasons_s2}"
    print("-> ASSERT SKENARIO 2: [PASSED] (Universal gate likuiditas aktif: rejected karena spread_too_wide, bukan dump)")

    print("\n" + "=" * 70)
    print("KESIMPULAN: SELURUH ASSERTION HIJAU (100% SUCCESS)")
    print("=" * 70)


if __name__ == "__main__":
    main()
