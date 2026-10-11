# Review kesiapan forward test VST — 11 Oktober 2026

**Verdict: REQUEST CHANGES; belum saya rekomendasikan memulai sesi forward demo utama/panjang pada revisi ini.**

Commit: `d909385150183b90fb4243a028ec4addc9cded9f`.

Perbaikan Hermes terhadap kasus review sebelumnya sudah masuk: **15/15 test regresi lama lulus tanpa perubahan pada test review tersebut**. Namun empat kelompok cacat masih terbukti pada varian kondisi operasional yang belum tercakup. Kriteria review adalah konsistensi pencatatan, pengendalian entry, dan pengendalian loss untuk sesi demo; bukan pembuktian profitabilitas atau persetujuan live money.

## Metode dan hasil

- Kode disalin ke `/tmp/bingx-review-20261011-6psiuori`; database/log terpisah. Transport HTTP eksternal diblokir dan API bursa memakai mock. Tidak menjalankan daemon atau memanggil akun bursa.
- Source Python produksi dibandingkan dengan salinan setelah pengujian: identik.
- Regresi sebelumnya: **15 passed**.
- Pemeriksaan lanjutan: **8 failed, 2 passed**. Dua kontrol positif membuktikan order dengan quote valid tetap bisa disubmit dan income milik strategi pada hari ini dihitung dengan benar sambil mengabaikan income kemarin.
- Suite yang sudah ada, tanpa `test_live_vst.py`: **293 passed, 4 failed**. Empat kegagalan masih sama seperti review sebelumnya: dua test F-04 memerlukan kredensial pada akun lokal `naufal`, dua test watchlist mencoba ticker HTTP yang belum dimock. Ini keterbatasan isolasi/fixture suite, bukan empat defect produksi tambahan.

## 1. P1 — Kepemilikan posisi hilang saat restart database nyata

**Lokasi:** `tenant_manager.py:142`, `tenant_manager.py:171`, `orchestrator.py:246`, skema/persistensi `db.py`.

Helper hidrasi baru memulihkan risk budget, PnL, streak dan processed IDs. Akan tetapi ia membaca `executed_symbols` dari record sesi, sedangkan database tidak memiliki kolom/persistensi field tersebut dan helper tidak membangun ulang ownership dari `order_records`. Setelah restart daftar menjadi kosong. Ingestion baru sekarang mengabaikan setiap income yang simbolnya tidak ada di daftar itu.

**Reproduksi:** simpan sesi serta order `TEST-USDT` ke SQLite; buat orchestrator baru; hidrasi dari row database asli; bursa mock mengembalikan realized loss -4 untuk posisi yang sama. `reconcile_outcomes()` mengembalikan sukses, tetapi `executed_symbols=[]` dan `daily_realized_pnl=0.0`. Risk budget 2 berhasil dipulihkan; ownership yang gagal.

**Dampak:** posisi yang ditutup setelah restart dapat tidak masuk daily loss/cooldown, dan anti-reentry terhadap simbol lama hilang. Test hidrasi dengan dictionary buatan tidak cukup membuktikan persistensi nyata.

**Perbaikan yang diperlukan:** persist ownership order/posisi atau rekonstruksi dari ledger sebelum entry diizinkan. Gunakan identitas order/posisi untuk attribution; daftar simbol saja tetap tidak membedakan transaksi manual pada simbol yang sama. Tambahkan round-trip test start → order tercatat → process restart → posisi close → daily loss terhitung tepat sekali.

## 2. P1 — Invalidasi watchlist masih bisa dilewati pada UNKNOWN dan pembaruan entry

**Lokasi:** `orchestrator.py:751`, `orchestrator.py:873`, `watchlist_manager.py:95`.

Varian pertama: jawaban invalidasi `None` menghasilkan WAIT, tetapi saat disimpan ke watchlist diubah menjadi `bool(None) == False`. `gate_downgrade_reason` disimpan tetapi trigger hanya memeriksa boolean risk-present. Trigger selanjutnya dapat mengirim order.

Varian kedua: kandidat sudah berada di watchlist sebelum evaluasi baru menemukan invalidasi. Cabang `UPDATED_EXISTING` memperbarui score/harga/ATR, tetapi tidak memperbarui risk flag, detail, atau downgrade reason. Entry lama tetap terlihat tidak diblokir.

**Reproduksi:** kedua jalur menghasilkan satu pemanggilan place_order walaupun evaluasi terakhir WAIT akibat invalidasi yang belum diselesaikan.

**Perbaikan yang diperlukan:** simpan tri-state/entry eligibility secara utuh; UNKNOWN tetap blocked. Pembaruan entry harus memperbarui alasan blokir serta konteks arah/playbook yang relevan. Hanya evaluasi baru yang benar-benar menyelesaikan alasan invalidasi boleh mengaktifkan entry kembali. Pertahankan kontrol positif untuk WAIT yang semata-mata menunggu konfirmasi harga.

## 3. P1 — Pergantian sesi saat triage masih meneruskan kandidat siklus lama

**Lokasi:** `orchestrator.py:771` (identitas siklus), `orchestrator.py:313` (snapshot per kandidat), pemanggilan `_evaluate_and_execute_candidate` setelah `evaluate_batch_triage`.

Perubahan terbaru memperbaiki pergantian sesi saat deep evaluation. Tetapi snapshot per kandidat diambil setelah triage, dan identitas/generation awal run_cycle tidak diteruskan sebagai kontrak wajib untuk direct candidates.

**Reproduksi:** sesi A memulai scanning dan triage; di tengah triage sesi A dihentikan, sesi B dibuat; hasil triage lama kembali sebagai fallback. Kandidat dari siklus A mendapat snapshot sesi B pada tahap deep evaluation, lalu place_order tetap dipanggil.

**Dampak:** siklus lama tidak sepenuhnya dibatalkan oleh pergantian sesi. Ini juga menyulitkan attribution karena log keputusan dapat memakai identitas sesi pengganti.

**Perbaikan yang diperlukan:** buat satu execution context immutable pada awal run_cycle, berisi ID/generation, direction, mode dan budget. Teruskan sampai submit serta periksa setelah operasi yang memblokir. Jangan mengganti konteks lama dengan current_session baru. Test stop-only, stop+restart saat triage, dan stop+restart saat deep evaluation harus sama-sama lolos.

## 4. P1 — Validasi umur quote belum konsisten dan memiliki pengecualian fixture di produksi

**Lokasi:** `orchestrator.py:498`, `orchestrator.py:918`, critical section submit setelah set_leverage.

Empat kasus gagal:

1. Direct execution menerima timestamp `1700000000000` karena pengecualian `is_fixture_ts`.
2. Direct execution menerima timestamp `1`, juga karena pengecualian untuk angka di bawah `100_000_000_000`.
3. Watchlist menerima depth berumur satu jam; timestamp disimpan tetapi umurnya tidak divalidasi.
4. Quote berumur 55 detik lolos pemeriksaan awal. Simulasi preflight leverage menambah waktu 10 detik. Order tetap disubmit saat umur quote 65 detik, melewati batas 60 detik yang diterapkan kode.

**Dampak:** kelulusan test dengan fixture tertentu belum berarti syarat freshness berlaku di jalur EXCHANGE_DEMO. Pengecualian angka khusus juga melemahkan penolakan timestamp salah satuan/invalid.

**Perbaikan yang diperlukan:** hapus pengecualian fixture dari kode runtime; mock waktu/quote di test. Satukan validasi untuk direct dan watchlist, termasuk missing/invalid timestamp sesuai kontrak data, harga finite, spread, dan freshness. Periksa ulang umur quote tepat sebelum submit; ambil ulang/re-size atau tolak bila sudah kedaluwarsa.

## Perubahan yang sudah terverifikasi pada kasus sebelumnya

- Fill unknown tetap nullable melalui tenant dan SQLite pada kasus respons tanpa avgPrice.
- Fixed-risk dan state PnL dipulihkan oleh worker untuk field yang memang ada di record sesi.
- Batas leverage pilihan pengguna tidak lagi dinaikkan menjadi 20x pada kasus review.
- Update risk budget diteruskan dari endpoint ke manager.
- String `null` pada parser tidak lagi dianggap jawaban no-risk.
- Duplikasi simbol dalam dua evaluasi paralel yang direproduksi sebelumnya berhasil diblokir di critical section.
- Income API error menghentikan scanning; income kemarin tidak dihitung sebagai loss hari ini; day reset kosong dipersist.
- EMA warmup dengan flag invalid sekarang memblokir hard gate.

Kelulusan ini spesifik pada kasus uji. Ia belum menutup varian pada empat temuan di atas.

## Catatan di luar empat kelompok reproduksi

Ada cabang fixture tambahan pada `client.get_income` yang mengembalikan list kosong berdasarkan literal API key dummy/kosong. Sebaiknya fixture dipindahkan ke test, dan konfigurasi runtime yang tidak valid gagal secara eksplisit. Jalur income juga masih menerima timestamp sangat kecil sebagai tanggal hari ini.

Pagination income, biaya/funding dalam definisi daily loss, ownership berbasis order, dan lifecycle exit/fill reconciliation tetap perlu diselesaikan sesuai catatan review sebelumnya. Review kali ini tidak menguji ulang seluruh gap lama atau menambahkan klaim bahwa empat kelompok di atas adalah seluruh cacat yang mungkin ada.

## Bukti dan cara mengulang

- `reports/evidence/codex-review-2026-10-11-regresi-lama.txt`
- `reports/evidence/codex-review-2026-10-11-regresi-lanjutan.txt`
- `reports/evidence/codex-review-2026-10-11-baseline.txt`
- `reports/evidence/test_codex_followup_review_2026_10_11.py`

Jalankan pada snapshot temp agar import db.py tidak menyentuh database proyek:

```bash
REVIEW_DIR=$(mktemp -d /tmp/bingx-review.XXXXXX)
git archive d909385150183b90fb4243a028ec4addc9cded9f | tar -x -C "$REVIEW_DIR"
cp reports/evidence/test_codex_remediation_regressions_2026_10_10.py "$REVIEW_DIR/test_codex_review_regressions.py"
cp reports/evidence/test_codex_followup_review_2026_10_11.py "$REVIEW_DIR/test_codex_followup_review.py"
cp reports/evidence/codex_review_isolation.py "$REVIEW_DIR/review_isolation.py"
cd "$REVIEW_DIR"
/home/naufal-ananta/bot/bingx-short-agent/.venv/bin/python -m pytest -q -p review_isolation test_codex_review_regressions.py test_codex_followup_review.py --disable-warnings --tb=short
```

## Syarat penutupan sebelum sesi demo utama

Empat kelompok di atas perlu diperbaiki dan seluruh 25 kasus review (15 lama + 10 lanjutan, termasuk dua kontrol positif) harus lulus. Ini kriteria minimum berdasarkan temuan yang sudah direproduksi, bukan jaminan bebas bug. Setelah baseline teknis memenuhi kontrak tersebut, sesi VST dapat digunakan untuk observasi perilaku dan hasil strategi dengan batas risiko yang dapat diaudit. Saat ini hasil demo bisa tercemar oleh loss yang tidak terhitung dan entry yang seharusnya diblokir.

Tidak ada kode produksi atau setting akun yang diubah dalam review ini; hanya artefak laporan dan bukti pengujian ditambahkan.
