"""CLI Runner for BingX Memecoin Short Entry Agent (Dry-Run & Live Execution)."""

import sys
import argparse
from config import load_config
from client import BingXClient
from orchestrator import SessionOrchestrator

def main():
    parser = argparse.ArgumentParser(description="BingX Memecoin Short-Only Entry Agent")
    parser.add_argument("--margin", type=float, default=5.0, help="Target initial margin per position in USDT (default: 5.0)")
    parser.add_argument("--leverage", type=int, default=20, help="Leverage multiplier cap (default: 20)")
    parser.add_argument("--quota", type=int, default=2, help="Number of entry positions per session (default: 2)")
    parser.add_argument("--live", action="store_true", help="Execute real orders to BingX VST (default is Dry-Run)")
    parser.add_argument("--mode", type=str, choices=["PUMP_GAINERS", "MEME_ONLY"], default="PUMP_GAINERS", help="Scanner mode: PUMP_GAINERS or MEME_ONLY (default: PUMP_GAINERS)")
    parser.add_argument("--min-pump", type=float, default=0.0, help="Minimum 24h gain percentage to consider (default: 0.0)")
    args = parser.parse_args()

    print("================================================================================")
    print("           BINGX AGENTIC SHORT-ONLY ENTRY SYSTEM — TERMINAL RUNNER              ")
    print("================================================================================")

    config = load_config()
    config.universe_mode = args.mode
    config.min_pump_percent = args.min_pump

    if not (config.api_key and config.secret_key):
        print("[ERROR] Credentials not found! Check /home/naufal-ananta/Documents/asecret/bingx-testing.txt")
        sys.exit(1)

    print(f"Target Environment : {config.bingx_host} (Demo VST)")
    print(f"API Key Identifier : {config.masked_api_key}")
    print(f"AI Gateway (9Router): {config.ai_gateway_url} (Model: {config.ai_model_name})")
    print(f"Universe Mode      : {config.universe_mode} (Min 24h Pump: >={config.min_pump_percent}%)")
    print(f"Mode Operasional   : {'LIVE EXECUTION (VST)' if args.live else 'DRY-RUN (Simulasi Sinyal & Sizing)'}")
    print(f"Parameter Sesi     : Margin=${args.margin:.2f} | Leverage={args.leverage}x | Kuota={args.quota} posisi")
    print("--------------------------------------------------------------------------------")

    client = BingXClient(config)

    # 1. Account Health & Mode Check
    try:
        bal_data = client.get_balance()
        vst_asset: dict = {}
        if isinstance(bal_data, list) and len(bal_data) > 0:
            for item in bal_data:
                if isinstance(item, dict) and item.get("asset") == "VST":
                    vst_asset = item
                    break
            if not vst_asset and isinstance(bal_data[0], dict):
                vst_asset = bal_data[0]
        elif isinstance(bal_data, dict):
            vst_asset = bal_data

        balance = float(vst_asset.get("balance", 0)) if isinstance(vst_asset, dict) else 0.0
        equity = float(vst_asset.get("equity", 0)) if isinstance(vst_asset, dict) else 0.0
        used_margin = float(vst_asset.get("usedMargin", 0)) if isinstance(vst_asset, dict) else 0.0

        mode_data = client.get_position_mode()
        is_hedge = str(mode_data.get("dualSidePosition", "")).lower() == "true"

        print(f"Saldo Akun         : {balance:,.2f} VST | Ekuitas: {equity:,.2f} VST | Used Margin: {used_margin:,.2f} VST")
        print(f"Position Mode      : {'Hedge Mode (Dual-Side) [OK]' if is_hedge else 'One-Way Mode [WARNING: Harap ubah ke Hedge]'}")
    except Exception as e:
        print(f"[ERROR] Gagal membaca data akun: {str(e)}")
        sys.exit(1)

    print("--------------------------------------------------------------------------------")
    print("[1/4] Memeriksa Posisi Aktif & Order Klien (Coexistence Check)...")
    orchestrator = SessionOrchestrator(config)
    occupied = orchestrator.scanner.get_occupied_symbols()
    if occupied:
        print(f"      [PROTEKSI AKTIF] Simbol dengan posisi/order manual ({len(occupied)}): {', '.join(occupied)}")
        print("      Agen DILARANG menyentuh pair di atas.")
    else:
        print("      Tidak ada posisi terbuka atau pending order manual. Seluruh universe tersedia.")

    print(f"\n[2/4] Memulai Sesi & Memindai Universe ({config.universe_mode})...")
    orchestrator.start_session(margin_per_pos=args.margin, leverage=args.leverage, quota=args.quota)
    candidates = orchestrator.scanner.scan_universe(mode=config.universe_mode, limit_candidates=5)

    if not candidates:
        print(f"      [INFO] Tidak ditemukan kandidat {config.universe_mode} yang memenuhi filter likuiditas/spread saat ini.")
        return

    print(f"      Ditemukan {len(candidates)} kandidat lolos filter teknis awal:")
    for idx, c in enumerate(candidates, 1):
        print(f"      {idx}. {c.symbol:<16} Price: {c.last_price:<10} 24h: {c.price_change_percent:>+6.2f}% | Spread: {c.spread_percent:.4f}% | Vol: ${c.volume_24h_usdt:,.0f}")

    print("\n[3/4] Melakukan Evaluasi AI via 9Router & Kalkulasi Sizing Lot...")
    res = orchestrator.run_cycle(dry_run=not args.live)

    print("\n=============================== HASIL EVALUASI SIKLUS ===========================")
    print(f"ID Sesi        : {res.get('session_id')}")
    print(f"Status Sesi    : {res.get('session_status')}")
    print(f"Kuota Terpakai : {res.get('filled_count')} / {res.get('quota')}")
    print("--------------------------------------------------------------------------------")

    evals = res.get("evaluations", [])
    for ev in evals:
        sym = ev.get("symbol")
        dec = ev.get("ai_decision")
        conf = ev.get("ai_confidence")
        evidence = ev.get("ai_evidence", "-")
        sizing = ev.get("sizing", {})
        qty = sizing.get("quantity", 0)
        notional = sizing.get("notional_value", 0)
        eff_lev = sizing.get("effective_leverage", 0)

        badge = f"[{dec}]"
        print(f"\nSimbol        : {sym} (Harga: {ev.get('price')})")
        print(f"Keputusan AI  : {badge:<12} (Confidence: {conf}%)")
        print(f"Alasan Analis : {evidence}")
        print(f"Sizing Lot    : {qty} koin (Notional: ${notional:.2f} USDT @ {eff_lev}x leverage)")
        
        if ev.get("executed"):
            print(f"Status Order  : [LIVE SUCCESS] Order ID: {ev.get('order_id')} (Client ID: {ev.get('client_order_id')})")
        elif ev.get("dry_run"):
            print(f"Status Order  : [DRY-RUN SIMULASI] Siap kirim order SHORT MARKET (Client ID: {ev.get('client_order_id')})")
        elif dec == "ENTER_SHORT" and not sizing.get("is_valid"):
            print(f"Status Order  : [REJECTED BY SIZING] {sizing.get('rejection_reason')}")
        else:
            print("Status Order  : [WAIT/SKIP] Tidak ada order yang dieksekusi.")

    print("\n================================================================================")
    print("Siklus selesai.")

if __name__ == "__main__":
    main()
