from plain_explainer import humanize_ai_decision

def test_humanize_ai_decision_executed():
    res = humanize_ai_decision(
        symbol="AIINU-USDT",
        decision="ENTER_SHORT",
        confidence=75,
        evidence="Wick rejection on 15m",
        risk_factors="none",
        price=0.170118,
        change_24h=15.0,
        spread_pct=0.08,
        margin_per_pos=5.0,
        leverage=20,
        executed=True,
        order_id="ord_998877",
        dry_run=False,
        sizing_valid=True,
        is_quota_full=False
    )
    assert res["badge_label"] == "ORDER SHORT TERPASANG"
    assert "ord_998877" in res["action_advice"]
    assert res["confidence_text"] == "Tingkat Keyakinan AI: 75%"

def test_humanize_ai_decision_dry_run():
    res = humanize_ai_decision(
        symbol="AIINU-USDT",
        decision="ENTER_SHORT",
        confidence=72,
        evidence="Exhaustion",
        risk_factors="",
        price=0.170118,
        change_24h=12.0,
        spread_pct=0.05,
        executed=False,
        dry_run=True
    )
    assert res["badge_label"] == "SIMULASI SHORT TERBUKA"

def test_humanize_ai_decision_quota_full():
    res = humanize_ai_decision(
        symbol="AIINU-USDT",
        decision="ENTER_SHORT",
        confidence=80,
        evidence="Exhaustion",
        risk_factors="",
        price=0.170118,
        change_24h=12.0,
        spread_pct=0.05,
        executed=False,
        dry_run=False,
        is_quota_full=True
    )
    assert res["badge_label"] == "TERTAHAN: KUOTA PENUH"

def test_humanize_ai_decision_sizing_invalid():
    res = humanize_ai_decision(
        symbol="AIINU-USDT",
        decision="ENTER_SHORT",
        confidence=80,
        evidence="Exhaustion",
        risk_factors="",
        price=0.170118,
        change_24h=12.0,
        spread_pct=0.05,
        executed=False,
        dry_run=False,
        sizing_valid=False
    )
    assert res["badge_label"] == "TERLEWAT: MINIMAL BURSA"

def test_humanize_ai_decision_wait_and_skip():
    wait_res = humanize_ai_decision(
        symbol="BTC-USDT",
        decision="WAIT",
        confidence=60,
        evidence="Momentum continues",
        risk_factors="",
        price=65000.0,
        change_24h=3.0,
        spread_pct=0.01
    )
    assert wait_res["badge_label"] == "STATUS: MEMANTAU (TUNGGU MOMEN)"

    skip_res = humanize_ai_decision(
        symbol="LOW-USDT",
        decision="SKIP",
        confidence=0,
        evidence="Hard gate reject",
        risk_factors="low_volume",
        price=1.0,
        change_24h=0.0,
        spread_pct=0.35
    )
    assert skip_res["badge_label"] == "STATUS: DILEWATI"


def test_humanize_ai_decision_with_fibonacci_and_wave():
    res = humanize_ai_decision(
        symbol="PUMP-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        evidence="Buyer exhaustion wick",
        risk_factors="",
        price=1.25,
        change_24h=25.0,
        spread_pct=0.04,
        fibonacci={
            "valid": True,
            "zone": "PEAK_EXHAUSTION",
            "retracement_ratio": 0.05
        },
        impulse_wave={
            "valid": True,
            "consecutive_bull_bars": 3,
            "volume_fade": True,
            "confluent_rejection": True,
            "exhaustion_score": 85
        },
        funding_sentiment="EXTREME_LONG_CROWD",
        funding_rate=0.0008
    )
    assert "Fibonacci" in res["fibonacci_note"]
    assert "puncak kenaikan" in res["fibonacci_note"]
    assert "Struktur Gelombang" in res["wave_note"]
    assert "85/100" in res["wave_note"]
    assert "Funding Rate" in res["funding_note"]
    assert res["fibonacci_zone"] == "PEAK_EXHAUSTION"
    assert res["exhaustion_score"] == 85

