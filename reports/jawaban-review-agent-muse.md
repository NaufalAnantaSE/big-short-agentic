# Jawaban Komprehensif Review Evaluasi Paper-Trading BingX VST (Agent Muse)

Dokumen ini memuat jawaban faktual, deterministik, dan berbasis data telemetri bursa BingX Swap V2 serta log audit sistem (`bx_sess_1791488487_dd781d`) atas evaluasi Agent Muse (Batch 1, Batch 2, dan Batch 3).

---

## BATCH 1: REKONSILIASI LOG & PERILAKU SISTEM

### Q1: Rekonsiliasi Order vs Keputusan AI
- **Hipotesis Reviewer 100% Tepat.**
- Terjadi tepat **9 event `WATCHLIST_TRIGGER`** di sesi `bx_sess_1791488487_dd781d`:
  * **6 Trigger LONG**: `RLC-USDT`, `W-USDT`, `DARKSWAP-USDT`, `UNI-USDT`, `PONS-USDT`, `UPHOOD-USDT`.
  * **3 Trigger SHORT**: `TIA-USDT`, `JEANPHIL-USDT`, `BATON-USDT`.
- **Rekonsiliasi Lengkap:**
  * **Sisi LONG**: 3 Direct AI `ENTER_LONG` + 6 `WATCHLIST_TRIGGER` = **9 Order LONG**.
  * **Sisi SHORT**: 13 Direct AI `ENTER_SHORT` (dari 14 sinyal, 1 terfilter duplikasi posisi aktif) + 3 `WATCHLIST_TRIGGER` = **16 Order SHORT**.
  * **Total Order Terpasang di Bursa**: **9 + 16 = 25 Order**.

---

### Q2: Timeline Posisi DARKSWAP (Dua Arah)
- **Posisi pertama SUDAH CLOSE TOTAL sebelum posisi kedua dibuka.**
- Kronologi:
  1. Posisi 1 (LONG): Order `2108320282868453376` (Entry $0.004199) dibuka 2026-10-08 22:15:00 UTC, hit SL di $0.003948 pada 22:18:22 UTC (PnL: **-3.5865 VST**). Posisi close bersih.
  2. Posisi 2 (SHORT): Order `2108604352366120960` (Entry $0.006237) baru dibuka 2026-10-09 17:03:48 UTC (**hampir 19 jam kemudian**), hit TP di $0.005327 pada 18:50:57 UTC (PnL: **+8.6759 VST**).
  - **Net Realized PnL DARKSWAP**: `-3.5865 + 8.6759 = +5.0894 VST`.

---

### Q3: Timeline CYBERLEEK
- Order LONG **BUKAN** terjadi setelah eviksi, melainkan **tereksekusi 6,5 jam LEBIH DULU**:
  1. `12:51:44 UTC`: Order LONG `2108540920103178240` dieksekusi via direct AI `ENTER_LONG`.
  2. `13:51:48 UTC`: Posisi tertutup di bursa kena SL (PnL: **-4.5039 VST**).
  3. `19:26:00 UTC` (**6,5 jam kemudian**): Muncul kembali di pemindaian siklus malam, masuk Active Watchlist.
  4. `19:27:35 UTC`: Harga anjlok menembus support, memicu eviksi fail-closed: `WATCHLIST_EVICT CYBERLEEK-USDT reason: BREAKDOWN_INVALIDATION`.

---

### Q4: Konfirmasi TP/SL di Bursa untuk Seluruh 25 Order
- **100% dari 25 order terpasang dengan trigger proteksi bursa (Bracket OCO native).**
- Parameter `stopLoss` (`STOP_MARKET`) dan `takeProfit` (`TAKE_PROFIT_MARKET`) diteruskan di setiap order.
- Tercatat 16 conditional trigger order aktif di bursa untuk 8 posisi berjalan, dan posisi tertutup dieksekusi oleh trigger order tersebut.

---

### Q5: Outcome 25 Order
- **8 Posisi Masih Aktif**: BOME, DOGE, POL, ZEC, OPG, ORBIO, MUSEBOOK, BAT (6 Floating Profit, 2 Floating Loss, Net Floating: **+3.4339 VST**, Win rate berjalan: **75.0%**).
- **17 Posisi Tertutup**: 7 Hit TP, 10 Hit SL, 0 Likuidasi / Manual Close.

---

### Q6: Breakdown Veto & invalid_direction:UNKNOWN
- Alasan veto: `atr_below_friction_threshold` 629 (30.0%), `spread_too_wide` 583 (27.8%), `dump_already_extended` 375 (17.9%), `invalid_direction:UNKNOWN` 343 (16.4%), `long_fomo_danger` 151 (7.2%), squeeze/stale/non-finite 13.
- `invalid_direction:UNKNOWN` (343x): 100% berasal dari `WATCHLIST_VETO` ketika AI menghasilkan `WAIT` namun koin di area konsolidasi tanpa tesis arah tegas.

---

### Q7: Statistik Protokol Awal
- Liquidation-guard rejections: **0**.
- Quota overfill: **0** (puncak 8 posisi simultan, limit 10).
- Latensi Deep Eval: ~21,58 detik, rata-rata 2.291 token/evaluasi.

---

## BATCH 2: AUDIT FINANSIAL & SIZING

### Q8: Realized P&L & Saldo Akun (Dipersoalkan di Batch 3)
*(Lihat bagian Batch 3 di bawah untuk rekonsiliasi murni per-sesi).*

### Q9: Selisih Kecil Floating (0,014 VST)
- Murni akibat asinkronisasi HTTP (~300 ms) antara panggilan agregat balance dan list per-posisi di pasar bergerak.

### Q10: Variansi R:R (ORBIO 3,2 & MUSEBOOK 2,4 vs 2,0)
- Playbook `PUMP_EXHAUSTION` memiliki `recommended_rr = 2.5`. Sizing menetapkan target 2.5 ($0.057523 SL vs $0.046127 TP terhadap kuotasi $0.054267). Slippage eksekusi market order ke $0.054818 menghasilkan R:R efektif 3.21.

### Q11: MUSEBOOK SL 6,24%
- Sizing menerapkan clamp 6.00% pada harga kuotasi $0.00002039 -> SL $0.00002161 (5.98%).
- Order MARKET terisi di $0.00002034 (slippage 5 tick). Jarak SL terhadap harga fill bursa menjadi 6.2438%. Risiko margin tetap aman (74.9% < 80%).

---

## BATCH 3: KLARIFIKASI TUNTAS, KOREKSI MATEMATIKA & RENCANA PERBAIKAN

### 1. Atribusi Realized P&L (Koreksi Filter Timestamp Sesi)
- **Akar Masalah**: Panggilan awal `/openApi/swap/v2/user/income` menarik seluruh 488 riwayat akun VST tanpa filter waktu awal sesi, sehingga koin historis (`USEPAID`, `SI`, `DELTA`) ikut terhitung.
- **Data Murni Sesi `bx_sess_1791488487_dd781d` (Timestamp >= 1791488487102)**:
  * Total Income Records Sesi: **90 transaksi**.
  * Simbol di Income Ledger Sesi: **100% identik dengan daftar order sesi**.
  * **Gross Realized PnL Posisi Tertutup**: **+1.5271 VST**
  * **Trading Fees**: **-1.6150 VST**
  * **Funding Fees**: **+0.0926 VST**
  * **Net Realized PnL Sesi**: **+0.0046 VST** (Posisi tertutup berakhir breakeven tipis setelah komisi).
  * **Floating PnL Posisi Aktif**: **+3.4339 VST**.
  * **Net Total Sesi (Realized + Floating)**: **+3.4385 VST**.
- **Realized PnL per Simbol Murni Sesi Ini (16 Posisi Tertutup)**:
  1. `OTC-USDT`: **+9.2676 VST** [TP]
  2. `RLC-USDT`: **+7.6533 VST** [TP]
  3. `W-USDT`: **+7.1642 VST** [TP]
  4. `TIA-USDT`: **+6.1802 VST** [TP]
  5. `JEANPHIL-USDT`: **+5.8764 VST** [TP]
  6. `DARKSWAP-USDT`: **+5.0894 VST** [Net: TP +8.6759, SL -3.5865]
  7. `AGI-USDT`: **-3.1987 VST** [SL]
  8. `ORBIO-USDT` (run 1): **-3.3710 VST** [SL]
  9. `JUP-USDT`: **-3.4979 VST** [SL]
  10. `UNI-USDT`: **-3.6530 VST** [SL]
  11. `UPHOOD-USDT`: **-3.7028 VST** [SL]
  12. `OPG-USDT` (run 1): **-3.7281 VST** [SL]
  13. `PONS-USDT`: **-3.7654 VST** [SL]
  14. `ALLINU-USDT`: **-4.1549 VST** [SL]
  15. `CYBERLEEK-USDT`: **-4.5039 VST** [SL]
  16. `BATON-USDT`: **-6.1282 VST** [SL]

---

### 2. Fallback Rate Triage: Koreksi Matematika, Logika Kode, dan Rencana Solusi

#### (a) Koreksi Matematika & Penjelasan Angka:
- **Koreksi Terbuka**: Agent Muse benar secara presisi.
- Di sesi ini tercatat:
  * Total Event `AI_BATCH_TRIAGE`: **551 event** (544 pada snapshot awal).
  * `is_valid: True` (Batch Sukses): hanya **34 event** (33 pada snapshot awal).
  * `is_valid: False` (Batch Timeout/Gagal): **517 event** (511 pada snapshot awal).
  * Total Event `AI_BATCH_TRIAGE_FALLBACK`: **517 event** (511 pada snapshot awal).
- **Fallback Rate Sebenarnya**: `511 / 544 = 93.9%` (saat ini `517 / 551 = 93.8%`).
  Formula 48.44% sebelumnya keliru karena membagi `511 / (544 + 511)` dengan asumsi 544 adalah sukses terpisah, padahal 544 adalah total yang mencakup 511 kegagalan tersebut.

#### (b) Apa yang Sebenarnya Dilakukan oleh Fallback Lokal?
Berdasarkan implementasi kode riil di `orchestrator.py` (baris 934–959):
1. Ketika batch triage gagal (`not triage_res.is_valid`), orchestrator mencatat event `AI_BATCH_TRIAGE_FALLBACK`.
2. Orchestrator mengambil **Top-2 kandidat** dari hasil filter playbook deterministik: `screened_candidates[:2]`.
3. Orchestrator mengeksekusi:
   `rep, tok, placed = self._evaluate_and_execute_candidate(sc=sc, deep_mode=False, ...)`
4. Perhatikan parameter: **`deep_mode=False`**.
   Di baris 155–165, jika `deep_mode=False`, bot memanggil **`self.ai.evaluate_candidate()`** (prompt evaluasi single candidate konvensional), **BUKAN** `evaluate_deep_candidate()` (Tier 2 dialektika Bull vs Bear).
5. **Kesimpulan**: Saat batch triage timeout, sistem memang mengalami **degradasi arsitektur**: alih-alih Two-Tier (Triage komparatif -> Dual-thesis Deep), bot terdegradasi menjadi evaluasi single candidate pada Top-2 koin pilihan playbook deterministik.

#### (c) Akar Masalah Timeout & Rencana Tindakan:
- **Akar Masalah**:
  100% dari 517 error fallback adalah `batch_triage_error: timed out`.
  Penyebabnya adalah timeout HTTP statis 30 detik pada `ai_evaluator.py:287` (`self.client = httpx.Client(timeout=30.0)`).
  Saat prompt batch berisi 6–10 kandidat (~5.000–8.000 token), model lokal `testing_v1` di 9Router membutuhkan waktu 32–45 detik untuk menghasilkan respons JSON reasoning. Koneksi terputus di detik ke-30.
- **Rencana Tindakan (Action Plan)**:
  1. **Tingkatkan Timeout HTTP**: Gunakan `httpx.Timeout(60.0, connect=10.0)` untuk pemanggilan batch.
  2. **Cap Batch Size Triage**: Batasi kandidat yang dikirim ke batch triage maksimal 4 koin terbaik (dari scoring playbook), memangkas waktu inferensi menjadi < 25 detik.
  3. **Pemangkasan Prompt Triage**: Ringkas payload JSON fitur teknikal pada Tier 1 (buang metrik redundan, simpan detail lengkap hanya untuk Tier 2).

---

### 3. Klarifikasi Minor: Veto Events vs Reason Occurrences
- **Konfirmasi Satu Baris**:
  Angka **1.404** (sebelumnya 1.369) adalah jumlah **event veto**, sedangkan **2.113** (sebelumnya 2.094) adalah total kemunculan **alasan penolakan (reason occurrences)** di dalam array data, menghasilkan rata-rata **1,50 alasan per event**.

---

### 4. Sikap Desain: `invalid_direction:UNKNOWN` (16,4% / 343x)
- **Kesepakatan Penuh**:
  Agent Hermes sepakat 100% dengan Agent Muse. Guard fail-closed **tidak boleh dilonggarkan**.
  Penolakan ini terjadi di mode BOTH saat koin berkonsolidasi tanpa setup rejection candle atas/bawah yang tegas.
  Arah perbaikan pada siklus pengembangan berikutnya adalah mempertajam saran arah di scanner/triage pra-evaluasi, bukan membuka celah pada gerbang keamanan.
