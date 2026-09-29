"""Session Orchestrator managing quota, execution gates, and dry-run/live modes."""

import time
import uuid
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from config import AppConfig
from client import BingXClient, BingXAPIError
from sizing import SizingCalculator, SizingResult
from scanner import MarketScanner, CandidatePair
from ai_evaluator import AIEvaluator, AIEvaluationResult
from audit_logger import AuditLogger
from market_features import build_candidate_features, hard_gate

class SessionState(BaseModel):
    session_id: str
    status: str = "IDLE"  # IDLE, ACTIVE_SEARCHING, EXECUTING_ENTRY, EXHAUSTED, TERMINATED
    margin_per_pos: float
    leverage: int
    quota: int
    filled_count: int = 0
    executed_symbols: List[str] = Field(default_factory=list)
    started_at: float = 0.0


MAX_TRIAGE_CANDIDATES = 12
MAX_DEEP_CANDIDATES = 1
MAX_CYCLE_TOKENS = 30000

class SessionOrchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = BingXClient(config)
        self.scanner = MarketScanner(self.client, config)
        self.ai = AIEvaluator(config)
        self.current_session: Optional[SessionState] = None

    def start_session(self, margin_per_pos: float = 5.0, leverage: int = 20, quota: int = 2) -> SessionState:
        """Initializes and activates a new entry session."""
        session_id = f"bx_sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self.current_session = SessionState(
            session_id=session_id,
            status="ACTIVE_SEARCHING",
            margin_per_pos=margin_per_pos,
            leverage=min(leverage, 20),
            quota=quota,
            started_at=time.time()
        )
        AuditLogger.log_event("SESSION_START", {
            "margin_per_pos": margin_per_pos,
            "leverage": min(leverage, 20),
            "quota": quota
        }, session_id=session_id)
        return self.current_session

    def stop_session(self) -> Optional[SessionState]:
        """Terminates active session without touching existing open positions."""
        if self.current_session:
            self.current_session.status = "TERMINATED"
        return self.current_session

    def run_cycle(self, dry_run: bool = True, limit_candidates: int = 5) -> Dict[str, Any]:
        """
        Executes one full scan-evaluate-execute cycle:
        1. Checks quota
        2. Scans unoccupied memecoins
        3. Requests AI review via 9Router
        4. Calculates exact lot sizing
        5. Executes order (if dry_run=False) or returns order plan (if dry_run=True)
        """
        if not self.current_session or self.current_session.status != "ACTIVE_SEARCHING":
            return {"status": "NO_ACTIVE_SESSION", "message": "No active session in searching state."}

        if self.current_session.filled_count >= self.current_session.quota:
            self.current_session.status = "EXHAUSTED"
            return {"status": "QUOTA_EXHAUSTED", "filled": self.current_session.filled_count, "quota": self.current_session.quota}

        # Step 1: Scan candidates
        candidates = self.scanner.scan_universe(mode=self.config.universe_mode, limit_candidates=limit_candidates)
        if not candidates:
            return {"status": "NO_CANDIDATES", "message": "No eligible unoccupied pairs found."}

        cycle_results = []

        deep_count = 0
        cycle_tokens = 0
        for cand in candidates:
            # Check if quota reached during cycle
            if self.current_session.filled_count >= self.current_session.quota:
                self.current_session.status = "EXHAUSTED"
                break

            # Fetch recent 15m klines for AI
            try:
                klines = self.client.get_klines(cand.symbol, interval="15m", limit=10)
                closes = [k.get("close") for k in klines if "close" in k]
            except Exception:
                closes = []

            try:
                market_features = build_candidate_features(self.client, cand.symbol)
                allowed, gate_reasons = hard_gate(market_features, self.config.max_spread_pct)
            except Exception as exc:
                market_features = {"fresh": False}
                allowed, gate_reasons = False, [f"feature_error:{type(exc).__name__}"]

            if not allowed:
                cycle_results.append({
                    "symbol": cand.symbol,
                    "price": cand.last_price,
                    "ai_decision": "SKIP",
                    "ai_confidence": 0,
                    "ai_evidence": "Deterministic hard gate rejected candidate",
                    "risk_factors": ",".join(gate_reasons),
                    "market_features": market_features,
                    "executed": False,
                    "order_id": None,
                })
                AuditLogger.log_event("HARD_GATE_REJECT", {
                    "symbol": cand.symbol,
                    "reasons": gate_reasons,
                }, session_id=self.current_session.session_id)
                continue

            # Step 2: AI Evaluation via 9Router
            candidate_payload = {
                "symbol": cand.symbol,
                "price": cand.last_price,
                "price_change_24h": cand.price_change_percent,
                "spread_pct": cand.spread_percent,
                "klines_15m_closes": closes[-5:] if closes else [],
                "market_features": market_features,
            }
            if deep_count < MAX_DEEP_CANDIDATES and cycle_tokens < MAX_CYCLE_TOKENS:
                ai_res = self.ai.evaluate_adversarial(candidate_payload)
                deep_count += 1
            else:
                ai_res = self.ai.evaluate_candidate(
                    symbol=cand.symbol,
                    price_change_24h=cand.price_change_percent,
                    current_price=cand.last_price,
                    klines_summary=closes,
                    spread_pct=cand.spread_percent,
                    market_features=market_features
                )
            cycle_tokens += int(ai_res.usage.get("total_tokens", 0) or 0)
            AuditLogger.log_ai_evaluation(
                symbol=cand.symbol,
                decision=ai_res.decision,
                confidence=ai_res.confidence,
                evidence=ai_res.key_evidence,
                risk_factors=ai_res.risk_factors,
                model=self.config.ai_model_name,
                session_id=self.current_session.session_id,
                usage=ai_res.usage,
                latency_ms=ai_res.latency_ms
            )

            # Step 3: Sizing
            sizing = SizingCalculator.calculate_lot(
                symbol=cand.symbol,
                margin_usdt=self.current_session.margin_per_pos,
                target_leverage=self.current_session.leverage,
                current_price=cand.last_price,
                contract_info=cand.contract_info,
                max_allowed_leverage=20
            )

            execution_report: Dict[str, Any] = {
                "symbol": cand.symbol,
                "price": cand.last_price,
                "ai_decision": ai_res.decision,
                "ai_confidence": ai_res.confidence,
                "ai_evidence": ai_res.key_evidence,
                "sizing": sizing.model_dump(),
                "executed": False,
                "order_id": None
            }

            if ai_res.decision == "ENTER_SHORT" and sizing.is_valid:
                client_order_id = f"bx_short_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                
                if dry_run:
                    execution_report["executed"] = False
                    execution_report["dry_run"] = True
                    execution_report["client_order_id"] = client_order_id
                    execution_report["message"] = (
                        f"[DRY-RUN] Pre-flight: Set leverage to {sizing.effective_leverage}x | "
                        f"Submit SHORT MARKET order: {sizing.quantity} {cand.symbol}"
                    )
                    self.current_session.filled_count += 1
                    self.current_session.executed_symbols.append(cand.symbol)
                else:
                    try:
                        # Pre-Flight Leverage Assertion (MANDATORY GATE):
                        # Exchange defaults new pairs to 5x. We must set target leverage before placing the order.
                        self.client.set_leverage(
                            symbol=cand.symbol,
                            leverage=sizing.effective_leverage,
                            side="SHORT"
                        )
                        execution_report["leverage_set"] = sizing.effective_leverage
                        AuditLogger.log_leverage_adjustment(
                            symbol=cand.symbol,
                            leverage=sizing.effective_leverage,
                            side="SHORT",
                            session_id=self.current_session.session_id
                        )

                        order_res = self.client.place_order(
                            symbol=cand.symbol,
                            side="SELL",
                            position_side="SHORT",
                            order_type="MARKET",
                            quantity=sizing.quantity,
                            client_order_id=client_order_id
                        )
                        execution_report["executed"] = True
                        execution_report["dry_run"] = False
                        execution_report["client_order_id"] = client_order_id
                        execution_report["order_id"] = order_res.get("orderId")
                        self.current_session.filled_count += 1
                        self.current_session.executed_symbols.append(cand.symbol)

                        AuditLogger.log_order_submission(
                            symbol=cand.symbol,
                            side="SELL",
                            position_side="SHORT",
                            order_type="MARKET",
                            quantity=sizing.quantity,
                            price=cand.last_price,
                            client_order_id=client_order_id,
                            order_id=order_res.get("orderId"),
                            status="FILLED",
                            session_id=self.current_session.session_id
                        )
                    except BingXAPIError as e:
                        execution_report["executed"] = False
                        execution_report["error"] = str(e)
                        AuditLogger.log_event("ORDER_ERROR", {
                            "symbol": cand.symbol,
                            "error": str(e),
                            "client_order_id": client_order_id
                        }, session_id=self.current_session.session_id)

            cycle_results.append(execution_report)

        if self.current_session.filled_count >= self.current_session.quota:
            self.current_session.status = "EXHAUSTED"

        AuditLogger.log_event("CYCLE_SUMMARY", {
            "candidate_count": len(candidates),
            "deep_review_count": deep_count,
            "total_ai_tokens": cycle_tokens,
            "token_budget": MAX_CYCLE_TOKENS,
            "quota_filled": self.current_session.filled_count,
        }, session_id=self.current_session.session_id)

        return {
            "session_id": self.current_session.session_id,
            "session_status": self.current_session.status,
            "filled_count": self.current_session.filled_count,
            "quota": self.current_session.quota,
            "evaluations": cycle_results
        }
