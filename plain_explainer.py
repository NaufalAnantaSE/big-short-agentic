"""Plain Explainer module: Translates quantitative AI signals and market data
into clear, reassuring, senior-friendly Indonesian language for older clients and non-technical users.
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
    leverage: int = 20
) -> Dict[str, Any]:
    """
    Produces a senior-friendly narrative card with high legibility and clear, empathetic explanations.
    """
    decision = decision.upper()
    clean_sym = symbol.replace("-USDT", "")
    
    # 1. Headline badge & title
    if decision == "ENTER_SHORT":
        badge_color = "emerald"
        badge_label = "REKOMENDASI: AMAN BUKA POSISI JUAL"
        summary_title = f"Koin {clean_sym} Siap Dijual (Potensi Penurunan Terbuka)"
        action_advice = "AI mendeteksi lonjakan harga telah mencapai batas jenuh pembeli. Sangat ideal untuk membuka posisi jual (Short) dengan modal kecil yang terukur."
    elif decision == "WAIT":
        badge_color = "amber"
        badge_label = "STATUS: SEDANG DIPANTAU (TUNGGU MOMEN)"
        summary_title = f"Koin {clean_sym} Masih Naik, AI Memilih Menunggu"
        action_advice = "Koin ini sedang mengalami kenaikan tajam namun belum menunjukkan tanda pasti penurunan. Untuk menjaga modal Anda tetap aman, bot menahan diri sampai pembeli benar-benar habis."
    else:  # SKIP
        badge_color = "slate"
        badge_label = "STATUS: DILEWATI DEMI KEAMANAN"
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

    # 3. Simple explanation of technical evidence
    plain_reason = ""
    evidence_lower = (evidence or "").lower()
    risk_lower = (risk_factors or "").lower()

    if "hard gate" in evidence_lower or "hard_gate" in evidence_lower:
        plain_reason = "Koin ini otomatis disaring oleh sistem keamanan awal karena kriteria dasar pasar (seperti volume transaksi atau stabilitas harga) belum memenuhi syarat ketat."
    elif "exhaustion" in evidence_lower or "buyer dry-up" in evidence_lower or "rejection" in evidence_lower:
        plain_reason = "Grafik menunjukkan bahwa para pembeli besar sudah mulai berhenti membeli dan harga mulai tertahan di atas, menandakan penurunan segera terjadi."
    elif "illiquid" in evidence_lower or "volume" in evidence_lower or "drought" in evidence_lower:
        plain_reason = "Aktivitas transaksi koin ini terlalu sedikit atau sepi di pasar. Demi keselamatan modal Anda, bot tidak memaksakan masuk."
    elif "flat" in evidence_lower or "consolidation" in evidence_lower:
        plain_reason = "Harga koin bergerak menyamping tanpa arah tren yang jelas, sehingga tidak ada peluang menguntungkan saat ini."
    else:
        plain_reason = evidence if evidence else "AI telah mengkaji struktur pergerakan koin dan memilih opsi paling berhati-hati."

    # 4. Senior-friendly capital transparency note
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
        "raw_risk": risk_factors
    }
