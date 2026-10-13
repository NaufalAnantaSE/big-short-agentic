# Laporan Peluncuran Batch Konfirmasi SHORT-Only (N=30 VST)

- **Tanggal Peluncuran**: 14 Oktober 2026 (05:14 UTC / 12:14 WIB)
- **Status Otorisasi**: **GO-AHEAD RESMI DIBERIKAN** (Naufal Ananta, Agent Muse, Lead Reviewer Gemini 4 Argon)
- **Pelaksana**: Agent Hermes (Executor)
- **Target Subjek**: Akun Utama User 3 (`naufal`)

---

## 1. Parameter Sesi Aktif

Sesi background autonomous telah diluncurkan pada VPS Tencent Cloud (`124.156.193.170`) melalui daemon `bingx-agent.service`.

| Parameter | Nilai Konfigurasi | Keterangan |
|---|---|---|
| **Session ID** | `bx_sess_1791926045_8981c2` | Identitas sesi persisten di `sessions` |
| **User ID** | `3` (`naufal`) | Akun tunggal untuk kontrol independensi sampel |
| **Status Sesi** | `ACTIVE_SEARCHING` | Sedang memindai universe pasar secara berkala |
| **Direction Mode** | `SHORT` | SHORT-only ditegakkan (LONG/BOTH ditunda) |
| **Simultaneous Quota** | `2` | Maksimal 2 posisi aktif bersamaan |
| **Batch Target** | `30` Entry Terisi | Pengambilan berhenti di 30, menunggu semua outcome |
| **Risk Budget per Trade** | `2.0` VST | Fixed-risk sizing berbasis jarak Stop Loss riil |
| **Margin per Pos** | `5.0` VST | Margin awal per posisi |
| **Leverage** | `20x` | Isolated leverage |
| **Environment** | `BINGX_VST` | BingX Standard Futures VST Demo |
| **Execution Mode** | `EXCHANGE_DEMO` | Eksekusi riil via API bursa demo |
| **Auto Scan** | `True` (Interval 60s) | Pemindaian otonom siklis tanpa henti |
| **Exit Policy** | `MANUAL_ONLY` | Menyerahkan penutupan pada resting TP/SL bursa |

---

## 2. Protokol Gerbang Trade #1 (Mengikat)

Sesuai instruksi Naufal dan kesepakatan tim, Trade #1 menjadi gerbang pengaman kritis:

1. **Audit Entry (Verifikasi TP/SL Staging $\le 4$ detik)**:
   - Sistem wajib mencatat event `TPSL_VERIFIED` di `audit.jsonl` dan tabel `audit_logs`.
   - Query bursa `get_open_orders()` wajib membuktikan order `STOP_MARKET` dan `TAKE_PROFIT_MARKET` berstatus resting aktif di server BingX dalam rentang staging $\le 4.0$ detik pasca fill entry.
2. **Audit Exit (Rekonsiliasi Otomatis F-07 Tanpa Intervensi Manual)**:
   - Begitu Trade #1 menyentuh exit bursa, siklus `reconcile_outcomes()` wajib secara otomatis mendeteksi income ledger `REALIZED_PNL`.
   - Baris record di `order_records` wajib bertransisi ke `status = 'CLOSED'` dengan atribut lengkap:
     * `exit_price` (harga fill bursa riil)
     * `exit_time` (timestamp bursa riil)
     * `exit_reason` (`TAKE_PROFIT` / `STOP_LOSS` / `MARKET_CLOSE`)
     * `exit_fee`, `funding_fee`, `realized_pnl`, `realized_r`.
3. **Klausul Penghentian Darurat**:
   - Jika salah satu audit (entry atau exit) gagal atau menunjukkan anomali $\rightarrow$ **Jeda Batch Segera (`auto_scan = 0`)**, buat laporan audit mendalam, dan jangan lanjutkan ke Trade #2 sebelum tinjauan Naufal & Muse.

---

## 3. Catatan Integritas & Kepatuhan

- **Prompt & AI Engine**: 100% identik dengan konfigurasi baseline (Gemini 3.8 Flash via 9Router, zero-masking). Dilarang mengubah prompt, model, atau bobot strategi di tengah batch.
- **Pencatatan Tugas**: Berkas `/home/naufal-ananta/Downloads/ringkasan-tugas-hermes-short-only-2026-10-13.md` telah diperbarui (Tugas 3, 4, 5 berstatus SELESAI; Tugas 6 berstatus AKTIF).
- **Memori Persisten Hermes**: Catatan operasional telah diperbarui via `memory` tool untuk mengunci status batch konfirmasi GO-AHEAD.

---

## 4. Monitoring Telemetri

- **Log Server Live**: `tail -f /home/ubuntu/bingx-short-agent/logs/server.log`
- **Log Audit Events**: `tail -f /home/ubuntu/bingx-short-agent/logs/audit.jsonl`
- **Kueri Status DB**:
  ```sql
  SELECT id, symbol, side, quantity, price, stop_loss_price, take_profit_price, status, exit_time, realized_pnl, realized_r 
  FROM order_records 
  WHERE session_id = 'bx_sess_1791926045_8981c2';
  ```

Hermes standby memantau siklus scan dan akan segera menyusun laporan audit Trade #1 begitu entry dan exit pertamanya terdeteksi.
