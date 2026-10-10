#!/usr/bin/env python3
"""
Final consolidated falsification analysis for the 13 ENTER decisions.

Registered decision rule (fixed before running):
  - majority blocked by the fixed deterministic layer -> entry-quality cluster
    (F-01/F-05/F-08) supported as cause of the losing streak;
  - almost all still admitted -> variance dominates, priority shifts to risk management.

Point-in-time discipline: only bars closed before the original decision timestamp are used
(BingX honours startTime+endTime, and _closed_rows drops the forming bar).

Declared limitation: historical order-book depth and open interest have no point-in-time
endpoint. Their VALUES are therefore unknown in replay; a benign spread is assumed and the
ATR-friction gate is reported as a sensitivity (breakeven spread) instead of a single
arbitrary verdict. Freshness is treated as known-true: the bot was live-scanning, and a
stale feed would have blocked the scan before any AI evaluation.
"""
import importlib.util
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "/home/naufal-ananta/bot/bingx-short-agent"
sys.path.insert(0, BASE)

import market_features as mf  # noqa: E402
from market_features import compute_market_features, hard_gate, PRODUCTION_CANDLE_BUFFER_MS  # noqa: E402
from strategy_playbook import evaluate_playbooks  # noqa: E402

WS = "/home/naufal-ananta/.hermes/cache/scratch"

_spec = importlib.util.spec_from_file_location("pb_baseline", "/tmp/oldpb/strategy_playbook_baseline.py")
pbb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pbb)


def api(path, params, tries=5):
    url = f"https://open-api.bingx.com{path}?" + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hermes-replay/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (i + 1))
    raise last


def klines(sym, itv, end, n=300):
    step = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000}[itv]
    j = api("/openApi/swap/v3/quote/klines", {"symbol": sym, "interval": itv,
                                             "startTime": end - n * step, "endTime": end, "limit": n})
    if j.get("code") != 0:
        raise RuntimeError(f"{j.get('code')} {j.get('msg')}")
    return j.get("data") or []


def funding(sym, end):
    j = api("/openApi/swap/v2/quote/fundingRate", {"symbol": sym,
                                                   "startTime": end - 8 * 3_600_000, "endTime": end, "limit": 50})
    rows = sorted(j.get("data") or [], key=lambda r: r.get("fundingTime", 0))
    return rows[-1] if rows else None


def book(price, sp, ts):
    h = price * (sp / 100.0) / 2.0
    return {"bids": [[str(round(price - h, 8)), "1000"]],
            "asks": [[str(round(price + h, 8)), "1000"]], "T": ts}


def main():
    decisions = json.load(open(f"{WS}/falsification_decisions.json"))
    enters = {x["symbol"] + x["ts"]: x for x in json.load(open(f"{WS}/falsification_enters_enriched.json"))}

    rows = []
    for d in decisions:
        sym, want = d["symbol"], ("LONG" if d["decision"].endswith("LONG") else "SHORT")
        ms = int(datetime.fromisoformat(d["ts"]).timestamp() * 1000)
        try:
            k = {t: klines(sym, t, ms, 300) for t in ("1m", "15m", "1h")}
            fu = funding(sym, ms)
        except Exception as exc:
            rows.append({**d, "error": str(exc)})
            print(f"{sym:16s} ERROR {exc}")
            continue

        c15 = mf._closed_rows(k["15m"], ms, interval="15m", buffer_ms=PRODUCTION_CANDLE_BUFFER_MS)
        last = c15[-1]["close"] if c15 else 1.0

        def feats(sp):
            f = compute_market_features(
                k,
                {"lastFundingRate": (fu or {}).get("fundingRate"),
                 "updateTime": (fu or {}).get("fundingTime", ms)},
                {"openInterest": None, "time": ms},
                book(last, sp, ms), ms,
                buffer_ms=PRODUCTION_CANDLE_BUFFER_MS,
            )
            f["fresh"] = True
            return f

        f = feats(0.05)
        ok, reasons = hard_gate(f, 0.35, direction=want)
        pb = evaluate_playbooks(sym, last, 0.0, 0.05, f)
        pbb_res = pbb.evaluate_playbooks(sym, last, 0.0, 0.05, f)

        tf = f.get("timeframes") or {}
        atr = max(float((tf.get("1h") or {}).get("atr_pct", 0) or 0),
                  float((tf.get("15m") or {}).get("atr_pct", 0) or 0))
        # atr_to_friction gate fails when atr/(0.10+spread) < 3.0
        breakeven = (atr / 3.0) - 0.10

        rec = {**d,
               "gate_pass": ok, "gate_reasons": reasons,
               "fixed_pb": pb.playbook, "fixed_dir": pb.direction,
               "fixed_match": (pb.playbook != "NONE" and pb.direction == want),
               "base_pb": pbb_res.playbook, "base_dir": pbb_res.direction,
               "base_match": (pbb_res.playbook != "NONE" and pbb_res.direction == want),
               "div_fixed": (f.get("rsi") or {}).get("divergence"),
               "div_base": mf._detect_rsi_divergence_unaligned(c15),
               "rsi": round(float((f.get("rsi") or {}).get("rsi_15m") or 0), 2),
               "ema": (f.get("ema_trend") or {}).get("trend"),
               "atr_pct": round(atr, 3), "breakeven_spread": round(breakeven, 3),
               "intrabar": sum(1 for r in k["15m"] if (r.get("time", 0) + 900_000) > ms - PRODUCTION_CANDLE_BUFFER_MS),
               "risk_factors": enters.get(sym + d["ts"], {}).get("risk_factors"),
               "key_evidence": enters.get(sym + d["ts"], {}).get("key_evidence")}
        rows.append(rec)
        print(f"{sym:16s} {d['decision']:12s} gate={'PASS' if ok else 'BLOCK':5s} "
              f"fixed={pb.playbook:16s}({'M' if rec['fixed_match'] else '-'}) "
              f"base={pbb_res.playbook:16s}({'M' if rec['base_match'] else '-'}) "
              f"atr%={atr:6.2f} be_spread={breakeven:6.2f}")

    json.dump(rows, open(f"{WS}/falsification_final.json", "w"), indent=2)

    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    print(f"\n=== FINAL (n={n}) ===")
    print(f"hard gate blocked @0.05% spread   : {sum(1 for r in ok if not r['gate_pass'])}/{n}")
    print(f"would block if spread >= breakeven: {sum(1 for r in ok if r['breakeven_spread'] < 0.35)}/{n}")
    for r in ok:
        if r["breakeven_spread"] < 0.35:
            print(f"    {r['symbol']:16s} blocked once spread > {r['breakeven_spread']:.3f}%")
    print(f"fixed playbook endorses AI dir    : {sum(1 for r in ok if r['fixed_match'])}/{n}")
    print(f"baseline playbook endorses AI dir : {sum(1 for r in ok if r['base_match'])}/{n}")
    print(f"endorsement LOST due to F-05      : {sum(1 for r in ok if r['base_match'] and not r['fixed_match'])}/{n}")
    print(f"divergence flipped by F-08        : {sum(1 for r in ok if r['div_base'] != r['div_fixed'])}/{n}")
    for r in ok:
        if r["div_base"] != r["div_fixed"]:
            print(f"    {r['symbol']:16s} {r['div_base']} -> {r['div_fixed']}")
    print(f"intrabar bar present in feed      : {sum(1 for r in ok if r['intrabar'] > 0)}/{n}")


if __name__ == "__main__":
    main()
