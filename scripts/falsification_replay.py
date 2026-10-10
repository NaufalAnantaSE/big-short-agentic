#!/usr/bin/env python3
"""
Falsification replay (corrected) for the 13 ENTER decisions of session bx_sess_1791579205_ab6bff.

Fixes a harness artifact in the first run: with depth absent, friction_pct defaulted to
1.10 and inflated the atr_to_friction gate into a false block. Here the ATR ratio is
recomputed across a range of plausible spreads so the result does not depend on one
arbitrary friction assumption.

POINT-IN-TIME DISCIPLINE: features come only from bars closed before the decision
timestamp. BingX honours startTime+endTime; _closed_rows drops the forming bar.

UNKNOWABLE INPUTS (declared, not hidden): historical order-book depth and open interest
do not exist as point-in-time series. Their FRESHNESS at decision time is a known fact
(the bot was live-scanning; stale feeds would have blocked the scan), but their VALUES are
not recoverable. MODE B therefore assumes a benign spread and reports sensitivity across
0.02-0.20%; it is an experiment, not a production path.
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, "/home/naufal-ananta/bot/bingx-short-agent")

import market_features as mf  # noqa: E402
from market_features import (  # noqa: E402
    compute_market_features,
    hard_gate,
    PRODUCTION_CANDLE_BUFFER_MS,
)
from strategy_playbook import evaluate_playbooks  # noqa: E402

BASE_URL = "https://open-api.bingx.com"
SPREAD_CASES = [0.02, 0.05, 0.10, 0.20]


def api_get(path, params):
    url = f"{BASE_URL}{path}?" + urllib.parse.urlencode(params)
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
        raise RuntimeError(f"klines {symbol} {interval}: {j.get('code')} {j.get('msg')}")
    return j.get("data") or []


def fetch_funding(symbol, end_ms):
    j = api_get("/openApi/swap/v2/quote/fundingRate", {
        "symbol": symbol, "startTime": end_ms - 8 * 3_600_000, "endTime": end_ms, "limit": 50,
    })
    rows = sorted(j.get("data") or [], key=lambda r: r.get("fundingTime", 0))
    return rows[-1] if rows else None


def depth_for_spread(price, spread_pct, ts_ms):
    """Synthetic order book producing exactly `spread_pct`. Only the spread is consumed
    by the gate; the levels exist so the pipeline has a well-formed book."""
    half = price * (spread_pct / 100.0) / 2.0
    bid = round(price - half, 8)
    ask = round(price + half, 8)
    return {"bids": [[str(bid), "1000"]], "asks": [[str(ask), "1000"]], "T": ts_ms}


def main():
    with open("/home/naufal-ananta/.hermes/cache/scratch/falsification_decisions.json") as fh:
        decisions = json.load(fh)

    results = []
    for d in decisions:
        symbol = d["symbol"]
        want = "LONG" if d["decision"].endswith("LONG") else "SHORT"
        dec_ms = int(datetime.fromisoformat(d["ts"]).timestamp() * 1000)
        rec = dict(d)

        try:
            klines = {tf: fetch_klines(symbol, tf, dec_ms, 300) for tf in ("1m", "15m", "1h")}
            fund = fetch_funding(symbol, dec_ms)
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
            results.append(rec)
            print(f"{symbol:18s} ERROR {exc}")
            continue

        funding = {"lastFundingRate": (fund or {}).get("fundingRate"),
                   "updateTime": (fund or {}).get("fundingTime", dec_ms)}

        raw15 = klines["15m"]
        closed15 = mf._closed_rows(raw15, dec_ms, interval="15m", buffer_ms=PRODUCTION_CANDLE_BUFFER_MS)
        rec["closed_15m"] = len(closed15)
        rec["intrabar_leaked"] = sum(
            1 for r in raw15 if (r.get("time", 0) + 900_000) > dec_ms - PRODUCTION_CANDLE_BUFFER_MS
        )

        # ---- MODE A: production-faithful (depth/OI absent -> freshness fails closed)
        featsA = compute_market_features(
            klines, funding, {"openInterest": None, "time": dec_ms},
            {"bids": [], "asks": [], "T": dec_ms}, dec_ms,
            buffer_ms=PRODUCTION_CANDLE_BUFFER_MS,
        )
        okA, reasonsA = hard_gate(featsA, 0.35, direction=want)
        rec["modeA_pass"], rec["modeA_reasons"] = okA, reasonsA

        # ---- ATR context (independent of the friction assumption)
        tf = featsA.get("timeframes") or {}
        atr_pct = max(
            float((tf.get("1h") or {}).get("atr_pct", 0.0) or 0.0),
            float((tf.get("15m") or {}).get("atr_pct", 0.0) or 0.0),
        )
        rec["atr_pct"] = round(atr_pct, 4)

        # ---- MODE B: candle-conditioned. Freshness known-true; spread swept.
        modeB = {}
        featsB_ref = None
        for sp in SPREAD_CASES:
            last = closed15[-1]["close"] if closed15 else 1.0
            featsB = compute_market_features(
                klines, funding, {"openInterest": None, "time": dec_ms},
                depth_for_spread(last, sp, dec_ms), dec_ms,
                buffer_ms=PRODUCTION_CANDLE_BUFFER_MS,
            )
            featsB["fresh"] = True
            okB, reasonsB = hard_gate(featsB, 0.35, direction=want)
            modeB[f"{sp:.2f}"] = {"pass": okB, "reasons": reasonsB,
                                  "atr_to_friction": round(float(featsB.get("atr_to_friction") or 0.0), 3)}
            if abs(sp - 0.05) < 1e-9:
                featsB_ref = featsB
        rec["modeB_by_spread"] = modeB
        rec["modeB_pass_005"] = modeB["0.05"]["pass"]

        # ---- playbook under the FIXED rules (uses the 0.05% reference features)
        pb = evaluate_playbooks(symbol, closed15[-1]["close"] if closed15 else 0.0,
                                0.0, 0.05, featsB_ref)
        rec["playbook_fixed"] = pb.playbook
        rec["playbook_dir_fixed"] = pb.direction
        rec["playbook_score_fixed"] = pb.score
        rec["dir_match"] = (pb.playbook != "NONE" and pb.direction == want)
        rec["divergence_fixed"] = (featsA.get("rsi") or {}).get("divergence")
        rec["divergence_baseline"] = mf._detect_rsi_divergence_unaligned(closed15)
        rec["rsi_15m"] = round(float((featsA.get("rsi") or {}).get("rsi_15m") or 0.0), 2)
        rec["ema_trend"] = (featsA.get("ema_trend") or {}).get("trend")
        rec["ema_valid"] = (featsA.get("ema_trend") or {}).get("valid")

        results.append(rec)
        print(f"{symbol:18s} {d['decision']:12s} A={'PASS' if okA else 'BLOCK':5s} "
              f"B@0.05={'PASS' if rec['modeB_pass_005'] else 'BLOCK':5s} "
              f"atr%={rec['atr_pct']:6.3f} pb={pb.playbook:16s} "
              f"dir={'MATCH' if rec['dir_match'] else 'MISS':5s} "
              f"div {rec['divergence_baseline']}->{rec['divergence_fixed']}")

    out = "/home/naufal-ananta/.hermes/cache/scratch/falsification_results.json"
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2)

    ok = [r for r in results if "error" not in r]
    n = len(ok)
    print(f"\n=== SUMMARY (n={n}) ===")
    print(f"MODE A (production-faithful) blocked : {sum(1 for r in ok if not r['modeA_pass'])}/{n}")
    for sp in SPREAD_CASES:
        k = f"{sp:.2f}"
        blocked = sum(1 for r in ok if not r["modeB_by_spread"][k]["pass"])
        print(f"MODE B blocked @spread {k}%        : {blocked}/{n}")
    print(f"playbook endorses AI direction       : {sum(1 for r in ok if r['dir_match'])}/{n}")
    print(f"playbook returns NONE                : {sum(1 for r in ok if r['playbook_fixed'] == 'NONE')}/{n}")
    print(f"divergence changed by F-08           : {sum(1 for r in ok if r['divergence_baseline'] != r['divergence_fixed'])}/{n}")
    print(f"intrabar bars leaked                 : {sum(1 for r in ok if r['intrabar_leaked'] > 0)}/{n}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
