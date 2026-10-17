# Laporan Investigasi Ground-Truth: Akar Masalah 0 Entry & Gangguan Upstream 9Router AI Gateway

- **Tanggal**: 18 Oktober 2026
- **Dari**: Agent Hermes (Eksekutor Lapangan & Ground-Truth)
- **Kepada**: Gemini 4 Argon (Lead Reviewer)
- **Tembusan (CC)**: Agent Muse (First-Pass Reviewer / Monitor), Naufal Ananta (Decision Maker)
- **Sesi Target**: `bx_sess_1791926045_8981c2` (User 3 / `naufal`)
- **Status Operasional Sesi**: `ACTIVE_SEARCHING`, `quota = 10`, `auto_scan = 1`, `filled_count = 1` (Posisi `CORE-USDT` terbuka aktif)
- **Lampiran Data Terstruktur Wajib**: `reports/evidence/evidence_0_entry_9router_investigation_2026_10_18.json`
- **Sifat Pemeriksaan**: **100% Read-Only (Zero Mutation)** — Tidak ada restart service, tidak ada perubahan kode, dan tidak ada modifikasi konfigurasi/database.

---

## 1. Ringkasan Eksekutif & Jawaban Investigasi

Investigasi mendalam berbasis sumber primer (*ground-truth audit*) telah dijalankan untuk menjawab anomali **0 entry baru** pada sesi konfirmasi SHORT-only $N=30$.

### Kesimpulan Definitif:
1. **Bukan Karena Pasar Sepi**: Filter screening dan *hard-gate* bursa tetap aktif meloloskan kandidat-kandidat potensial dari pasar (misalnya `AGT-USDT` lolos 396 kali, `DNA-USDT` 237 kali, `CLAUDIA-USDT` 218 kali, `GTC-USDT` 112 kali, `OPG-USDT` 103 kali).
2. **Akar Masalah Teknis Terkonfirmasi (Kemungkinan 2 Terbukti Faktual)**:
   - Service **`9router.service`** di VPS menyala normal dan port `20128` listening (`tcp 0.0.0.0:20128`).
   - Namun, endpoint completions untuk model **`testing_v1`** (yang dipetakan ke `ag/gemini-3.8-flash-high` via provider Antigravity) **menolak seluruh permintaan dengan HTTP 403**:
     ```json
     {"error":{"message":"[antigravity/gemini-3.8-flash-high] [403]: HTTP 403 (reset after 2m)"}}
     ```
   - Seluruh model lain di bawah provider Antigravity (`ag/gemini-3.8-flash`, `ag/gemini-3.7-flash-high`, `ag/gemini-3.6-flash-high`, `ag/claude-sonnet-4-6`) juga mengembalikan `HTTP 403` serupa.
3. **Mekanisme Terjadinya 0 Entry Diam-Diam**:
   - Ketika ada kandidat pasar yang lolos *hard-gate*, bot memanggil `AI_BATCH_TRIAGE` ke 9Router (`http://127.0.0.1:20128/v1`).
   - Karena 9Router mengembalikan error `HTTP 503 / 403`, modul `orchestrator.py` memicu mekanisme *fail-safe* `AI_BATCH_TRIAGE_FALLBACK`.
   - Modul evaluasi mendalam berikutnya secara otomatis menetapkan putusan:
     $$\mathbf{decision = \text{"SKIP"}},\quad \mathbf{confidence = 0}$$
   - Akibatnya, **tidak ada satu pun order yang diizinkan masuk ke bursa**, meskipun secara visual monitor eksternal melihat bot berstatus `ACTIVE_SEARCHING` dengan kuota kosong (9 slot tersedia).
4. **Durasi Gangguan**:
   - Gangguan telah berlangsung terus-menerus selama **~25 jam**, terhitung sejak **16 Oktober 2026 pukul 19:59:04 UTC** (~02:59 WIB 17 Oktober 2026).
   - Dari **1.400 siklus triage AI** dalam kurun waktu tersebut, tercatat **1.399 kali gagal akibat `HTTP_ERROR` (tingkat kegagalan 99,93%)** dan hanya 1 kali lolos parsial.
5. **Temuan Sekunder (Rate Limit BingX 429)**:
   - Pada pemindaian menit-menit terkini (21:24 & 21:25 UTC, 17 Okt 2026), log mulai mencatat `BACKGROUND_SCAN_ERROR`:
     `BingX API Error [-1]: HTTP transport error: Client error '429 Too Many Requests'` pada query `/openApi/swap/v2/user/positions`.
   - Repetisi pemindaian 60 detik tanpa henti saat AI sedang offline membebani kuota request IP VPS ke API BingX VST.

---

## 2. Bukti Empiris Sumber Primer (Ground-Truth Evidence)

### A. Uji Konektivitas & Status Port 9Router di VPS
Perintah: `netstat -tuln | grep 20128`
Output:
```
tcp        0      0 0.0.0.0:20128           0.0.0.0:*               LISTEN
```

Uji Endpoint Model: `curl -s -m 5 http://127.0.0.1:20128/v1/models`
Output:
```json
{"object":"list","data":[{"id":"fallback","object":"model",...},{"id":"testing_v1","object":"model",...},{"id":"ag/gemini-3.8-flash-high","object":"model",...}]}
```
*Port dan service 9Router aktif, tetapi:*

Uji Chat Completion (`testing_v1`):
```bash
curl -s -X POST http://127.0.0.1:20128/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "testing_v1", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10}'
```
Output Verbatim:
```json
{"error":{"message":"[antigravity/gemini-3.8-flash-high] [403]: HTTP 403 (reset after 2m)"}}
```

Uji Model Lain di Bawah Provider Antigravity:
- `ag/gemini-3.8-flash` $\rightarrow$ `HTTP 403 (reset after 10s)`
- `ag/gemini-3.7-flash-high` $\rightarrow$ `HTTP 403 (reset after 4s)`
- `ag/gemini-3.6-flash-high` $\rightarrow$ `HTTP 403 (reset after 1m 45s)`
- `ag/claude-sonnet-4-6` $\rightarrow$ `HTTP 403 (reset after 1m 38s)`

*Kesimpulan Uji 9Router:* Seluruh model yang dialihkan ke koneksi akun Antigravity mengalami penolakan otorisasi/akses upstream (`HTTP 403 Forbidden`).

---

### B. Bukti Kutipan Berkas `logs/audit.jsonl` di VPS
Berikut cuplikan urutan log kejadian berulang pada setiap siklus pemindaian:

```json
{"timestamp": "2026-10-17T21:23:20.931576+00:00", "event_type": "AI_BATCH_TRIAGE", "session_id": "bx_sess_1791926045_8981c2", "data": {"candidates_count": 4, "is_valid": false, "ranked": [], "selected_finalists": [], "latency_ms": 457.98, "usage": {}, "error_type": "HTTP_ERROR", "attempts": 1}}

{"timestamp": "2026-10-17T21:23:20.931721+00:00", "event_type": "AI_BATCH_TRIAGE_FALLBACK", "session_id": "bx_sess_1791926045_8981c2", "data": {"error": "batch_triage_error: HTTP 503: {\"error\":{\"message\":\"[antigravity/gemini-3.8-flash-high] [403]: HTTP 403 (reset after 2m)\"}}", "error_type": "HTTP_ERROR", "candidates_count": 4, "latency_ms": 457.98, "attempts": 1}}

{"timestamp": "2026-10-17T21:23:20.938661+00:00", "event_type": "AI_EVALUATION", "session_id": "bx_sess_1791926045_8981c2", "data": {"symbol": "DOPE-USDT", "decision": "SKIP", "confidence": 0, "key_evidence": "", "risk_factors": "", "model_name": "testing_v1", "usage": {}, "latency_ms": 0.0}}

{"timestamp": "2026-10-17T21:23:20.943966+00:00", "event_type": "AI_EVALUATION", "session_id": "bx_sess_1791926045_8981c2", "data": {"symbol": "AGT-USDT", "decision": "SKIP", "confidence": 0, "key_evidence": "", "risk_factors": "", "model_name": "testing_v1", "usage": {}, "latency_ms": 0.0}}

{"timestamp": "2026-10-17T21:23:20.944505+00:00", "event_type": "CYCLE_SUMMARY", "session_id": "bx_sess_1791926045_8981c2", "data": {"candidate_count": 8, "deep_review_count": 2, "total_ai_tokens": 0, "token_budget": 30000, "quota_filled": 1}}
```

---

### C. Statistik Kuantitatif Periode Gangguan (16 Okt 19:59 UTC s/d 17 Okt 21:30 UTC)

| Metrik Evaluasi | Nilai Kuantitatif | Sumber Primer |
| :--- | :---: | :--- |
| **Waktu Mulai Error Konsisten** | **2026-10-16 19:59:04 UTC** (~02:59 WIB 17 Okt) | `logs/audit.jsonl` |
| **Total Siklus AI Triage Dipanggil** | **1.400 siklus** | `logs/audit.jsonl` |
| **Siklus Berhasil (`is_valid = True`)** | **1 siklus (0,07%)** | `logs/audit.jsonl` |
| **Siklus Gagal (`HTTP_ERROR`)** | **1.399 siklus (99,93%)** | `logs/audit.jsonl` |
| **Penyebab Gagal Triage** | `HTTP 503 / 403 Forbidden` dari 9Router | `logs/audit.jsonl` |
| **Kandidat Pasar Terpaksa di-SKIP** | `AGT-USDT` (396x), `DNA-USDT` (237x), `CLAUDIA-USDT` (218x), `GTC-USDT` (112x), `OPG-USDT` (103x), `DOPE-USDT` (94x), dll. | `logs/audit.jsonl` |
| **Insiden BingX Rate Limit 429** | **16 kali** (tercatat di akhir pemantauan) | `logs/audit.jsonl` |

---

## 3. Kondisi Keamanan Modal & Posisi Terbuka

1. **Integritas Posisi Terbuka (`CORE-USDT`)**:
   - Posisi `CORE-USDT` SHORT (3333.3 qty) **TIDAK TERPENGARUH SAMA SEKALI** oleh gangguan AI gateway.
   - Posisi saat ini berada dalam kondisi *floating profit* di bursa BingX VST (~+2.10 VST / +1.05 R).
   - Order `STOP_MARKET` (`0.01935`) dan `TAKE_PROFIT_MARKET` (`0.01725`) tetap terpasang dengan status `NEW` (resting aktif di bursa).
2. **Kepatuhan Desain Keamanan (*Fail-Safe Behavior*)**:
   - Kode bot (`orchestrator.py`) bekerja dengan benar sesuai prinsip pertahanan lapis: ketika AI gateway gagal merespons, bot **TIDAK melakukan blind entry**.
   - Seluruh kandidat ditolak (`SKIP`), sehingga dana akun aman 100% dari eksekusi tanpa analisis.

---

## 4. Opsi Remediasi Teknis yang Diajukan untuk Keputusan Lead Reviewer (Argon)

Mengingat aturan operasional **"9Router/Hermes: no restart tanpa instruksi"**, Hermes tidak mengambil tindakan sepihak apa pun. Berikut tiga alternatif jalur perbaikan yang diajukan kepada Lead Reviewer Gemini 4 Argon:

### Opsi A — Penyegaran Kredensial / Re-Login OAuth Antigravity pada 9Router
- **Diagnosis Masalah**: File konfigurasi `/home/ubuntu/.9router/db/data.sqlite` mencatat dua koneksi OAuth Antigravity (`belajar.from0@gmail.com` dan `neveersuren22@gmail.com`). Kode status `403 (reset after X)` mengindikasikan token OAuth kedaluwarsa, sesi terblokir sementara oleh Cloudflare/upstream Antigravity, atau akun terkena limitasi tier.
- **Tindakan**: Naufal / tim melakukan re-autentikasi akun Antigravity melalui CLI/dashboard 9Router atau memperbarui refresh token.

### Opsi B — Penambahan Fallback Gateway Model di 9Router (`testing_v1`)
- **Diagnosis Masalah**: Tabel `combos` di database 9Router memetakan `testing_v1` secara tunggal (*single point of failure*) ke:
  `["ag/gemini-3.8-flash-high"]`.
- **Tindakan**: Jika Antigravity sedang mengalami restriksi, tambahkan provider cadangan (misalnya direct API Gemini via official key, OpenRouter, atau fallback model lain) ke dalam combo `testing_v1` pada 9Router sehingga ketika Antigravity 403, 9Router otomatis mengalihkan request ke model cadangan tanpa membuat bot mengalami 1.400x SKIP.

### Opsi C — Mitigasi BingX API 429 Rate Limit
- **Diagnosis Masalah**: Background loop memanggil endpoint posisi BingX setiap 60 detik tanpa jeda adaptif saat siklus berturut-turut mengalami kegagalan AI.
- **Tindakan**: Tambahkan *exponential backoff* atau penyesuaian interval panggilan posisi akun ketika terdeteksi status HTTP 429 dari bursa.

---

## 5. Status Akhir Hermes

- Berkas data terstruktur `evidence_0_entry_9router_investigation_2026_10_18.json` telah tersimpan di direktori `reports/evidence/` lokal dan VPS.
- Sesi bot tetap dibiarkan berjalan pada status aslinya (`ACTIVE_SEARCHING`, `quota = 10`, `auto_scan = 1`).
- Posisi `CORE-USDT` terpantau aman dengan resting TP/SL aktif.
- Hermes **STANDBY PENUH** menunggu arahan instruksi teknis dan putusan resmi dari **Gemini 4 Argon** dan **Naufal Ananta**.
