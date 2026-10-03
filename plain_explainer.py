"""Plain Explainer module: Translates quantitative AI signals, Fibonacci retracements,
impulse exhaustion, and market data into clear, reassuring, senior-friendly Indonesian language.
"""

from typing import Dict, Any, Optional

def humanize_ai_decision(
    symbol: str,
    decision: str,
    confidence: int,
    evidence: str,
    risk_factors: str,
    price: float,
    change_24h: float,
    spread_pct: float,
    margin_per_pos: float = 5.0,
    leverage: int = 20,
    executed: bool = False,
    order_id: Optional[str] = None,
    dry_run: bool = False,
    sizing_valid: bool = True,
    is_quota_full: bool = False,
    fibonacci: Optional[Dict[str, Any]] = None,
    impulse_wave: Optional[Dict[str, Any]] = None,
    funding_sentiment: Optional[str] = None,
    funding_rate: Optional[float] = None
) -> Dict[str, Any]:
    """
    Produces a senior-friendly narrative card with high legibility and clear, empathetic explanations.
    """
    decision = decision.upper()
    clean_sym = symbol.replace("-USDT", "")
    
    # 1. Headline badge & title
    if decision == "ENTER_SHORT":
        badge_color = "emerald"
        if executed:
            badge_label = "ORDER SHORT TERPASANG"
            summary_title = f"Posisi Jual Koin {clean_sym} Berhasil Dibuka"
            action_advice = f"AI mendeteksi batas jenuh pembeli dan posisi jual (Short) telah berhasil dieksekusi ke bursa BingX (Order ID: {order_id or '-'})."
        elif dry_run:
            badge_label = "SIMULASI SHORT TERBUKA"
            summary_title = f"Simulasi Short Koin {clean_sym} Aktif"
            action_advice = "Koin memenuhi kriteria short dan simulasi eksekusi berhasil dicatat dalam mode dry-run."
        elif is_quota_full:
            badge_color = "slate"
            badge_label = "TERTAHAN: KUOTA PENUH"
            summary_title = f"Koin {clean_sym} Siap Dijual (Tertahan Kuota)"
            action_advice = "Koin ini sangat ideal untuk di-short, namun kuota maksimal posisi akun Anda saat ini sudah penuh."
        elif not sizing_valid:
            badge_color = "amber"
            badge_label = "TERLEWAT: MINIMAL BURSA"
            summary_title = f"Koin {clean_sym} Dilewati (Notional di Bawah Min Bursa)"
            action_advice = "Koin ini memiliki sinyal short yang baik, tetapi batas minimum transaksi BingX untuk pair ini lebih besar dari margin per koin Anda."
        else:
            badge_label = "EKSEKUSI: SIAP BUKA POSISI"
            summary_title = f"Koin {clean_sym} Siap Dijual (Potensi Penurunan Terbuka)"
            action_advice = "AI mendeteksi lonjakan harga telah mencapai batas jenuh pembeli. Posisi jual (Short) siap dieksekusi."
    elif decision == "WAIT":
        badge_color = "amber"
        badge_label = "STATUS: MEMANTAU (TUNGGU MOMEN)"
        summary_title = f"Koin {clean_sym} Masih Naik, AI Menunggu Puncak Jenuh"
        action_advice = "Koin ini sedang mengalami kenaikan tajam namun belum menunjukkan tanda pasti penurunan. Untuk menjaga modal Anda tetap aman, bot menahan diri sampai pembeli benar-benar habis."
    else:  # SKIP
        badge_color = "slate"
        badge_label = "STATUS: DILEWATI"
        summary_title = f"Koin {clean_sym} Dilewati (Risiko Kurang Ideal)"
        action_advice = "Koin ini dilewati karena pergerakan harga tidak memenuhi standar keamanan atau transaksi pasar sedang terlalu sepi."

    # 2. Plain market context
    market_notes = []
    if change_24h > 10.0:
        market_notes.append(f"Harga melonjak +{change_24h:.1f}% dalam 24 jam terakhir.")
    elif change_24h < -5.0:
        market_notes.append(f"Harga koin sudah turun tajam ({change_24h:.1f}%), bukan saat ideal membuka posisi jual baru.")
    else:
        market_notes.append(f"Pergerakan harga 24 jam cenderung datar ({change_24h:+.1f}%).")

    if spread_pct > 0.20:
        market_notes.append("Selisih harga jual dan beli di pasar agak renggang (biaya masuk lebih besar).")
    else:
        market_notes.append("Likuiditas pasar cukup baik dan transaksi berlangsung lancar.")

    # 3. Fibonacci & Impulse Wave Explanations
    fib_note = ""
    if fibonacci and fibonacci.get("valid"):
        zone = fibonacci.get("zone")
        ratio = float(fibonacci.get("retracement_ratio", 0.0) or 0.0)
        pct = max(0.0, min(100.0, ratio * 100.0))
        if zone == "PEAK_EXHAUSTION":
            fib_note = f"Analisa Fibonacci: Berada di puncak kenaikan (koreksi baru {pct:.1f}%), peluang posisi jual paling optimal."
        elif zone == "BLOW_OFF_EXTENSION":
            fib_note = "Analisa Fibonacci: Lonjakan ekstrem menembus batas atas (Blow-Off Top), jenuh beli sangat tinggi."
        elif zone == "SHALLOW_PULLBACK":
            fib_note = f"Analisa Fibonacci: Penolakan harga awal terkonfirmasi (koreksi {pct:.1f}% dari puncak)."
        elif zone == "EXTENDED_DUMP":
            fib_note = f"Analisa Fibonacci: Harga sudah anjlok terlalu jauh ({pct:.1f}%), sistem mencegah jual di dasar."
        else:
            fib_note = f"Analisa Fibonacci: Berada di zona tengah gelombang ({pct:.1f}%)."
        market_notes.append(fib_note)

    wave_note = ""
    if impulse_wave and impulse_wave.get("valid"):
        bars = impulse_wave.get("consecutive_bull_bars", 0)
        fade = impulse_wave.get("volume_fade", False)
        confluent = impulse_wave.get("confluent_rejection", False)
        score = impulse_wave.get("exhaustion_score", 0)
        parts = []
        if bars >= 3:
            parts.append(f"{bars} candle naik beruntun")
        if fade:
            parts.append("volume beli melemah")
        if confluent:
            parts.append("ekor penolakan atas jelas")
        if parts:
            wave_note = f"Struktur Gelombang: {', '.join(parts)} (Skor Jenuh Pasar: {score}/100)."
            market_notes.append(wave_note)

    funding_note = ""
    if funding_sentiment:
        fr_pct = (funding_rate * 100) if funding_rate is not None else None
        fr_str = f" ({fr_pct:+.3f}%)" if fr_pct is not None else ""
        if funding_sentiment == "EXTREME_LONG_CROWD":
            funding_note = f"Biaya Pasar (Funding Rate): Posisi Long sangat padat{fr_str}, pembeli membayar fee ke Short."
            market_notes.append(funding_note)
        elif funding_sentiment == "MODERATE_LONG_CROWD":
            funding_note = f"Biaya Pasar (Funding Rate): Posisi Long aktif membayar fee{fr_str}."
            market_notes.append(funding_note)
        elif funding_sentiment == "EXTREME_SHORT_CROWD_SQUEEZE_RISK":
            funding_note = f"Biaya Pasar (Funding Rate): Waspada short squeeze{fr_str}."
            market_notes.append(funding_note)

    # 4. Simple explanation of technical evidence
    plain_reason = ""
    evidence_lower = (evidence or "").lower()
    risk_lower = (risk_factors or "").lower()

    if "dump_already_extended" in risk_lower or "extended_dump" in risk_lower:
        plain_reason = "Harga koin sudah turun jauh dari puncaknya. Sistem menolak membuka posisi jual agar modal Anda tidak terjebak memantul di dasar harga."
    elif "hard gate" in evidence_lower or "hard_gate" in evidence_lower:
        plain_reason = "Koin ini otomatis disaring oleh sistem keamanan awal karena kriteria dasar pasar (seperti volume transaksi atau stabilitas harga) belum memenuhi syarat ketat."
    elif "exhaustion" in evidence_lower or "buyer dry-up" in evidence_lower or "rejection" in evidence_lower:
        plain_reason = "Grafik menunjukkan bahwa para pembeli besar sudah mulai berhenti membeli dan harga mulai tertahan di atas, menandakan penurunan segera terjadi."
    elif "illiquid" in evidence_lower or "volume" in evidence_lower or "drought" in evidence_lower:
        plain_reason = "Aktivitas transaksi koin ini terlalu sedikit atau sepi di pasar. Demi keselamatan modal Anda, bot tidak memaksakan masuk."
    elif "flat" in evidence_lower or "consolidation" in evidence_lower:
        plain_reason = "Harga koin bergerak menyamping tanpa arah tren yang jelas, sehingga tidak ada peluang menguntungkan saat ini."
    else:
        plain_reason = evidence if evidence else "AI telah mengkaji struktur pergerakan koin dan memilih opsi paling berhati-hati."

    # 5. Senior-friendly capital transparency note
    est_idr = int(margin_per_pos * 16200)
    capital_note = f"Modal dipakai: ${margin_per_pos:.2f} USDT (sekitar Rp {est_idr:,}). Posisi dikelola secara bertahap tanpa menyentuh saldo simpanan lainnya."

    return {
        "symbol": symbol,
        "clean_symbol": clean_sym,
        "price_formatted": f"${price:,.6f}" if price < 1 else f"${price:,.2f}",
        "decision": decision,
        "confidence": confidence,
        "confidence_text": f"Tingkat Keyakinan AI: {confidence}%",
        "badge_color": badge_color,
        "badge_label": badge_label,
        "summary_title": summary_title,
        "action_advice": action_advice,
        "plain_reason": plain_reason,
        "market_notes": market_notes,
        "capital_note": capital_note,
        "raw_evidence": evidence,
        "raw_risk": risk_factors,
        "fibonacci_note": fib_note,
        "wave_note": wave_note,
        "funding_note": funding_note,
        "fibonacci_zone": fibonacci.get("zone") if fibonacci else None,
        "fibonacci_retracement": fibonacci.get("retracement_ratio") if fibonacci else None,
        "exhaustion_score": impulse_wave.get("exhaustion_score") if impulse_wave else None
    }
