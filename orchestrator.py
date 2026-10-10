"""Session Orchestrator managing quota, execution gates, and dry-run/live modes."""

import time
import uuid
import threading
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from config import AppConfig
from client import BingXClient, BingXAPIError
from sizing import SizingCalculator, SizingResult
from scanner import MarketScanner, CandidatePair
from ai_evaluator import AIEvaluator, AIEvaluationResult, BatchTriageResult, TriageCandidate
from audit_logger import AuditLogger
from market_features import build_candidate_features, hard_gate
from contracts import Environment, ExecutionMode, DirectionMode, ExitPolicy, TradeAction, PlaybookType
from strategy_playbook import evaluate_playbooks, PlaybookMatch
from watchlist_manager import WatchlistManager


def _evaluate_hard_gate(
    market_features: Dict[str, Any],
    max_spread_pct: float,
    direction: str = "SHORT"
) -> tuple[bool, list[str]]:
    """Evaluates hard_gate with direction awareness, defaulting to SHORT."""
    try:
        return hard_gate(market_features, max_spread_pct, direction=direction)
    except TypeError:
        return hard_gate(market_features, max_spread_pct)


def _safe_rr(raw: Any, default: float = 2.0) -> float:
    """Safely coerces recommended R:R to float with min 2.0 guardrail, protecting against non-numeric payloads."""
    try:
        val = float(raw)
        import math
        return val if math.isfinite(val) and val >= 2.0 else default
    except (ValueError, TypeError):
        return default


class SessionState(BaseModel):
    session_id: str
    status: str = "IDLE"  # IDLE, ACTIVE_SEARCHING, EXECUTING_ENTRY, EXHAUSTED, TERMINATED
    generation_token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    margin_per_pos: float
    leverage: int
    quota: int
    filled_count: int = 0
    environment: str = Environment.BINGX_VST.value
    execution_mode: str = ExecutionMode.EXCHANGE_DEMO.value
    direction_mode: str = DirectionMode.SHORT.value
    exit_policy: str = ExitPolicy.MANUAL_ONLY.value
    universe_mode: str = "PUMP_GAINERS"
    executed_symbols: List[str] = Field(default_factory=list)
    started_at: float = 0.0


MAX_TRIAGE_CANDIDATES = 12
MAX_CYCLE_TOKENS = 30000

class SessionOrchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = BingXClient(config)
        self.scanner = MarketScanner(self.client, config)
        self.ai = AIEvaluator(config)
        self.watchlist = WatchlistManager()
        self.current_session: Optional[SessionState] = None
        self._session_lock = threading.Lock()

    def start_session(
        self,
        margin_per_pos: float = 5.0,
        leverage: int = 20,
        quota: int = 2,
        environment: str = Environment.BINGX_VST.value,
        execution_mode: str = ExecutionMode.EXCHANGE_DEMO.value,
        direction_mode: str = DirectionMode.SHORT.value,
        exit_policy: str = ExitPolicy.MANUAL_ONLY.value,
        universe_mode: str = "PUMP_GAINERS"
    ) -> SessionState:
        """Initializes and activates a new entry session."""
        session_id = f"bx_sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        self.config.universe_mode = universe_mode
        self.current_session = SessionState(
            session_id=session_id,
            status="ACTIVE_SEARCHING",
            margin_per_pos=margin_per_pos,
            leverage=min(leverage, 20),
            quota=quota,
            environment=environment,
            execution_mode=execution_mode,
            direction_mode=direction_mode,
            exit_policy=exit_policy,
            universe_mode=universe_mode,
            started_at=time.time()
        )
        AuditLogger.log_event("SESSION_START", {
            "margin_per_pos": margin_per_pos,
            "leverage": min(leverage, 20),
            "quota": quota,
            "environment": environment,
            "execution_mode": execution_mode,
            "direction_mode": direction_mode,
            "exit_policy": exit_policy,
            "universe_mode": universe_mode
        }, session_id=session_id)

        # Startup reconciliation: Phase 2 feature, removed from hot path
        self.watchlist.entries.clear()
        return self.current_session

    def stop_session(self) -> Optional[SessionState]:
        """Terminates active session, cancels all linked resting orders, and clears watchlist entries."""
        with self._session_lock:
            if self.current_session:
                self.current_session.status = "TERMINATED"
                self.current_session.generation_token = f"TERMINATED_{uuid.uuid4().hex}"
                for entry in self.watchlist.get_all_entries():
                    self.watchlist.cancel_entry_resting_order(
                        entry=entry,
                        reason="SESSION_STOPPED",
                        client=self.client,
                        session_id=self.current_session.session_id
                    )
                self.watchlist.entries.clear()
            return self.current_session

    def _evaluate_and_execute_candidate(
        self,
        sc: Dict[str, Any],
        deep_mode: bool,
        effective_dry_run: bool,
        is_local_paper: bool,
    ) -> tuple[Dict[str, Any], int, bool]:
        """Evaluates a single candidate and executes/dry-runs if signal is affirmative."""
        cand: CandidatePair = sc["cand"]
        closes: list = sc["closes"]
        market_features: Dict[str, Any] = sc["market_features"]
        playbook_match = sc["playbook_match"]
        atr_val = sc["atr_val"]
        cand_allowed = sc.get("allowed_directions", [])
        cand_sugg = sc.get("suggested_direction", "UNKNOWN")

        candidate_payload = {
            "symbol": cand.symbol,
            "price": cand.last_price,
            "price_change_24h": cand.price_change_percent,
            "spread_pct": cand.spread_percent,
            "klines_15m_closes": closes[-5:] if closes else [],
            "market_features": market_features,
            "playbook": playbook_match.model_dump() if playbook_match else {},
            "allowed_directions": cand_allowed,
            "suggested_direction": cand_sugg,
        }

        # Determine trade direction intent from candidate/features/session
        session_dir = getattr(self.current_session, "direction_mode", "SHORT") if self.current_session else "SHORT"
        if session_dir in ("LONG", "SHORT"):
            target_eval_dir = session_dir
        elif cand_sugg in ("LONG", "SHORT"):
            target_eval_dir = cand_sugg
        elif len(cand_allowed) == 1:
            target_eval_dir = cand_allowed[0]
        else:
            target_eval_dir = "BOTH"

        if deep_mode:
            # Tier 2: Single structured dialectical deep evaluation
            ai_res = self.ai.evaluate_deep_candidate(candidate_payload, direction=target_eval_dir)
        else:
            ai_res = self.ai.evaluate_candidate(
                symbol=cand.symbol,
                price_change_24h=cand.price_change_percent,
                current_price=cand.last_price,
                klines_summary=closes,
                spread_pct=cand.spread_percent,
                market_features=market_features,
                direction=target_eval_dir
            )

        tokens_used = int(ai_res.usage.get("total_tokens", 0) or 0)
        session_id = self.current_session.session_id if self.current_session else ""
        session_gen = getattr(self.current_session, "generation_token", "") if self.current_session else ""
        AuditLogger.log_ai_evaluation(
            symbol=cand.symbol,
            decision=ai_res.decision,
            confidence=ai_res.confidence,
            evidence=ai_res.key_evidence,
            risk_factors=ai_res.risk_factors,
            model=self.config.ai_model_name,
            session_id=session_id,
            usage=ai_res.usage,
            latency_ms=ai_res.latency_ms
        )

        is_short_intent = (ai_res.decision == "ENTER_SHORT")
        is_long_intent = (ai_res.decision == "ENTER_LONG")
        is_wait_intent = (ai_res.decision == "WAIT")

        if is_long_intent:
            pos_dir = "LONG"
        elif is_short_intent:
            pos_dir = "SHORT"
        elif is_wait_intent:
            # Preserve candidate direction into WAIT watchlist; WAIT must NOT infer SHORT from decision!
            if target_eval_dir in ("LONG", "SHORT"):
                pos_dir = target_eval_dir
            elif cand_sugg in ("LONG", "SHORT"):
                pos_dir = cand_sugg
            elif len(cand_allowed) == 1:
                pos_dir = cand_allowed[0]
            else:
                pos_dir = "UNKNOWN"
        else:
            pos_dir = "UNKNOWN"

        target_rr = _safe_rr(playbook_match.recommended_rr if playbook_match else 2.0)
        current_lev = self.current_session.leverage if self.current_session else 20
        effective_target_lev = current_lev
        if atr_val and cand.last_price > 0:
            est_sl_pct = min(6.0, max(1.5, (1.5 * float(atr_val) / cand.last_price) * 100.0))
            max_safe_lev = int(75.0 / est_sl_pct)
            if effective_target_lev > max_safe_lev:
                effective_target_lev = max(1, max_safe_lev)

        margin_per_pos = self.current_session.margin_per_pos if self.current_session else 5.0
        if pos_dir in ("LONG", "SHORT"):
            sizing = SizingCalculator.calculate_lot(
                symbol=cand.symbol,
                margin_usdt=margin_per_pos,
                target_leverage=effective_target_lev,
                current_price=cand.last_price,
                contract_info=cand.contract_info,
                max_allowed_leverage=20,
                direction=pos_dir,
                atr=atr_val,
                target_rr=target_rr
            )
        else:
            sizing = SizingResult(
                symbol=cand.symbol,
                target_margin=margin_per_pos,
                effective_leverage=effective_target_lev,
                entry_price=cand.last_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason=f"invalid_direction:{pos_dir}"
            )

        execution_report: Dict[str, Any] = {
            "symbol": cand.symbol,
            "price": cand.last_price,
            "ai_decision": ai_res.decision,
            "ai_confidence": ai_res.confidence,
            "ai_evidence": ai_res.key_evidence,
            "direction": pos_dir,
            "playbook": playbook_match.model_dump() if playbook_match else None,
            "sizing": sizing.model_dump(),
            "stop_loss_price": sizing.stop_loss_price,
            "take_profit_price": sizing.take_profit_price,
            "sl_percent": sizing.sl_percent,
            "tp_percent": sizing.tp_percent,
            "risk_amount_usdt": sizing.risk_amount_usdt,
            "potential_profit_usdt": sizing.potential_profit_usdt,
            "executed": False,
            "order_id": None
        }

        # Gate enforcement just before execution/watchlist
        direction_valid = pos_dir in ("LONG", "SHORT")
        session_allowed = (
            (session_dir == "BOTH" and direction_valid) or
            (session_dir == "SHORT" and pos_dir == "SHORT") or
            (session_dir == "LONG" and pos_dir == "LONG")
        )
        candidate_allowed = (not cand_allowed) or (pos_dir in cand_allowed)
        gate_ok = False
        gate_reasons = []
        if direction_valid:
            gate_ok, gate_reasons = _evaluate_hard_gate(market_features, self.config.max_spread_pct, direction=pos_dir)

        veto_reason = None
        if is_short_intent or is_long_intent:
            if not direction_valid:
                veto_reason = f"invalid_or_unknown_direction:{pos_dir}"
            elif not session_allowed:
                veto_reason = f"direction_{pos_dir}_barred_in_{session_dir}_session"
            elif not candidate_allowed:
                veto_reason = f"direction_{pos_dir}_barred_for_candidate"
            elif not gate_ok:
                veto_reason = f"hard_gate_rejected_{pos_dir}:{','.join(gate_reasons)}"

        # P0-2: Fresh quote revalidation and executable price re-sizing before order execution
        executable_price = cand.last_price
        quote_ts = int(time.time() * 1000)
        if (is_short_intent or is_long_intent) and not veto_reason:
            fresh_quote = None
            try:
                fresh_depth = self.client.get_depth(cand.symbol, limit=5)
                if fresh_depth and isinstance(fresh_depth, dict):
                    bids = fresh_depth.get("bids") or []
                    asks = fresh_depth.get("asks") or []
                    if bids and asks and len(bids[0]) >= 2 and len(asks[0]) >= 2:
                        b1 = float(bids[0][0])
                        a1 = float(asks[0][0])
                        q_ts = fresh_depth.get("T") or int(time.time() * 1000)
                        if b1 > 0 and a1 > 0:
                            fresh_quote = {"bid1": b1, "ask1": a1, "quote_ts": q_ts}
            except Exception:
                pass

            if fresh_quote is None and getattr(cand, "bid1", 0) > 0 and getattr(cand, "ask1", 0) > 0:
                fresh_quote = {
                    "bid1": cand.bid1,
                    "ask1": cand.ask1,
                    "quote_ts": int(time.time() * 1000)
                }

            if fresh_quote is None:
                veto_reason = "quote_unavailable_at_execution"
            else:
                bid1 = fresh_quote["bid1"]
                ask1 = fresh_quote["ask1"]
                quote_ts = fresh_quote["quote_ts"]
                executable_price = ask1 if pos_dir == "LONG" else bid1
                spread_pct = ((ask1 - bid1) / bid1 * 100.0) if bid1 > 0 else 999.0
                drift_pct = abs(executable_price - cand.last_price) / cand.last_price * 100.0 if cand.last_price > 0 else 999.0

                if drift_pct > 0.50:
                    veto_reason = f"price_drift_exceeded:{drift_pct:.2f}%>0.50%"
                elif spread_pct > self.config.max_spread_pct:
                    veto_reason = f"spread_too_wide_at_execution:{spread_pct:.2f}%>{self.config.max_spread_pct}%"
                else:
                    sizing = SizingCalculator.calculate_lot(
                        symbol=cand.symbol,
                        margin_usdt=margin_per_pos,
                        target_leverage=effective_target_lev,
                        current_price=executable_price,
                        contract_info=cand.contract_info,
                        max_allowed_leverage=20,
                        direction=pos_dir,
                        atr=atr_val,
                        target_rr=target_rr
                    )
                    if not sizing.is_valid:
                        veto_reason = f"resizing_invalid:{sizing.rejection_reason}"
                    else:
                        execution_report["sizing"] = sizing.model_dump()
                        execution_report["stop_loss_price"] = sizing.stop_loss_price
                        execution_report["take_profit_price"] = sizing.take_profit_price
                        execution_report["sl_percent"] = sizing.sl_percent
                        execution_report["tp_percent"] = sizing.tp_percent
                        execution_report["risk_amount_usdt"] = sizing.risk_amount_usdt
                        execution_report["potential_profit_usdt"] = sizing.potential_profit_usdt
                        execution_report["request_price"] = executable_price
                        execution_report["quote_ts"] = quote_ts

        # P0-4: Session-stop race protection
        if not self.current_session or self.current_session.status == "TERMINATED":
            curr_st = self.current_session.status if self.current_session else "NONE"
            veto_reason = f"SESSION_TERMINATED:{curr_st}"
        elif getattr(self.current_session, "generation_token", "") != session_gen:
            veto_reason = "SESSION_GENERATION_MISMATCH"
        elif self.current_session.session_id != session_id:
            veto_reason = "SESSION_ID_MISMATCH"

        if veto_reason:
            execution_report["veto_reason"] = veto_reason
            AuditLogger.log_event("TRADE_EXECUTION_VETO", {
                "symbol": cand.symbol,
                "ai_decision": ai_res.decision,
                "target_direction": pos_dir,
                "veto_reason": veto_reason
            }, session_id=session_id)

        placed = False
        can_execute = (
            (is_short_intent or is_long_intent) and
            direction_valid and
            session_allowed and
            candidate_allowed and
            gate_ok and
            not veto_reason and
            sizing.is_valid
        )

        if can_execute:
            target_pos_side = pos_dir
            target_order_side = "BUY" if target_pos_side == "LONG" else "SELL"
            prefix = "bx_long" if target_pos_side == "LONG" else "bx_short"
            client_order_id = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}"

            if effective_dry_run:
                tag = "[LOCAL-PAPER]" if is_local_paper else "[DRY-RUN]"
                execution_report["executed"] = False
                execution_report["dry_run"] = True
                execution_report["client_order_id"] = client_order_id
                execution_report["request_price"] = executable_price
                execution_report["avg_fill_price"] = executable_price
                execution_report["slippage"] = 0.0
                execution_report["slippage_pct"] = 0.0
                execution_report["quote_ts"] = quote_ts
                tpsl_info = f" [TP: ${sizing.take_profit_price} (+{sizing.tp_percent}%), SL: ${sizing.stop_loss_price} (-{sizing.sl_percent}%)]" if sizing.take_profit_price else ""
                execution_report["message"] = (
                    f"{tag} Pre-flight: Set leverage to {sizing.effective_leverage}x | "
                    f"Submit {target_pos_side} MARKET order: {sizing.quantity} {cand.symbol}{tpsl_info}"
                )
                if self.current_session:
                    self.current_session.filled_count += 1
                    self.current_session.executed_symbols.append(cand.symbol)
                placed = True
            else:
                try:
                    self.client.set_leverage(
                        symbol=cand.symbol,
                        leverage=sizing.effective_leverage,
                        side=target_pos_side
                    )
                    execution_report["leverage_set"] = sizing.effective_leverage
                    AuditLogger.log_leverage_adjustment(
                        symbol=cand.symbol,
                        leverage=sizing.effective_leverage,
                        side=target_pos_side,
                        session_id=session_id
                    )

                    order_res = self.client.place_order(
                        symbol=cand.symbol,
                        side=target_order_side,
                        position_side=target_pos_side,
                        order_type="MARKET",
                        quantity=sizing.quantity,
                        client_order_id=client_order_id,
                        stop_loss_price=sizing.stop_loss_price,
                        take_profit_price=sizing.take_profit_price
                    )
                    safe_res = order_res or {}
                    order_data = (safe_res.get("order") if isinstance(safe_res.get("order"), dict) else safe_res) or {}
                    order_id_raw = order_data.get("orderId") or safe_res.get("orderId") or client_order_id
                    order_id_str = str(order_id_raw)
                    order_status = order_data.get("status", "FILLED")
                    raw_avg = order_data.get("avgPrice") or order_data.get("price")
                    actual_avg_price = float(raw_avg) if raw_avg and float(raw_avg) > 0 else executable_price
                    slippage = actual_avg_price - executable_price
                    slippage_pct = (slippage / executable_price * 100.0) if executable_price > 0 else 0.0

                    execution_report["executed"] = True
                    execution_report["dry_run"] = False
                    execution_report["client_order_id"] = client_order_id
                    execution_report["order_id"] = order_id_str
                    execution_report["request_price"] = executable_price
                    execution_report["avg_fill_price"] = actual_avg_price
                    execution_report["slippage"] = slippage
                    execution_report["slippage_pct"] = slippage_pct
                    execution_report["quote_ts"] = quote_ts
                    execution_report["status"] = order_status
                    if self.current_session:
                        self.current_session.filled_count += 1
                        self.current_session.executed_symbols.append(cand.symbol)
                    placed = True

                    AuditLogger.log_order_submission(
                        symbol=cand.symbol,
                        side=target_order_side,
                        position_side=target_pos_side,
                        order_type="MARKET",
                        quantity=sizing.quantity,
                        price=executable_price,
                        client_order_id=client_order_id,
                        order_id=order_id_str,
                        status=order_status,
                        session_id=session_id,
                        stop_loss_price=sizing.stop_loss_price,
                        take_profit_price=sizing.take_profit_price,
                        quote_ts=quote_ts,
                        request_price=executable_price,
                        avg_fill_price=actual_avg_price,
                        slippage=slippage,
                        slippage_pct=slippage_pct
                    )
                except BingXAPIError as e:
                    execution_report["executed"] = False
                    execution_report["error"] = str(e)
                    AuditLogger.log_event("ORDER_ERROR", {
                        "symbol": cand.symbol,
                        "error": str(e),
                        "client_order_id": client_order_id
                    }, session_id=session_id)
        elif is_wait_intent and ai_res.confidence >= 65:
            if not direction_valid or not session_allowed or not candidate_allowed or not gate_ok:
                reasons_str = f"invalid_direction:{pos_dir}" if not direction_valid else (
                    f"barred_in_session:{session_dir}" if not session_allowed else (
                        f"barred_for_candidate" if not candidate_allowed else f"hard_gate:{','.join(gate_reasons)}"
                    )
                )
                execution_report["watchlist_status"] = f"VETOED_WATCHLIST: {reasons_str}"
                AuditLogger.log_event("WATCHLIST_VETO", {
                    "symbol": cand.symbol,
                    "target_direction": pos_dir,
                    "reason": reasons_str
                }, session_id=session_id)
            else:
                added, status_msg = self.watchlist.add_candidate(
                    symbol=cand.symbol,
                    current_price=cand.last_price,
                    conviction_score=ai_res.confidence,
                    playbook=str(playbook_match.playbook) if playbook_match else None,
                    atr=atr_val or 0.0,
                    direction=pos_dir,
                    margin_per_pos=margin_per_pos,
                    leverage=effective_target_lev,
                    stop_loss_price=sizing.stop_loss_price,
                    take_profit_price=sizing.take_profit_price,
                    client=self.client,
                    session_id=session_id
                )
                execution_report["watchlist_status"] = status_msg

        return execution_report, tokens_used, placed

    def run_cycle(self, dry_run: bool = True, limit_candidates: int = 8) -> Dict[str, Any]:
        """
        Executes one full scan-evaluate-execute cycle:
        1. Checks quota
        2. Scans unoccupied memecoins
        3. Requests AI review via 9Router
        4. Calculates exact lot sizing
        5. Executes order (if dry_run=False) or returns order plan (if dry_run=True)
        """
        if not self.current_session or self.current_session.status not in ("ACTIVE_SEARCHING", "EXHAUSTED"):
            return {"status": "NO_ACTIVE_SESSION", "message": "No active session in searching state."}

        session_id = self.current_session.session_id
        cycle_gen = getattr(self.current_session, "generation_token", "")

        try:
            occupied = self.scanner.get_occupied_symbols()
        except Exception as e:
            session_id = self.current_session.session_id if self.current_session else ""
            AuditLogger.log_event("EXPOSURE_UNKNOWN", {
                "error": str(e),
                "message": "Account exposure query failed; failing closed to prevent double-entry / quota violation."
            }, session_id=session_id)
            return {
                "status": "EXPOSURE_UNKNOWN",
                "error": str(e),
                "message": "Account exposure query failed; new entries blocked (fail-closed)."
            }

        occupied_count = len(occupied)
        self.current_session.filled_count = occupied_count

        # Strictly active positions determine available slots
        available_slots = self.current_session.quota - self.current_session.filled_count

        if available_slots <= 0:
            self.current_session.status = "EXHAUSTED"
            return {"status": "QUOTA_EXHAUSTED", "filled": self.current_session.filled_count, "quota": self.current_session.quota}

        if self.current_session.filled_count < self.current_session.quota and self.current_session.status == "EXHAUSTED":
            self.current_session.status = "ACTIVE_SEARCHING"

        is_local_paper = bool(self.current_session and self.current_session.execution_mode == ExecutionMode.LOCAL_PAPER.value)
        effective_dry_run = dry_run or is_local_paper

        cycle_results = []

        # Step 1: Active Watchlist Evaluation (Priority execution before general scan)
        for entry in self.watchlist.get_all_entries():
            if available_slots <= 0:
                break
            if entry.symbol in occupied:
                self.watchlist.evict_entry(entry.symbol, reason="POSITION_ALREADY_OPEN", client=self.client, session_id=self.current_session.session_id)
                continue

            try:
                w_klines = self.client.get_klines(entry.symbol, interval="15m", limit=15)
                w_depth = self.client.get_depth(entry.symbol, limit=5)
                bids = w_depth.get("bids", []) if isinstance(w_depth, dict) else []
                asks = w_depth.get("asks", []) if isinstance(w_depth, dict) else []
                bid1 = float(bids[0][0]) if bids else entry.initial_price
                ask1 = float(asks[0][0]) if asks else entry.initial_price
                w_curr_price = (bid1 + ask1) / 2.0 if bid1 > 0 and ask1 > 0 else entry.initial_price
                w_spread = ((ask1 - bid1) / bid1) * 100.0 if bid1 > 0 else 0.0

                should_evict, evict_reason, trigger_res = self.watchlist.check_deterministic_reversal(
                    entry=entry,
                    klines_15m=w_klines,
                    current_price=w_curr_price,
                    current_spread_pct=w_spread
                )

                if should_evict:
                    self.watchlist.evict_entry(entry.symbol, reason=evict_reason or "EVICTED", client=self.client, session_id=self.current_session.session_id)
                    continue

                if trigger_res.triggered:
                    AuditLogger.log_event("WATCHLIST_TRIGGER", {
                        "symbol": entry.symbol,
                        "pattern": trigger_res.pattern,
                        "trigger_price": w_curr_price,
                        "evidence": trigger_res.evidence,
                        "reasons": trigger_res.reasons
                    }, session_id=self.current_session.session_id)

                    contracts = self.client.get_contracts()
                    contract_info = next((c for c in contracts if c.get("symbol") == entry.symbol), {})

                    sizing = SizingCalculator.calculate_lot(
                        symbol=entry.symbol,
                        margin_usdt=self.current_session.margin_per_pos,
                        target_leverage=entry.leverage,
                        current_price=w_curr_price,
                        contract_info=contract_info,
                        max_allowed_leverage=20,
                        direction=entry.direction,
                        atr=entry.atr if entry.atr > 0 else None,
                        target_rr=2.0
                    )

                    if sizing.is_valid:
                        # P0-4: Session-stop race protection
                        if (
                            not self.current_session
                            or self.current_session.status == "TERMINATED"
                            or getattr(self.current_session, "generation_token", "") != cycle_gen
                            or self.current_session.session_id != session_id
                        ):
                            AuditLogger.log_event("TRADE_EXECUTION_VETO", {
                                "symbol": entry.symbol,
                                "veto_reason": "SESSION_TERMINATED_AT_WATCHLIST_TRIGGER"
                            }, session_id=session_id)
                            break

                        target_pos_side = entry.direction.upper()
                        target_order_side = "SELL" if target_pos_side == "SHORT" else "BUY"
                        prefix = "bx_short" if target_pos_side == "SHORT" else "bx_long"
                        client_order_id = f"{prefix}_wl_{int(time.time())}_{uuid.uuid4().hex[:6]}"

                        w_exec_report = {
                            "symbol": entry.symbol,
                            "price": w_curr_price,
                            "ai_decision": "ENTER_SHORT" if target_pos_side == "SHORT" else "ENTER_LONG",
                            "ai_confidence": entry.conviction_score,
                            "ai_evidence": f"[WATCHLIST_TRIGGER {trigger_res.pattern}] {trigger_res.evidence}",
                            "playbook": None,
                            "sizing": sizing.model_dump(),
                            "stop_loss_price": sizing.stop_loss_price,
                            "take_profit_price": sizing.take_profit_price,
                            "sl_percent": sizing.sl_percent,
                            "tp_percent": sizing.tp_percent,
                            "risk_amount_usdt": sizing.risk_amount_usdt,
                            "potential_profit_usdt": sizing.potential_profit_usdt,
                            "executed": False,
                            "order_id": None
                        }

                        if effective_dry_run:
                            tag = "[LOCAL-PAPER]" if is_local_paper else "[DRY-RUN]"
                            w_exec_report["executed"] = False
                            w_exec_report["dry_run"] = True
                            w_exec_report["client_order_id"] = client_order_id
                            tpsl_info = f" [TP: ${sizing.take_profit_price} (+{sizing.tp_percent}%), SL: ${sizing.stop_loss_price} (-{sizing.sl_percent}%)]" if sizing.take_profit_price else ""
                            w_exec_report["message"] = (
                                f"{tag} [WATCHLIST-REVERSAL] Set leverage {sizing.effective_leverage}x | "
                                f"Submit {target_pos_side} MARKET order: {sizing.quantity} {entry.symbol}{tpsl_info}"
                            )
                            self.current_session.filled_count += 1
                            self.current_session.executed_symbols.append(entry.symbol)
                            self.watchlist.evict_entry(entry.symbol, reason="TRIGGER_EXECUTED", client=self.client, session_id=self.current_session.session_id)
                            available_slots -= 1
                            cycle_results.append(w_exec_report)
                        else:
                            try:
                                self.client.set_leverage(
                                    symbol=entry.symbol,
                                    leverage=sizing.effective_leverage,
                                    side=target_pos_side
                                )
                                AuditLogger.log_leverage_adjustment(
                                    symbol=entry.symbol,
                                    leverage=sizing.effective_leverage,
                                    side=target_pos_side,
                                    session_id=self.current_session.session_id
                                )
                                order_res = self.client.place_order(
                                    symbol=entry.symbol,
                                    side=target_order_side,
                                    position_side=target_pos_side,
                                    order_type="MARKET",
                                    quantity=sizing.quantity,
                                    client_order_id=client_order_id,
                                    stop_loss_price=sizing.stop_loss_price,
                                    take_profit_price=sizing.take_profit_price
                                )
                                order_id_raw = order_res.get("orderId") or order_res.get("order", {}).get("orderId") or client_order_id
                                order_id_str = str(order_id_raw)
                                w_exec_report["executed"] = True
                                w_exec_report["dry_run"] = False
                                w_exec_report["client_order_id"] = client_order_id
                                w_exec_report["order_id"] = order_id_str
                                self.current_session.filled_count += 1
                                self.current_session.executed_symbols.append(entry.symbol)
                                self.watchlist.evict_entry(entry.symbol, reason="TRIGGER_EXECUTED", client=self.client, session_id=self.current_session.session_id)
                                available_slots -= 1

                                AuditLogger.log_order_submission(
                                    symbol=entry.symbol,
                                    side=target_order_side,
                                    position_side=target_pos_side,
                                    order_type="MARKET",
                                    quantity=sizing.quantity,
                                    price=w_curr_price,
                                    client_order_id=client_order_id,
                                    order_id=order_id_str,
                                    status="FILLED",
                                    session_id=self.current_session.session_id,
                                    stop_loss_price=sizing.stop_loss_price,
                                    take_profit_price=sizing.take_profit_price
                                )
                                cycle_results.append(w_exec_report)
                            except BingXAPIError as e:
                                w_exec_report["executed"] = False
                                w_exec_report["error"] = str(e)
                                AuditLogger.log_event("ORDER_ERROR", {
                                    "symbol": entry.symbol,
                                    "error": str(e),
                                    "client_order_id": client_order_id
                                }, session_id=self.current_session.session_id)
                                cycle_results.append(w_exec_report)
            except Exception as w_err:
                AuditLogger.log_event("WATCHLIST_EVAL_ERROR", {
                    "symbol": entry.symbol,
                    "error": str(w_err)
                }, session_id=self.current_session.session_id)

        # Step 2: Scan candidates if slots are still available
        if available_slots <= 0:
            return {
                "status": "WATCHLIST_ACTIVE",
                "message": "Watchlist evaluated; remaining slots occupied by resting orders or active positions.",
                "cycle_results": cycle_results
            }

        current_dir = getattr(self.current_session, "direction_mode", "SHORT") if self.current_session else "SHORT"
        current_universe_mode = getattr(self.current_session, "universe_mode", self.config.universe_mode) or self.config.universe_mode
        candidates = self.scanner.scan_universe(
            mode=current_universe_mode,
            limit_candidates=limit_candidates,
            direction=current_dir
        )
        if not candidates:
            return {
                "status": "NO_CANDIDATES" if not cycle_results else "WATCHLIST_EXECUTED",
                "message": "No eligible unoccupied pairs found." if not cycle_results else "Watchlist processed.",
                "cycle_results": cycle_results
            }

        # Collect screened candidates that pass hard gate
        session_allowed_dirs = ["SHORT", "LONG"] if current_dir == "BOTH" else ([current_dir] if current_dir in ("SHORT", "LONG") else ["SHORT"])
        screened_candidates = []
        for cand in candidates:
            if self.current_session.filled_count >= self.current_session.quota:
                self.current_session.status = "EXHAUSTED"
                break

            try:
                klines = self.client.get_klines(cand.symbol, interval="15m", limit=10)
                closes = [k.get("close") for k in klines if "close" in k]
            except Exception:
                closes = []

            try:
                market_features = build_candidate_features(self.client, cand.symbol)
            except Exception as exc:
                market_features = {"fresh": False}

            # Evaluate hard gate separately for each session-allowed direction
            cand_allowed_dirs = []
            all_gate_reasons = []
            for d in session_allowed_dirs:
                try:
                    d_ok, d_reasons = _evaluate_hard_gate(market_features, self.config.max_spread_pct, direction=d)
                except Exception as exc:
                    d_ok, d_reasons = False, [f"feature_error:{type(exc).__name__}"]
                if d_ok:
                    cand_allowed_dirs.append(d)
                else:
                    # Deduplicate while preserving order: universal reasons
                    # (e.g. spread_too_wide) repeat in every direction's
                    # evaluation and must not be displayed twice.
                    for r in d_reasons:
                        if r not in all_gate_reasons:
                            all_gate_reasons.append(r)

            if not cand_allowed_dirs:
                cycle_results.append({
                    "symbol": cand.symbol,
                    "price": cand.last_price,
                    "ai_decision": "SKIP",
                    "ai_confidence": 0,
                    "ai_evidence": "Deterministic hard gate rejected candidate",
                    "risk_factors": ",".join(all_gate_reasons),
                    "market_features": market_features,
                    "playbook": None,
                    "executed": False,
                    "order_id": None,
                })
                AuditLogger.log_event("HARD_GATE_REJECT", {
                    "symbol": cand.symbol,
                    "reasons": all_gate_reasons,
                }, session_id=self.current_session.session_id)
                continue

            playbook_match = evaluate_playbooks(
                symbol=cand.symbol,
                price=cand.last_price,
                change_24h=cand.price_change_percent,
                spread_pct=cand.spread_percent,
                market_features=market_features
            )

            atr_val = market_features.get("atr") if isinstance(market_features, dict) else None

            # Safe extraction of nested indicator features
            rsi_raw = market_features.get("rsi") if isinstance(market_features, dict) else None
            if isinstance(rsi_raw, dict):
                rsi_val = float(rsi_raw.get("rsi_15m", 50.0) or 50.0)
            elif isinstance(rsi_raw, (int, float)):
                rsi_val = float(rsi_raw)
            else:
                rsi_val = 50.0

            vol_raw = market_features.get("volume_sma_ratio") if isinstance(market_features, dict) else None
            vol_ratio = float(vol_raw) if isinstance(vol_raw, (int, float)) else 1.0

            fr_raw = market_features.get("funding_rate") if isinstance(market_features, dict) else None
            funding_val = float(fr_raw) if isinstance(fr_raw, (int, float)) else 0.0

            fib_raw = market_features.get("fibonacci") if isinstance(market_features, dict) else None
            fib_zone = fib_raw.get("zone", "UNKNOWN") if isinstance(fib_raw, dict) else "UNKNOWN"

            summary = {
                "symbol": cand.symbol,
                "price_change_24h": cand.price_change_percent,
                "current_price": cand.last_price,
                "spread_pct": cand.spread_percent,
                "atr_pct": round((float(atr_val) / cand.last_price) * 100.0, 2) if atr_val and cand.last_price > 0 else 0.0,
                "rsi_15m": round(rsi_val, 1),
                "funding_rate": funding_val,
                "volume_sma_ratio": round(vol_ratio, 2),
                "fib_zone": str(fib_zone),
                "playbook_matched": str(playbook_match.playbook) if playbook_match else "NONE",
                "allowed_directions": cand_allowed_dirs,
            }

            screened_candidates.append({
                "cand": cand,
                "closes": closes,
                "market_features": market_features,
                "playbook_match": playbook_match,
                "atr_val": atr_val,
                "summary": summary,
                "allowed_directions": cand_allowed_dirs,
            })

        if not screened_candidates:
            return {
                "status": "NO_CANDIDATES" if not cycle_results else "WATCHLIST_EXECUTED",
                "message": "No candidates passed deterministic gates." if not cycle_results else "Watchlist processed.",
                "cycle_results": cycle_results
            }

        # Step 2: Tier 1 Batch Triage via 9Router
        # Cap batch to top 4 candidates for fast LLM inference (< 25s) and timeout protection.
        # In BOTH mode, balance and interleave candidates symmetrically across LONG and SHORT.
        triage_batch: list[Dict[str, Any]] = []
        if current_dir == "BOTH":
            def _get_target_dir(sc_item):
                pm = sc_item.get("playbook_match")
                if pm and hasattr(pm, "direction") and pm.direction in ("LONG", "SHORT"):
                    return pm.direction
                dirs = sc_item.get("allowed_directions", [])
                if "LONG" in dirs and "SHORT" not in dirs:
                    return "LONG"
                if "SHORT" in dirs and "LONG" not in dirs:
                    return "SHORT"
                return "LONG" if sc_item["cand"].price_change_percent < 5.0 else "SHORT"

            long_cands = [sc for sc in screened_candidates if _get_target_dir(sc) == "LONG"]
            short_cands = [sc for sc in screened_candidates if _get_target_dir(sc) == "SHORT"]
            long_cands.sort(key=lambda x: getattr(x.get("playbook_match"), "score", 0) if x.get("playbook_match") else 0, reverse=True)
            short_cands.sort(key=lambda x: getattr(x.get("playbook_match"), "score", 0) if x.get("playbook_match") else 0, reverse=True)

            selected_syms = set()
            # Interleave LONG and SHORT candidates: [L1, S1, L2, S2] so fallback triage_batch[:2] evaluates 1 LONG + 1 SHORT
            max_len = max(len(long_cands), len(short_cands))
            for idx in range(max_len):
                if idx < len(long_cands) and len(triage_batch) < 4:
                    sc = long_cands[idx]
                    triage_batch.append(sc)
                    selected_syms.add(sc["cand"].symbol)
                if idx < len(short_cands) and short_cands[idx]["cand"].symbol not in selected_syms and len(triage_batch) < 4:
                    sc = short_cands[idx]
                    triage_batch.append(sc)
                    selected_syms.add(sc["cand"].symbol)
            if len(triage_batch) < 4:
                for sc in screened_candidates:
                    if sc["cand"].symbol not in selected_syms:
                        triage_batch.append(sc)
                        selected_syms.add(sc["cand"].symbol)
                        if len(triage_batch) >= 4:
                            break
        else:
            triage_batch = screened_candidates[:4]

        triage_res = self.ai.evaluate_batch_triage(
            [sc["summary"] for sc in triage_batch],
            direction=current_dir
        )

        AuditLogger.log_event("AI_BATCH_TRIAGE", {
            "candidates_count": len(triage_batch),
            "is_valid": triage_res.is_valid,
            "ranked": [c.model_dump() for c in triage_res.ranked_candidates],
            "selected_finalists": triage_res.selected_finalists,
            "latency_ms": triage_res.latency_ms,
            "usage": triage_res.usage,
            "error_type": getattr(triage_res, "error_type", None),
            "attempts": getattr(triage_res, "attempts", 1),
        }, session_id=self.current_session.session_id)

        candidate_map = {sc["cand"].symbol: sc for sc in screened_candidates}
        triage_map = {c.symbol: c for c in triage_res.ranked_candidates}
        handled_symbols = set()
        deep_count = 0
        cycle_tokens = int(triage_res.usage.get("total_tokens", 0) or 0) if isinstance(triage_res.usage, dict) else 0

        if triage_res.is_valid:
            # 2A: Process WATCH candidates with conviction >= 70 directly into Active Watchlist
            for t_cand in triage_res.ranked_candidates:
                if t_cand.action == "WATCH":
                    sc = candidate_map.get(t_cand.symbol)
                    if not sc:
                        continue
                    handled_symbols.add(t_cand.symbol)
                    cand_item = sc["cand"]
                    sugg_dir = getattr(t_cand, "suggested_direction", "UNKNOWN")
                    cand_allowed = sc.get("allowed_directions", [])

                    if current_dir in ("LONG", "SHORT"):
                        pos_dir = current_dir
                    elif sugg_dir in ("LONG", "SHORT"):
                        pos_dir = sugg_dir
                    elif len(cand_allowed) == 1:
                        pos_dir = cand_allowed[0]
                    else:
                        pos_dir = "UNKNOWN"

                    direction_valid = pos_dir in ("LONG", "SHORT")
                    session_allowed = (
                        (current_dir == "BOTH" and direction_valid) or
                        (current_dir == "SHORT" and pos_dir == "SHORT") or
                        (current_dir == "LONG" and pos_dir == "LONG")
                    )
                    cand_allowed_ok = (not cand_allowed) or (pos_dir in cand_allowed)
                    gate_ok = False
                    gate_reasons = []
                    if direction_valid:
                        gate_ok, gate_reasons = _evaluate_hard_gate(sc["market_features"], self.config.max_spread_pct, direction=pos_dir)

                    if not (direction_valid and session_allowed and cand_allowed_ok and gate_ok):
                        veto_msg = (
                            f"invalid_direction:{pos_dir}" if not direction_valid else (
                                f"direction_{pos_dir}_barred_in_session" if not session_allowed else (
                                    f"direction_{pos_dir}_barred_for_candidate" if not cand_allowed_ok else (
                                        f"hard_gate_rejected_{pos_dir}:{','.join(gate_reasons)}"
                                    )
                                )
                            )
                        )
                        cycle_results.append({
                            "symbol": cand_item.symbol,
                            "price": cand_item.last_price,
                            "ai_decision": "SKIP",
                            "ai_confidence": t_cand.conviction_score,
                            "ai_evidence": f"[TIER 1 WATCH VETOED: {veto_msg}] {t_cand.triage_reason}",
                            "playbook": sc["playbook_match"].model_dump() if sc["playbook_match"] else None,
                            "executed": False,
                            "order_id": None
                        })
                        AuditLogger.log_event("WATCH_CANDIDATE_VETO", {
                            "symbol": cand_item.symbol,
                            "pos_dir": pos_dir,
                            "reason": veto_msg
                        }, session_id=self.current_session.session_id)
                        continue

                    if t_cand.conviction_score >= 70:
                        atr_v = sc["atr_val"]
                        target_rr = _safe_rr(sc["playbook_match"].recommended_rr if sc.get("playbook_match") else 2.0)

                        # Smart Adaptive Leverage for WATCH candidate (ATR-capped to avoid liquidation guard reject)
                        effective_target_lev = self.current_session.leverage
                        if atr_v and cand_item.last_price > 0:
                            est_sl_pct = min(6.0, max(1.5, (1.5 * float(atr_v) / cand_item.last_price) * 100.0))
                            max_safe_lev = int(75.0 / est_sl_pct)
                            if effective_target_lev > max_safe_lev:
                                effective_target_lev = max(1, max_safe_lev)

                        sizing = SizingCalculator.calculate_lot(
                            symbol=cand_item.symbol,
                            margin_usdt=self.current_session.margin_per_pos,
                            target_leverage=effective_target_lev,
                            current_price=cand_item.last_price,
                            contract_info=cand_item.contract_info,
                            max_allowed_leverage=20,
                            direction=pos_dir,
                            atr=atr_v,
                            target_rr=target_rr
                        )
                        added, status_msg = self.watchlist.add_candidate(
                            symbol=cand_item.symbol,
                            current_price=cand_item.last_price,
                            conviction_score=t_cand.conviction_score,
                            playbook=str(sc["playbook_match"].playbook) if sc["playbook_match"] else None,
                            atr=atr_v or 0.0,
                            direction=pos_dir,
                            margin_per_pos=self.current_session.margin_per_pos,
                            leverage=effective_target_lev,
                            stop_loss_price=sizing.stop_loss_price,
                            take_profit_price=sizing.take_profit_price,
                            client=self.client,
                            session_id=self.current_session.session_id
                        )
                        cycle_results.append({
                            "symbol": cand_item.symbol,
                            "price": cand_item.last_price,
                            "ai_decision": "WAIT",
                            "ai_confidence": t_cand.conviction_score,
                            "ai_evidence": f"[TIER 1 WATCH] {t_cand.triage_reason}",
                            "playbook": sc["playbook_match"].model_dump() if sc["playbook_match"] else None,
                            "sizing": sizing.model_dump(),
                            "stop_loss_price": sizing.stop_loss_price,
                            "take_profit_price": sizing.take_profit_price,
                            "sl_percent": sizing.sl_percent,
                            "tp_percent": sizing.tp_percent,
                            "risk_amount_usdt": sizing.risk_amount_usdt,
                            "potential_profit_usdt": sizing.potential_profit_usdt,
                            "watchlist_status": status_msg,
                            "executed": False,
                            "order_id": None
                        })
                    else:
                        cycle_results.append({
                            "symbol": cand_item.symbol,
                            "price": cand_item.last_price,
                            "ai_decision": "SKIP",
                            "ai_confidence": t_cand.conviction_score,
                            "ai_evidence": f"[TIER 1 WATCH REJECTED: score {t_cand.conviction_score} < 70] {t_cand.triage_reason}",
                            "playbook": sc["playbook_match"].model_dump() if sc["playbook_match"] else None,
                            "executed": False,
                            "order_id": None
                        })

            # 2B: Evaluate Finalists (adaptive cap 2, skip #2 if quota exhausted)
            finalist_syms = triage_res.selected_finalists[:2]
            for f_sym in finalist_syms:
                if self.current_session.filled_count >= self.current_session.quota:
                    self.current_session.status = "EXHAUSTED"
                    break
                if f_sym in handled_symbols:
                    continue
                sc = candidate_map.get(f_sym)
                if not sc:
                    continue
                handled_symbols.add(f_sym)
                t_cand = triage_map.get(f_sym)
                if t_cand and getattr(t_cand, "suggested_direction", "UNKNOWN") in ("LONG", "SHORT"):
                    sc["suggested_direction"] = t_cand.suggested_direction
                deep_count += 1
                rep, tok, placed = self._evaluate_and_execute_candidate(
                    sc=sc,
                    deep_mode=True,
                    effective_dry_run=effective_dry_run,
                    is_local_paper=is_local_paper
                )
                cycle_results.append(rep)
                cycle_tokens += tok
                # Skip finalist #2 if finalist #1 placed an order and quota reached
                if placed and self.current_session.filled_count >= self.current_session.quota:
                    self.current_session.status = "EXHAUSTED"
                    break

            # 2C: Remaining candidates (marked SKIP or not in finalists)
            for sc in screened_candidates:
                s_sym = sc["cand"].symbol
                if s_sym not in handled_symbols:
                    t_cand = triage_map.get(s_sym)
                    t_reason = t_cand.triage_reason if t_cand else "Omitted from triage finalists"
                    t_score = t_cand.conviction_score if t_cand else 0
                    cycle_results.append({
                        "symbol": s_sym,
                        "price": sc["cand"].last_price,
                        "ai_decision": "SKIP",
                        "ai_confidence": t_score,
                        "ai_evidence": f"[TIER 1 SKIP] {t_reason}",
                        "playbook": sc["playbook_match"].model_dump() if sc["playbook_match"] else None,
                        "executed": False,
                        "order_id": None
                    })
        else:
            # Fallback mode: evaluate top 2 candidates sequentially if triage failed
            AuditLogger.log_event("AI_BATCH_TRIAGE_FALLBACK", {
                "error": triage_res.error_message,
                "error_type": getattr(triage_res, "error_type", None),
                "candidates_count": len(triage_batch),
                "latency_ms": triage_res.latency_ms,
                "attempts": getattr(triage_res, "attempts", 1),
            }, session_id=self.current_session.session_id)

            for sc in triage_batch[:2]:
                if self.current_session.filled_count >= self.current_session.quota:
                    self.current_session.status = "EXHAUSTED"
                    break
                deep_count += 1
                cand_allowed = sc.get("allowed_directions", [])
                if current_dir in ("LONG", "SHORT"):
                    sc["suggested_direction"] = current_dir
                elif len(cand_allowed) == 1:
                    sc["suggested_direction"] = cand_allowed[0]
                else:
                    sc["suggested_direction"] = "UNKNOWN"

                rep, tok, placed = self._evaluate_and_execute_candidate(
                    sc=sc,
                    deep_mode=True,  # Tier 2 structured dual-thesis evaluation for fallback finalists
                    effective_dry_run=effective_dry_run,
                    is_local_paper=is_local_paper
                )
                cycle_results.append(rep)
                cycle_tokens += tok

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
