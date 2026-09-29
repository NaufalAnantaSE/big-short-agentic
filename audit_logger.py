"""Structured JSONL Audit Logger for recording development and live trading events."""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

LOGS_DIR = Path(__file__).resolve().parent / "logs"
AUDIT_LOG_FILE = LOGS_DIR / "audit.jsonl"

class AuditLogger:
    @classmethod
    def _ensure_dir(cls):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def log_event(cls, event_type: str, details: Dict[str, Any], session_id: Optional[str] = None):
        cls._ensure_dir()
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "session_id": session_id,
            "data": details
        }
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    @classmethod
    def log_leverage_adjustment(cls, symbol: str, leverage: int, side: str = "SHORT", session_id: Optional[str] = None):
        cls.log_event("LEVERAGE_ADJUSTMENT", {
            "symbol": symbol,
            "leverage": leverage,
            "side": side,
            "status": "ASSERTED"
        }, session_id=session_id)

    @classmethod
    def log_order_submission(
        cls,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: float,
        price: Optional[float],
        client_order_id: str,
        order_id: Optional[Any],
        status: str,
        session_id: Optional[str] = None
    ):
        cls.log_event("ORDER_SUBMISSION", {
            "symbol": symbol,
            "side": side,
            "position_side": position_side,
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "client_order_id": client_order_id,
            "order_id": str(order_id) if order_id else None,
            "status": status
        }, session_id=session_id)

    @classmethod
    def log_ai_evaluation(
        cls,
        symbol: str,
        decision: str,
        confidence: int,
        evidence: str,
        risk_factors: str,
        model: str,
        session_id: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        latency_ms: float = 0.0
    ):
        cls.log_event("AI_EVALUATION", {
            "symbol": symbol,
            "decision": decision,
            "confidence": confidence,
            "key_evidence": evidence,
            "risk_factors": risk_factors,
            "model_name": model,
            "usage": usage or {},
            "latency_ms": latency_ms
        }, session_id=session_id)
