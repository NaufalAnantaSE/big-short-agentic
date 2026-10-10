"""Quantitative Multi-Strategy Playbook Engine.

Autonomously classifies and scores market setups into high-probability strategy playbooks:
1. PUMP_EXHAUSTION (Short): Blow-off / peak exhaustion, overbought RSI, upper wick rejection, Bollinger overextension.
2. SUPPORT_PULLBACK (Long): Healthy retracement to Fibonacci 0.382-0.618, uptrend alignment (EMA), oversold/rebound RSI.
3. BREAKDOWN_RETEST (Short): Support breakdown, weak pullback retest under EMA/Fib, rejection upper wick.
4. FUNDING_SQUEEZE (Short): Abnormal positive funding rate crowd, retail longs paying extreme fees.
5. OVERSOLD_REVERSAL (Long): Strict conjunction of oversold RSI/Bollinger + Bullish Divergence + Bullish confirmation/support reclaim.
6. NONE: No clear edge or high-risk consolidation.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from contracts import PlaybookType, DirectionMode


class PlaybookMatch(BaseModel):
    playbook: str = PlaybookType.NONE.value
    direction: str = DirectionMode.SHORT.value
    score: int = Field(default=0, ge=0, le=100)
    title_id: str = "Pemantauan Pasar Konservatif"
    explanation_id: str = "Pergerakan harga saat ini belum membentuk pola keuntungan tinggi yang jelas. Bot tetap siaga memantau tanpa memaksakan risiko."
    recommended_rr: float = 2.0
    matched_signals: List[str] = Field(default_factory=list)


def evaluate_playbooks(
    symbol: str,
    price: float,
    change_24h: float,
    spread_pct: float,
    market_features: Dict[str, Any]
) -> PlaybookMatch:
    """
    Evaluates deterministic quantitative features and selects the best matching strategy playbook.
    """
    mf = market_features or {}
    fib = mf.get("fibonacci") or {}
    imp = mf.get("impulse_wave") or {}
    rsi = mf.get("rsi") or {}
    bb = mf.get("bollinger") or {}
    ema = mf.get("ema_trend") or {}
    fr = mf.get("funding_rate")
    f_sent = mf.get("funding_sentiment")

    candidates: List[PlaybookMatch] = []

    # -------------------------------------------------------------
    # 1. PUMP_EXHAUSTION (SHORT)
    # -------------------------------------------------------------
    pe_signals = []
    pe_score = 0
    rsi_15m = float(rsi.get("rsi_15m", 50.0) or 50.0)

    # P1-2 Mandatory Condition: MUST have confirmed core exhaustion / rejection pattern
    has_pe_core = (
        imp.get("confluent_rejection") is True
        or float(imp.get("wick_15m", 0.0) or 0.0) >= 0.20
        or rsi.get("divergence") == "BEARISH_DIV"
        or fib.get("is_peak_exhaustion") is True
        or fib.get("zone") in ("PEAK_EXHAUSTION", "BLOW_OFF_EXTENSION")
    )

    if has_pe_core:
        if fib.get("is_peak_exhaustion") or fib.get("zone") in ("PEAK_EXHAUSTION", "BLOW_OFF_EXTENSION"):
            pe_score += 30
            pe_signals.append("Harga di area puncak jenuh Fibonacci")

        if rsi.get("divergence") == "BEARISH_DIV":
            pe_score += 30
            pe_signals.append("Bearish Divergence (pelemahan daya beli)")
        elif rsi.get("is_overbought") or rsi_15m >= 68.0:
            pe_score += 20
            pe_signals.append(f"RSI jenuh beli ({rsi_15m:.1f})")

        if bb.get("is_overextended_upper") or float(bb.get("percent_b", 0.5) or 0.5) >= 0.95:
            pe_score += 15
            pe_signals.append("Harga menembus pita atas Bollinger Bands")

        if imp.get("confluent_rejection") or float(imp.get("wick_15m", 0.0) or 0.0) >= 0.25:
            pe_score += 15
            pe_signals.append("Ekor penolakan atas (upper wick) jelas")

        if imp.get("volume_fade"):
            pe_score += 10
            pe_signals.append("Volume beli melemah di puncak")

        if change_24h >= 8.0:
            pe_score += 10
            pe_signals.append(f"Lonjakan 24 jam signifikan (+{change_24h:.1f}%)")

        if pe_score >= 50:
            candidates.append(PlaybookMatch(
                playbook=PlaybookType.PUMP_EXHAUSTION.value,
                direction=DirectionMode.SHORT.value,
                score=min(100, pe_score),
                title_id="Strategi Jual di Pucuk (Pump Exhaustion)",
                explanation_id="Harga koin mengalami kenaikan tajam namun momentum pembeli telah habis di puncak grafik. Bot bersiap mengambil keuntungan dari pembalikan harga turun.",
                recommended_rr=2.5,
                matched_signals=pe_signals
            ))

    # -------------------------------------------------------------
    # 2. SUPPORT_PULLBACK (LONG)
    # -------------------------------------------------------------
    sp_signals = []
    sp_score = 0
    trend = ema.get("trend", "NEUTRAL")

    # P1-2 Mandatory Condition: MUST have real support zone and NOT be in breakdown danger
    has_sp_core = (
        fib.get("is_golden_pullback") is True
        or fib.get("zone") in ("GOLDEN_POCKET", "SUPPORT_RETEST", "PULLBACK_VALUE")
    )
    is_sp_breakdown = bool(fib.get("is_dump_extended") or fib.get("is_long_breakdown_danger"))

    if has_sp_core and not is_sp_breakdown:
        if fib.get("is_golden_pullback"):
            sp_score += 30
            sp_signals.append("Koreksi sehat di area Golden Pocket Fib (0.382 - 0.618)")

        if trend in ("STRONG_UPTREND", "MILD_UPTREND"):
            sp_score += 25
            sp_signals.append(f"Tren makro EMA mendukung kenaikan ({trend})")

        if rsi.get("divergence") == "BULLISH_DIV":
            sp_score += 25
            sp_signals.append("Bullish Divergence (daya beli mulai menguat)")
        elif 32.0 <= rsi_15m <= 48.0:
            sp_score += 15
            sp_signals.append(f"RSI berada di area diskon koreksi ({rsi_15m:.1f})")

        if fib and not is_sp_breakdown:
            sp_score += 15
            sp_signals.append("Struktur support belum rusak")

        if bb.get("is_overextended_lower"):
            sp_score += 10
            sp_signals.append("Harga menguji pita bawah Bollinger Bands")

        if 0.5 <= change_24h <= 40.0:
            sp_score += 10
            sp_signals.append("Rentang kenaikan 24 jam dalam batas stabil")

        if sp_score >= 50:
            candidates.append(PlaybookMatch(
                playbook=PlaybookType.SUPPORT_PULLBACK.value,
                direction=DirectionMode.LONG.value,
                score=min(100, sp_score),
                title_id="Strategi Beli Pantulan Sehat (Support Pullback)",
                explanation_id="Koin berada dalam tren naik makro dan baru saja menyelesaikan koreksi sehat di area support kunci. Bot bersiap membeli saat harga mulai memantul naik.",
                recommended_rr=2.0,
                matched_signals=sp_signals
            ))

    # -------------------------------------------------------------
    # 3. BREAKDOWN_RETEST (SHORT)
    # -------------------------------------------------------------
    br_signals = []
    br_score = 0
    ratio = float(fib.get("retracement_ratio", 0.0) or 0.0)

    # P1-2 Mandatory Condition: MUST have actual structural breakdown of major support
    has_br_breakdown = (
        ratio >= 0.65
        or fib.get("is_dump_extended") is True
        or fib.get("zone") in ("BREAKDOWN", "BELOW_SUPPORT")
    )

    if has_br_breakdown:
        if trend in ("STRONG_DOWNTREND", "MILD_DOWNTREND"):
            br_score += 30
            br_signals.append("Tren makro EMA dominan menurun")

        br_score += 25
        br_signals.append("Support utama telah ditembus (Breakdown)")

        if float(imp.get("wick_15m", 0.0) or 0.0) >= 0.20:
            br_score += 20
            br_signals.append("Upaya pantulan kembali tertolak (Retest Rejection)")

        if rsi_15m <= 48.0:
            br_score += 15
            br_signals.append(f"RSI lemah di bawah batas netral ({rsi_15m:.1f})")

        if br_score >= 50:
            candidates.append(PlaybookMatch(
                playbook=PlaybookType.BREAKDOWN_RETEST.value,
                direction=DirectionMode.SHORT.value,
                score=min(100, br_score),
                title_id="Strategi Jebol Support (Breakdown Retest)",
                explanation_id="Garis pertahanan harga (support) telah ditembus ke bawah dan upaya pantulan gagal. Bot bersiap membuka posisi jual mengikuti arus penurunan.",
                recommended_rr=2.0,
                matched_signals=br_signals
            ))

    # -------------------------------------------------------------
    # 4. FUNDING_SQUEEZE (SHORT)
    # -------------------------------------------------------------
    fs_signals = []
    fs_score = 0

    if f_sent == "EXTREME_LONG_CROWD" or (fr is not None and fr >= 0.0008):
        fs_score += 40
        fs_signals.append("Funding rate positif ekstrem (kerumunan pembeli overleveraged)")
    elif f_sent == "MODERATE_LONG_CROWD" or (fr is not None and fr >= 0.0003):
        fs_score += 20
        fs_signals.append("Funding rate condong berat ke sisi Long")

    if rsi_15m >= 62.0 or fib.get("is_peak_exhaustion"):
        fs_score += 25
        fs_signals.append("Harga di area rawan aksi ambil untung")

    if imp.get("volume_fade"):
        fs_score += 20
        fs_signals.append("Volume transaksi mulai mengering")

    if fs_score >= 55:
        candidates.append(PlaybookMatch(
            playbook=PlaybookType.FUNDING_SQUEEZE.value,
            direction=DirectionMode.SHORT.value,
            score=min(100, fs_score),
            title_id="Strategi Tekanan Biaya Pasar (Funding Squeeze)",
            explanation_id="Biaya pasar (Funding Rate) sangat tinggi karena terlalu banyak trader ritel bertaruh posisi Beli. Bot memanfaatkan potensi likuidasi massal saat harga berbalik turun.",
            recommended_rr=2.0,
            matched_signals=fs_signals
        ))

    # -------------------------------------------------------------
    # 5. OVERSOLD_REVERSAL (LONG)
    # -------------------------------------------------------------
    # Strict conjunction requirement:
    # 1. Oversold condition
    # 2. Bullish divergence
    # 3. Actual bullish confirmation / support reclaim from available candle features
    is_os = bool(rsi.get("is_oversold") or rsi_15m <= 32.0 or (bb.get("is_overextended_lower") and rsi_15m <= 38.0))
    has_bull_div = (rsi.get("divergence") == "BULLISH_DIV")

    lower_wick_15m = float(imp.get("lower_wick_15m", 0.0) or 0.0)
    lower_wick_1h = float(imp.get("lower_wick_1h", 0.0) or 0.0)
    has_wick_rejection = (lower_wick_15m >= 0.25 or lower_wick_1h >= 0.20 or bool(imp.get("confluent_lower_rejection")))

    timeframes = mf.get("timeframes") or {}
    last_direction_15m = timeframes.get("15m", {}).get("last_direction")
    consec_bull = float(imp.get("consecutive_bull_bars", 0) or 0)
    has_bull_candle = (last_direction_15m == "UP" or consec_bull >= 1)

    swing_low = float(fib.get("swing_low", 0.0) or 0.0)
    percent_b = float(bb.get("percent_b", 0.5) or 0.5)
    has_support_reclaim = (swing_low > 0 and price >= swing_low) or (percent_b >= 0.05)

    has_confirmation = has_wick_rejection or has_bull_candle or has_support_reclaim

    # Strict conjunction: MUST have oversold + bullish divergence + confirmation
    if is_os and has_bull_div and has_confirmation:
        os_score = 50  # Base score for meeting the strict conjunction
        os_signals = [
            f"Kondisi jenuh jual (RSI: {rsi_15m:.1f})",
            "Bullish Divergence terkonfirmasi (RSI vs Harga)",
        ]

        if has_wick_rejection:
            os_score += 20
            os_signals.append(f"Penolakan harga bawah (Lower wick: {lower_wick_15m:.1%})")

        if has_bull_candle:
            os_score += 15
            os_signals.append("Konfirmasi candle pembalikan arah naik (Bullish Reversal)")

        if has_support_reclaim:
            os_score += 15
            os_signals.append("Reclaim batas support / pantulan Bollinger Bands")

        if os_score >= 50:
            candidates.append(PlaybookMatch(
                playbook=PlaybookType.OVERSOLD_REVERSAL.value,
                direction=DirectionMode.LONG.value,
                score=min(100, os_score),
                title_id="Strategi Pembalikan Jenuh Jual (Oversold Reversal)",
                explanation_id="Koin mengalami tekanan jual ekstrem namun menunjukkan divergensi bullish dan konfirmasi pantulan support. Bot bersiap membuka posisi beli pembalikan arah.",
                recommended_rr=2.5,
                matched_signals=os_signals
            ))

    # -------------------------------------------------------------
    # Select Best Match
    # -------------------------------------------------------------
    if not candidates:
        return PlaybookMatch(
            playbook=PlaybookType.NONE.value,
            direction=DirectionMode.SHORT.value,
            score=0,
            title_id="Pemantauan Pasar Konservatif",
            explanation_id="Pergerakan harga saat ini belum membentuk pola keuntungan tinggi yang jelas. Bot tetap siaga memantau tanpa memaksakan risiko.",
            recommended_rr=2.0,
            matched_signals=["Kondisi pasar abu-abu / tidak ada keunggulan statistik"]
        )

    # Sort descending by score
    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[0]
