#!/usr/bin/env python3
"""
Fase 3: Experimental Validation Harness (Shadow & Replay).

This module computes the metrics required by the live-money protocol from a REAL
replay dataset. It deliberately contains NO trade outcomes of its own.

WHY: a synthetic outcome list can be quoted as if it were an experiment result.
The earlier version of this file shipped hardcoded "baseline" and "LLM" trade lists
and a `run_synthetic_shadow_test()` entry point. Those numbers were not a market
replay, did not call the scanner/gates/model, and must never appear in any report
except as a record-shape example. They have been removed.

Required metrics per experiment (computed here):
- Net expectancy in R
- Profit factor
- Max drawdown in R
- MAE / MFE distributions
- Full costs (fee + funding + slippage)
- Confidence calibration buckets vs realized win rate
- Stratification by playbook, direction, execution path, and fallback status

Record shape (FORMAT EXAMPLE ONLY — zeros, not results):

    {
      "symbol": "EXAMPLE-USDT",
      "playbook": "PUMP_EXHAUSTION",
      "direction": "SHORT",
      "realized_r": 0.0,
      "holding_time_s": 0,
      "fee": 0.0,
      "funding_fee": 0.0,
      "slippage_pct": 0.0,
      "mae_pct": 0.0,
      "mfe_pct": 0.0,
      "ai_confidence": 0.0,
      "is_fallback": false,
      "execution_path": "DIRECT",
      "quote_ts": 0,
      "entry_ts": 0,
      "exit_ts": 0,
      "exit_reason": "TP"
    }
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Sequence
from collections import defaultdict

REQUIRED_FIELDS = ("symbol", "playbook", "direction", "realized_r")


class ReplayDatasetError(ValueError):
    """Raised when a replay dataset is missing, malformed, or lacks provenance."""


@dataclass
class ReplayTradeResult:
    symbol: str
    playbook: str
    direction: str  # LONG or SHORT
    realized_r: float
    holding_time_s: int = 0
    fee: float = 0.0
    funding_fee: float = 0.0
    slippage_pct: float = 0.0
    mae_pct: float = 0.0  # Maximum Adverse Excursion (% against entry)
    mfe_pct: float = 0.0  # Maximum Favorable Excursion (% in favor of entry)
    ai_confidence: float = 0.0
    is_fallback: bool = False
    execution_path: str = "UNKNOWN"  # DIRECT | FALLBACK | WATCHLIST
    quote_ts: int = 0
    entry_ts: int = 0
    exit_ts: int = 0
    exit_reason: str = "UNKNOWN"


def _require_finite_number(record: Dict[str, Any], key: str, source: str) -> float:
    raw = record.get(key, 0.0)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ReplayDatasetError(f"{source}: field '{key}' must be numeric, got {raw!r}")
    return float(raw)


def parse_replay_records(records: Sequence[Dict[str, Any]], source: str = "<memory>") -> List[ReplayTradeResult]:
    """Validates raw replay records (fail-closed) and converts them to typed results."""
    if not records:
        raise ReplayDatasetError(f"{source}: dataset is empty; refusing to compute metrics")

    parsed: List[ReplayTradeResult] = []
    for index, record in enumerate(records):
        where = f"{source}[{index}]"
        if not isinstance(record, dict):
            raise ReplayDatasetError(f"{where}: record must be an object, got {type(record).__name__}")
        missing = [f for f in REQUIRED_FIELDS if record.get(f) in (None, "")]
        if missing:
            raise ReplayDatasetError(f"{where}: missing required field(s): {', '.join(missing)}")

        direction = str(record["direction"]).upper()
        if direction not in ("LONG", "SHORT"):
            raise ReplayDatasetError(f"{where}: direction must be LONG or SHORT, got {record['direction']!r}")

        parsed.append(ReplayTradeResult(
            symbol=str(record["symbol"]),
            playbook=str(record["playbook"]),
            direction=direction,
            realized_r=_require_finite_number(record, "realized_r", where),
            holding_time_s=int(_require_finite_number(record, "holding_time_s", where)),
            fee=_require_finite_number(record, "fee", where),
            funding_fee=_require_finite_number(record, "funding_fee", where),
            slippage_pct=_require_finite_number(record, "slippage_pct", where),
            mae_pct=_require_finite_number(record, "mae_pct", where),
            mfe_pct=_require_finite_number(record, "mfe_pct", where),
            ai_confidence=_require_finite_number(record, "ai_confidence", where),
            is_fallback=bool(record.get("is_fallback", False)),
            execution_path=str(record.get("execution_path", "UNKNOWN")).upper(),
            quote_ts=int(_require_finite_number(record, "quote_ts", where)),
            entry_ts=int(_require_finite_number(record, "entry_ts", where)),
            exit_ts=int(_require_finite_number(record, "exit_ts", where)),
            exit_reason=str(record.get("exit_reason", "UNKNOWN")).upper(),
        ))
    return parsed


def load_replay_dataset(path: str) -> List[ReplayTradeResult]:
    """
    Loads a real replay dataset from a JSON file. Fails closed when the file is
    missing, unreadable, malformed, or contains no usable records.
    """
    if not path or not os.path.isfile(path):
        raise ReplayDatasetError(f"replay dataset not found: {path!r}; refusing to fabricate results")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayDatasetError(f"replay dataset unreadable ({path}): {exc}") from exc

    if isinstance(payload, dict):
        records = payload.get("trades")
        if records is None:
            raise ReplayDatasetError(f"{path}: expected a JSON array or an object with a 'trades' array")
    else:
        records = payload

    if not isinstance(records, list):
        raise ReplayDatasetError(f"{path}: 'trades' must be an array")
    return parse_replay_records(records, source=path)


def calculate_experiment_metrics(trades: Sequence[ReplayTradeResult]) -> Dict[str, Any]:
    """Computes standard trading metrics required for live-money validation."""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "net_expectancy_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "total_fee": 0.0,
            "total_funding": 0.0,
            "avg_holding_time_s": 0.0,
            "avg_mae_pct": 0.0,
            "avg_mfe_pct": 0.0,
        }

    wins = [t for t in trades if t.realized_r > 0]
    losses = [t for t in trades if t.realized_r < 0]
    total_trades = len(trades)
    win_rate = len(wins) / total_trades

    total_r_gain = sum(t.realized_r for t in wins)
    total_r_loss = abs(sum(t.realized_r for t in losses))
    net_r = sum(t.realized_r for t in trades)
    net_expectancy_r = net_r / total_trades

    profit_factor = (total_r_gain / total_r_loss) if total_r_loss > 0 else (float("inf") if total_r_gain > 0 else 0.0)

    cumulative_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for t in trades:
        cumulative_r += t.realized_r
        if cumulative_r > peak_r:
            peak_r = cumulative_r
        dd = peak_r - cumulative_r
        if dd > max_dd_r:
            max_dd_r = dd

    total_fee = sum(t.fee for t in trades)
    total_funding = sum(t.funding_fee for t in trades)
    avg_mae = sum(t.mae_pct for t in trades) / total_trades
    avg_mfe = sum(t.mfe_pct for t in trades) / total_trades
    avg_holding = sum(t.holding_time_s for t in trades) / total_trades

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "net_r": round(net_r, 4),
        "net_expectancy_r": round(net_expectancy_r, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_r": round(max_dd_r, 4),
        "total_fee": round(total_fee, 4),
        "total_funding": round(total_funding, 4),
        "avg_holding_time_s": round(avg_holding, 1),
        "avg_mae_pct": round(avg_mae, 4),
        "avg_mfe_pct": round(avg_mfe, 4),
    }


def calibrate_confidence_buckets(trades: Sequence[ReplayTradeResult]) -> Dict[str, Dict[str, Any]]:
    """
    Groups trades by AI confidence into 10% buckets and computes empirical win
    rate and expectancy per bucket. Confidence is NOT a probability until calibrated here.
    """
    bucket_ranges = [
        ("50-60", 50.0, 60.0),
        ("60-70", 60.0, 70.0),
        ("70-80", 70.0, 80.0),
        ("80-90", 80.0, 90.0),
        ("90-100", 90.0, 100.0),
    ]

    buckets: Dict[str, Dict[str, Any]] = {}
    for name, low, high in bucket_ranges:
        if name == "90-100":
            matched = [t for t in trades if low <= t.ai_confidence <= high]
        else:
            matched = [t for t in trades if low <= t.ai_confidence < high]

        count = len(matched)
        wins = sum(1 for t in matched if t.realized_r > 0)
        win_rate = (wins / count) if count > 0 else 0.0
        net_r = sum(t.realized_r for t in matched)
        expectancy = (net_r / count) if count > 0 else 0.0

        buckets[name] = {
            "count": count,
            "wins": wins,
            "win_rate": round(win_rate, 4),
            "net_r": round(net_r, 4),
            "expectancy_r": round(expectancy, 4),
        }

    return buckets


def _group_metrics(trades: Sequence[ReplayTradeResult], key) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[ReplayTradeResult]] = defaultdict(list)
    for t in trades:
        grouped[str(key(t))].append(t)
    return {name: calculate_experiment_metrics(items) for name, items in grouped.items()}


def run_replay_report(trades: Sequence[ReplayTradeResult]) -> Dict[str, Any]:
    """
    Produces the Fase 3 report from a validated replay dataset. There is no
    synthetic path: callers must supply real trades with provenance.
    """
    if not trades:
        raise ReplayDatasetError("run_replay_report: refusing to report on an empty dataset")

    return {
        "overall": calculate_experiment_metrics(trades),
        "confidence_calibration": calibrate_confidence_buckets(trades),
        "stratification_by_playbook": _group_metrics(trades, lambda t: t.playbook),
        "stratification_by_direction": _group_metrics(trades, lambda t: t.direction),
        "stratification_by_execution_path": _group_metrics(trades, lambda t: t.execution_path),
        "stratification_by_fallback": _group_metrics(trades, lambda t: "FALLBACK" if t.is_fallback else "SUCCESS"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fase 3 replay metrics (requires a real dataset)")
    parser.add_argument("--dataset", required=True, help="Path to a JSON replay dataset")
    parser.add_argument("--out", default=None, help="Optional path to write the JSON report")
    args = parser.parse_args()

    dataset = load_replay_dataset(args.dataset)
    report = run_replay_report(dataset)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote replay report to {args.out}")
    else:
        print(text)
