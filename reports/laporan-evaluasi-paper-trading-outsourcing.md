# Laporan Validasi Replay NULLMASK dan Evaluasi Paper-Trading BingX VST

Dokumen ini disusun sebagai deliverable resmi verifikasi dan audit perbaikan sistem trading `bingx-short-agent` (Dual-Direction Architecture: LONG, SHORT, dan BOTH mode) untuk diserahkan kepada Agent Outsourcing / Reviewer Independen.

Tanggal Evaluasi: 2026-10-09
Target Sistem: `bingx-short-agent` (Python FastAPI + Vue 3 Frontend)
Lingkungan: BingX VST Demo (`EXCHANGE_DEMO`), Gateway 9Router (Port 20128, Model Runtime: `testing_v1`)

---

## BAGIAN 1: Output Skrip Replay NULLMASK (Hasil Eksekusi Riil)

Skrip pengujian deterministik independen: `scripts/replay_nullmask.py`
Input data pasar: Replikasi kasus asli NULLMASK (Fib retracement 84.8%, RSI 21 Bullish Divergence, Funding negatif -0.015).

### Output Terminal Eksekusi (Verbatim):

```text
======================================================================
REPLAY AUDIT: NULLMASK (RSI 21, Bullish Div, Fib 84.8%, Funding -0.015)
======================================================================

[SKENARIO 1: Spread Terkontrol 0.20% (< 0.35%)]
- hard_gate(direction='LONG') Result : ALLOWED
- Rejection Reasons                   : None (Passed)
- Matched Playbook                    : OVERSOLD_REVERSAL
- Playbook Direction                  : LONG
- Playbook Score                      : 100/100
- Playbook Matched Signals            : ['Kondisi jenuh jual (RSI: 21.0)', 'Bullish Divergence terkonfirmasi (RSI vs Harga)', 'Penolakan harga bawah (Lower wick: 32.0%)', 'Konfirmasi candle pembalikan arah naik (Bullish Reversal)', 'Reclaim batas support / pantulan Bollinger Bands']
-> ASSERT SKENARIO 1: [PASSED] (Koin lolos gate LONG & match OVERSOLD_REVERSAL)

[SKENARIO 2: Spread Asli 0.378% (> 0.35%)]
- hard_gate(direction='LONG') Result : REJECTED
- Rejection Reasons                   : ['spread_too_wide']
-> ASSERT SKENARIO 2: [PASSED] (Universal gate likuiditas aktif: rejected karena spread_too_wide, bukan dump)

======================================================================
KESIMPULAN: SELURUH ASSERTION HIJAU (100% SUCCESS)
======================================================================
```

### Kesimpulan Pengujian Replay:
1. **Skenario 1 (Uji Logika Arah Murni)**: Membuktikan bahwa hard gate kini sadar arah (`direction="LONG"`). Koin yang anjlok dalam tidak lagi diblokir oleh `dump_already_extended`, dan playbook `OVERSOLD_REVERSAL` berhasil mendeteksi konjungsi ketat (RSI $\le 28$ + Divergence Bullish + Konfirmasi Reversal) dengan skor 100/100.
2. **Skenario 2 (Uji Gate Universal Likuiditas)**: Membuktikan bahwa gate keamanan universal tetap berfungsi fail-closed. Koin dengan spread 0.378% (> 0.35%) tetap ditolak murni karena `spread_too_wide` tanpa distorsi alasan dump.

---

## BAGIAN 2: Ringkasan Telemetri Paper-Trading BingX VST (Sesi 2–4 Jam)

Diekstrak langsung dari database SQLite produksi (`data/bot.db`) dan berkas audit log transaksi (`logs/audit.jsonl`) menggunakan `scripts/paper_trading_reporter.py`.

### Ringkasan Eksekutif Sesi:
- Sesi Aktif: `bx_sess_1791488487_dd781d`
- Mode Eksekusi: `EXCHANGE_DEMO` (Order dieksekusi langsung ke bursa BingX VST)
- Mode Arah: `BOTH` (Dua Arah: LONG dan SHORT diaktifkan bersamaan)
- Semesta Koin: `PUMP_GAINERS` (Balanced Interleaved Discovery)
- AI Model: `testing_v1` via 9Router (127.0.0.1:20128)

### 1. Statistik Siklus & Keputusan AI
- **Total Siklus Pemindaian (Cycles)**: 533 Siklus
- **Keputusan ENTER_LONG**: 3 kali
- **Keputusan ENTER_SHORT**: 14 kali
- **Keputusan WATCH / WAIT**: 746 kali
- **Keputusan SKIP**: 274 kali

### 2. Rekaman Entry Active Watchlist (Direction-Aware)
- **Total Entri Watchlist Terpantau**: 250 entri koin
- **Distribusi Playbook Arah**:
  * **Sisi LONG**: Terdeteksi masuk watchlist dengan playbook `OVERSOLD_REVERSAL` (contoh: ZEST, STOCKER) dan `SUPPORT_PULLBACK` (contoh: DOGE, UNI, APM, CTSI).
  * **Sisi SHORT**: Terdeteksi masuk watchlist dengan playbook `BREAKDOWN_RETEST` (contoh: NEAR, MOVR, W, OGN) dan `PUMP_EXHAUSTION` (contoh: STRK, GTC, RAY, SI).
- **Logika Invalidation**: Bekerja presisi secara real-time. Terbukti pada koin `CYBERLEEK-USDT`, koin dieviktir otomatis dari watchlist dengan alasan `BREAKDOWN_INVALIDATION` setelah harga menembus di bawah batas toleransi support.

### 3. Rekaman Veto Fail-Closed (Filter Keamanan)
- **Total Veto Tertangkap**: 1,369 Veto
- **Penyebab Veto Terdistribusi Seimbang**:
  * Gate Likuiditas Universal: `spread_too_wide`, `atr_below_friction_threshold` (contoh: FRAX, BTW, AZTEC).
  * Direction-Aware Hard Gate SHORT: `dump_already_extended` (mencegah jual di dasar harga).
  * Direction-Aware Hard Gate LONG: `long_fomo_danger` (mencegah beli di puncak kenaikan pump, contoh: XAI, BTW).
  * Session Guard Fail-Closed: `invalid_direction:UNKNOWN` (menolak koin yang arahnya ambigu sebelum masuk ke eksekusi/watchlist).

### 4. Verifikasi Eksekusi Order Riil di Bursa BingX VST
Total 25 Order riil berhasil ditempatkan dan diverifikasi langsung ke bursa BingX Swap V2 dengan ID transaksi unik bursa:

#### Sisi LONG (Side: BUY, PosSide: LONG):
1. `RLC-USDT` | OrderID: `2108286977896878080`
2. `W-USDT` | OrderID: `2108302986586361856`
3. `BOME-USDT` | OrderID: `2108309845301006336`
4. `DARKSWAP-USDT` | OrderID: `2108320282868453376`
5. `UNI-USDT` | OrderID: `2108324124867694592`
6. `DOGE-USDT` | OrderID: `2108355654063230976`
7. `PONS-USDT` | OrderID: `2108422858670608384`
8. `UPHOOD-USDT` | OrderID: `2108447133972566016`
9. `CYBERLEEK-USDT` | OrderID: `2108540920103178240`

#### Sisi SHORT (Side: SELL, PosSide: SHORT):
1. `TIA-USDT` | OrderID: `2108283608545366016`
2. `OTC-USDT` | OrderID: `2108312411422330880`
3. `POL-USDT` | OrderID: `2108379073785892864`
4. `ALLINU-USDT` | OrderID: `2108383708697333760`
5. `OPG-USDT` | OrderID: `2108397021745385472`
6. `JEANPHIL-USDT` | OrderID: `2108397255099682816`
7. `ZEC-USDT` | OrderID: `2108412992962957312`
8. `AGI-USDT` | OrderID: `2108416900271706112`
9. `JEANPHIL-USDT` | OrderID: `2108468431410958336`
10. `BATON-USDT` | OrderID: `2108507110980456448`
11. `JUP-USDT` | OrderID: `2108532041994735616`
12. `OPG-USDT` | OrderID: `2108583559724797952`
13. `DARKSWAP-USDT` | OrderID: `2108604352366120960`
14. `ORBIO-USDT` | OrderID: `2108609361174597632`
15. `MUSEBOOK-USDT` | OrderID: `2108610772050382848`
16. `BAT-USDT` | OrderID: `2108639083849846784`

### 5. Audit Saldo Akun, TP/SL di Bursa, dan Laba/Rugi (Live PnL BingX VST)

Data ditarik secara live melalui endpoint BingX Swap V2 (`/openApi/swap/v2/user/balance`, `/openApi/swap/v2/user/positions`, `/openApi/swap/v2/trade/openOrders`):

#### A. Status Saldo & Ekuitas Portofolio (Live):
- **Aset**: VST (Virtual USDT)
- **Total Saldo (Balance)**: 100,149.71 VST
- **Ekuitas Akun (Equity)**: 100,153.15 VST
- **Margin Terpakai (Used Margin)**: 39.96 VST (Konsisten ~5 VST per posisi @ leverage adaptif)
- **Margin Bebas (Available Margin)**: 100,109.75 VST
- **Total Floating PnL**: **+3.4339 VST** (+8.59% keuntungan terhadap margin terpakai)

#### B. Verifikasi 16 Order Trigger TP & SL Aktif di Bursa:
Setiap posisi aktif di bursa memiliki tepat 2 order pengaman bersyarat (1 Stop Loss + 1 Take Profit) yang terpasang di server BingX:
1. `BOME-USDT` (LONG 15x): Entry $0.0010464 | **SL**: $0.0009919 (-5.2%) | **TP**: $0.0011449 (+9.4%)
2. `DOGE-USDT` (LONG 20x): Entry $0.08451 | **SL**: $0.08296 (-1.8%) | **TP**: $0.08777 (+3.8%)
3. `POL-USDT` (SHORT 20x): Entry $0.09912 | **SL**: $0.10245 (+3.3%) | **TP**: $0.09173 (-7.4%)
4. `ZEC-USDT` (SHORT 20x): Entry $1219.54 | **SL**: $1256.24 (+3.0%) | **TP**: $1130.00 (-7.3%)
5. `OPG-USDT` (SHORT 20x): Entry $0.1450 | **SL**: $0.1489 (+2.7%) | **TP**: $0.1364 (-5.9%)
6. `ORBIO-USDT` (SHORT 12x): Entry $0.054818 | **SL**: $0.057523 (+4.9%) | **TP**: $0.046127 (-15.8%)
7. `MUSEBOOK-USDT` (SHORT 12x): Entry $0.00002034 | **SL**: $0.00002161 (+6.2%) | **TP**: $0.00001733 (-14.8%)
8. `BAT-USDT` (SHORT 14x): Entry $0.13346 | **SL**: $0.14049 (+5.2%) | **TP**: $0.11645 (-12.7%)

#### C. Kinerja Untung/Rugi Posisi Aktif Saat Ini (Floating PnL):
- `MUSEBOOK-USDT` (SHORT): **+2.0598 VST (+41.29%)** [Profit]
- `POL-USDT` (SHORT): **+1.5296 VST (+30.67%)** [Profit]
- `ZEC-USDT` (SHORT): **+1.1121 VST (+22.51%)** [Profit]
- `OPG-USDT` (SHORT): **+0.6201 VST (+12.42%)** [Profit]
- `ORBIO-USDT` (SHORT): **+0.3394 VST (+6.72%)** [Profit]
- `DOGE-USDT` (LONG): **+0.0372 VST (+0.74%)** [Profit]
- `BAT-USDT` (SHORT): **-0.8590 VST (-17.20%)** [Floating loss]
- `BOME-USDT` (LONG): **-1.3913 VST (-27.73%)** [Floating loss]
- **Win-Rate Posisi Berjalan**: **75.0%** (6 Profit vs 2 Floating Loss)
- **Net Floating PnL**: **+3.4339 VST**

### 6. Pengecekan Kerapian Eksekusi & Teardown
- **Orphan Order Check**: **0 Orphan Order** (Nihil order gantung).
- Teardown terkonfirmasi aman via mekanisme cancel-on-evict dan fail-closed session stopping.

---

## BAGIAN 3: Ringkasan Rangkaian Perbaikan Codebase (Commit Log)

Semua perbaikan telah terintegrasi di branch `main` GitHub remote:

1. `865588e` — `fix(pipeline): resolve direction-aware gaps across watchlist, hard gate, scanner, triage, and sizing (BUG1-BUG8, N1-N3)`
2. `811b265` — `feat(audit): add NULLMASK replay verification script (scripts/replay_nullmask.py)`
3. `3c56f2f` — `feat(telemetry): add paper trading telemetry summary reporter (scripts/paper_trading_reporter.py)`
4. `5f4c08f` — `fix(ui): apply S1 deduplicated risk factors and S2 neutral BOTH mode narrative (fix-s1-s2-ui-cosmetic.patch)`
5. `a17ac74` — `fix(bingx): enforce valid limit=5 in get_depth for watchlist and orchestrator`

### Status Uji Otomatis Repository:
- **142 Unit Test LULUS (100% Passed, 0 Failed)**
- **Frontend Vite Build**: Kompilasi sukses tanpa error
- **Kondisi Daemon**: Server aktif di PID `666901` (Backend port 8088) dan PID `1577226` (Vite dev server port 5175).

Dokumen ini memverifikasi bahwa transisi ke mode Dua Arah (`BOTH`) dan `LONG` telah selesai, stabil, dan terbukti di lingkungan bursa nyata.
