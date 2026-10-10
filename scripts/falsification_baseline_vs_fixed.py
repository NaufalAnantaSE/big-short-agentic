#!/usr/bin/env python3
"""
Baseline-vs-fixed comparison for the 13 ENTER decisions.

For each decision it evaluates BOTH playbook engines on identical point-in-time features:
  - baseline: strategy_playbook.py as of commit 2151599 (pre-F-05)
  - fixed   : current working tree (F-05 mandatory structure)

This isolates what the F-05 change actually does to real historical decisions, instead of
asserting it from synthetic fixtures.
"""
import importlib.util
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime

BASE_DIR = "/home/naufal-ananta/bot/bingx-short-agent"
sys.path.insert(0, BASE_DIR)

import market_features as mf  # noqa: E402
from market_features import compute_market_features, PRODUCTION_CANDLE_BUFFER_MS  # noqa: E402
from strategy_playbook import evaluate_playbooks as fixed_eval  # noqa: E402

# Load the pre-F-05 engine under a distinct module name.
spec = importlib.util.spec_from_file_location("pb_baseline", "/tmp/oldpb/strategy_playbook_baseline.py")
pb_baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb_baseline)
baseline_eval = pb_baseline.evaluate_playbooks


def api_get(path, params):
    url = f"https://open-api.bingx.com{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-replay/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_klines(symbol, interval, end_ms, count=300):
    step = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000}[interval]
    j = api_get("/openApi/swap/v3/quote/klines", {
        "symbol": symbol, "interval": interval,
        "startTime": end_ms - count * step, "endTime": end_ms, "limit": count,
    })
    if j.get("code") != 0:
        raise RuntimeError(f"{j.get('code')} {j.get('msg')}")
    return j.get("data") or []


def fetch_funding(symbol, end_ms):
    j = api_get("/openApi/swap/v2/quote/fundingRate", {
        "symbol": symbol, "startTime": end_ms - 8 * 3_600_000, "endTime": end_ms, "limit": 50,
    })
    rows = sorted(j.get("data") or [], key=lambda r: r.get("fundingTime", 0))
    return rows[-1] if rows else None


def depth_for_spread(price, spread_pct, ts_ms):
    half = price * (spread_pct / 100.0) / 2.0
    return {"bids": [[str(round(price - half, 8)), "1000"]],
            "asks": [[str(round(price + half, 8)), "1000"]], "T": ts_ms}


def main():
    decisions = json.load(open("/home/naufal-ananta/.hermes/cache/scratch/falsification_decisions.json"))
    rows = []
    for d in decisions:
        symbol, want = d["symbol"], ("LONG" if d["decision"].endswith("LONG") else "SHORT")
        dec_ms = int(datetime.fromisoformat(d["ts"]).timestamp() * 1000)
        for attempt in (1, 2, 3):
            try:
                klines = {tf: fetch_klines(symbol, tf, dec_ms, 300) for tf in ("1m", "15m", "1h")}
                fund = fetch_funding(symbol, dec_ms)
                break
            except Exception as exc:
                if attempt == 3:
                    rows.append({**d, "error": str(exc)})
                    print(f"{symbol:18s} ERROR {exc}")
                    klines = None
        if klines is None:
            continue

        closed15 = mf._closed_rows(klines["15m"], dec_ms, interval="15m", buffer_ms=PRODUCTION_CANDLE_BUFFER_MS)
        last = closed15[-1]["close"] if closed15 else 1.0
        feats = compute_market_features(
            klines,
            {"lastFundingRate": (fund or {}).get("fundingRate"),
             "updateTime": (fund or {}).get("fundingTime", dec_ms)},
            {"openInterest": None, "time": dec_ms},
            depth_for_spread(last, 0.05, dec_ms),
            dec_ms, buffer_ms=PRODUCTION_CANDLE_BUFFER_MS,
        )
        feats["fresh"] = True

        b = baseline_eval(symbol, last, 0.0, 0.05, feats)
        f = fixed_eval(symbol, last, 0.0, 0.05, feats)

        rec = {
            **d,
            "baseline_playbook": b.playbook, "baseline_dir": b.direction, "baseline_score": b.score,
            "fixed_playbook": f.playbook, "fixed_dir": f.direction, "fixed_score": f.score,
            "baseline_match": (b.playbook != "NONE" and b.direction == want),
            "fixed_match": (f.playbook != "NONE" and f.direction == want),
            "divergence": (feats.get("rsi") or {}).get("divergence"),
            "atr_pct": round(max(float((feats.get("timeframes", {}).get("1h") or {}).get("atr_pct", 0) or 0),
                                 float((feats.get("timeframes", {}).get("15m") or {}).get("atr_pct", 0) or 0)), 3),
            "ema_trend": (feats.get("ema_trend") or {}).get("trend"),
        }
        rows.append(rec)
        flag = "" if rec["baseline_match"] == rec["fixed_match"] else "  <-- CHANGED"
        print(f"{symbol:18s} {d['decision']:12s} base={b.playbook:16s}({'M' if rec['baseline_match'] else '-'}) "
              f"fixed={f.playbook:16s}({'M' if rec['fixed_match'] else '-'}){flag}")

    out = "/home/naufal-ananta/.hermes/cache/scratch/falsification_baseline_vs_fixed.json"
    json.dump(rows, open(out, "w"), indent=2)

    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    print(f"\n=== BASELINE vs FIXED (n={n}) ===")
    print(f"baseline playbook endorsed AI direction : {sum(1 for r in ok if r['baseline_match'])}/{n}")
    print(f"fixed    playbook endorsed AI direction : {sum(1 for r in ok if r['fixed_match'])}/{n}")
    print(f"decisions changed by F-05               : {sum(1 for r in ok if r['baseline_match'] != r['fixed_match'])}/{n}")
    print(f"baseline returned NONE                  : {sum(1 for r in ok if r['baseline_playbook'] == 'NONE')}/{n}")
    print(f"fixed    returned NONE                  : {sum(1 for r in ok if r['fixed_playbook'] == 'NONE')}/{n}")
    print(f"fixed endorses OPPOSITE direction       : {sum(1 for r in ok if r['fixed_playbook'] != 'NONE' and r['fixed_dir'] != ('LONG' if r['decision'].endswith('LONG') else 'SHORT'))}/{n}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
