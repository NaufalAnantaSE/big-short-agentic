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
from contracts import Environment, ExecutionMode, DirectionMode, ExitPolicy, TradeAction, PlaybookType
from strategy_playbook import evaluate_playbooks, PlaybookMatch
from watchlist_manager import WatchlistManager

class SessionState(BaseModel):
    session_id: str
    status: str = "IDLE"  # IDLE, ACTIVE_SEARCHING, EXECUTING_ENTRY, EXHAUSTED, TERMINATED
    margin_per_pos: float
    leverage: int
    quota: int
    filled_count: int = 0
    environment: str = Environment.BINGX_VST.value
    execution_mode: str = ExecutionMode.EXCHANGE_DEMO.value
    direction_mode: str = DirectionMode.SHORT.value
    exit_policy: str = ExitPolicy.MANUAL_ONLY.value
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
        self.watchlist = WatchlistManager()
        self.current_session: Optional[SessionState] = None

    def start_session(
        self,
        margin_per_pos: float = 5.0,
        leverage: int = 20,
        quota: int = 2,
        environment: str = Environment.BINGX_VST.value,
        execution_mode: str = ExecutionMode.EXCHANGE_DEMO.value,
        direction_mode: str = DirectionMode.SHORT.value,
        exit_policy: str = ExitPolicy.MANUAL_ONLY.value
    ) -> SessionState:
        """Initializes and activates a new entry session."""
        session_id = f"bx_sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
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
            started_at=time.time()
        )
        AuditLogger.log_event("SESSION_START", {
            "margin_per_pos": margin_per_pos,
            "leverage": min(leverage, 20),
            "quota": quota,
            "environment": environment,
            "execution_mode": execution_mode,
            "direction_mode": direction_mode,
            "exit_policy": exit_policy
        }, session_id=session_id)

        # Startup reconciliation: reconcile open and orphan resting orders on exchange
        if self.config.api_key and self.config.api_key != "mock":
            try:
                self.watchlist.reconcile_resting_orders(self.client, session_id=session_id)
            except Exception:
                pass

        return self.current_session

    def stop_session(self) -> Optional[SessionState]:
        """Terminates active session and cancels all linked resting orders."""
        if self.current_session:
            self.current_session.status = "TERMINATED"
            for entry in self.watchlist.get_all_entries():
                self.watchlist.cancel_entry_resting_order(
                    entry=entry,
                    reason="SESSION_STOPPED",
                    client=self.client,
                    session_id=self.current_session.session_id
                )
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
        if not self.current_session or self.current_session.status not in ("ACTIVE_SEARCHING", "EXHAUSTED"):
            return {"status": "NO_ACTIVE_SESSION", "message": "No active session in searching state."}

        # Synchronize and reconcile open/resting orders on exchange
        if not dry_run and self.config.api_key and self.config.api_key != "mock":
            try:
                self.watchlist.reconcile_resting_orders(self.client, session_id=self.current_session.session_id)
            except Exception:
                pass

        try:
            occupied = self.scanner.get_occupied_symbols()
        except Exception:
            occupied = set()

        occupied_count = len(occupied)
        resting_count = self.watchlist.count_resting_orders()
        slots_used = occupied_count + resting_count
        self.current_session.filled_count = occupied_count

        available_slots = self.current_session.quota - slots_used

        if available_slots <= 0 and self.current_session.filled_count >= self.current_session.quota:
            self.current_session.status = "EXHAUSTED"
            for entry in self.watchlist.get_all_entries():
                self.watchlist.cancel_entry_resting_order(entry, reason="QUOTA_EXHAUSTED", client=self.client, session_id=self.current_session.session_id)
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
                w_depth = self.client.get_depth(entry.symbol, limit=2)
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
        candidates = self.scanner.scan_universe(
            mode=self.config.universe_mode,
            limit_candidates=limit_candidates,
            direction=current_dir
        )
        if not candidates:
            return {
                "status": "NO_CANDIDATES" if not cycle_results else "WATCHLIST_EXECUTED",
                "message": "No eligible unoccupied pairs found." if not cycle_results else "Watchlist processed.",
                "cycle_results": cycle_results
            }

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
                    "playbook": None,
                    "executed": False,
                    "order_id": None,
                })
                AuditLogger.log_event("HARD_GATE_REJECT", {
                    "symbol": cand.symbol,
                    "reasons": gate_reasons,
                }, session_id=self.current_session.session_id)
                continue

            # Autonomous Multi-Strategy Playbook Classification
            playbook_match = evaluate_playbooks(
                symbol=cand.symbol,
                price=cand.last_price,
                change_24h=cand.price_change_percent,
                spread_pct=cand.spread_percent,
                market_features=market_features
            )

            # Step 2: AI Evaluation via 9Router
            candidate_payload = {
                "symbol": cand.symbol,
                "price": cand.last_price,
                "price_change_24h": cand.price_change_percent,
                "spread_pct": cand.spread_percent,
                "klines_15m_closes": closes[-5:] if closes else [],
                "market_features": market_features,
                "playbook": playbook_match.model_dump(),
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

            # Step 3: Sizing with Dynamic ATR TP/SL & Risk Calculations
            is_short_intent = (ai_res.decision == "ENTER_SHORT")
            is_long_intent = (ai_res.decision == "ENTER_LONG")
            pos_dir = "LONG" if is_long_intent else "SHORT"
            atr_val = market_features.get("atr") if isinstance(market_features, dict) else None

            # Recommended Risk:Reward from matched playbook
            target_rr = playbook_match.recommended_rr if playbook_match.recommended_rr else 2.0

            # Smart Adaptive Leverage: if ATR SL percentage is wide (e.g. 4.5% - 6.0%),
            # dynamically cap leverage so that sl_pct * leverage <= 75% of margin.
            # This guarantees positions execute safely without being rejected by liquidation guard.
            effective_target_lev = self.current_session.leverage
            if atr_val and cand.last_price > 0:
                est_sl_pct = min(6.0, max(1.5, (1.5 * float(atr_val) / cand.last_price) * 100.0))
                max_safe_lev = int(75.0 / est_sl_pct)
                if effective_target_lev > max_safe_lev:
                    effective_target_lev = max(1, max_safe_lev)

            sizing = SizingCalculator.calculate_lot(
                symbol=cand.symbol,
                margin_usdt=self.current_session.margin_per_pos,
                target_leverage=effective_target_lev,
                current_price=cand.last_price,
                contract_info=cand.contract_info,
                max_allowed_leverage=20,
                direction=pos_dir,
                atr=atr_val,
                target_rr=target_rr
            )

            execution_report: Dict[str, Any] = {
                "symbol": cand.symbol,
                "price": cand.last_price,
                "ai_decision": ai_res.decision,
                "ai_confidence": ai_res.confidence,
                "ai_evidence": ai_res.key_evidence,
                "playbook": playbook_match.model_dump(),
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

            # Determine trade direction permissions
            session_dir = getattr(self.current_session, "direction_mode", "SHORT")

            direction_allowed = (
                (session_dir == "BOTH") or
                (session_dir == "SHORT" and is_short_intent) or
                (session_dir == "LONG" and is_long_intent)
            )

            if (is_short_intent or is_long_intent) and direction_allowed and sizing.is_valid:
                target_pos_side = "LONG" if is_long_intent else "SHORT"
                target_order_side = "BUY" if is_long_intent else "SELL"
                prefix = "bx_long" if is_long_intent else "bx_short"
                client_order_id = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                
                if effective_dry_run:
                    tag = "[LOCAL-PAPER]" if is_local_paper else "[DRY-RUN]"
                    execution_report["executed"] = False
                    execution_report["dry_run"] = True
                    execution_report["client_order_id"] = client_order_id
                    tpsl_info = f" [TP: ${sizing.take_profit_price} (+{sizing.tp_percent}%), SL: ${sizing.stop_loss_price} (-{sizing.sl_percent}%)]" if sizing.take_profit_price else ""
                    execution_report["message"] = (
                        f"{tag} Pre-flight: Set leverage to {sizing.effective_leverage}x | "
                        f"Submit {target_pos_side} MARKET order: {sizing.quantity} {cand.symbol}{tpsl_info}"
                    )
                    self.current_session.filled_count += 1
                    self.current_session.executed_symbols.append(cand.symbol)
                else:
                    try:
                        # Pre-Flight Leverage Assertion (MANDATORY GATE):
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
                            session_id=self.current_session.session_id
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
                        order_id_raw = order_res.get("orderId") or order_res.get("order", {}).get("orderId") or client_order_id
                        order_id_str = str(order_id_raw)
                        execution_report["executed"] = True
                        execution_report["dry_run"] = False
                        execution_report["client_order_id"] = client_order_id
                        execution_report["order_id"] = order_id_str
                        self.current_session.filled_count += 1
                        self.current_session.executed_symbols.append(cand.symbol)

                        AuditLogger.log_order_submission(
                            symbol=cand.symbol,
                            side=target_order_side,
                            position_side=target_pos_side,
                            order_type="MARKET",
                            quantity=sizing.quantity,
                            price=cand.last_price,
                            client_order_id=client_order_id,
                            order_id=order_id_str,
                            status="FILLED",
                            session_id=self.current_session.session_id,
                            stop_loss_price=sizing.stop_loss_price,
                            take_profit_price=sizing.take_profit_price
                        )
                    except BingXAPIError as e:
                        execution_report["executed"] = False
                        execution_report["error"] = str(e)
                        AuditLogger.log_event("ORDER_ERROR", {
                            "symbol": cand.symbol,
                            "error": str(e),
                            "client_order_id": client_order_id
                        }, session_id=self.current_session.session_id)
            elif ai_res.decision == "WAIT" and ai_res.confidence >= 65:
                # Add to stateful Active Watchlist for continuous deterministic tracking
                added, status_msg = self.watchlist.add_candidate(
                    symbol=cand.symbol,
                    current_price=cand.last_price,
                    conviction_score=ai_res.confidence,
                    playbook=str(playbook_match.playbook) if playbook_match else None,
                    atr=atr_val or 0.0,
                    direction=pos_dir,
                    margin_per_pos=self.current_session.margin_per_pos,
                    leverage=effective_target_lev,
                    stop_loss_price=sizing.stop_loss_price,
                    take_profit_price=sizing.take_profit_price,
                    client=self.client,
                    session_id=self.current_session.session_id
                )
                execution_report["watchlist_status"] = status_msg

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
