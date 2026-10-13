# Protokol Pendaftaran Batch Konfirmasi SHORT-Only (Pre-Registered Experiment Protocol)

**Tanggal Pendaftaran:** 2026-10-13  
**Status:** DIDAFTARKAN (Menunggu Persetujuan Naufal Ananta Sebelum Entry Pertama)  
**Tujuan Eksperimen:** Memverifikasi secara independen dan prospektif apakah strategi pump-exhaustion SHORT menghasilkan positive expectancy pada lingkungan BingX VST setelah perbaikan F-07 dan fix silent-drop TP/SL.  
**Target Sampel:** **N = 30 trade SHORT prospektif**  

---

## 1. Spesifikasi Lingkungan & Parameter Sistem

| Parameter | Nilai Terdaftar | Keterangan |
|---|---|---|
| **Environment** | `BINGX_VST` | Paper trading swap perpetual demo resmi BingX |
| **Execution Mode** | `EXCHANGE_DEMO` | Order terkirim riil ke bursa VST (bukan local dry-run) |
| **Direction Mode** | `SHORT` | Arah LONG dan BOTH dimatikan permanen |
| **AI Model** | Gemini 3.8 Flash (`testing_v1`) | **Identik 100% dengan batch BOTH** (Dilarang ganti model/provider) |
| **AI Prompt** | Two-Tier Triage & Deep Dual-Thesis | **Identik 100% dengan batch BOTH** (Dilarang ubah prompt) |
| **Universe** | Top Volatile & Gainer Pairs | Identik dengan batch BOTH |
| **Risk Budget per Trade (1R)** | **2.00 VST / USDT** | Fixed structural risk (|entry - SL| × qty = ~$2.00) |
| **Target Risk:Reward** | **>= 2.0x** | Dynamic ATR TP/SL (SL 1.5% - 6.0%, TP >= 2x SL) |
| **Akun Sampel Utama** | **User 3 (`naufal`)** | 1 akun utama diprioritaskan demi independensi observasi |
| **Akun Sekunder** | User 5 (`agussiswanto`) | Jika aktif: entri simbol bersama dicatat sebagai 1 sinyal unik |

---

## 2. Dokumentasi Eksplisit Perbedaan Kode dari Baseline `01d31d0`

Baseline pembekuan batch BOTH adalah commit `01d31d0`. Perubahan yang berlaku pada batch konfirmasi ini strictly dibatasi pada 2 perbaikan teknis:

1. **Perbaikan F-07 (Commit `a5cf2c0`):**
   - Kode sebelumnya: `reconcile_outcomes()` hanya mencatat PnL sesi, mengabaikan kolom-kolom `order_records` sehingga status trade tetap OPEN / tidak tercatat di database tanpa backfill manual.
   - Kode sekarang: `reconcile_outcomes()` secara real-time mengonsumsi income ledger bursa (`REALIZED_PNL`, `TRADING_FEE`, `FUNDING_FEE`), memetakan order penutup dari exchange, mencatat `exit_price`, `exit_time` (timestamp bursa), `exit_reason`, `exit_fee`, `funding_fee`, `realized_pnl`, dan `realized_r` secara otomatis, transparan, dan idempoten.
2. **Perbaikan Silent-Drop TP/SL & Fail-Closed (Commit `8798187`):**
   - Kode sebelumnya: Bot mengirimkan parameter TP/SL dalam order MARKET, namun jika bursa mengabaikan conditional order anak, posisi dibiarkan terbuka telanjang tanpa SL di bursa.
   - Kode sekarang: Fungsi `_verify_and_enforce_tpsl()` memverifikasi keberadaan resting order di bursa via `get_open_orders()`. Jika terdeteksi silent drop, bot mencoba penempatan ulang via trigger order independen. Jika Stop Loss tetap tidak terkonfirmasi resting di bursa, bot **seketika menutup posisi secara darurat (fail-closed)** demi melindungi modal dari risiko *black swan*.

*Tidak ada perubahan lain pada logika screening scanner, formula indikator ATR/RSI, playbook rules, atau sizing calculator.*

---

## 3. Definisi Kurva Drawdown & Aturan Penghentian (Stopping Rules)

1. **Definisi Kurva Drawdown:**
   - Dihitung trade-by-trade secara runut waktu berdasarkan akumulasi Realized R bersih:
     $$DD_t = \max_{0 \le i \le t} (\text{CumR}_i) - \text{CumR}_t$$
2. **Batas Drawdown Maksimum (Hard Circuit Breaker):**
   - **Batas Toleransi Drawdown: 6.00 R** (~$12.00 VST).
   - Jika akumulasi drawdown menyentuh atau melebihi 6.00 R, seluruh proses scanning dan eksekusi **wajib dihentikan lebih awal (early stopping)**.
3. **Daily Loss Limit:**
   - Batas kerugian harian: 3.0% modal per sesi (~$3.00 VST). Jika tercapai, sistem memasuki status jeda hingga pergantian hari UTC.
4. **Consecutive Losses Cooldown:**
   - 3 kerugian beruntun memicu jeda pemindaian (*cooldown*) selama 30 menit.

---

## 4. Protokol Eksekusi Sampel (Sampling Protocol)

1. **Aturan Seleksi:**
   - Bot akan mengambil **30 entri terisi pertama** yang lolos filter sistem secara berurutan.
   - Dilarang keras melakukan *cherry-picking* atau memilih 30 trade yang selesai tercepat (anti-bias seleksi).
2. **Pembekuan Kuota:**
   - Begitu order entri ke-30 terisi (`filled_count == 30`), bot menghentikan pemindaian order baru (`auto_scan = 0`, status `EXHAUSTED`).
   - Sistem tetap memantau hingga seluruh 30 posisi tertutup sempurna via TP/SL bursa atau batas aturan penghentian.
3. **Integritas Observasi:**
   - Tidak diperkenankan melakukan intervensi manual (menutup posisi manual di luar aturan fail-closed sistem).
   - Tidak diperkenankan mengubah model, prompt, atau konfigurasi sizing di tengah jalan.

---

## 5. Kriteria Evaluasi Statistik (Pre-Registered Criteria)

Setelah seluruh 30 trade selesai:
1. **Metrik Finansial Definitif:**
   - Data wajib ditarik langsung dari buku besar bursa (`order_records` yang terekonsiliasi via F-07).
   - Metrik utama:
     * Mean Net Realized R per trade ($\bar{R}$)
     * Win Rate (%)
     * Profit Factor (Gross Gains / Gross Losses)
     * Total Net PnL (VST) & Total Fee Drag (%)
     * Maximum Drawdown (R)
2. **Uji Hipotesis & Confidence Interval (CI 90% Dua Sisi):**
   - Formula:
     $$CI_{90\%} = \bar{R} \pm t_{0.05, df=29} \times \frac{s}{\sqrt{30}}$$
   - **Kriteria Keberhasilan:**
     * Batas bawah $CI_{90\%} > 0.00\text{ R}$: **Mendukung hipotesis** bahwa sistem SHORT memiliki keunggulan statistik (*positive edge*). Membuka gerbang ke review terpisah untuk kesiapan dana nyata (bukan persetujuan otomatis live pilot).
     * Rentang CI mencakup angka $0.00\text{ R}$: **Inkonklusif** (memerlukan evaluasi atau peninjauan ulang).
     * Mean $\bar{R} \le 0.00\text{ R}$: **Menolak hipotesis**.
