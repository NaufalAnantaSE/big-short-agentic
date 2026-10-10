import pytest
from tenant_manager import _resolve_effective_leverage


def test_effective_leverage_comes_from_sizing_output():
    """
    F-07 Acceptance Test:
    The order ledger must record the adaptive leverage actually used by sizing
    (SizingCalculator output key `effective_leverage`), NOT the session default.
    """
    sizing = {"effective_leverage": 12, "is_valid": True}
    assert _resolve_effective_leverage(sizing, session_leverage=20) == 12


def test_effective_leverage_falls_back_to_session_when_missing():
    """When sizing output has no leverage, fall back to session leverage."""
    assert _resolve_effective_leverage({}, session_leverage=20) == 20
    assert _resolve_effective_leverage(None, session_leverage=15) == 15


def test_effective_leverage_ignores_invalid_values():
    """Zero/negative/non-numeric leverage must not be recorded as effective leverage."""
    assert _resolve_effective_leverage({"effective_leverage": 0}, session_leverage=20) == 20
    assert _resolve_effective_leverage({"effective_leverage": -5}, session_leverage=20) == 20
    assert _resolve_effective_leverage({"effective_leverage": "abc"}, session_leverage=20) == 20
    assert _resolve_effective_leverage({"effective_leverage": None}, session_leverage=20) == 20
