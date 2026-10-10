"""
F-08 acceptance tests: timestamp-aligned RSI divergence.

Defect: the previous detector compared the current bar against the MAXIMUM price and the
MAXIMUM RSI of a previous slice *independently*, so the two extremes could come from
different bars. That reported bearish divergence on sequences whose actual price pivot
still had strengthening momentum — a false exhaustion signal.

Each test asserts the FIXED behaviour and, where relevant, proves the old implementation
disagrees. Without that contrast the test would not discriminate the bug.
"""
from market_features import _detect_rsi_divergence, _detect_rsi_divergence_unaligned


def rows_from_closes(closes):
    return [{"close": c} for c in closes]


# Captured by exhaustive search: old detector says BEARISH_DIV, aligned pivots say NONE.
FALSE_POSITIVE_SEQUENCE = [
    104.5625, 108.2875, 112.3943, 107.5694, 103.0583, 105.3672, 109.5914, 109.5871,
    110.7687, 105.786, 104.9602, 109.4786, 113.1386, 117.242, 122.7949, 120.1677,
    116.005, 112.4861, 113.0063, 115.2435, 120.3651, 123.2015, 125.2341, 128.6975,
]

# Genuine divergence: aligned pivots still confirm weakening momentum at higher highs.
GENUINE_BEARISH_SEQUENCE = [
    97.6886, 98.8778, 99.5249, 101.1694, 100.574, 100.6936, 97.7621, 94.688, 92.1484,
    92.4641, 90.9975, 92.8618, 92.339, 92.0215, 95.0455, 95.2189, 95.6003, 98.917,
    102.7043, 100.0833, 100.1782, 101.582, 102.7187,
]


def test_false_positive_is_removed_by_pivot_alignment():
    """The old detector fires here; the aligned one must not."""
    rows = rows_from_closes(FALSE_POSITIVE_SEQUENCE)
    assert _detect_rsi_divergence_unaligned(rows) == "BEARISH_DIV", "precondition: old bug fires"
    assert _detect_rsi_divergence(rows) == "NONE"


def test_genuine_bearish_divergence_still_detected():
    """Fix must not simply disable the signal: real divergence still fires."""
    rows = rows_from_closes(GENUINE_BEARISH_SEQUENCE)
    assert _detect_rsi_divergence(rows) == "BEARISH_DIV"


def test_no_divergence_on_steady_uptrend():
    """Monotonic rise has no divergence at all."""
    rows = rows_from_closes([100.0 + i for i in range(30)])
    assert _detect_rsi_divergence(rows) == "NONE"


def test_insufficient_history_fails_closed():
    """Too little history must return NONE rather than guess."""
    assert _detect_rsi_divergence(rows_from_closes([100.0, 101.0, 102.0])) == "NONE"


def test_rsi_analysis_wires_aligned_divergence():
    """The playbook consumes divergence via _rsi_analysis; it must carry the aligned result."""
    from market_features import _rsi_analysis
    res = _rsi_analysis(rows_from_closes(GENUINE_BEARISH_SEQUENCE), [])
    assert res["valid"] is True
    assert res["divergence"] == "BEARISH_DIV"
