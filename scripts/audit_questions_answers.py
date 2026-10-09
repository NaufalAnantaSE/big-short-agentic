#!/usr/bin/env python3
"""Audit Answers Script for Agent Muse Review Questions."""

import os
import sys
import json
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tenant_manager import TenantSessionManager
from config import load_config
import db

def main():
    session_id = "bx_sess_1791488487_dd781d"

    tm = TenantSessionManager(base_config=load_config())
    client = tm.get_client(11)

    # 1. Orders in Session
    orders_in_sess = []
    with open("logs/audit.jsonl", "r", errors="ignore") as f:
        for line in f:
            if not line.strip(): continue
            try: entry = json.loads(line)
            except: continue
            if entry.get("session_id") != session_id: continue
            if entry.get("event_type") == "ORDER_SUBMISSION":
                orders_in_sess.append(entry.get("data", {}))

    positions = client.get_positions()
    open_syms = {p["symbol"]: p for p in positions}

    print(f"TOTAL ORDERS IN SESSION: {len(orders_in_sess)}")

    all_orders_bingx = {}
    for o in orders_in_sess:
        sym = o["symbol"]
        if sym not in all_orders_bingx:
            try:
                res = client._request("GET", "/openApi/swap/v2/trade/allOrders", params={"symbol": sym, "limit": 20}, signed=True)
                order_list = res.get("orders", []) if isinstance(res, dict) else res
                all_orders_bingx[sym] = order_list
            except Exception as e:
                all_orders_bingx[sym] = []

    print("\n=== OUTCOME BREAKDOWN FOR 25 ORDERS ===")
    tp_count = 0
    sl_count = 0
    open_count = 0
    closed_pnl_total = 0.0

    for idx, o in enumerate(orders_in_sess, 1):
        sym = o["symbol"]
        oid = str(o.get("order_id"))
        pos_side = o.get("position_side")

        # Check if currently open
        if sym in open_syms and open_syms[sym]["positionSide"] == pos_side:
            p = open_syms[sym]
            open_count += 1
            print(f"{idx}. {sym} ({pos_side}) -> OPEN | Entry: {p.get('avgPrice')} | Mark: {p.get('markPrice')} | Floating PnL: {p.get('unrealizedProfit')} VST ({float(p.get('pnlRatio', 0))*100:.2f}%)")
        else:
            sym_orders = all_orders_bingx.get(sym, [])
            close_order = None
            for bo in sym_orders:
                if bo.get("positionSide") == pos_side and bo.get("status") == "FILLED" and str(bo.get("orderId")) != oid:
                    close_order = bo
                    break

            if close_order:
                pnl = float(close_order.get("profit", 0) or 0)
                closed_pnl_total += pnl
                c_type = close_order.get("type", "")
                if "TAKE_PROFIT" in c_type or pnl > 0:
                    tp_count += 1
                    outcome = f"HIT TP ({c_type})"
                else:
                    sl_count += 1
                    outcome = f"HIT SL ({c_type})"
                print(f"{idx}. {sym} ({pos_side}) -> CLOSED: {outcome} | PnL: {pnl:+.4f} VST | ClosePrice: {close_order.get('avgPrice')}")
            else:
                print(f"{idx}. {sym} ({pos_side}) -> CLOSED (Order {oid})")

    print("\n=== SUMMARY OF OUTCOMES ===")
    print(f"Still Open: {open_count}")
    print(f"Hit TP: {tp_count}")
    print(f"Hit SL: {sl_count}")
    print(f"Total Realized PnL from closed positions: {closed_pnl_total:+.4f} VST")

if __name__ == "__main__":
    main()
