# Analisis profitabilitas — 10 Oktober 2026

Analisis read-only terhadap review Muse, laporan rerun, audit.jsonl, database lokal, dan kode saat pemeriksaan. Tidak menjalankan bot, mengakses kredensial, mengambil ledger bursa terbaru, atau mengubah strategi. Angka PnL di bawah berasal dari laporan; yang diverifikasi ulang secara lokal adalah event order, implementasi, dan contoh perilaku fungsi.

## Kesimpulan

Prioritas utama adalah kualitas data, validasi pola, harga saat eksekusi, dan sizing berbasis kerugian. Timeout serta RR minimum adalah kontrol teknis; keduanya belum membuktikan bahwa sinyal memiliki expectancy positif. Klaim laporan bahwa infrastruktur 100% bebas cacat teknis terlalu kuat.

## Batas data finansial

- Snapshot review: 9 entry, 4 posisi tertutup rugi, 5 masih terbuka. Gross realized -10,6424 VST, komisi -0,5439, funding +0,0881, net realized -11,0981.
- Gross loss jauh lebih besar daripada komisi. Fokus utama bukan sekadar fee drag.
- Dua LONG tertutup: JEANPHIL -2,58 dan DARKSWAP -4,24, sekitar 64% gross loss dari empat close. Sampel dua trade tidak cukup untuk menyimpulkan LONG selalu buruk.
- Winrate 0% hanya berlaku untuk empat close pada snapshot. Posisi yang belum mencapai TP masih tersensor; jangan menyamakan ini dengan winrate final sembilan trade.
- Audit lokal sesi yang sama berlanjut hingga 01:29:37 UTC: 123 triage, 30 fallback, 232 deep evaluation, 10 order. Order tambahan JEANPHIL LONG pada 01:21:24 UTC. Database masih ACTIVE_SEARCHING dengan stopped_at kosong; status lokal tidak membuktikan proses bot saat ini masih hidup.
- Hitungan 109 triage pada review belum dapat direproduksi dari log lokal untuk cutoff sekitar 00:52 UTC: sebelum 00:53 tercatat 106. Batas snapshot atau kelengkapan artefak perlu direkonsiliasi.
- Review menyebut JEANPHIL stop 19 detik, laporan rerun 34 detik. Tidak tersedia bukti fill/close terbaru yang diperiksa untuk memutuskan mana yang benar.

## Temuan kode dan prioritas

### P0 — Candle berjalan bisa dipakai sebagai candle tertutup

market_features.py:_closed_rows hanya memeriksa time < now_ms, tanpa interval atau closeTime. Contoh lokal: candle yang baru mulai satu detik sebelumnya diterima. Jika timestamp adalah waktu pembukaan, candle 15m/1h yang sedang berjalan dianggap selesai. watchlist_manager.py juga memakai klines_15m[-1] langsung tanpa validasi penutupan atau pengurutan di jalur itu.

Volume candle berjalan yang baru terbentuk dapat terlihat sangat rendah dibanding candle penuh, lalu ditafsirkan sebagai volume fade. Wick dan RSI juga bisa berubah sebelum close. Log entry GENIUS/GENSYN memang menyebut volume dry-up; kontribusi candle parsial terhadap trade tertentu masih hipotesis karena snapshot OHLCV lengkap tidak tersimpan dalam event AI.

Perbaikan: normalisasi format dan urutan candle; pastikan open_time + interval <= server_now dengan buffer, atau gunakan closeTime yang tervalidasi. Gunakan candle tertutup untuk konfirmasi; data intrabar boleh menjadi fitur terpisah dengan makna eksplisit. Tambahkan validasi umur candle dan jumlah histori minimum.

### P0 — Harga dan hard gate tidak disegarkan sebelum order langsung

orchestrator.py:_evaluate_and_execute_candidate memakai cand.last_price dari scanner untuk quantity dan TP/SL setelah triage serta deep evaluation. Hard gate dipanggil lagi tetapi terhadap objek fitur lama. Flag fresh merupakan hasil perhitungan sebelumnya, bukan pemeriksaan umur data saat order.

Untuk GENIUS, durasi triage sekitar 60 detik lalu order muncul 46,8 detik setelah triage selesai; untuk ADA sekitar 60 + 23,2 detik. Ini bagian dari waktu tunggu, bukan pengukuran lengkap umur quote. Harga scanner diambil sebelum tahapan tersebut.

Perbaikan: ambil ulang bid/ask, depth, mark price dan fitur relevan; tolak jika setup sudah invalid atau drift terlalu besar; hitung ulang quantity dan RR terhadap harga executable. Simpan timestamp quote, harga permintaan, actual average fill, fee, dan slippage. Pertimbangkan limit IOC dengan batas harga setelah mengecek dukungan API; ada tradeoff fill yang tidak lengkap atau terlewat.

ORDER_SUBMISSION saat ini menulis price=cand.last_price dan status FILLED setelah respons order, tanpa merekonsiliasi actual avgPrice/status. Itu bukan bukti harga fill aktual. Jangan mengklaim RR pasca-fill dari angka ini saja.

### P1 — Nama playbook tidak menjamin pola wajib

Tiga reproduksi lokal:

| Input minimal | Hasil |
|---|---|
| Uptrend + perubahan 24h 1%, tanpa golden pullback/rebound | SUPPORT_PULLBACK, skor 50 |
| Peak Fibonacci + RSI 70, tanpa rejection/breakdown | PUMP_EXHAUSTION, skor 50 |
| Downtrend + retracement 0,7, tanpa retest/rejection | BREAKDOWN_RETEST, skor 55 |

Skor aditif adalah ranking, bukan probabilitas keberhasilan. UNKNOWN/missing fitur juga dapat menambah poin "struktur support belum rusak". Oversold reversal menganggap price >= swing_low atau %B >= 0,05 sebagai support reclaim; itu tidak membuktikan proses breakdown lalu reclaim.

Perbaikan: syarat wajib setiap strategi terlebih dahulu, baru skor tambahan. SHORT exhaustion memerlukan rejection/struktur gagal melanjutkan kenaikan; pullback LONG memerlukan tren, area support nyata, dan konfirmasi rebound; retest memerlukan breakdown lalu retest gagal secara kronologis. Missing data harus membatalkan syarat terkait.

### P1 — Indikator tidak sepenuhnya sesuai namanya

- ATR = mean(high-low), bukan true range yang memperhitungkan previous close. Ini memengaruhi filter friction dan stop.
- Pengambilan 30 candle untuk EMA50 memicu fallback mean(closes), sehingga EMA50 aktual tidak dihitung.
- Divergence membandingkan ekstrem harga dan RSI secara terpisah, bukan pasangan pivot harga/RSI yang selaras.
- Level Fibonacci, Bollinger dan EMA dibulatkan enam desimal untuk semua harga. Pada harga MUSEBOOK 0,00002148, setengah langkah pembulatan 0,0000005 sekitar 2,33% harga. Ini dapat merusak interpretasi level micro-price, walaupun logika boolean tertentu dihitung sebelum pembulatan.

Perbaikan: rumus indikator yang konsisten, histori warmup memadai, pivot bertimestamp, dan presisi berdasarkan kontrak. Bandingkan hasil terhadap implementasi referensi sebelum menguji perubahan strategi.

### P1 — Margin tetap bukan risiko tetap; clamp stop bisa memotong invalidasi

Notional ditentukan margin × leverage. Risk per trade kemudian mengikuti jarak SL. Dengan margin 5 VST, notional 100 dan SL 1,93% menghasilkan risiko sekitar 1,93; notional 60 dan SL 6% menghasilkan 3,60, sebelum biaya/slippage. Leverage adaptif dibatasi dari toleransi 75% margin, bukan target loss tetap.

JEANPHIL memiliki peringatan AI ATR 1h >13%, tetapi stop diclamp maksimum 6%. Leverage turun membantu mengurangi notional; tidak membuat stop 6% selaras dengan volatilitas atau invalidasi struktur. DARKSWAP loss laporan -4,24 juga melebihi perkiraan loss stop dari quote sekitar 3,60; perlu data fill/mark trigger/close untuk menjelaskan selisih.

Perbaikan: tentukan invalidation stop dari struktur + volatilitas, lalu quantity = risk_budget / abs(entry-stop), dengan buffer biaya/slippage dan batas margin/notional. Jika stop yang wajar tidak cocok dengan batas risiko atau target yang realistis, SKIP. Budget portofolio harus mempertimbangkan posisi legacy dan konsentrasi arah/korelasi, bukan hanya kuota simbol.

## Mengapa RR >=2 belum cukup

Untuk payoff ideal +2R/-1R dan biaya nol, expectancy positif memerlukan winrate >33,3%; +2,5R/-1R memerlukan >28,6%. Dengan biaya c dalam unit R per trade, expectancy p*b - (1-p) - c, sehingga p > (1+c)/(b+1). Gunakan realized average win/loss, bukan hanya jarak TP/SL rencana.

TP kode dihitung sebagai jarak SL × RR. Harga tidak harus mencapai TP yang dibuat rumus. Contoh DARKSWAP: AI menyebut resistance sekitar 0,005564 sedangkan TP rencana 0,006157. Ini menunjukkan resistance dekat belum dipakai sebagai batas target; tidak membuktikan TP mustahil. Pastikan ruang ke resistance/support berikutnya cukup sebelum entry, alih-alih memperbesar TP demi memenuhi RR.

## Eksperimen demo berikutnya

1. Perbaiki data candle, indikator, telemetry fill/close, dan revalidation eksekusi sebagai baseline baru. Bekukan versi kode, konfigurasi dan model gateway.
2. Pisahkan hasil berdasarkan playbook, LONG/SHORT, direct/watchlist, fallback/success, volatilitas, likuiditas dan market regime. Jangan mematikan LONG permanen berdasarkan dua loss.
3. Bandingkan baseline deterministik tanpa LLM dengan pipeline LLM pada opportunity set yang sama, menggunakan shadow decisions atau replay. Confidence 74 bukan probabilitas 74% sebelum dikalibrasi terhadap outcome.
4. Uji konfirmasi struktur wajib, lalu sizing fixed-risk sebagai perubahan terpisah. Risk sizing membatasi kerugian dan membuat perbandingan adil; tidak menciptakan edge dengan sendirinya.
5. Catat net expectancy dalam R, profit factor, max drawdown, MAE/MFE, holding time, biaya dan slippage. MAE/MFE membantu menentukan apakah stop terlalu sempit atau entry memang salah; jangan langsung menambah trailing/partial TP tanpa bukti jalur harga.
6. Kumpulkan beberapa ratus closed trades sebagai sasaran awal praktis, melintasi kondisi pasar dan window di luar periode tuning. Tidak ada jumlah sampel universal yang menjamin signifikan; periksa ketidakpastian, korelasi trade dan multiple testing.
7. Ukur funding, fee serta biaya model/gateway yang benar-benar dibayar. PnL VST saja belum memasukkan biaya operasional AI.

Timeout 75 detik adalah eksperimen operasional terpisah. Kode yang dibaca masih read timeout 60 detik. Perubahan timeout harus disertai data expiry/revalidation agar fallback berkurang tanpa mengeksekusi sinyal yang sudah basi.

## Referensi eksternal

- BingX menjelaskan TP/SL berbasis market tidak menjamin harga fill: https://bingx.com/en-sa/support/articles/26392412034713/
- Referensi pasar resmi BingX API mencantumkan openTime/closeTime kline: https://github.com/BingX-API/api-ai-skills/blob/main/skills/swap-market/SKILL.md
- Bailey dkk., The Probability of Backtest Overfitting, untuk pemisahan tuning dan evaluasi: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf

## Tambahan pemeriksaan setelah pertanyaan tentang kelengkapan audit

Audit awal cukup untuk menetapkan prioritas perbaikan, tetapi belum merupakan pembuktian akar penyebab setiap kerugian atau pembuktian profitabilitas. Pemeriksaan lanjutan menemukan celah berikut. Reproduksi memakai mock API dan mematikan penulisan audit log; tidak ada order bursa yang dikirim.

### P0 — Kegagalan membaca exposure dianggap akun kosong

scanner.py:get_occupied_symbols menangkap exception dari get_positions dan get_open_orders lalu melanjutkan. Reproduksi kedua API melempar timeout menghasilkan set() kosong. Jika hanya satu API gagal, hasil juga dapat tidak lengkap. run_cycle memiliki fallback occupied=set() untuk exception di lapisan luar.

Dampak potensial: posisi aktif tidak diketahui, simbol yang sama dipilih kembali, atau kuota dihitung terlalu rendah. Background worker memang mengambil positions lebih awal dan berhenti bila panggilan awal itu gagal, tetapi pembacaan sukses sebelumnya tidak menjamin pembacaan berikutnya sukses; jalur manual juga harus terlindungi.

Perbaikan: bedakan state EMPTY yang valid dari UNKNOWN akibat error. UNKNOWN memblokir entry baru, lalu retry/reconcile. Semua pintu order harus memakai snapshot exposure yang lengkap dan cukup baru. Belum ada bukti error ini terjadi pada sesi rugi yang direview.

### P0 — Order bisa diteruskan setelah sesi dihentikan saat AI bekerja

Status sesi diperiksa di awal run_cycle, tetapi can_execute pada _evaluate_and_execute_candidate tidak memeriksa ulang status atau identitas sesi setelah evaluasi AI. Reproduksi lokal mengubah status menjadi TERMINATED di dalam mock evaluasi AI lalu mengembalikan ENTER_SHORT valid; mock place_order tetap dipanggil.

Perbaikan: cancellation/generation token per sesi, pemeriksaan identitas serta status sesaat sebelum submit, dan sinkronisasi stop dengan bagian submit yang kritis. Periksa juga tumpang tindih pemindaian manual dengan scheduler: reservasi _currently_scanning ada pada scheduler, tetapi run_cycle_for_user sendiri belum memakai penguncian yang sama. Reproduksi race manual/scheduler belum dilakukan.

Tidak ditemukan bukti bahwa race stop terjadi pada sesi yang direview. Tujuan perbaikan adalah memastikan kontrol berhenti menambah risiko bekerja konsisten.

### P0 — Jalur watchlist tidak melewati seluruh validasi entry terkini

Jalur trigger watchlist di orchestrator.py mengambil candle/depth dan memeriksa reversal serta sizing, tetapi tidak membangun ulang fitur penuh atau menjalankan _evaluate_hard_gate seperti jalur direct entry. ATR dan leverage diambil dari entry watchlist yang TTL-nya sampai 30 menit. Ambang spread watchlist 0,40%, sedangkan konfigurasi umum 0,35%. Depth kosong bahkan memiliki fallback ke initial_price, sehingga spread dapat terlihat nol.

Perbaikan: satu fungsi validasi akhir yang wajib dilalui direct entry, fallback AI, dan watchlist. Meliputi kelengkapan/freshness data, arah sesi, status sesi, exposure, spread, volatilitas, drift harga, sizing, serta risiko portofolio. Pertahankan konteks playbook dan target RR saat watchlist memicu; jalur saat ini mengisi playbook=None dan target_rr=2.0.

Sesi yang diperiksa tidak mencatat WATCHLIST_TRIGGER, jadi celah ini bukan penjelasan langsung untuk sembilan order pada snapshot.

### P1 — Kuota posisi belum menjadi batas kerugian portofolio

Kuota membatasi jumlah simbol occupied pada satu waktu. Posisi yang tutup dapat membuka slot baru sehingga total entry dan akumulasi loss tetap bertambah. Pada jalur trading yang diperiksa belum terdapat batas loss harian, batas total risiko stop, exposure berkorelasi, atau cooldown berbasis hasil trade. executed_symbols dicatat, tetapi tidak dipakai sebagai gerbang permanen anti-entry ulang di orchestrator yang dibaca; jangan menganggap narasi deduplikasi dalam laporan sebagai jaminan kode.

Perbaikan: definisikan modal strategi yang benar-benar dialokasikan, batas total risk-at-stop, batas konsentrasi arah/kelompok pasar, dan penghentian entry ketika loss budget habis. Hitung posisi legacy juga. Nilai batas ditentukan dari toleransi risiko dan pengujian; kontrol ini membatasi drawdown, bukan membuktikan edge.

### P1 — Outcome dan attribution belum cukup lengkap untuk pembelajaran

order_records mencatat entry, tetapi skema yang diperiksa tidak menyimpan close fill, exit reason, fee/funding per posisi, atau realized R. tenant_manager.py juga merekam leverage dari setting sesi, bukan effective_leverage hasil sizing. Karena itu order leverage adaptif 12x dapat tercatat sebagai leverage sesi 20x.

Perbaikan: ledger trade lifecycle berdasarkan order/position identity, actual fills, effective leverage, biaya, waktu keluar dan alasan keluar. Filter income hanya berdasarkan timestamp tidak cukup bila posisi legacy masih terbuka atau simbol ditradingkan ulang. Buat snapshot equity awal/akhir dan pisahkan contribution sesi dari akun keseluruhan.

### P2 — Hipotesis tambahan yang perlu eksperimen, bukan langsung dijadikan aturan

- Regime pasar: pipeline belum memasukkan benchmark BTC/ETH sebagai konteks lintas aset. Uji apakah exhaustion SHORT hanya bekerja pada kondisi tertentu; jangan menyimpulkan overbought otomatis berarti waktunya short.
- Likuiditas: minimum volume default 50.000 USDT/hari dan spread sesaat belum mengukur kapasitas eksekusi. Uji depth dalam rentang harga, impact untuk ukuran order, umur listing, serta kestabilan spread.
- Konsistensi arah: mode LONG menolak perubahan 24h di atas 40%, sedangkan BOTH menerima kandidat hingga 500% untuk discovery. Kandidat dari pool SHORT dapat kemudian mendapat keputusan LONG jika hard gate mengizinkan. Bila batas +40% dimaksudkan sebagai batas risiko LONG universal, tegakkan pada arah final; saat ini batas tersebut adalah aturan discovery yang berbeda per mode.
- Exit: TP/SL statis belum menjawab apakah trade yang lama tidak bergerak sebaiknya ditutup atau apakah profit sempat besar sebelum kembali rugi. Uji time exit, structure exit, trailing atau partial TP hanya setelah tersedia MAE/MFE dan outcome path; penambahan aturan dapat memperburuk expectancy.
- Demo ke live: fill, depth dan slippage demo belum membuktikan kualitas eksekusi live. Gunakan stress test biaya/impact dan shadow observation data publik sebelum menarik kesimpulan transferabilitas.

Kelengkapan berikutnya membutuhkan replay dengan snapshot data saat keputusan, rekonsiliasi fill/close bursa, dan eksperimen di luar periode tuning. Semua defect yang sudah direproduksi dapat diprioritaskan sekarang; manfaat perubahan strategi terhadap net PnL tetap harus diukur.
