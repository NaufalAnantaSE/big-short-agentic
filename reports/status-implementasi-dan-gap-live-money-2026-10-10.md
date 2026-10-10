# Laporan Status Implementasi dan Gap Live-Money — BingX Agentic Trader

Tanggal laporan: 10 Oktober 2026  
Disusun oleh: Agent Hermes  
Untuk: Naufal Ananta dan Agent Muse  
Status: **BELUM SIAP LIVE-MONEY — implementasi parsial, perlu remediasi dan validasi**

## 1. Ringkasan eksekutif

Perubahan P0/P1 dan utilitas metrik Fase 3 sudah dikomit dan dipush ke GitHub. Namun, keberadaan commit dan test suite hijau **tidak membuktikan seluruh acceptance criteria selesai**. Pemeriksaan ulang menemukan beberapa helper belum terhubung ke alur produksi, pengujian terlalu sempit, serta klaim validasi yang sebenarnya berasal dari hasil sintetis.

Laporan ini mengoreksi pernyataan sebelumnya bahwa Fase 1, 2, dan 3 telah selesai 100%. Pernyataan tersebut ditarik sebagai kesimpulan readiness. Kode dan commit tetap ada; yang dikoreksi adalah cakupan bukti dan status penyelesaiannya.

Kesimpulan utama:

- Push berhasil: HEAD lokal dan remote identik saat pemeriksaan laporan.
- Hasil pengujian terakhir yang tercatat: 214 passed, 5 warnings; build frontend berhasil.
- EMA50 masih menerima kurang dari 50 candle melalui jalur produksi default.
- Divergence masih membandingkan ekstrem harga dan RSI secara terpisah, bukan pasangan pivot pada timestamp yang sama.
- Daily-loss/cooldown belum memperoleh outcome trade secara otomatis melalui caller produksi yang ditemukan.
- Ledger exit dan snapshot equity baru memiliki helper dan test, belum lifecycle integration yang lengkap.
- Validator Fase 3 berisi daftar outcome sintetis hardcoded. Bukan replay market, bukan panggilan pipeline LLM aktual, dan bukan bukti keunggulan LLM.
- Tidak ada bukti baru dalam pekerjaan ini bahwa versi terbaru telah diaktifkan pada daemon atau diuji dalam rehearsal bursa.

## 2. Identitas snapshot dan batas pemeriksaan

| Elemen | Nilai |
|---|---|
| Repository lokal | `/home/naufal-ananta/bot/bingx-short-agent` |
| GitHub | https://github.com/NaufalAnantaSE/big-short-agentic |
| Branch | `main` |
| Snapshot kode | `be8cd56ad7fcfcb2901ac61aaac61172391264ef` |
| Commit sebelum rangkaian perubahan | `7bed0f7` |
| Jumlah commit yang dipush | 14 |
| Status sebelum laporan ditulis | Working tree bersih, lokal sinkron dengan origin/main |
| Dokumen acuan | `/home/naufal-ananta/Downloads/panduan-pengembangan-live-money.md` |

Nomor baris kode di laporan merujuk snapshot di atas. Laporan ini sendiri dibuat setelah push tersebut dan belum termasuk dalam snapshot. Pemeriksaan menggunakan pembacaan kode, pencarian caller, status Git, dan hasil tool yang tersedia dalam sesi. Ini bukan audit keamanan menyeluruh atau penetapan profitabilitas.

Dokumen Muse menetapkan Fase 1 = perbaikan kritis, Fase 2 = kualitas sinyal/risiko, Fase 3 = validasi eksperimental. Daftar sebelumnya yang menyebut Fase 3 sebagai WebSocket/funding/UI/secret-hook bukan isi fase tersebut dalam dokumen acuan.

## 3. Bukti verifikasi

### 3.1 Git — diperiksa ulang saat laporan dibuat

Perintah: `git status --short --branch`, `git rev-parse HEAD`, `git log -14 --oneline`, dan `git ls-remote origin refs/heads/main`.

Hasil:

- Status: `## main...origin/main` tanpa perubahan pada saat pemeriksaan.
- HEAD lokal: `be8cd56ad7fcfcb2901ac61aaac61172391264ef`.
- Remote `refs/heads/main`: hash identik.
- Push sebelumnya: `7bed0f7..be8cd56 main -> main`.

### 3.2 Pengujian — hasil terakhir sesi, tidak dijalankan ulang untuk penulisan laporan

| Pemeriksaan | Hasil nyata terakhir | Batas bukti |
|---|---|---|
| `pytest -q` | 214 passed, 5 warnings, 37.13 detik | Membuktikan suite yang tersedia lolos, bukan seluruh kebutuhan terpenuhi |
| `npm run build` di frontend | Vite sukses; 19 modules transformed; 1.35 detik | Build bundel, bukan browser E2E atau verifikasi perilaku trading |
| Pemeriksaan pola secret sebelum push | 0 nama file sensitif yang cocok; 0 pola token/private-key yang cocok pada tambahan diff | Pemindaian pola terbatas, bukan audit secret komprehensif |
| Aktivasi daemon | Tidak dilakukan pada langkah push | Versi proses aktif belum diverifikasi |
| Rehearsal bursa untuk snapshot ini | Tidak ada bukti baru | Hasil VST historis tidak otomatis berlaku untuk snapshot baru |

Lima warning berasal dari deprecation FastAPI/Starlette/httpx. Total test meningkat dari baseline historis 171 menjadi 214 (+43), tetapi kenaikan jumlah test tidak sama dengan jumlah kebutuhan yang selesai. Tidak semua perubahan memiliki jejak RED yang memadai untuk perilaku yang diklaim.

## 4. Inventaris commit

| Commit | Pekerjaan yang tercatat | Status penerimaan saat ini |
|---|---|---|
| `83f2c36` | Closed-candle validation | Ada implementasi; buffer produksi perlu koreksi/verifikasi |
| `a13093f` | Quote revalidation dan telemetry | Ada gate direct; provenance fill belum ketat |
| `0b6e902` | Exposure UNKNOWN fail-closed | Exception handling tersedia; audit seluruh pintu order masih perlu |
| `9a48e14` | Session generation check | Check tersedia; critical section submit belum terlindungi |
| `80b370a` | Watchlist parity | Spread/depth/context diperbaiki; paritas penuh belum selesai |
| `896642b` | Pemisahan mock dari client | Fixture test tersedia; bukan sandbox jaringan total |
| `0bd87fd` | Fixed-risk sizing | Helper tersedia; aktivasi lewat jalur tenant belum tersambung |
| `2ae638b` | Mandatory playbook conditions | Gate parsial, pola inti masih dapat terlewat |
| `d66e7c4` | Portfolio-risk controls | State/gate tersedia; outcome integration belum lengkap |
| `32ddfbd` | Ledger lifecycle | Skema/helper dan entry wiring parsial |
| `2cf01c2` | True Range dan warmup parameter | True Range berubah; warmup produksi belum diwajibkan |
| `58bf0f8` | Micro-price precision | Presisi magnitude-based; alignment divergence belum diimplementasikan |
| `afad0cf` | Shadow validation metrics | Utilitas sintetis, bukan validasi eksperimen selesai |
| `be8cd56` | Laporan historis VST/Codex | Dokumentasi; tidak membuktikan readiness snapshot baru |

## 5. Temuan teknis dan dampak

### F-01 — Buffer closed-candle produksi tidak sesuai klaim sebelumnya — **FIXED (`2151599`)**

Bukti: `market_features.py:68–104`, `560–610`, dan `689`.

`_closed_rows` sudah memeriksa close timestamp atau open timestamp + interval. Tetapi `buffer_ms` default masih 0, termasuk `compute_market_features`, dan caller pengambilan fitur tidak meneruskan buffer nonzero. Klaim bahwa buffer 2000 ms aktif seragam tidak didukung jalur ini.

Tindak lanjut: tetapkan buffer pada konfigurasi produksi, pastikan konsisten di direct/watchlist, dan uji tepat sebelum/sesudah batas close serta clock skew.

**SUDAH DIPERBAIKI (`2151599`).** `PRODUCTION_CANDLE_BUFFER_MS = 5000` kini diterapkan di `build_candidate_features`, jalur scan `orchestrator.py` (yang sebelumnya mengirim AI `limit=10` termasuk bar berjalan), dan `check_deterministic_reversal` watchlist. Kedalaman kline produksi dinaikkan ke `PRODUCTION_KLINE_LIMIT = 120`. Regression: `test_phase2_indicators.py::test_ema_trend_invalid_below_warmup` dan fixture 60 bar pada test Phase 2.

### F-02 — Generation check belum menghilangkan race stop/submit — **FIXED (`0512374`)**

Bukti: `orchestrator.py:126`, `396–465`, `706–771`; pencarian `_session_lock`.

Lock dipakai ketika stop, tetapi pemeriksaan token dan submit order berjalan di luar critical section yang sama. Terdapat panggilan `set_leverage` antara check dan `place_order`. Stop yang terjadi setelah check tetap berpotensi diikuti submit.

**SUDAH DIPERBAIKI (`0512374`).** `_session_lock` diubah menjadi `threading.RLock()` dengan helper atomik `_is_session_valid_for_execution(session_id, generation_token)`. Critical section membungkus validasi sesi dan pemanggilan `place_order` baik pada alur direct execution maupun watchlist reversal execution. Regression: `tests/test_f02_atomic_stop_submit.py` (3 test, RED → GREEN).

### F-03 — Quote/fill dan jalur watchlist belum setara sepenuhnya — **FIXED (`8286193`)**

Bukti: `orchestrator.py:350–394`, `475–494`, `650–799`.

Jalur direct melakukan drift gate dan resizing terhadap executable price. Namun, saat avg fill tidak tersedia, kode menggantinya dengan executable quote (`actual_avg_price`), sehingga nilai estimasi dapat tampil sebagai actual fill. Status order juga mempunyai fallback `FILLED`.

Watchlist masih melakukan sizing dengan `entry.atr` dan `entry.leverage`, memakai mid-price, serta memiliki blok submit tersendiri. Belum ada satu final-validation gateway yang membuktikan seluruh kebutuhan freshness/exposure/portfolio risk dilalui sama oleh direct, fallback, dan watchlist.

**SUDAH DIPERBAIKI (`8286193`).** Fabrikasi fill rate dihapus total: jika bursa tidak mengembalikan average price terisi, sistem menandai order sebagai `PENDING_RECONCILIATION` dengan `actual_avg_price = None` dan `slippage = None`. Pada watchlist: sizing kini menggunakan executable price riil yang menyeberang spread (`bid1` untuk SHORT, `ask1` untuk LONG), dipasang spread blowout guard (`max_spread_pct`), anti-reentry guard (`executed_symbols`), dan pelacakan provenance `EXCHANGE_REPORTED` / `PENDING_RECONCILIATION`. Regression: `tests/test_f03_parity_and_fill_provenance.py` (6 test, RED → GREEN).

### F-04 — Fixed-risk belum menjadi perilaku default aplikasi tenant — **FIXED (`1e89102`)**

Bukti: `orchestrator.py:58`, `80–107`, `259`, `703`; `tenant_manager.py:357–387`.

`risk_budget_per_trade` bersifat opsional dengan default `None`. Jalur start sesi tenant tidak meneruskannya. Formula fixed-risk tersedia, tetapi klaim semua trade memakai risiko tetap $2 tidak benar; $2 berasal dari skenario uji, bukan konfigurasi universal yang terverifikasi.

**SUDAH DIPERBAIKI (`1e89102`).** Parameter diintegrasikan dari `AppConfig.default_risk_budget_usdt = 2.0`, `SessionStartRequest`, `TenantSessionManager.start_session(..., risk_budget_per_trade=2.0)`, persistensi kolom `risk_budget_per_trade` pada tabel `sessions`, pemulihan saat restart/rehidrasi tenant, serta kedua jalur sizing (direct dan watchlist staging). Setup yang melanggar toleransi risiko fixed-risk (+-10%) otomatis ditolak (fail-closed). Regression: `tests/test_f04_fixed_risk_tenant_defaults.py` (4 test, RED → GREEN).

### F-05 — Mandatory conditions belum mewajibkan seluruh pola inti — **FIXED (`49ea57c`)**

Bukti: `strategy_playbook.py:55–99`, `110–153`, `163–194`.

- PUMP_EXHAUSTION dapat memenuhi core gate dari zona Fibonacci saja; zona puncak bukan bukti rejection fisik.
- SUPPORT_PULLBACK mewajibkan zona support, tetapi tren dan konfirmasi rebound belum menjadi seluruh syarat wajib; tren masih poin tambahan.
- BREAKDOWN_RETEST menerima retracement/flag sebagai breakdown, sementara retest rejection masih poin tambahan, bukan urutan wajib breakdown → retest gagal.

Tindak lanjut: reproduksi negatif tiap pola tanpa struktur inti dan pastikan ditolak. Validasi missing/invalid feature tidak menghasilkan poin yang meloloskan setup.

**SUDAH DIPERBAIKI (`49ea57c`).** Tiga pola kini menuntut struktur inti penuh: PUMP_EXHAUSTION wajib bukti rejection fisik (wick/confluent rejection/divergence) — zona Fibonacci puncak saja tidak lagi memenuhi core gate; SUPPORT_PULLBACK wajib uptrend makro **dan** konfirmasi rebound; BREAKDOWN_RETEST wajib breakdown **dan** retest gagal. Regression: `tests/test_f05_playbook_mandatory_structure.py` (8 test, RED → GREEN). Dampak terukur pada keputusan nyata ada di bagian 10.

### F-06 — Daily-loss/cooldown belum tersambung ke outcome trade produksi — **FIXED (`6a5dd21`)**

Bukti: `orchestrator.py:140–158`, `576–600`, `327–328`; pencarian caller `record_trade_outcome` dan penulisan `daily_realized_pnl`.

Helper outcome menambah PnL dan loss streak. Namun pencarian sumber Python tidak menemukan caller produksi helper tersebut. Test daily-loss mengisi nilai PnL sesi secara manual. Karena itu, test membuktikan gate atas state yang diisi, bukan pembaruan state dari closed trade bursa.

Anti-reentry terlihat pada evaluasi direct; paritas pada watchlist dan pemulihan setelah restart belum terbukti. Max total risk-at-stop konkuren dan batas konsentrasi arah dari panduan belum ditunjukkan oleh perubahan ini.

**SUDAH DIPERBAIKI (`6a5dd21`).** `BingXClient` diperkaya dengan query riil `/openApi/swap/v2/user/income` (realized PnL). `SessionOrchestrator.reconcile_outcomes()` otomatis mengatribusikan realized PnL pada simbol sesi aktif, mendeduplikasi income event via `processed_income_ids`, mereset loss streak dan PnL saat pergantian tanggal UTC (`DAY_BOUNDARY_RESET`), memicu cooldown saat loss streak tercapai, serta menghentikan seluruh siklus baru saat `max_daily_loss_pct` terlampaui. Status PnL dipersistensikan ke SQLite dan dipulihkan saat restart. Regression: `tests/test_f06_outcome_ingestion_and_daily_loss.py` (5 test, RED → GREEN).

### F-07 — Ledger lifecycle dan equity masih parsial; leverage memakai key keliru — **PARTIAL FIX (`89936f6`)**

Sub-issue leverage **SUDAH DIPERBAIKI** pada `89936f6`: tenant sekarang memakai helper `_resolve_effective_leverage()` yang membaca key `effective_leverage` (output nyata `SizingCalculator`), dengan fallback ke leverage sesi hanya bila nilai tidak ada/tidak valid. Regression: `tests/test_f07_effective_leverage.py` (3 test, RED → GREEN).

Sisa yang **belum** diperbaiki:

Bukti: `db.py:270`, `457` dan helper query berikutnya; `tenant_manager.py:704–729`; `sizing.py:10`.

- `record_trade_exit` dan `update_session_equity` hanya ditemukan pada definisi/helper dan test, bukan caller produksi.
- Tenant mengambil `sizing.get("adaptive_leverage")`, sedangkan output sizing memakai `effective_leverage`. Jalur ini dapat fallback ke leverage sesi dan menggagalkan atribusi leverage aktual.
- Pencatatan entry memakai fallback harga dan status FILLED; belum membuktikan reconciled fill lifecycle.
- `get_closed_trade_attribution` tidak memfilter `status = 'CLOSED'` dan menggunakan identifier tanpa parameter tenant. Batas kepemilikan dan semantik closed-only perlu ditetapkan sebelum diekspos.
- Missing realized PnL/R pada helper exit diubah menjadi 0; unknown tidak dapat dibedakan dari benar-benar nol.

Tindak lanjut: benar-benar sambungkan entry/exit/equity, gunakan field leverage yang tepat, pertahankan unknown, tambahkan idempotency, ownership, partial-fill, dan manual/legacy attribution tests.

### F-08 — P1-5 belum selesai: EMA, divergence, dan contract precision — **PARTIAL FIX (`8f794f8`, `2151599`)**

Bukti: `market_features.py:18–33`, `402–440`, `515–555`, `610`; `tests/test_p1_5_indicator_improvements.py:54–91`.

- `_ema_trend_analysis` default `min_bars=3`; caller produksi tidak meneruskan 50. Test hanya memanggil opsi 50 secara eksplisit.
- `_calculate_ema` masih fallback ke mean saat histori kurang dari period.
- Divergence masih mengambil `max/min` harga dan RSI terpisah. Test menerima `BEARISH_DIV` maupun `NONE`, sehingga tidak membuktikan alignment pivot.
- `_round_price` memilih 6/8/10 desimal berdasarkan magnitude. Ini perbaikan terhadap hardcoded 6, tetapi bukan presisi berdasarkan metadata kontrak.
- True Range telah memperhitungkan previous close. Agregasi ATR berupa mean 14 True Range; kesesuaian terhadap reference smoothing harus didokumentasikan, tidak diasumsikan sama dengan seluruh platform bursa.

Tindak lanjut: wajibkan warmup di jalur aktual, gunakan pasangan pivot berindeks/timestamp sama, dan tambahkan reference-based tests serta contract-precision checks.

**SEBAGIAN DIPERBAIKI (`8f794f8`, `2151599`).**

- **Aligned pivots — SELESAI (`8f794f8`).** `_detect_rsi_divergence` kini membandingkan pivot harga terkonfirmasi dengan nilai RSI **pada indeks bar yang sama**. Implementasi lama dipertahankan sebagai `_detect_rsi_divergence_unaligned` khusus untuk pembanding baseline. Regression: `tests/test_f08_divergence_alignment.py` (5 test) memuat deret pembeda yang membuktikan versi lama menyala palsu dan versi baru tidak.
- **Warmup produksi — SELESAI (`2151599`).** `EMA_WARMUP_BARS = 50` diteruskan dari `compute_market_features` ke `_ema_trend_analysis`; di bawah warmup trend dilaporkan `valid: False`.
- **Contract precision — BELUM.** `_round_price` masih memilih desimal berdasarkan magnitude, bukan metadata kontrak. Ini sisa yang jujur belum dikerjakan.
- **Agregasi ATR** masih mean 14 True Range; kesesuaian terhadap smoothing referensi bursa belum didokumentasikan.

### F-09 — Fase 3 adalah contoh metrik sintetis, bukan eksperimen selesai

Bukti: `scripts/shadow_replay_validator.py:26–39`, `42–102`, `148–198`.

`run_synthetic_shadow_test` mendefinisikan enam outcome baseline dan empat outcome LLM secara hardcoded. Tidak ada pemanggilan scanner, hard gate, model, atau execution replay untuk menghasilkan keputusan tersebut. Daftar LLM menghilangkan sebagian loss baseline berdasarkan isi kode, sehingga delta hasil tidak dapat ditafsirkan sebagai keunggulan LLM.

`net_expectancy_r` adalah rata-rata `realized_r` input. Fee/funding dijumlahkan terpisah, bukan dikonversi dan dikurangkan ke R. Slippage tidak digunakan dalam kalkulasi net, dan tidak ada field biaya AI. Label net hanya sah bila input sudah benar-benar net dengan provenance yang jelas; contoh saat ini tidak membuktikannya.

MAE/MFE adalah angka input, bukan hasil pengukuran lintasan harga. Stratifikasi baru playbook dan arah; belum direct/watchlist, fallback, regime, volatilitas, likuiditas, atau konteks BTC/ETH. Tidak ada freeze manifest kode/config/model atau holdout ratusan trade.

Tindak lanjut: tempatkan hasil sintetis sebagai fixture pengujian saja. Bangun replay opportunity set nyata yang sama, provenance keputusan/outcome, cost accounting, dan holdout sebelum laporan eksperimen diterima.

**SUDAH DIBUANG (`e5fe5dc`).** Sesuai arahan Naufal, angka outcome hardcoded tidak lagi hanya dilabeli — seluruh jalur sintetis dihapus dari modul:

- `ShadowReplayValidator` dan `run_synthetic_shadow_test()` dihilangkan total.
- Dua daftar trade hardcoded (baseline & "LLM") dihapus.
- Harness sekarang wajib memuat dataset replay nyata via `load_replay_dataset(path)` dan **fail-closed** (`ReplayDatasetError`) bila file hilang, kosong, malformed, field wajib absen, arah tidak dikenal, atau nilai non-numerik.
- Stratifikasi diperluas: playbook, arah, **execution path**, dan **fallback**.
- Ada guard test `test_no_synthetic_result_path_remains()` yang gagal bila entry point sintetis dimasukkan kembali.
- Angka nol pada docstring hanya contoh bentuk record, bukan hasil. Regression: `tests/test_fase3_shadow_replay_validator.py` (11 test).

Catatan: konversi fee/slippage/AI-cost menjadi R masih belum dilakukan; itu tetap bagian dari remediasi Fase 3, bukan sesuatu yang dianggap selesai.

### F-10 — Test hijau belum memenuhi disiplin acceptance

Bukti: test divergence yang permisif; test EMA memakai argumen berbeda dari production caller; test risiko mengisi state langsung; `tests/conftest.py:12–30`.

Fixture jaringan hanya memotong sebagian endpoint untuk credential dummy tertentu dan mengecualikan test live. Jangan menyebut seluruh suite terisolasi jaringan mutlak tanpa transport-level deny dan database disposable yang diverifikasi.

Tindak lanjut: setiap gap mendapat regression RED yang gagal karena perilaku sasaran, lalu GREEN pada implementasi produksi. Pisahkan helper test, integrasi offline, browser, dan rehearsal exchange dalam laporan.

## 6. Urutan remediasi dan acceptance

Owner yang diusulkan: Hermes untuk implementasi; Muse untuk review independen. Deadline belum ditetapkan. Jangan melemahkan gate untuk membuat test atau eksperimen terlihat berhasil.

1. **Tutup P0 terlebih dahulu:** atomic stop/submit, validasi buffer produksi, final gateway lintas jalur, serta actual-fill provenance. Acceptance: regression direct/watchlist/fallback dan concurrency lolos; tidak ada submit setelah stop terlineariskan.
2. **Sambungkan P1 risk dan ledger:** budget API/session, persistence/recovery, real outcome ingestion, equity snapshots, effective leverage, tenant isolation, idempotency. Acceptance: event lifecycle lengkap menghasilkan ledger dan risk gate yang konsisten, termasuk duplicate/partial/missing events.
3. **Selesaikan pola dan indikator:** mandatory structure, warmup produksi, aligned pivots, presisi kontrak, referensi per indikator. Acceptance: reproduksi negatif ditolak dan output dibandingkan referensi terdokumentasi.
4. **Review independen:** cek diff dan regression per requirement, bukan hanya jumlah test. Catat P0/P1 terbuka; jangan menutup butir dari judul commit.
5. **Baru jalankan Fase 3:** freeze commit/config/model; opportunity set nyata identik; OOS/holdout; biaya lengkap; ratusan closed trades lintas regime; kalibrasi confidence dan seluruh stratifikasi.
6. **Rehearsal exchange terpisah:** setelah persetujuan operasional, verifikasi lifecycle versi yang benar, rekonsiliasi saldo, dan orphan-order checks. Dokumen atau Git push bukan izin aktivasi live.

## 7. Checklist promosi live-money

- [ ] Fase 1 dan 2 selesai dengan bukti per requirement, bukan sekadar commit.
- [ ] Tidak ada P0/P1 terbuka pada review Agent Muse.
- [ ] Expectancy net positif dalam R pada sampel ratusan trade di luar tuning.
- [ ] Drawdown sesuai toleransi yang ditetapkan.
- [ ] Fallback rate kurang dari 10% pada sesi validasi nyata.
- [ ] Fee, funding, slippage, dan biaya AI diperhitungkan dengan satuan/provenance yang jelas.
- [ ] Rekonsiliasi wallet delta, ledger bursa, equity dan floating; selisih lebih dari 0,01 VST diinvestigasi.
- [ ] Versi daemon aktif dan rehearsal exchange telah diverifikasi secara terpisah.

**Verdict:** source code telah dipush, tetapi readiness live-money belum terpenuhi. Jangan memakai hasil sintetis, title commit, test count, atau laporan historis sebagai pengganti bukti acceptance.

## 9. Analisis prioritas: apa yang paling mungkin menjelaskan 4 SL beruntun?

Pertanyaan Naufal: dari 10 temuan, mana yang paling mungkin menjelaskan 4 SL beruntun sesi `bx_sess_1791579205_ab6bff` — atau semuanya variance?

Metode: agregasi `logs/audit.jsonl` untuk `session_id = bx_sess_1791579205_ab6bff` (1.291 baris). Ini bukti log, bukan pendapat.

### 9.1 Fakta dari log

| Metrik | Nilai |
|---|---|
| `AI_EVALUATION` | 358 |
| Keputusan: WAIT / SKIP / ENTER | 211 / 136 / **13** |
| `ORDER_SUBMISSION` | **11** (8 SHORT, 3 LONG) |
| `HARD_GATE_REJECT` | 379 |
| `WATCHLIST_TRIGGER` | **0** |
| `WATCHLIST_VETO` | 14, **semuanya** `invalid_direction:UNKNOWN` |
| `AI_BATCH_TRIAGE_FALLBACK` | 40 |
| Confidence seluruh ENTER | **72–78** (semua menempel ambang) |

Alasan gate terbanyak: `atr_below_friction_threshold` 289, `spread_too_wide` 169, `long_fomo_danger` 129, `dump_already_extended` 55.

Temuan paling penting dari 13 ENTER: **JEANPHIL-USDT muncul 3 kali sebagai keputusan `ENTER_LONG` dan 2 kali benar-benar terkirim** dalam sesi yang sama:

- `bx_long_1791584917_fe0c1b` @ 0.010849
- `bx_long_1791595284_d26b58` @ 0.010834 (±2j53m kemudian)

Ini masuk LONG ke simbol yang sudah punya posisi LONG. Gate anti-re-entry P1-3 belum ada saat sesi itu berjalan, jadi tidak ada yang memblokir.

Kedua, `risk_factors` yang ditulis AI sendiri pada entry JEANPHIL sudah menyebut invalidasinya:

> "stop-run risk below EMA50 (0.01049)" dan "1h ATR >13% poses liquidation risk"

AI menandai risiko stop-run, lalu tetap `ENTER_LONG`. Laporan review mencatat JEANPHIL kena SL dalam 19 detik.

Ketiga, `ORDER_SUBMISSION` sesi itu **tidak memuat** `quote_ts`, `request_price`, `avg_fill_price`, `slippage`, maupun `effective_leverage`. Tidak ada exit/close event sama sekali di log, sehingga atribusi R per-trade tidak mungkin dihitung dari log ini — F-07 dan P0-2 tampak nyata di data.

### 9.2 Diskrepansi yang perlu direkonsiliasi

Laporan review menyebut **9 order (7 SHORT, 2 LONG)**. Agregasi log ini menghitung **11 submission (8 SHORT, 3 LONG)**. Selisih 2 = 1 SHORT + 1 LONG tambahan (termasuk JEANPHIL LONG kedua). Penyebab belum dipastikan: kemungkinan perbedaan window waktu atau deduplikasi. Saya tidak menyimpulkan mana yang benar — ini perlu direkonsiliasi sebelum angka apa pun dipakai untuk keputusan.

### 9.3 Penilaian per temuan

| Temuan | Kaitan ke 4 SL | Dasar |
|---|---|---|
| **F-05** (syarat wajib parsial) | **Paling kuat** | 13 ENTER lolos meski `risk_factors` sendiri menyebut kondisi invalidasi (JEANPHIL: stop-run di EMA50). Gate menerima tesis yang bertentangan dengan eksekusinya — persis pola "LLM self-contradictory risk factors bypassing execution gates". |
| **F-01** (buffer closed-candle 0) | **Kuat** | Alasan tiap ENTER bersandar pada "RSI bearish divergence", "peak Fibonacci exhaustion", "volume dry-up" — fitur yang paling rusak bila candle belum tutup. Ini bisa memproduksi sinyal exhaustion palsu. Belum terbukti: log tidak merekam status candle per keputusan. |
| **F-08** (divergence tidak selaras pivot) | **Kuat** | Semua justifikasi SHORT mengutip divergence; bila divergence membandingkan ekstrem terpisah, ia bisa menyala palsu. Confidence 72–78 (menempel ambang) konsisten dengan sinyal batas. |
| **F-06** (daily loss / anti-re-entry) | **Menjelaskan akumulasi, bukan SL pertama** | JEANPHIL LONG 2× dalam satu sesi. Tanpa gate, kerugian menumpuk alih-alih berhenti di satu trade. |
| **F-04** (fixed-risk opt-in) | **Menjelaskan besar, bukan arah** | Variasi ukuran loss, bukan sebab loss. |
| **F-02, F-07, F-09, F-10** | **Tidak relevan** | Tidak ada jalur kausal ke kualitas entry; F-07 hanya menerangkan kenapa atribusinya tidak bisa dibuktikan. |

### 9.4 Jawaban langsung

**Tidak bisa dipastikan pada n=4, tapi ada klaster yang jauh lebih masuk akal daripada murni variance.**

- Sisi variance: sistem RR 2:1 dengan win rate asli ~35–40% memberi peluang 4 loss beruntun sekitar 13–18%. Jadi "kebetulan" tidak bisa dibuang.
- Sisi non-variance: bukti yang tidak bisa dijelaskan variance adalah **JEANPHIL** — AI menulis sendiri risiko stop-run di EMA50, tetap masuk LONG, dan kena SL dalam 19 detik. Itu bukan nasib; itu gate yang meloloskan setup yang invalidasi-nya sudah dikenali. Ditambah 13 ENTER yang semuanya berconfidence 72–78 (menempel ambang, bukan keyakinan kuat) dan **JEANPHIL LONG dua kali**.

Prioritas yang saya usulkan, berbasis bukti ini:

1. **F-05 + F-08 + F-01 sebagai satu klaster kualitas entry** — ini yang paling mungkin menurunkan frekuensi SL, bukan sekadar memperkecilnya.
2. **F-06 + F-07** — pembatas kerugian dan atribusi; penting, tapi tidak akan mengubah sinyal yang salah menjadi benar.
3. **Rekonsiliasi 9 vs 11 order** sebelum metrik apa pun dipakai untuk keputusan.

Uji yang bisa memfalsifikasi dugaan ini: jalankan ulang 13 keputusan ENTER sesi itu melalui pipeline yang sudah diperbaiki (candle closed, divergence selaras, syarat wajib penuh) dan hitung berapa yang tetap lolos. Bila mayoritas terblokir, klaster entry-quality terbukti; bila hampir semua tetap lolos, variance lebih dominan dan prioritas berpindah ke manajemen risiko. Itu mengubah dugaan menjadi bukti, dan tidak butuh sesi baru.

## 10. Uji falsifikasi 13 keputusan ENTER (F-01 / F-05 / F-08)

**Aturan keputusan didaftarkan lebih dulu, sebelum hasil diketahui.** Bila mayoritas dari 13 keputusan ENTER sesi `bx_sess_1791579205_ab6bff` kini terblokir oleh lapisan deterministik yang sudah diperbaiki, klaster kualitas entry (F-01/F-05/F-08) didukung sebagai penyebab 4 SL beruntun. Bila hampir semuanya tetap lolos, variance lebih dominan dan prioritas berpindah ke manajemen risiko (F-06/F-04).

**Metode.** `scripts/falsification_analysis.py`, dengan `scripts/falsification_replay.py` dan `scripts/falsification_baseline_vs_fixed.py` sebagai pass pendukung. Klines diambil **point-in-time**: `startTime`+`endTime` diisi timestamp keputusan asli (BingX menghormati keduanya — terverifikasi: window 10 jam mengembalikan 40 bar 15m, bukan 120), lalu `_closed_rows` membuang bar yang belum tutup. Tidak ada look-ahead. Playbook dijalankan dua kali atas fitur yang identik: mesin baseline (commit `2151599`, pre-F-05, dimuat via `git show`) dan mesin sekarang.

### 10.1 Hasil

| Metrik | Nilai |
|---|---|
| Hard gate memblokir @ spread wajar | **0/13** |
| Hard gate memblokir bila spread ≥ breakeven | 5/13 (breakeven 0.29–0.34%) |
| Playbook baseline meng-endorse arah AI | 10/13 |
| Playbook setelah F-05 meng-endorse arah AI | **6/13** |
| Endorsement dicabut oleh F-05 | 4/13 |
| Divergence dibalik F-08 (`BEARISH_DIV` → `NONE`) | 2/13 (ADA, CORE — keduanya SHORT) |
| Bar belum tutup hadir di feed | **13/13** |
| Kode produksi yang membaca `risk_factors` sebagai gate | **0** |
| Entry yang `risk_factors`-nya menyebut risiko invalidasi | 4/13 |

Pecahan arah: **SHORT 2/8** masih ter-endorse (baseline 5/8) · **LONG 4/5** (baseline 5/5).

### 10.2 Verdict terhadap aturan keputusan

**Dukungan parsial — bukan konfirmasi.** 7 dari 13 keputusan masih lolos, sehingga syarat "mayoritas terblokir" tidak terpenuhi dan variance belum bisa dikesampingkan pada n=4. Efek F-05 terkonsentrasi di sisi SHORT — sisi yang mendominasi kerugian sesi itu — tetapi itu memperkuat hipotesis, tidak membuktikannya.

### 10.3 Temuan paling tajam: tidak ada gate untuk kontradiksi internal

Pencarian menyeluruh menemukan **nol** kode produksi yang membaca `risk_factors` sebagai gate. Field itu hanya ditulis ke audit log, disimpan ke DB, dan dihumanisasi oleh `plain_explainer.py` — tidak pernah menolak apa pun.

Empat dari 13 entry menulis risiko invalidasi di `risk_factors`-nya sendiri lalu tetap dieksekusi. Yang paling tegas adalah JEANPHIL (LONG ketiga): *"stop-run risk below EMA50 (0.01049)"*. Kontradiksi internal ini tidak punya gate sama sekali.

**SUDAH DIPERBAIKI: Ekstensi P1-2 (`afc6e0c`).** Gate kontradiksi terstruktur (bukan tebak-tebakan regex/keyword):
1. Skema prompt Tier 2 (`build_structured_deep_prompt`) dan Fallback (`evaluate_candidate`) mewajibkan Contradiction Audit: `invalidation_risk_present` (true/false), `invalidation_risk_detail`, dan `invalidation_rebuttal`.
2. Evaluator menjalankan `apply_invalidation_gate`:
   - Jawaban absen/ambigu (`None`) → fail-closed ke `WAIT` (`invalidating_risk_answer_missing`).
   - Jawaban `True` tanpa sanggahan konkret/substantif (placeholder/teks kosong/bare denial <15 karakter) → otomatis downgrade ke `WAIT` (`invalidating_risk_unrebutted`).
   - Jawaban `True` dengan sanggahan substantif faktual → `ENTER` diizinkan.
   - Jawaban `False` → `ENTER` diizinkan.
3. Terintegrasi ke orchestrator (`SessionOrchestrator.run_cycle`): keputusan di-downgrade menjadi `WAIT`, dialihkan ke watchlist tanpa mengisi kuota/eksekusi trade, dan dicatat di telemetri/audit log.
4. Regression: `tests/test_p1_2_invalidation_gate.py` (44 test, RED → GREEN). Total suite: **283 passed**.

### 10.4 Batas yang tidak boleh dilewati saat mengutip angka ini

1. Blokir 13/13 pada mode production-faithful adalah **artefak harness**, bukan temuan. Depth orderbook dan open interest tidak punya endpoint historis point-in-time, sehingga freshness fail-closed. Metrik itu dibuang dari laporan, tidak disajikan sebagai hasil.
2. `playbook = NONE` **tidak memblokir order**. Di jalur produksi playbook hanya konteks untuk LLM dan kunci sortir (`orchestrator.py`). Karena itu replay ini **tidak boleh** diklaim sebagai "sistem baru akan mencegah trade tersebut"; yang benar adalah sistem tidak lagi menyajikannya sebagai setup ter-endorse.
3. 5/13 punya breakeven spread 0.29–0.34%. Bila spread riil saat itu lebih lebar dari itu, gate ATR akan memblokirnya. Tidak dapat diverifikasi tanpa depth historis, jadi dilaporkan sebagai sensitivitas, bukan verdict.
4. LLM tidak dijalankan ulang (non-deterministik, biaya token). Yang di-replay adalah lapisan deterministik yang menggating dan memberi skor.

**Artefak mentah:** `~/.hermes/cache/scratch/falsification_final.json` — 13 baris, per keputusan: status gate, playbook baseline vs fixed, divergence, ATR, breakeven spread, dan status intrabar.

## 11. Sumber dan provenance

1. Panduan Muse lokal, terutama baris 11–18 (anti-halu), 33–89 (P0/P1), 93–109 (eksperimen/promosi).
2. Source snapshot: https://github.com/NaufalAnantaSE/big-short-agentic/tree/be8cd56ad7fcfcb2901ac61aaac61172391264ef — file/baris dirinci per temuan.
3. Output Git diperiksa ulang saat laporan dibuat; output pytest/build berasal dari eksekusi nyata terakhir pada sesi yang sama, bukan dijalankan ulang atau dibuat ulang sebagai log.
4. Temuan di atas berasal dari pembacaan kode dan caller search; skenario race dan gap integrasi belum direproduksi sebagai regression baru.
5. Bagian 10 berasal dari eksekusi nyata `scripts/falsification_analysis.py` atas data klines historis BingX yang diambil saat laporan ini dibuat; angka tidak disalin dari pass sebelumnya dan tidak direkonstruksi dari ingatan. Suite akhir: 239 passed (dari 225 sebelum F-01/F-05/F-08).

Dokumen ini bukan persetujuan Muse, bukan laporan profitabilitas, dan tidak mengubah kode produksi, menghentikan posisi, atau me-restart bot.
