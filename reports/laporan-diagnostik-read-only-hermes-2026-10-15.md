# Laporan Diagnostik Read-Only Lead Reviewer & First-Pass Reviewer

- **Tanggal**: 15 Oktober 2026
- **Dari**: Agent Hermes (Executor)
- **Kepada**: Agent Muse (First-Pass Reviewer / Planner), Agent Gemini 4 Argon (Lead Reviewer), Naufal Ananta (Decision Maker)
- **Dasar Instruksi**:
  1. `instruksi_revisi_hermes_d89a672_2026_10_14 (3).md` (Bagian 2 — Perintah Kerja Presisi untuk Hermes)
  2. Arahan tambahan Agent Muse (Daftar distinct event types sebelum penghitungan, rincian Triase Tier-1, penanganan error verbatim)
- **Sesi Target**: `bx_sess_1791926045_8981c2` (User 3 / `naufal`)
- **Status Sesi**: DIJEDA (`auto_scan = 0`, status `TERMINATED` di DB, service `bingx-agent.service` active melayani API)
- **Kepatuhan Protokol**: 100% Read-Only (0 mutasi kode, 0 kueri SQL mutasi, 0 endpoint bursa mutasi, tidak menyalakan auto-scan)

---

## 1. Ringkasan Eksekutif Hasil Diagnostik

1. **Hipotesis Utama Lead Reviewer Gemini 4 Argon TERBUKTI 100% VALID**:
   - Kuota 2 slot **TIDAK PERNAH JEBOL** di bursa BingX VST. Di bursa, tidak pernah ada lebih dari 2 posisi terbuka sekaligus.
   - Dari 5 trade sesi ini: **4 trade SUDAH TERTUTUP di bursa** (`CNPY`, `CITREA`, `STANDARD`, `ZEREBRO`), dan **hanya 1 trade yang MASIH TERBUKA di bursa** (`KMNO-USDT` SHORT, saat ini mengantongi *unrealized profit* **+4,32 VST / +2,16 R**).
   - Angka `sessions.filled_count = 1` di database adalah akurat secara semantik kode saat ini (mencerminkan jumlah posisi bursa yang aktif = 1), bukan counter kumulatif.
2. **Penyebab Tertahannya Status 3 Trade di Database Lokal Terkonfirmasi**:
   - Kolom `sessions.executed_symbols` di SQLite terkunci pada `'["CNPY-USDT"]'`.
   - Pada setiap siklus, `_hydrate_session_state()` menimpa memori RAM dengan nilai database lama tersebut (`["CNPY-USDT"]`), sehingga ketika event `REALIZED_PNL` untuk `CITREA`, `STANDARD`, dan `ZEREBRO` ditarik oleh `reconcile_outcomes()`, fungsi tersebut melakukan `continue` karena simbol-simbol tersebut tidak terdaftar di `executed_symbols`.
3. **Mekanika TP/SL Bekerja Sempurna (0 Silent Drop, 5/5 Terkonfirmasi)**:
   - `CITREA-USDT` tertutup secara otomatis oleh order **`TAKE_PROFIT_MARKET`** resting bursa menghasilkan **+5,19 VST (+2,60 R)**.
   - `STANDARD-USDT` tertutup oleh order **`STOP_MARKET`** resting bursa (**-2,33 VST / -1,19 R**).
   - `ZEREBRO-USDT` tertutup oleh order **`STOP_MARKET`** resting bursa (**-2,20 VST / -1,11 R**).
   - `KMNO-USDT` (masih terbuka) saat ini memiliki order `STOP_MARKET` (`0.04071`) dan `TAKE_PROFIT_MARKET` (`0.03622`) yang **RESTING AKTIF di server BingX**.
   - Audit log mencatat tepat **5 event `TPSL_VERIFIED`** dan **0 event `TPSL_SILENT_DROP_DETECTED`** maupun `ORDER_ERROR`.
4. **Kinerja Finansial Riil Sesi N=30 Sejauh Ini (5 Trade)**:
   - **4 Trade Closed**: 1 Win (`CITREA` +2,60 R), 3 Loss (`CNPY` -1,06 R, `STANDARD` -1,19 R, `ZEREBRO` -1,11 R). Total Realized Net PnL = **-1,42 VST (-0,76 R)**.
   - **1 Trade Open**: `KMNO-USDT` mengambang **+4,32 VST (+2,16 R)**. Jika KMNO menyentuh TP, total kumulatif menjadi **+3,65 VST (+1,77 R)**.

---

## 2. Tabel Rekonsiliasi Fakta 5 Trade (Ground-Truth Bursa vs DB)

| # | Simbol | Status DB Lokal | Status Riil Bursa | Entry Price | Exit Price | Trigger / Alasan Exit | Gross PnL (VST) | Total Fees & Funding (VST) | Net Realized PnL (VST) | Realized R | Keterangan / Status Resting TP/SL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **CNPY-USDT** | `CLOSED` | **SUDAH TERTUTUP** | 0.3093 | 0.3223 | `STOP_LOSS` (`STOP_MARKET`) | -2.0635 | Fee: -0.0501<br>Fund: 0.0000 | **-2.0891** | **-1.0614 R** | Terekonsiliasi di DB. |
| 2 | **KMNO-USDT** | `FILLED` (`exit_time IS NULL`) | **MASIH TERBUKA** | 0.03947 | - | *Posisi Berjalan* | - | Entry Fee: -0.0308<br>Fund: +0.0073 | *Unrealized: +4.32 VST* | *Floating: +2.16 R* | TP `0.03622` & SL `0.04071` **RESTING AKTIF** di bursa (Mark: 0.03671). |
| 3 | **CITREA-USDT** | `FILLED` (`exit_time IS NULL`) | **SUDAH TERTUTUP** | 0.014428 | 0.013375 | `TAKE_PROFIT` (`TAKE_PROFIT_MARKET`) | +5.2518 | Fee: -0.0693<br>Fund: +0.0078 | **+5.1903** | **+2.5951 R** | **TAKE PROFIT BINGX HIT!** Tertahan di DB akibat bug `executed_symbols`. |
| 4 | **STANDARD-USDT** | `FILLED` (`exit_time IS NULL`) | **SUDAH TERTUTUP** | 0.3301 | 0.3421 | `STOP_LOSS` (`STOP_MARKET`) | -2.2623 | Fee: -0.0634<br>Fund: 0.0000 | **-2.3258** | **-1.1852 R** | Tertahan di DB akibat bug `executed_symbols`. |
| 5 | **ZEREBRO-USDT** | `FILLED` (`exit_time IS NULL`) | **SUDAH TERTUTUP** | 0.033253 | 0.034610 | `STOP_LOSS` (`STOP_MARKET`) | -2.1421 | Fee: -0.0536<br>Fund: 0.0000 | **-2.1956** | **-1.1127 R** | Tertahan di DB akibat bug `executed_symbols`. |

**Total 4 Trade Tertutup di Bursa**:
- **Gross PnL**: -1.2160 VST
- **Total Fees (Entry + Exit)**: -0.2364 VST
- **Total Funding Fees**: +0.0151 VST
- **Net Realized PnL**: **-1.4202 VST** (Net R: **-0.7642 R**)
- **Unrealized PnL (Posisi KMNO)**: **+4.3155 VST** (Mark: 0.03671 vs Entry: 0.03947)

---

## 3. Hasil Eksekusi Langkah demi Langkah (Verbatim Output)

### Langkah 1 — Verifikasi Commit & Status Service VPS
Perintah:
```bash
cd /home/ubuntu/bingx-short-agent && git rev-parse --short HEAD && git status --short && systemctl is-active bingx-agent.service
```
Output:
```
9af19ac
?? frontend/dist.bak-20261011-214207/
?? scripts/audit_all_58_exchange_tpsl.py
?? scripts/backfill_5_remaining.py
?? scripts/check_tpsl_history.py
?? scripts/extract_long_audit.py
?? scripts/update_vps_5.py
active
```
*Catatan: Commit `9af19ac` adalah commit pencatatan laporan peluncuran di atas basis kode `9e2f50b`.*

---

### Langkah 2 — Database SQLite VPS (`sessions` & `order_records`)
Perintah Python read-only dieksekusi via SQLite URI `mode=ro`.

Output:
```json
=== 1. SESSION ROW IN DB ===
{
  "session_id": "bx_sess_1791926045_8981c2",
  "user_id": 3,
  "status": "TERMINATED",
  "quota": 2,
  "filled_count": 1,
  "auto_scan": 0,
  "margin_per_pos": 5.0,
  "leverage": 20,
  "risk_budget_per_trade": 2.0,
  "daily_realized_pnl": 0.0,
  "consecutive_losses": 0,
  "cooldown_until": 0.0,
  "last_pnl_date": "2026-10-14",
  "executed_symbols": "[\"CNPY-USDT\"]",
  "processed_income_ids": "[\"1791537317374547190_513_5378649\"]",
  "started_at": 1791926045.8342974,
  "last_scan_at": 1792004757.520939,
  "stopped_at": 1792005982.7209349
}

=== 2. ORDER RECORDS IN DB (COUNT = 5) ===
[
  {
    "id": 62,
    "symbol": "CNPY-USDT",
    "side": "SELL",
    "position_side": "SHORT",
    "status": "CLOSED",
    "quantity": 158.73,
    "request_price": 0.3091,
    "price": 0.3102,
    "avg_fill_price": 0.3093,
    "stop_loss_price": 0.3217,
    "take_profit_price": 0.2776,
    "effective_leverage": 18,
    "notional": 49.063443,
    "quote_ts": 1791926526506,
    "created_at": "2026-10-13T21:22:07.821266+00:00",
    "exit_price": 0.3223,
    "exit_time": "2026-10-13T22:33:30+00:00",
    "exit_reason": "STOP_LOSS",
    "entry_fee": 0.0,
    "exit_fee": -0.02557934,
    "funding_fee": 0.0,
    "realized_pnl": -2.08906934,
    "realized_r": -1.0614,
    "client_order_id": "bx_short_1791926526_877b95",
    "order_id": "2110118909211316224"
  },
  {
    "id": 63,
    "symbol": "KMNO-USDT",
    "side": "SELL",
    "position_side": "SHORT",
    "status": "FILLED",
    "quantity": 1562.5,
    "request_price": 0.03943,
    "price": 0.0395,
    "avg_fill_price": 0.03947,
    "stop_loss_price": 0.04071,
    "take_profit_price": 0.03622,
    "effective_leverage": 20,
    "notional": 61.609375,
    "quote_ts": 1791929075806,
    "created_at": "2026-10-13T22:04:37.054433+00:00",
    "exit_price": null,
    "exit_time": null,
    "exit_reason": null,
    "entry_fee": 0.0,
    "exit_fee": 0.0,
    "funding_fee": 0.0,
    "realized_pnl": 0.0,
    "realized_r": 0.0,
    "client_order_id": "bx_short_1791929075_b94f7c",
    "order_id": "2110129601649840128"
  },
  {
    "id": 64,
    "symbol": "CITREA-USDT",
    "side": "SELL",
    "position_side": "SHORT",
    "status": "FILLED",
    "quantity": 4987.5,
    "request_price": 0.014428,
    "price": 0.014439,
    "avg_fill_price": 0.014428,
    "stop_loss_price": 0.014829,
    "take_profit_price": 0.013426,
    "effective_leverage": 20,
    "notional": 71.95965,
    "quote_ts": 1791932624613,
    "created_at": "2026-10-13T23:03:45.852845+00:00",
    "exit_price": null,
    "exit_time": null,
    "exit_reason": null,
    "entry_fee": 0.0,
    "exit_fee": 0.0,
    "funding_fee": 0.0,
    "realized_pnl": 0.0,
    "realized_r": 0.0,
    "client_order_id": "bx_short_1791932624_8ae4be",
    "order_id": "2110144486383292416"
  },
  {
    "id": 65,
    "symbol": "STANDARD-USDT",
    "side": "SELL",
    "position_side": "SHORT",
    "status": "FILLED",
    "quantity": 188.68,
    "request_price": 0.3299,
    "price": 0.3312,
    "avg_fill_price": 0.3301,
    "stop_loss_price": 0.3405,
    "take_profit_price": 0.3034,
    "effective_leverage": 20,
    "notional": 62.245532,
    "quote_ts": 1791976220699,
    "created_at": "2026-10-14T11:10:21.965199+00:00",
    "exit_price": null,
    "exit_time": null,
    "exit_reason": null,
    "entry_fee": 0.0,
    "exit_fee": 0.0,
    "funding_fee": 0.0,
    "realized_pnl": 0.0,
    "realized_r": 0.0,
    "client_order_id": "bx_short_1791976220_ace84e",
    "order_id": "2110327341738627072"
  },
  {
    "id": 66,
    "symbol": "ZEREBRO-USDT",
    "side": "SELL",
    "position_side": "SHORT",
    "status": "FILLED",
    "quantity": 1578.53,
    "request_price": 0.033236,
    "price": 0.03325,
    "avg_fill_price": 0.033253,
    "stop_loss_price": 0.034503,
    "take_profit_price": 0.030068,
    "effective_leverage": 19,
    "notional": 52.46402308,
    "quote_ts": 1791989030023,
    "created_at": "2026-10-14T14:43:51.411037+00:00",
    "exit_price": null,
    "exit_time": null,
    "exit_reason": null,
    "entry_fee": 0.0,
    "exit_fee": 0.0,
    "funding_fee": 0.0,
    "realized_pnl": 0.0,
    "realized_r": 0.0,
    "client_order_id": "bx_short_1791989030_5169e4",
    "order_id": "2110381068344365056"
  }
]
```

---

### Langkah 3 — Fakta Live Bursa BingX VST (User 3)
Pemanggilan endpoint `client.get_positions()`, `client.get_open_orders()`, `client.get_income()`, dan `client.get_all_orders()` berhasil tanpa error penolakan parameter.

Output:
```json
=== 1. LIVE OPEN POSITIONS ON BINGX VST (USER 3) ===
[
  {
    "positionId": "2110129601675005954",
    "symbol": "KMNO-USDT",
    "currency": "VST",
    "positionAmt": "1562.50",
    "availableAmt": "1562.50",
    "positionSide": "SHORT",
    "isolated": false,
    "avgPrice": "0.03947",
    "initialMargin": "3.0837",
    "margin": "7.3992",
    "leverage": 20,
    "unrealizedProfit": "4.3155",
    "realisedProfit": "-0.0236",
    "liquidationPrice": 64.14289,
    "pnlRatio": "1.3994",
    "maxMarginReduction": "0.0000",
    "riskRate": "0.0000",
    "markPrice": "0.03671",
    "positionValue": "57.35",
    "onlyOnePosition": false,
    "createTime": 1791929076008,
    "updateTime": 1791993648498,
    "minIncreaseMargin": "0.92"
  }
]

=== 2. LIVE OPEN ORDERS (TP/SL TRIGGERS) ON BINGX VST (USER 3) ===
[
  {
    "symbol": "KMNO-USDT",
    "orderId": 2110129601946148865,
    "side": "BUY",
    "positionSide": "SHORT",
    "type": "STOP_MARKET",
    "origQty": "1562.50",
    "price": "0.00000",
    "executedQty": "0.00",
    "avgPrice": "0.03947",
    "cumQuote": "0",
    "stopPrice": "0.04071",
    "status": "NEW",
    "time": 1791929076073,
    "updateTime": 1791929076073,
    "reduceOnly": true
  },
  {
    "symbol": "KMNO-USDT",
    "orderId": 2110129601946148864,
    "side": "BUY",
    "positionSide": "SHORT",
    "type": "TAKE_PROFIT_MARKET",
    "origQty": "1562.50",
    "price": "0.00000",
    "executedQty": "0.00",
    "avgPrice": "0.03947",
    "cumQuote": "0",
    "stopPrice": "0.03622",
    "status": "NEW",
    "time": 1791929076073,
    "updateTime": 1791929076073,
    "reduceOnly": true
  }
]

=== 3. BINGX INCOME LEDGER SINCE SESSION START (start_ms=1791926045834) ===
[
  {"symbol": "KMNO-USDT", "incomeType": "FUNDING_FEE", "income": "0.00108359", "time": 1791993648000, "tranId": "..."},
  {"symbol": "ZEREBRO-USDT", "incomeType": "REALIZED_PNL", "income": "-2.14206521", "time": 1791990920000, "tranId": "..."},
  {"symbol": "ZEREBRO-USDT", "incomeType": "TRADING_FEE", "income": "-0.02731646", "time": 1791990920000, "tranId": "..."},
  {"symbol": "ZEREBRO-USDT", "incomeType": "TRADING_FEE", "income": "-0.02624543", "time": 1791989030000, "tranId": "..."},
  {"symbol": "STANDARD-USDT", "incomeType": "REALIZED_PNL", "income": "-2.26233600", "time": 1791985928000, "tranId": "..."},
  {"symbol": "STANDARD-USDT", "incomeType": "TRADING_FEE", "income": "-0.03227280", "time": 1791985928000, "tranId": "..."},
  {"symbol": "STANDARD-USDT", "incomeType": "TRADING_FEE", "income": "-0.03114163", "time": 1791976221000, "tranId": "..."},
  {"symbol": "CITREA-USDT", "incomeType": "REALIZED_PNL", "income": "5.25183750", "time": 1791970511000, "tranId": "..."},
  {"symbol": "CITREA-USDT", "incomeType": "TRADING_FEE", "income": "-0.03335391", "time": 1791970511000, "tranId": "..."},
  {"symbol": "KMNO-USDT", "incomeType": "FUNDING_FEE", "income": "0.00308384", "time": 1791964852000, "tranId": "..."},
  {"symbol": "CITREA-USDT", "incomeType": "FUNDING_FEE", "income": "0.00243708", "time": 1791964852000, "tranId": "..."},
  {"symbol": "KMNO-USDT", "incomeType": "FUNDING_FEE", "income": "0.00310170", "time": 1791936040000, "tranId": "..."},
  {"symbol": "CITREA-USDT", "incomeType": "FUNDING_FEE", "income": "0.00533614", "time": 1791936040000, "tranId": "..."},
  {"symbol": "CITREA-USDT", "incomeType": "TRADING_FEE", "income": "-0.03597982", "time": 1791932625000, "tranId": "..."},
  {"symbol": "CNPY-USDT", "incomeType": "REALIZED_PNL", "income": "-2.06349000", "time": 1791930810000, "tranId": "..."},
  {"symbol": "CNPY-USDT", "incomeType": "TRADING_FEE", "income": "-0.02557934", "time": 1791930810000, "tranId": "..."},
  {"symbol": "KMNO-USDT", "incomeType": "TRADING_FEE", "income": "-0.03083736", "time": 1791929076000, "tranId": "..."},
  {"symbol": "CNPY-USDT", "incomeType": "TRADING_FEE", "income": "-0.02454759", "time": 1791926527000, "tranId": "..."}
]
```

Riwayat Order Kunci per Simbol:
- **CITREA-USDT**:
  * Entry: Market Sell `orderId: 2110144486383292416`, `avgPrice: 0.014428`, `qty: 4987.5`, status `FILLED`.
  * Exit: `orderId: 2110303394481573888`, type `TAKE_PROFIT_MARKET`, side `BUY`, `stopPrice: 0.013426`, `avgPrice: 0.013375`, `profit: 5.2518`, status `FILLED`.
  * SL Terbatal Otomatis: `orderId: 2110144486713155585`, type `STOP_MARKET`, status `CANCELLED`.
- **STANDARD-USDT**:
  * Entry: Market Sell `orderId: 2110327341738627072`, `avgPrice: 0.3301`, `qty: 188.68`, status `FILLED`.
  * Exit: `orderId: 2110368054970945536`, type `STOP_MARKET`, side `BUY`, `stopPrice: 0.3405`, `avgPrice: 0.3421`, `profit: -2.2623`, status `FILLED`.
  * TP Terbatal Otomatis: `orderId: 2110327342127210496`, type `TAKE_PROFIT_MARKET`, status `CANCELLED`.
- **ZEREBRO-USDT**:
  * Entry: Market Sell `orderId: 2110381068344365056`, `avgPrice: 0.033253`, `qty: 1578.53`, status `FILLED`.
  * Exit: `orderId: 2110388992286396416`, type `STOP_MARKET`, side `BUY`, `stopPrice: 0.034503`, `avgPrice: 0.034610`, `profit: -2.1420`, status `FILLED`.
  * TP Terbatal Otomatis: `orderId: 2110381068766502912`, type `TAKE_PROFIT_MARKET`, status `CANCELLED`.

---

### Langkah 4 — Statistik Audit Log (`logs/audit.jsonl`) Sesi `bx_sess_1791926045_8981c2`
Mengikuti arahan Agent Muse, daftar seluruh tipe event yang benar-benar ada diambil terlebih dahulu, kemudian dihitung secara presisi.

Output:
```json
=== 1. EVENT COUNTS FOR SESSION ===
{
  "SESSION_START": 1,
  "HARD_GATE_REJECT": 1301,
  "AI_BATCH_TRIAGE": 235,
  "AI_EVALUATION": 237,
  "CYCLE_SUMMARY": 235,
  "WATCHLIST_ENTER": 5,
  "LEVERAGE_ADJUSTMENT": 5,
  "TPSL_VERIFIED": 5,
  "ORDER_SUBMISSION": 5,
  "WATCHLIST_EVICT": 4,
  "AI_BATCH_TRIAGE_FALLBACK": 12,
  "POSITION_CLOSED": 1,
  "TRADE_OUTCOME_INGESTED": 1,
  "DAY_BOUNDARY_RESET": 1,
  "WATCHLIST_VETO": 12
}

=== 2. HARD GATE REJECT REASONS ===
{
  "dump_already_extended": 1154,
  "atr_below_friction_threshold": 145,
  "spread_too_wide": 310,
  "crowded_short_squeeze_risk": 2
}

=== 3. TIER-1 AI BATCH TRIAGE ACTIONS (TOTAL CANDIDATES: 605) ===
{
  "DEEP_ANALYZE": 216,
  "WATCH": 194,
  "SKIP": 195
}

=== 4. TIER-2 AI EVALUATION DECISIONS ===
{
  "SKIP": 114,
  "WAIT": 118,
  "ENTER_SHORT": 5
}

=== 5. ORDER SUBMISSIONS (SLIPPAGE & PROVENANCE) ===
[
  {
    "ts": "2026-10-13T21:22:07.815454+00:00",
    "symbol": "CNPY-USDT",
    "side": "SELL",
    "quantity": 158.73,
    "request_price": 0.3091,
    "avg_fill_price": 0.3093,
    "slippage_pct": 0.0647,
    "stop_loss_price": 0.3217,
    "take_profit_price": 0.2776,
    "fill_provenance": "EXCHANGE_REPORTED"
  },
  {
    "ts": "2026-10-13T22:04:37.046439+00:00",
    "symbol": "KMNO-USDT",
    "side": "SELL",
    "quantity": 1562.5,
    "request_price": 0.03943,
    "avg_fill_price": 0.03947,
    "slippage_pct": 0.1014,
    "stop_loss_price": 0.04071,
    "take_profit_price": 0.03622,
    "fill_provenance": "EXCHANGE_REPORTED"
  },
  {
    "ts": "2026-10-13T23:03:45.843831+00:00",
    "symbol": "CITREA-USDT",
    "side": "SELL",
    "quantity": 4987.5,
    "request_price": 0.014428,
    "avg_fill_price": 0.014428,
    "slippage_pct": 0.0,
    "stop_loss_price": 0.014829,
    "take_profit_price": 0.013426,
    "fill_provenance": "EXCHANGE_REPORTED"
  },
  {
    "ts": "2026-10-14T11:10:21.960198+00:00",
    "symbol": "STANDARD-USDT",
    "side": "SELL",
    "quantity": 188.68,
    "request_price": 0.3299,
    "avg_fill_price": 0.3301,
    "slippage_pct": 0.0606,
    "stop_loss_price": 0.3405,
    "take_profit_price": 0.3034,
    "fill_provenance": "EXCHANGE_REPORTED"
  },
  {
    "ts": "2026-10-14T14:43:51.405444+00:00",
    "symbol": "ZEREBRO-USDT",
    "side": "SELL",
    "quantity": 1578.53,
    "request_price": 0.033236,
    "avg_fill_price": 0.033253,
    "slippage_pct": 0.0511,
    "stop_loss_price": 0.034503,
    "take_profit_price": 0.030068,
    "fill_provenance": "EXCHANGE_REPORTED"
  }
]

=== 6. POSITION CLOSES & INCOME EVENTS IN LOG ===
[
  {
    "ts": "2026-10-13T22:35:22.231525+00:00",
    "event": "POSITION_CLOSED",
    "symbol": "CNPY-USDT",
    "client_order_id": "bx_short_1791926526_877b95",
    "order_id": "2110118909211316224",
    "exit_price": 0.3223,
    "exit_reason": "STOP_LOSS",
    "exit_time": "2026-10-13T22:33:30+00:00",
    "gross_pnl": -2.06349,
    "exit_fee": -0.02557934,
    "funding_fee": 0,
    "net_pnl": -2.08906934,
    "realized_r": -1.0614
  },
  {
    "ts": "2026-10-13T22:35:22.231686+00:00",
    "event": "TRADE_OUTCOME_INGESTED",
    "symbol": "CNPY-USDT",
    "income_id": "1791537317374547190_513_5378649",
    "realized_pnl": -2.06349,
    "session_daily_pnl": -2.06349,
    "consecutive_losses": 1
  }
]

=== 7. ERRORS OR TPSL DROPS ===
[]
```

---

## 4. Evaluasi Menjawab Keluhan Naufal (Didukung Fakta Empiris)

1. **Soal Keluhan Profit Tipis**:
   - Angka -2.08 VST yang dilihat Naufal di dashboard sebelumnya murni karena baru Trade #1 (`CNPY`) yang masuk ke database.
   - Fakta bursa membuktikan Trade #3 (`CITREA-USDT`) **berhasil Take Profit penuh** menghasilkan **+5,19 VST (+2,60 R)**.
   - Posisi Trade #2 (`KMNO-USDT`) saat ini **sedang floating profit +4,32 VST (+2,16 R)** dengan TP di 0.03622 (jarak mark price ke TP tinggal 1.3%).
   - Skenario jika KMNO kena TP: total PnL dari 5 trade adalah sekitar **+3,65 VST (+1,77 R)**.
2. **Soal Keluhan Pace Lambat (5 trade per hari)**:
   - Pace bukan disebabkan oleh scanner/AI (funnel membuktikan ada 235 siklus scan, 605 kandidat ditriase, dan 5 kandidat lolos).
   - Jeda 12 jam (06:03 WIB s/d 18:10 WIB) terjadi secara murni karena **kedua slot kuota terisi oleh `KMNO` dan `CITREA`** yang sedang ditahan (*holding*) di bursa. Begitu `CITREA` menyentuh TP pada 16:35 WIB, slot langsung kosong dan bot membuka `STANDARD` pada 18:10 WIB.
3. **Soal Penegakan Kuota**:
   - Kuota 2 slot di bursa terbukti **100% dipatuhi**. Tidak pernah ada 3 posisi terbuka serentak di bursa BingX VST.

---

## 5. Rekomendasi Langkah Selanjutnya

1. **Sesi Tetap DIJEDA**: Hermes tetap berada dalam mode standby, tidak mengubah kode atau database sebelum adanya rencana perbaikan resmi.
2. **Backfill Rekonsiliasi Exit & Perbaikan Bug `executed_symbols`**:
   - Perlu dibuatkan patch pada `tenant_manager.py` (menyimpan `executed_symbols` ke DB pada setiap entry dan merekonsiliasi income berdasarkan seluruh simbol yang ada di `order_records` sesi aktif).
   - Setelah patch disetujui Muse dan Gemini 4 Argon, 3 baris di `order_records` (`CITREA`, `STANDARD`, `ZEREBRO`) dapat direkonsiliasi secara otomatis atau melalui script backfill resmi sehingga status dan PnL lokal sinkron 100% dengan bursa.
