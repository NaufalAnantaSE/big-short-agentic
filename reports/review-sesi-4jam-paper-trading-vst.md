# Review Sesi Paper-Trading 4 Jam — BingX VST

**Sesi:** `bx_sess_1791579205_ab6bff` | **Durasi:** 3 jam 58 menit (109 siklus)
**Waktu:** 2026-10-09 20:53 UTC → 2026-10-10 00:52 UTC
**Mode:** BOTH, PUMP_GAINERS, margin $5/posisi, leverage adaptif (maks 20x), kuota 10
**Reviewer:** Agent Muse | **Executor:** Agent Hermes
**Tanggal review:** 2026-10-10

---

## 1. Verdict 3 Prasyarat Live Money

| Prasyarat | Target | Hasil | Status |
|---|---|---|---|
| #1 — Timeout 60s, compact prompt, cap 4, guardrail RR≥2.0 | Implementasi + test hijau | 171/171 test lolos; diverifikasi di diff `e30dd3e` + `8a7fd81` | **PASS** ✅ |
| #2 — Fallback rate < 10% | < 10% | **26,6%** (29/109), 100% READ_TIMEOUT di 60s | **BELUM TERCAPAI** ⚠️ |
| #3 — Guardrail RR + mitigasi fee drag | RR≥2.0 di kode | 9/9 order RR 2,00–2,50x (avg 2,33x) | **PASS (guardrail)** ✅ |

Progress #2 substansial (93,8% → 26,6%), tapi target belum kena. Lihat catatan penting di bagian 3.

---

## 2. Finansial — Terverifikasi Penuh

Agent Muse merekonsiliasi ulang seluruh angka terhadap tabel trade-by-trade — **semua cocok**.

- **Net sesi: −11,0981 VST** (wallet 100.149,28 → 100.138,18; cocok persis dengan ledger bursa)
- Gross realized −10,6424 + fee −0,5439 + funding +0,0881 = −11,0981 ✓
- Equity = Balance + Floating: 100.138,18 + 0,8439 = 100.139,03 ✓
- **9 order** (7 SHORT, 2 LONG) → **4 close, semuanya kena SL** (winrate 0%), 5 masih open
- Rata-rata loss: −2,66 VST/trade. Floating 5 posisi baru: +0,5472 (MUSEBOOK +0,53, NEAR +0,20)

**Penilaian:** guardrail bekerja (semua loss terukur, tidak ada likuidasi), tapi *edge* belum terbukti — n=9 terlalu kecil, sesuai ekspektasi yang disepakati. Observasi: JEANPHIL LONG kena SL dalam 19 detik (entry timing buruk); DARKSWAP LONG rugi terbesar (−4,24).

Catatan: floating total +0,8439 mencakup 7 posisi (5 baru + 2 legacy sesi sebelumnya); +0,5472 khusus 5 posisi sesi ini.

---

## 3. Teknis — Fallback & Two-Tier

- **Latensi triage sukses:** mean 25,11s, median 20,26s, P90 46,78s, maks 51,68s (dari >60s sebelumnya). Two-tier kini aktif di ~3/4 siklus.
- **29 fallback:** 100% `READ_TIMEOUT` tepat di 60,000–60,008 ms. Model (`testing_v1` → reasoning backend) menghasilkan 1.500–2.600 token penalaran per evaluasi; saat antrean padat, inferensi membengkak ke 62–68s.
- **Keberatan metodologis:** argumen "P90 46,78s → timeout 75s akan serap >95%" adalah *survivorship bias* — P90 dihitung dari panggilan yang sukses saja, tidak memprediksi ekor kegagalan.
- **Rekomendasi:** setujui bump read timeout 60s → 75s sebagai langkah taktis, tapi waspadai *diminishing returns*. Opsi struktural: batasi thinking-token di gateway bila ada parameternya.
- **Reframing penting:** target <10% ditetapkan saat fallback = degradasi ke single-candidate. Kini fallback = dual-thesis (`deep_mode=True`), jauh lebih kuat — 26,6% tidak seburuk angka mentahnya. Namun target tetap target.
- **Tier 2:** 206 deep eval, avg 16,01s. Keputusan: SKIP 37,4% / WAIT 57,3% / ENTER 5,3% (7 SHORT + 4 LONG). Selektivitas sehat, tidak over-trading.
- **Veto:** `atr_below_friction` 44,7%, `spread_too_wide` 32,2%, `long_fomo_danger` 13,5%, `dump_already_extended` 9,5%. Nol API error.
- **Interleave P2:** terverifikasi empiris — fallback mengevaluasi MUSEBOOK (LONG) + BATON (SHORT) secara berimbang.

---

## 4. Keputusan & Langkah Lanjut

1. **Bump read timeout → 75s** — disetujui (dengan catatan di atas).
2. **Sampel profitabilitas lebih panjang** — sesi 2–4 jam memvalidasi arsitektur, bukan edge. Edge statistik butuh sampel lebih besar sebelum live money.
3. **Pertanyaan terbuka** (detail di `daftar-pertanyaan-review-paper-trading.md`, Batch 4):
   - Rekonsiliasi 11 ENTER → 9 order (2 tidak tereksekusi kenapa?) + WATCHLIST_TRIGGER count
   - Hitungan `invalid_direction:UNKNOWN` sesi ini (apakah prompt baru menghilangkannya?)
   - Konfirmasi selisih floating 0,2967 = 2 posisi legacy

**Kesimpulan:** pipeline dan risk rails solid, arsitektur two-tier hidup kembali, guardrail RR efektif. Yang belum: fallback <10% dan bukti edge statistik. Belum saatnya live money — tapi arahnya benar.
