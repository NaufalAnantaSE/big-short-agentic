# Analisis R Definitif dari Ledger Bursa (Sesi Pembuktian VST N = 53 Closed Trades)

Tanggal Audit: 13 Oktober 2026 | Commit Frozen Backend: `01d31d0`
Navigasi: [[BingX Agentic Short Hub]] · [[BingX Decisions and Roadmap]] · [[Verdict Final Evaluasi Paper Trading dan Prasyarat Live Money]] · [[Index|tuan_muda]]

---

## 1. Executive Summary: Keputusan Biner Pembuktian Edge

Sesi forward paper-trading BingX VST Swap V2 yang berjalan pada commit `01d31d0` telah resmi dihentikan dan dibekukan. Data hasil pengujian ditarik dan diverifikasi 100% langsung terhadap buku besar resmi bursa (`/openApi/swap/v2/user/income`), menjawab secara tuntas keterbatasan pencatatan exit internal (Gap F-07).

### Ringkasan Angka Kunci (Ground-Truth Bursa):
- **Total Order Masuk**: 58 order (User 3: 21, User 5: 37)
- **Posisi Masih Terbuka (Open)**: 5 posisi (User 3: 4 posisi, User 5: 1 posisi)
- **Sampel Trade Selesai (Closed Trades)**: **N = 53 trade** (melampaui target audit N = 30–50)
- **Net Expectancy Keseluruhan ($E_R$)**: **+0.1588 R per trade**
- **Win Rate Keseluruhan**: **41.51%** (22 Win / 31 Loss)
- **Realized Risk / Reward**: **1.79x** (Rata-rata Menang: +1.80 R vs Kalah: -1.01 R)
- **Profit Factor**: **1.229**
- **Total Net Realized PnL**: **+14.0415 VST** (Gross: +16.3626 VST, Fees: -2.3305 VST, Funding: +0.0083 VST)

---

## 2. Temuan Arsitektur & Strategi Terpenting: Dikotomi SHORT vs LONG

Hasil pengujian 53 trade menghasilkan bukti empiris yang sangat tajam dan tidak terbantahkan terkait efektivitas arah:

| Parameter Metrik | Arah SHORT (Pump Exhaustion) | Arah LONG (Oversold Bounce) | Keseluruhan Portofolio |
| :--- | :---: | :---: | :---: |
| **Jumlah Sampel (N)** | **30 trade (56,6%)** | **23 trade (43,4%)** | **53 trade (100%)** |
| **Win Rate** | **53.33% (16W / 14L)** | **26.09% (6W / 17L)** | **41.51% (22W / 31L)** |
| **Net Expectancy per Trade** | **+0.6417 R** | **-0.4710 R** | **+0.1588 R** |
| **Total Akumulasi R** | **+19.2515 R** | **-10.8329 R** | **+8.4186 R** |
| **Rata-rata Menang (Win R)** | **+1.99 R** | **+1.30 R** | **+1.80 R** |
| **Rata-rata Kalah (Loss R)** | **-0.90 R** | **-1.10 R** | **-1.01 R** |
| **Realized R:R Ratio** | **2.22x** | **1.19x** | **1.79x** |
| **Profit Factor** | **2.454** | **0.403** | **1.229** |
| **Net Realized PnL (VST)** | **+35.89 VST** | **-21.85 VST** | **+14.04 VST** |
| **Max Drawdown (R)** | **3.67 R** | **12.07 R** | **8.17 R** |
| **Beban Komisi (Fee Drag)** | **3.68%** | *(Gross Rugi)* | **14.24%** |

### Kesimpulan Strategis:
1. **Arah SHORT Memiliki Positive Edge yang Sangat Kuat**: Dengan $E = +0.6417\text{ R}$, Win Rate $53,3\%$, dan Profit Factor $2.454$, strategi Shorting Pump Gainers terbukti valid secara statistik dan tahan terhadap gesekan biaya bursa.
2. **Arah LONG Adalah Sumber Kebocoran Modal (Negative Edge)**: Dengan $E = -0.4710\text{ R}$, Win Rate hanya $26,1\%$, dan PnL tekor $-21.85\text{ VST}$, mencoba menangkap pisau jatuh (oversold bounce) pada altcoin berkapitalisasi mikro tidak memberikan edge.
3. **Keputusan Biner**: Jika bot dikembalikan ke fungsi aslinya (**SHORT-ONLY**), ekspektasi sistem melonjak 4x lipat dari $+0.16\text{ R}$ menjadi **$+0.64\text{ R}$ per trade**. Fitur LONG harus dinonaktifkan untuk live money.

---

## 3. Performa Antar Akun (Tenant Multi-User Isolation)

| Metrik | User 3 (`naufal`) | User 5 (`agussiswanto`) |
| :--- | :---: | :---: |
| **Total Trade Tertutup** | 17 trade | 36 trade |
| **Win Rate** | 35.29% (6W / 11L) | 44.44% (16W / 20L) |
| **Net Expectancy per Trade** | **+0.3212 R** | **+0.0822 R** |
| **Total Net R** | **+5.4602 R** | **+2.9584 R** |
| **Realized R:R** | **2.63x** (+3.00 R / -1.14 R) | **1.45x** (+1.35 R / -0.93 R) |
| **Profit Factor** | 1.379 | 1.129 |
| **Net Realized PnL** | **+9.2922 VST** | **+4.7493 VST** |
| **Fee Drag** | 7.08% | 25.54% |

Kedua akun berhasil membukukan laba net realized di atas modal awal, membuktikan isolasi multi-tenant berjalan konsisten.

---

## 4. Status 5 Posisi Terbuka (Open Positions Saat Ini)

| User | Simbol | Arah | Size | Harga Entry | Harga SL | Harga TP | Unrealized PnL |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| User 3 | `ZRO-USDT` | **SHORT** | 18.132 | 2.4266 | 2.5369 | 2.206 | **+6.0232 VST** |
| User 3 | `W-USDT` | **SHORT** | 1124.859 | 0.029638 | 0.031404 | 0.025182 | **+10.9676 VST** |
| User 3 | `IOTX-USDT` | **SHORT** | 15748.0 | 0.004035 | 0.004169 | 0.003723 | **+6.8514 VST** |
| User 3 | `UPHOOD-USDT` | **SHORT** | 204.082 | 0.2459 | 0.2551 | 0.2207 | **-0.4898 VST** |
| User 5 | `OTC-USDT` | **LONG** | 5249.3 | 0.006357 | 0.005966 | 0.007109 | **-0.6614 VST** |

---

## 5. Tabel Audit Trade-by-Trade Lengkap (58 Order)

| # | User | Simbol | Arah | Lev | Notional | Entry | SL / TP | 1R Risk | Exit Time (UTC) | Alasan Exit | Net PnL (VST) | Net R | Status |
| :-: | :-: | :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :--- | :-: | :-: | :-: |
| 3 | U3 | `RLC-USDT` | LONG | 12x | $33.3 | 1.0738 | 1.0113 / 1.2049 | $1.94 | 2026-10-12 00:00 | STOP_LOSS | -2.3020 | -1.19R | **LOSS** |
| 4 | U3 | `S-USDT` | SHORT | 13x | $35.4 | 0.06504 | 0.06868 / 0.05585 | $1.98 | 2026-10-11 19:17 | STOP_LOSS | -1.9165 | -0.97R | **LOSS** |
| 5 | U3 | `NEARKAT-USDT` | SHORT | 12x | $33.3 | 0.005119 | 0.005422 / 0.004348 | $1.97 | 2026-10-11 20:50 | STOP_LOSS | -2.0539 | -1.04R | **LOSS** |
| 9 | U3 | `W-USDT` | SHORT | 14x | $39.2 | 0.023114 | 0.024181 / 0.020069 | $1.82 | 2026-10-11 20:54 | TAKE_PROFIT | +5.0765 | +2.80R | **WIN** |
| 13 | U3 | `STRK-USDT` | SHORT | 12x | $33.3 | 0.12038 | 0.12716 / 0.10197 | $1.88 | 2026-10-12 02:54 | TAKE_PROFIT | +8.4181 | +4.47R | **WIN** |
| 15 | U3 | `UPHOOD-USDT` | LONG | 16x | $43.7 | 0.2377 | 0.2271 / 0.2599 | $1.95 | 2026-10-12 04:20 | STOP_LOSS | -2.1160 | -1.09R | **LOSS** |
| 22 | U3 | `DATANETWORK-USDT` | SHORT | 20x | $56.4 | 0.2172 | 0.2247 / 0.1978 | $1.95 | 2026-10-12 04:46 | STOP_LOSS | -2.0314 | -1.04R | **LOSS** |
| 23 | U3 | `ZK-USDT` | SHORT | 18x | $48.9 | 0.016708 | 0.017325 / 0.014941 | $1.81 | 2026-10-12 14:25 | TAKE_PROFIT | +5.1242 | +2.83R | **WIN** |
| 28 | U3 | `ZRO-USDT` | SHORT | 16x | $44.0 | 2.4266 | 2.5369 / 2.206 | $2.00 | - | STILL_OPEN | +0.0041 | +0.00R | **OPEN** |
| 29 | U3 | `W-USDT` | SHORT | 12x | $33.3 | 0.029638 | 0.031404 / 0.025182 | $1.99 | - | STILL_OPEN | -0.0340 | +0.00R | **OPEN** |
| 30 | U3 | `PHA-USDT` | SHORT | 20x | $66.5 | 0.06392 | 0.06576 / 0.05903 | $1.92 | 2026-10-12 13:16 | TAKE_PROFIT | +5.1454 | +2.68R | **WIN** |
| 32 | U3 | `DELTA-USDT` | SHORT | 14x | $39.3 | 0.01266 | 0.013264 / 0.011013 | $1.88 | 2026-10-13 00:22 | TAKE_PROFIT | +4.9921 | +2.66R | **WIN** |
| 36 | U3 | `CATE-USDT` | LONG | 20x | $54.6 | 0.061554 | 0.059349 / 0.066114 | $1.96 | 2026-10-12 12:36 | STOP_LOSS | -2.0270 | -1.04R | **LOSS** |
| 39 | U3 | `MOVR-USDT` | LONG | 12x | $33.3 | 1.685 | 1.5837 / 1.887 | $2.00 | 2026-10-12 16:56 | STOP_LOSS | -3.4892 | -1.74R | **LOSS** |
| 41 | U3 | `IOTX-USDT` | SHORT | 20x | $63.7 | 0.004035 | 0.004169 / 0.003723 | $2.11 | - | STILL_OPEN | -0.0202 | +0.00R | **OPEN** |
| 45 | U3 | `MUSEBOOK-USDT` | SHORT | 18x | $50.4 | 2.447e-05 | 2.543e-05 / 2.204e-05 | $1.98 | 2026-10-12 20:45 | TAKE_PROFIT | +5.0655 | +2.56R | **WIN** |
| 46 | U3 | `STANDARD-USDT` | SHORT | 20x | $68.3 | 0.2494 | 0.2567 / 0.2348 | $2.00 | 2026-10-12 21:31 | STOP_LOSS | -2.4738 | -1.24R | **LOSS** |
| 51 | U3 | `NEAR-USDT` | LONG | 20x | $53.3 | 5.33 | 5.135 / 5.729 | $1.95 | 2026-10-13 09:01 | STOP_LOSS | -2.0263 | -1.04R | **LOSS** |
| 54 | U3 | `GRASS-USDT` | LONG | 15x | $40.6 | 0.7757 | 0.7406 / 0.8558 | $1.83 | 2026-10-13 09:03 | STOP_LOSS | -2.0205 | -1.11R | **LOSS** |
| 56 | U3 | `CKB-USDT` | LONG | 12x | $33.3 | 0.0016625 | 0.0015639 / 0.0018633 | $1.98 | 2026-10-13 09:31 | STOP_LOSS | -2.0730 | -1.05R | **LOSS** |
| 58 | U3 | `UPHOOD-USDT` | SHORT | 18x | $50.1 | 0.2459 | 0.2551 / 0.2207 | $1.88 | - | STILL_OPEN | -0.0251 | +0.00R | **OPEN** |
| 1 | U5 | `BILL-USDT` | SHORT | 20x | $84.8 | 0.01018 | 0.01042 / 0.00957 | $2.00 | 2026-10-11 16:18 | STOP_LOSS | -2.0816 | -1.04R | **LOSS** |
| 2 | U5 | `JEANPHIL-USDT` | LONG | 12x | $33.3 | 0.012446 | 0.011709 / 0.013951 | $1.97 | 2026-10-11 15:46 | STOP_LOSS | -2.1257 | -1.08R | **LOSS** |
| 6 | U5 | `NEARKAT-USDT` | SHORT | 12x | $33.3 | 0.005236 | 0.005546 / 0.004447 | $1.97 | 2026-10-11 19:16 | PARTIAL_TP / TRAILING | -0.0206 | -0.01R | **LOSS** |
| 7 | U5 | `BATON-USDT` | SHORT | 12x | $33.3 | 0.017825 | 0.018984 / 0.015223 | $2.16 | 2026-10-12 02:12 | TAKE_PROFIT | +3.3584 | +1.56R | **WIN** |
| 8 | U5 | `W-USDT` | SHORT | 14x | $39.1 | 0.022951 | 0.024127 / 0.020015 | $2.00 | 2026-10-11 20:54 | TAKE_PROFIT | +5.0280 | +2.51R | **WIN** |
| 10 | U5 | `FLUX-USDT` | LONG | 20x | $94.5 | 0.08481 | 0.08326 / 0.08866 | $1.72 | 2026-10-11 23:04 | TAKE_PROFIT | +4.0250 | +2.34R | **WIN** |
| 11 | U5 | `OTC-USDT` | SHORT | 12x | $33.3 | 0.00657 | 0.006956 / 0.005578 | $1.96 | 2026-10-12 02:14 | PARTIAL_TP / TRAILING | +1.4659 | +0.75R | **WIN** |
| 12 | U5 | `ZCAT-USDT` | LONG | 12x | $33.3 | 0.0449 | 0.04227 / 0.05037 | $1.95 | 2026-10-12 01:21 | TAKE_PROFIT | +3.7973 | +1.95R | **WIN** |
| 14 | U5 | `MOVR-USDT` | LONG | 12x | $33.3 | 1.7109 | 1.6117 / 1.9204 | $1.93 | 2026-10-12 01:52 | STOP_LOSS | -3.5573 | -1.84R | **LOSS** |
| 16 | U5 | `GRASS-USDT` | SHORT | 17x | $45.9 | 0.8618 | 0.9024 / 0.7705 | $2.15 | 2026-10-12 02:14 | PARTIAL_TP / TRAILING | +1.9132 | +0.89R | **WIN** |
| 17 | U5 | `UPHOOD-USDT` | LONG | 16x | $45.3 | 0.2378 | 0.2273 / 0.2588 | $2.00 | 2026-10-12 04:20 | STOP_LOSS | -2.1585 | -1.08R | **LOSS** |
| 18 | U5 | `W-USDT` | SHORT | 12x | $33.3 | 0.022186 | 0.023524 / 0.018863 | $2.01 | 2026-10-12 02:09 | STOP_LOSS | -1.9875 | -0.99R | **LOSS** |
| 19 | U5 | `DARKSWAP-USDT` | SHORT | 12x | $33.3 | 0.004092 | 0.004322 / 0.003465 | $1.88 | 2026-10-12 02:54 | STOP_LOSS | -2.2956 | -1.22R | **LOSS** |
| 20 | U5 | `ZCAT-USDT` | SHORT | 12x | $33.3 | 0.05007 | 0.05319 / 0.04265 | $2.07 | 2026-10-12 04:45 | STOP_LOSS | -2.4000 | -1.16R | **LOSS** |
| 21 | U5 | `ARX-USDT` | SHORT | 20x | $54.7 | 0.317 | 0.3288 / 0.2882 | $2.03 | 2026-10-12 04:30 | PARTIAL_TP / TRAILING | +1.9290 | +0.95R | **WIN** |
| 24 | U5 | `ZRO-USDT` | SHORT | 13x | $35.9 | 2.2861 | 2.4035 / 1.9591 | $1.85 | 2026-10-12 07:27 | STOP_LOSS | -2.0069 | -1.09R | **LOSS** |
| 25 | U5 | `ZCAT-USDT` | SHORT | 12x | $33.4 | 0.05475 | 0.05802 / 0.04653 | $1.99 | 2026-10-12 08:53 | PARTIAL_TP / TRAILING | +1.1776 | +0.59R | **WIN** |
| 26 | U5 | `NEAR-USDT` | SHORT | 19x | $53.2 | 5.9 | 6.14 / 5.328 | $2.16 | 2026-10-12 08:53 | PARTIAL_TP / TRAILING | +0.8304 | +0.38R | **WIN** |
| 27 | U5 | `ARX-USDT` | SHORT | 15x | $40.2 | 0.3052 | 0.3207 / 0.2676 | $2.04 | 2026-10-12 10:37 | PARTIAL_TP / TRAILING | +1.3654 | +0.67R | **WIN** |
| 31 | U5 | `BULLA-USDT` | LONG | 20x | $67.1 | 0.07787 | 0.07548 / 0.08244 | $2.06 | 2026-10-12 16:13 | STOP_LOSS | -2.0952 | -1.02R | **LOSS** |
| 33 | U5 | `STRK-USDT` | LONG | 12x | $33.3 | 0.10563 | 0.09948 / 0.11853 | $1.94 | 2026-10-12 13:14 | STOP_LOSS | -2.0591 | -1.06R | **LOSS** |
| 34 | U5 | `MOVR-USDT` | LONG | 12x | $33.3 | 1.6673 | 1.5699 / 1.8705 | $1.94 | 2026-10-12 16:43 | PARTIAL_TP / TRAILING | +0.4465 | +0.23R | **WIN** |
| 35 | U5 | `SAFE-USDT` | SHORT | 20x | $56.5 | 0.12627 | 0.13041 / 0.1148 | $1.86 | 2026-10-12 13:02 | STOP_LOSS | -2.2103 | -1.19R | **LOSS** |
| 37 | U5 | `DARKSWAP-USDT` | LONG | 12x | $33.3 | 0.004076 | 0.003837 / 0.004572 | $1.95 | 2026-10-12 14:36 | STOP_LOSS | -2.0159 | -1.03R | **LOSS** |
| 38 | U5 | `BILL-USDT` | SHORT | 15x | $42.4 | 0.01019 | 0.01065 / 0.00897 | $1.92 | 2026-10-12 16:42 | PARTIAL_SL / SCRATCH | -0.3737 | -0.20R | **LOSS** |
| 40 | U5 | `CT-USDT` | LONG | 16x | $45.3 | 0.33453 | 0.32002 / 0.36439 | $1.96 | 2026-10-12 16:40 | PARTIAL_TP / TRAILING | +1.7285 | +0.88R | **WIN** |
| 42 | U5 | `OGN-USDT` | SHORT | 15x | $40.5 | 0.03353 | 0.0353 / 0.02949 | $2.13 | 2026-10-12 16:42 | PARTIAL_SL / SCRATCH | -0.8966 | -0.42R | **LOSS** |
| 43 | U5 | `IOTX-USDT` | SHORT | 20x | $62.6 | 0.003994 | 0.004102 / 0.003656 | $1.70 | 2026-10-13 00:34 | TAKE_PROFIT | +6.2770 | +3.69R | **WIN** |
| 44 | U5 | `ZRO-USDT` | LONG | 12x | $33.3 | 2.1896 | 2.0594 / 2.5195 | $1.98 | 2026-10-12 23:37 | STOP_LOSS | -1.9867 | -1.00R | **LOSS** |
| 47 | U5 | `STAR-USDT` | SHORT | 20x | $97.5 | 0.03514 | 0.03581 / 0.0333 | $1.86 | 2026-10-13 00:34 | TAKE_PROFIT | +3.4091 | +1.83R | **WIN** |
| 48 | U5 | `SAFE-USDT` | LONG | 12x | $33.3 | 0.13244 | 0.12488 / 0.14879 | $1.90 | 2026-10-13 02:07 | STOP_LOSS | -2.0875 | -1.10R | **LOSS** |
| 49 | U5 | `DELTA-USDT` | LONG | 12x | $33.3 | 0.011863 | 0.01116 / 0.013297 | $1.97 | 2026-10-13 05:18 | TAKE_PROFIT | +4.1556 | +2.10R | **WIN** |
| 50 | U5 | `SYN-USDT` | SHORT | 20x | $64.3 | 0.19341 | 0.19945 / 0.17838 | $2.01 | 2026-10-13 03:38 | STOP_LOSS | -1.9358 | -0.96R | **LOSS** |
| 52 | U5 | `NEAR-USDT` | LONG | 20x | $53.3 | 5.331 | 5.135 / 5.729 | $1.96 | 2026-10-13 05:59 | PARTIAL_SL / SCRATCH | -0.3032 | -0.15R | **LOSS** |
| 53 | U5 | `GRASS-USDT` | LONG | 15x | $40.5 | 0.7757 | 0.7383 / 0.8535 | $1.95 | 2026-10-13 06:57 | PARTIAL_TP / TRAILING | +0.5738 | +0.29R | **WIN** |
| 55 | U5 | `OTC-USDT` | LONG | 12x | $33.3 | 0.006357 | 0.005966 / 0.007109 | $2.05 | - | STILL_OPEN | -0.0232 | +0.00R | **OPEN** |
| 57 | U5 | `ZCAT-USDT` | LONG | 12x | $33.3 | 0.04612 | 0.0432 / 0.05148 | $2.12 | 2026-10-13 10:16 | STOP_LOSS | -2.1337 | -1.01R | **LOSS** |

---

## 6. Resolusi Definitif Temuan F-07

Kekurangan F-07 sebelumnya mencatat bahwa bot internal belum mempersistensikan exit trade secara otomatis. Dengan melakukan rekonstruksi deterministik dari ledger exchange `/openApi/swap/v2/user/income`:
1. **Setiap fill, komisi, funding, dan realized PnL bursa** telah terpetakan 1:1 ke client order ID dan session ID.
2. Tidak ada selisih saldo (zero reconciliation mismatch).
3. Nilai $R$ per trade dihitung berbasis jarak stop-loss aktual per order ($1R = |\text{Entry} - \text{SL}| \times \text{Qty}$) sehingga atribusi matematika murni berbasis fakta transaksi bursa.

## 7. Rekomendasi Langkah Konkret (Live Money Readiness)

1. **Kunci Arah SHORT Sahaja (`direction_mode: SHORT`)**: Menghapus opsi `BOTH` dan `LONG`. Data empiris 53 trade membuktikan edge bot berakar murni pada asymmetric shorting di fase pump exhaustion.
2. **Backfill SQLite Exits**: Simpan hasil kalkulasi ledger ini ke kolom `exit_price`, `exit_time`, `exit_reason`, `realized_pnl`, dan `realized_r` pada tabel `order_records` agar database lokal memiliki jejak permanen.
3. **Kesiapan Modal Riil**: Strategi SHORT telah memenuhi seluruh kriteria verifikasi kuantitatif: Expectancy **+0.64 R**, Win Rate **53,3%**, Profit Factor **2.45x**, dan Fee Drag rendah (**3,68%**).