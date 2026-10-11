# Review independen remediasi Muse/Hermes — 10 Oktober 2026

**Verdict: REQUEST CHANGES.** Klaim remediasi P0/P1 selesai 100%, tidak ada fabrikasi fill, dan hanya validasi profitabilitas yang tersisa belum didukung perilaku kode secara menyeluruh.

Commit yang diperiksa: `42cc9110a18ac2341b9849f08bce73a21a66be05`.

Dokumen pembanding:

- `/home/naufal-ananta/Downloads/ringkasan-review-muse-2026-10-10.md`
- `reports/laporan-rekapitulasi-remediasi-dan-kesiapan-sistem-2026-10-10.md`

Review mencakup jalur produksi Python, test remediasi, dan bukti audit lokal. Tidak mengubah implementasi trading, memanggil API bursa, menjalankan daemon, atau mengakses kredensial riil. Pengujian dilakukan pada salinan source di `/tmp/bingx-remediation-review-jplh4h1n`, dengan database/log salinan terpisah dan transport HTTP eksternal diblokir. Data kecil buatan dalam test adalah fixture untuk menguji software, bukan bukti performa pasar historis.

## Ringkasan hasil verifikasi

- **15 kasus regresi independen gagal pada assertion perilaku yang diharapkan**, membuktikan celah pada kondisi yang diuji. Ini kumpulan kasus terarah, bukan estimasi persentase seluruh sistem yang cacat.
- Suite yang ada, dengan `test_live_vst.py` dikecualikan: **293 passed, 4 failed, 5 warnings**. Dua test F-04 mengandalkan akun `naufal` yang sudah memiliki kredensial, dan dua test watchlist melakukan request ticker yang belum dimock. Empat kegagalan ini menunjukkan ketergantungan lingkungan test; bukan empat regresi logika produksi baru. Saya tidak mengklaim telah mereproduksi angka 301 passed.
- Buffer closed candle, penggunaan true range, permintaan histori 120 bar, pembandingan pivot RSI yang selaras, dan lock stop/submit merupakan perubahan nyata. Namun perbaikan lokal tersebut belum memastikan kontrak perilaku tetap benar melalui tenant, database, restart, watchlist, dan siklus paralel.

## Temuan berprioritas tinggi

### R-01 / P1 — Worker restart kehilangan fixed-risk dan state pengendalian loss

**Lokasi:** `tenant_manager.py:121`, `tenant_manager.py:640`; pemulihan parsial pada `tenant_manager.py:280`.

Konstruktor `SessionState` pada `_execute_scheduled_cycle` dan `run_cycle_for_user` tidak memulihkan `risk_budget_per_trade`, daily PnL, streak, cooldown, processed income IDs atau executed symbols. Pemulihan beberapa field hanya dilakukan dalam `get_account_summary` ketika current session sudah ada. Artinya keselamatan trading bergantung pada dashboard dipanggil sebelum worker berjalan.

**Reproduksi:** state tersimpan dengan risk budget 2,5, daily loss -4, streak 3 dan satu ID processed dipulihkan worker menjadi `(None, 0.0, 0, [])`.

**Dampak:** order pertama setelah restart dapat kembali memakai sizing margin, sementara cooldown hilang. Ingestion mungkin menghitung ulang sebagian PnL, tetapi tidak menggantikan pemulihan yang benar; saat API error state tetap kosong, dan riwayat lintas hari bisa salah dihitung.

**Perbaikan:** satu fungsi hidrasi lengkap untuk semua jalur, dipanggil sebelum siklus pertama; persist ownership posisi/simbol dan day state; jangan jadikan pembacaan dashboard sebagai prosedur pemulihan. Test restart harus mengosongkan current_session dan menjalankan worker tanpa memanggil dashboard.

### R-02 / P1 — Fill yang tidak diketahui kembali difabrikasi di tenant dan database

**Lokasi:** `tenant_manager.py:762`, `tenant_manager.py:770`, `db.py:448`, `db.py:488`.

Orchestrator menghasilkan `SUBMITTED`, `avg_fill_price=None`, `PENDING_RECONCILIATION`, tetapi tenant menyimpan `status="FILLED"` dan `avg_fill_price=... or price`. Database mengulang fallback `avg_fill_price or price`. Status/provenance/slippage juga tidak diteruskan lengkap ke hasil humanized.

**Reproduksi integrasi:** exchange mock hanya mengembalikan order ID dan SUBMITTED. Melalui orchestrator → tenant → SQLite, hasil akhir menjadi `{'status': 'FILLED', 'avg_fill_price': 100.0}`.

**Dampak:** audit fill, slippage, risiko aktual dan PnL berikutnya dapat memakai harga quote sebagai transaksi nyata. Pernyataan Muse bahwa “tidak ada lagi fabrikasi fill” hanya benar pada sebagian jalur orchestrator.

**Perbaikan:** pertahankan nullable fill/status/provenance sampai storage dan API UI. Rekonsiliasi average fill serta filled quantity dari bursa. Hindari pula fallback `avgPrice or price` tanpa bukti bahwa price merupakan fill; price order dan average execution price mempunyai makna berbeda.

### R-03 / P1 — Revalidasi quote masih memakai harga lama saat depth gagal

**Lokasi:** `orchestrator.py:445`, `orchestrator.py:451`.

Jika depth baru gagal/invalid, direct entry memakai bid/ask dari candidate scanner dan memberi timestamp sekarang. Timestamp `T` dari depth yang berhasil juga tidak diuji umurnya sebelum submit.

**Dua reproduksi:** timeout depth tetap menghasilkan order; depth berumur satu jam dengan harga sama juga tetap menghasilkan order.

**Dampak:** kontrol harga sebelum eksekusi bisa dilewati tepat ketika API/data bermasalah. Timestamp baru pada data lama menyulitkan audit.

**Perbaikan:** data eksekusi yang unavailable, stale, crossed atau nonfinite harus memblokir order. Jangan mengganti timestamp asal. Terapkan umur quote maksimum dan ulangi validasi bila set_leverage atau antrian lock menunda submit terlalu lama.

### R-04 / P1 — Sinyal sesi lama bisa diadopsi sesi pengganti

**Lokasi:** `orchestrator.py:291`, `orchestrator.py:316`, `orchestrator.py:317`, `orchestrator.py:106`.

Direction sesi diambil sebelum AI, tetapi session ID dan generation token baru diambil setelah AI selesai. Jika sesi dihentikan lalu sesi baru dibuat saat AI bekerja, sinyal lama diberi identitas sesi baru. `start_session` juga belum memakai lock yang sama untuk penggantian state.

**Reproduksi:** mulai sesi SHORT; saat mock AI bekerja, stop sesi lalu buat sesi LONG; AI lama mengembalikan ENTER_SHORT. SHORT tetap dikirim ke sesi LONG yang baru.

**Perbaikan:** tangkap snapshot ID/generation/direction/budget sebelum evaluasi dan teruskan dari run_cycle sampai submit. Seluruh penggantian sesi harus disinkronkan. Tambahkan test stop+restart saat triage/deep evaluation dan start saat submit berlangsung.

### R-05 / P1 — Lock submit belum mencegah duplicate entry pada siklus paralel

**Lokasi:** `orchestrator.py:429`, `orchestrator.py:577`, `tenant_manager.py:625`, `api.py:295`.

Anti-reentry diperiksa sebelum critical section. Dua evaluasi dapat sama-sama melihat simbol belum dieksekusi, kemudian masuk lock dan submit bergantian. Lock menyerialkan pengiriman tetapi tidak mengulang pemeriksaan atau membuat reservasi simbol/kuota secara atomik. Scheduler memiliki reservasi sendiri; endpoint siklus manual belum melewati guard siklus yang sama.

**Reproduksi:** dua thread disinkronkan pada pemanggilan depth setelah pemeriksaan awal. Keduanya mengirim order simbol yang sama; jumlah place_order = 2.

**Perbaikan:** gunakan satu guard siklus untuk scheduler dan endpoint manual, ditambah reservasi simbol/risk/slot dalam critical section. Recheck occupied state dan kuota di sana; definisikan recovery status UNKNOWN bila submit timeout agar retry tidak menggandakan order.

### R-06 / P1 — Daily loss ingestion belum teratribusi dan tahan pergantian hari

**Lokasi:** `orchestrator.py:196`, `orchestrator.py:207`, `orchestrator.py:217`, `orchestrator.py:229`, `client.py:136`.

Empat reproduksi:

1. Income -4 bertimestamp kemarin, baru terambil hari ini, masuk sebagai daily PnL hari ini karena tanggal event tidak difilter setelah reset.
2. `executed_symbols=[]` membuat semua simbol diterima. Profit manual +10 pada simbol yang belum pernah ditradingkan bot dikreditkan ke daily PnL strategi. Setelah restart daftar ini juga kosong.
3. Reset hari dengan respons income kosong tidak dipersist karena early return mendahului `update_session_pnl_state`.
4. Error income API dicatat lalu diabaikan; `run_cycle` tetap melanjutkan scanning entry dengan state risiko yang tidak diketahui.

**Tambahan dari inspeksi:** attribution hanya berdasarkan simbol, bukan identitas posisi/order; startTime selalu awal sesi dengan limit 100 dan tidak ada pagination; hanya REALIZED_PNL yang dihitung sehingga daily PnL tersebut gross, tidak mencakup komisi/funding; exception persistence ditelan. Income ID memakai incomeId/tradeId/time, sementara bukti BingX lokal juga menyediakan tranId. Fallback timestamp saja tidak aman untuk dua event di milidetik yang sama. Kasus overflow pagination, collision ID, dan split-fill streak belum direproduksi dalam suite tambahan ini.

**Perbaikan:** ownership ledger yang persistent; tanggal berdasarkan timestamp event UTC; cursor/pagination dan dedup ID transaksi stabil; persist reset tanpa bergantung pada income baru; status UNKNOWN memblokir penambahan risiko sesuai kebijakan fail-closed. Nyatakan apakah loss budget memakai gross, net atau equity drawdown, lalu hitung konsisten.

### R-07 / P1 — Gate invalidasi dapat dilewati melalui watchlist

**Lokasi:** `ai_evaluator.py:721`, `orchestrator.py:660`, `orchestrator.py:801`, `watchlist_manager.py:68`.

ENTER yang memiliki invalidation risk tanpa rebuttal diturunkan menjadi WAIT. WAIT dengan confidence >=65 langsung masuk watchlist. Alasan invalidasi tidak disimpan sebagai kondisi yang harus diselesaikan; trigger berikutnya dapat submit berdasarkan reversal pattern tanpa memeriksa kembali risiko tersebut. Jalur trigger juga belum membangun ulang seluruh market features/hard gate; ATR berasal dari watchlist.

**Reproduksi:** AI memiliki risiko invalidasi eksplisit tanpa rebuttal → WAIT → kandidat tersimpan → trigger harga berikutnya → place_order terpanggil tanpa penilaian ulang invalidasi.

**Perbaikan:** bedakan WAIT karena timing dengan BLOCKED karena tesis invalid. Simpan kondisi invalidasi dan wajibkan re-evaluasi faktual sebelum unblock. Jalur watchlist harus melewati validator akhir yang sama seperti entry langsung. Ukuran “jumlah ENTER menjadi WAIT” tidak membuktikan order berbahaya benar-benar dicegah sampai siklus berikutnya diperiksa.

### R-08 / P1 — Flag EMA warmup invalid tidak memblokir hard gate

**Lokasi:** `market_features.py:703`, `market_features.py:723`.

EMA50 sekarang ditandai invalid bila histori kurang, tetapi hard_gate tidak membaca validitas EMA/timeframes. Meminta 120 bar tidak menjamin bursa memberikan 120 bar pada instrumen baru. Validitas umur candle juga tidak menjadi syarat hard gate.

**Reproduksi:** tiga candle tertutup per timeframe, funding/depth/OI segar, menghasilkan `ema_trend.valid=False` tetapi hard gate LONG lulus.

**Perbaikan:** untuk strategi yang membutuhkan EMA50, tegakkan histori minimum dan validitas fitur di eligibility validator. Missing/invalid feature harus menghasilkan alasan veto eksplisit. Jika strategi lain sengaja tidak membutuhkan EMA50, syarat itu harus dibedakan secara eksplisit; klaim warmup fail-closed universal saat ini tidak benar.

### R-09 / P1 — Fixed-risk dapat menaikkan leverage melampaui nilai yang dipilih

**Lokasi:** `sizing.py:615`.

Jika required margin terlalu besar, highest_safe_lev dihitung tanpa batas target_leverage. Kalkulator menaikkan leverage sampai cap kontrak/global.

**Reproduksi:** margin maksimal 5, target leverage 5x, entry 100, ATR 1,5 dan risk budget 2 menghasilkan order valid pada **20x**, dengan margin 4,445.

**Perbaikan:** perlakukan target yang diteruskan dari setting pengguna sebagai ceiling, atau bedakan target dengan izin maksimum secara eksplisit di kontrak API. Jika budget loss dan margin tidak dapat dipenuhi dalam batas tersebut, reject. Fee buffer juga belum dipakai dalam quantity sehingga label fixed risk perlu menjelaskan bahwa angka ini adalah risiko jarak stop sebelum biaya/slippage.

## Temuan tambahan

### R-10 / P2 — API menerima perubahan budget risiko tetapi membuang nilainya

**Lokasi:** `api.py:79`, `api.py:263`.

SessionUpdateRequest memiliki risk_budget_per_trade, tetapi endpoint tidak meneruskannya ke manager. Reproduksi request 0,5 menghasilkan success tanpa field tersebut pada call manager. Sambungkan validasi, state dan persistensi, atau tolak field yang belum didukung agar pengguna tidak mendapat konfirmasi palsu.

### R-11 / P2 — String null diperlakukan sebagai jawaban eksplisit “tidak ada risiko”

**Lokasi:** `ai_evaluator.py:56`.

Parser memperlakukan string `"null"`/`"none"` sebagai False, berbeda dari JSON null yang menjadi None. Reproduksi payload ENTER_SHORT dengan `invalidation_risk_present="null"` tetap menghasilkan ENTER_SHORT. Hapus alias placeholder tersebut dari jawaban no-risk; tambahkan test konsistensi null JSON dan string.

## Penilaian klaim dokumen

| Klaim | Penilaian setelah reproduksi |
|---|---|
| F-02 atomic stop/submit selesai | Perbaikan stop-only ada; pergantian sesi dan concurrent entry masih cacat |
| F-03 tidak ada fabrikasi fill | Tidak benar end-to-end; tenant/SQLite masih mengisi quote sebagai fill |
| F-04 fixed-risk universal dan rehidrasi selesai | Berlaku untuk start normal; worker restart belum memulihkan budget |
| F-06 ingestion teratribusi dan daily loss persisten | Belum benar pada ownership kosong, pergantian hari, respons kosong, dan API failure |
| F-01 warmup fail-closed | Flag invalid ada; gerbang entry belum menegakkannya |
| Gate invalidasi menyelamatkan ENTER | Mencegah immediate entry; watchlist dapat mengeksekusi kemudian tanpa reassessment |
| Semua P0/P1 selesai 100% dan tidak perlu rework | Ditolak berdasarkan reproduksi di atas |
| Live-money belum siap | Setuju, dengan alasan tambahan: defect implementasi masih terbuka |

Laporan Hermes sendiri juga menyebut F-07/F-08 PARTIAL dan F-10 IN PROGRESS. Ringkasan “100% selesai” perlu diselaraskan dengan matriks status tersebut. Exit ledger produksi yang belum tersambung dan presisi metadata kontrak tetap merupakan gap yang sudah diakui, bukan temuan baru saya.

Perbaikan playbook memperketat skor, tetapi BREAKDOWN_RETEST masih mengartikan ratio >=0,65 plus wick sebagai breakdown/retest tanpa urutan event support-break-retest. Ini keterbatasan definisi strategi yang perlu dicatat; belum ada reproduksi historical trade tambahan untuk menilai dampak PnL-nya.

Angka 9/11 order harus ditulis bersama cutoff. Saat review ini log sesi lama sudah berisi **17 submission ber-ID berbeda**, sembilan sebelum 00:53 UTC. Dua entry berikutnya adalah JEANPHIL 01:21 dan CYBERLEEK 02:02; masih ada entry sesudahnya. Ini tidak membuktikan angka 11 pada snapshot Muse salah. Label FILLED pada log lama juga tidak membuktikan fill bursa karena bug provenance lama.

## Bukti dan cara mengulang

- `reports/evidence/test_codex_remediation_regressions_2026_10_10.py`: 15 test perilaku yang diharapkan.
- `reports/evidence/codex-remediation-regressions-2026-10-10.txt`: output kegagalan lengkap.
- `reports/evidence/codex-remediation-baseline-2026-10-10.txt`: hasil suite yang sudah ada.
- `reports/evidence/codex_review_isolation.py`: transport blocker dan konfigurasi dummy.

Test review memiliki guard agar modul produksi yang diimpor harus berada di folder temp, karena db.py melakukan init_db saat import. Jangan menjalankannya langsung terhadap source produksi.

```bash
REVIEW_DIR=$(mktemp -d /tmp/bingx-review.XXXXXX)
git archive 42cc9110a18ac2341b9849f08bce73a21a66be05 | tar -x -C "$REVIEW_DIR"
cp reports/evidence/test_codex_remediation_regressions_2026_10_10.py "$REVIEW_DIR/test_codex_review_regressions.py"
cp reports/evidence/codex_review_isolation.py "$REVIEW_DIR/review_isolation.py"
cd "$REVIEW_DIR"
/home/naufal-ananta/bot/bingx-short-agent/.venv/bin/python -m pytest -q -p review_isolation test_codex_review_regressions.py --disable-warnings --tb=short
```

Pada commit tersebut, exit code 1 dan 15 failures merupakan hasil yang diharapkan dari reproduksi defect. Sesudah perbaikan, test harus dibuat lulus dengan memenuhi kontrak perilakunya, bukan menghapus assertion. Tambahkan kasus valid sebagai kontrol agar perbaikan tidak sekadar memblokir semua order.

## Urutan tindak lanjut

1. Benahi identity sesi, serialisasi/reservasi entry dan kewajiban quote segar.
2. Benahi hidrasi risiko serta attribution/day-boundary ingestion sebelum forward test dipakai menilai safety.
3. Pertahankan unknown fill sampai database dan sambungkan lifecycle reconciliation.
4. Tutup jalur watchlist yang melewati invalidasi, tegakkan validitas fitur, lalu hormati setting leverage/risk API.
5. Ulangi test integrasi melalui API/tenant/DB dan worker restart. Lanjutkan forward demo dengan baseline dibekukan serta telemetry yang benar setelah defect prioritas tinggi ditutup.

Review ini tidak menyimpulkan defect baru menyebabkan empat SL historis atau menjamin perbaikannya meningkatkan profit. Temuan membuktikan kontrol dan pencatatan belum konsisten pada jalur yang dapat dijalankan; pembuktian expectancy memerlukan evaluasi terpisah setelah baseline teknis diperbaiki.
