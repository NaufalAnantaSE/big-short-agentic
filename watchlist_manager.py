"""
Active Watchlist Engine and Deterministic Reversal Confirmation for BingX Short Agent.
Provides stateful memory across scan cycles, deterministic rule-based reversal detection,
pessimistic quota reservation, and resting order lifecycle management.
"""

import time
import uuid
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from client import BingXClient
from audit_logger import AuditLogger


class WatchlistEntry(BaseModel):
    symbol: str
    entered_at: float = Field(default_factory=time.time)
    ttl_seconds: float = 1800.0  # 30 minutes TTL
    initial_price: float
    swing_high: float
    conviction_score: float  # AI confidence (0-100) or Playbook score
    playbook: Optional[str] = None
    atr: float = 0.0
    direction: str = "SHORT"
    margin_per_pos: float = 5.0
    leverage: int = 20
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None

    # Resting order tracking
    resting_order_id: Optional[str] = None
    resting_client_order_id: Optional[str] = None
    resting_order_price: Optional[float] = None
    resting_order_type: Optional[str] = None  # "LIMIT" or "STOP_MARKET"
    resting_order_placed_at: Optional[float] = None
    last_checked_at: float = Field(default_factory=time.time)


class ReversalTriggerResult(BaseModel):
    triggered: bool
    pattern: Optional[str] = None  # "UPPER_WICK_REJECTION" | "MICRO_BREAKDOWN"
    trigger_price: float = 0.0
    evidence: str = ""
    reasons: List[str] = Field(default_factory=list)


class WatchlistManager:
    def __init__(self, max_size: int = 4, default_ttl_seconds: float = 1800.0):
        self.max_size = max_size
        self.default_ttl_seconds = default_ttl_seconds
        self.entries: Dict[str, WatchlistEntry] = {}

    def get_entry(self, symbol: str) -> Optional[WatchlistEntry]:
        return self.entries.get(symbol)

    def get_all_entries(self) -> List[WatchlistEntry]:
        return list(self.entries.values())

    def count_resting_orders(self) -> int:
        """[PHASE 2 FEATURE - PRE-WIRED FOR BREAKDOWN STOP-MARKET EXECUTION] Counts entries with active resting orders."""
        return sum(1 for e in self.entries.values() if e.resting_order_id or e.resting_client_order_id)

    def add_candidate(
        self,
        symbol: str,
        current_price: float,
        conviction_score: float,
        playbook: Optional[str] = None,
        atr: float = 0.0,
        direction: str = "SHORT",
        margin_per_pos: float = 5.0,
        leverage: int = 20,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        client: Optional[BingXClient] = None,
        session_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Adds a candidate to the watchlist with strict capacity enforcement.
        If full, evicts the entry with the lowest conviction score.
        """
        now = time.time()

        # If symbol already in watchlist, update conviction score and high if better
        if symbol in self.entries:
            existing = self.entries[symbol]
            existing.conviction_score = max(existing.conviction_score, conviction_score)
            existing.swing_high = max(existing.swing_high, current_price)
            existing.last_checked_at = now
            if atr > 0:
                existing.atr = atr
            return True, "UPDATED_EXISTING"

        # Check capacity
        if len(self.entries) >= self.max_size:
            # Find candidate with the lowest conviction score
            lowest_sym = min(self.entries.keys(), key=lambda s: self.entries[s].conviction_score)
            lowest_entry = self.entries[lowest_sym]

            # Only displace if new candidate has higher conviction score
            if conviction_score > lowest_entry.conviction_score:
                self.evict_entry(
                    symbol=lowest_sym,
                    reason="LOWEST_CONVICTION_DISPLACED",
                    client=client,
                    session_id=session_id
                )
            else:
                return False, f"WATCHLIST_FULL_LOWER_CONVICTION ({conviction_score} <= {lowest_entry.conviction_score})"

        # Create new entry
        new_entry = WatchlistEntry(
            symbol=symbol,
            entered_at=now,
            ttl_seconds=self.default_ttl_seconds,
            initial_price=current_price,
            swing_high=current_price,
            conviction_score=conviction_score,
            playbook=playbook,
            atr=atr,
            direction=direction,
            margin_per_pos=margin_per_pos,
            leverage=leverage,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            last_checked_at=now
        )
        self.entries[symbol] = new_entry

        AuditLogger.log_event("WATCHLIST_ENTER", {
            "symbol": symbol,
            "initial_price": current_price,
            "conviction_score": conviction_score,
            "playbook": playbook,
            "atr": atr,
            "ttl_seconds": self.default_ttl_seconds
        }, session_id=session_id)

        return True, "ADDED"

    def evict_entry(
        self,
        symbol: str,
        reason: str,
        client: Optional[BingXClient] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Evicts a symbol from the watchlist and immediately cancels any linked resting order.
        """
        entry = self.entries.pop(symbol, None)
        if not entry:
            return False

        resting_cancelled = False
        if entry.resting_order_id or entry.resting_client_order_id:
            resting_cancelled = self.cancel_entry_resting_order(
                entry=entry,
                reason=f"WATCHLIST_EVICTED_{reason}",
                client=client,
                session_id=session_id
            )

        AuditLogger.log_event("WATCHLIST_EVICT", {
            "symbol": symbol,
            "reason": reason,
            "conviction_score": entry.conviction_score,
            "initial_price": entry.initial_price,
            "swing_high": entry.swing_high,
            "time_in_watchlist_sec": round(time.time() - entry.entered_at, 1),
            "resting_order_cancelled": resting_cancelled
        }, session_id=session_id)

        return True

    def cancel_entry_resting_order(
        self,
        entry: WatchlistEntry,
        reason: str,
        client: Optional[BingXClient] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        [PHASE 2 FEATURE - PRE-WIRED FOR BREAKDOWN STOP-MARKET EXECUTION]
        Cancels the active resting order associated with an entry.
        """
        order_id = entry.resting_order_id
        client_oid = entry.resting_client_order_id
        if not (order_id or client_oid):
            return False

        if client:
            try:
                client.cancel_order(
                    symbol=entry.symbol,
                    order_id=order_id,
                    client_order_id=client_oid
                )
            except Exception as exc:
                AuditLogger.log_event("RESTING_ORDER_CANCEL_ERROR", {
                    "symbol": entry.symbol,
                    "order_id": order_id,
                    "client_order_id": client_oid,
                    "error": str(exc)
                }, session_id=session_id)

        AuditLogger.log_event("RESTING_ORDER_CANCEL", {
            "symbol": entry.symbol,
            "order_id": order_id,
            "client_order_id": client_oid,
            "order_price": entry.resting_order_price,
            "reason": reason
        }, session_id=session_id)

        entry.resting_order_id = None
        entry.resting_client_order_id = None
        entry.resting_order_price = None
        entry.resting_order_type = None
        entry.resting_order_placed_at = None
        return True

    def check_deterministic_reversal(
        self,
        entry: WatchlistEntry,
        klines_15m: List[Dict[str, Any]],
        current_price: float,
        current_spread_pct: float
    ) -> Tuple[bool, Optional[str], ReversalTriggerResult]:
        """
        Evaluates strict deterministic reversal confirmation and eviction conditions.
        Returns: (should_evict, eviction_reason, trigger_result)
        """
        now = time.time()
        entry.last_checked_at = now

        # Update swing high
        entry.swing_high = max(entry.swing_high, current_price)

        # ----------------------------------------------------
        # FAST EVICTION GATES
        # ----------------------------------------------------
        # 1. TTL Expiration (30 mins)
        if now - entry.entered_at >= entry.ttl_seconds:
            return True, "TTL_EXPIRED", ReversalTriggerResult(triggered=False, evidence="TTL expired (30m)")

        # 2. Spread Blowout (>0.40%)
        if current_spread_pct > 0.40:
            return True, "SPREAD_BLOWOUT", ReversalTriggerResult(triggered=False, evidence=f"Spread too wide ({current_spread_pct}% > 0.40%)")

        if not klines_15m or len(klines_15m) < 3:
            return False, None, ReversalTriggerResult(triggered=False, evidence="Insufficient 15m candle history")

        # Latest candle
        latest_c = klines_15m[-1]
        try:
            open_p = float(latest_c.get("open", 0))
            high_p = float(latest_c.get("high", 0))
            low_p = float(latest_c.get("low", 0))
            close_p = float(latest_c.get("close", 0))
            vol = float(latest_c.get("volume", latest_c.get("quoteVolume", 0)))
        except (ValueError, TypeError):
            return False, None, ReversalTriggerResult(triggered=False, evidence="Malformed candle values")

        # Update swing high with candle high
        entry.swing_high = max(entry.swing_high, high_p)

        # 4. Breakout Invalidation: Close candle 15m > initial_price * 1.02
        # (Closing beyond resistance/setup level by >2.0% confirms runaway continuation, not exhaustion)
        if close_p > entry.initial_price * 1.02:
            return True, "BREAKOUT_INVALIDATION", ReversalTriggerResult(triggered=False, evidence="Closed >2% above breakout level")

        # Calculate metrics
        upper_wick = high_p - max(open_p, close_p)
        body = abs(close_p - open_p)
        total_range = high_p - low_p
        effective_atr = entry.atr if entry.atr > 0 else total_range

        # Compute swing high and low across the available 15m window (up to 24 candles)
        window = klines_15m[-24:] if len(klines_15m) >= 24 else klines_15m
        highs = [float(c.get("high", 0)) for c in window]
        lows = [float(c.get("low", 0)) for c in window]
        win_high = max(highs) if highs else high_p
        win_low = min(lows) if lows else low_p
        swing_span = max(win_high - win_low, 1e-12)

        # Fibonacci Retracement from local swing high (Fib safety gate: 0.0 at peak, 1.0 at base)
        retracement = (win_high - close_p) / swing_span

        # Check both closed candle [-2] (if history allows) and latest candle [-1]
        candles_to_check = []
        if len(klines_15m) >= 4:
            candles_to_check.append((klines_15m[-2], "closed [-2]"))
        candles_to_check.append((latest_c, "latest [-1]"))

        # ----------------------------------------------------
        # PATTERN 1: Upper Wick Rejection (Exhaustion Reversal)
        # ----------------------------------------------------
        for cand_ref, cand_label in candles_to_check:
            c_open = float(cand_ref.get("open", 0))
            c_high = float(cand_ref.get("high", 0))
            c_low = float(cand_ref.get("low", 0))
            c_close = float(cand_ref.get("close", 0))
            c_wick = c_high - max(c_open, c_close)
            c_body = abs(c_close - c_open)
            c_range = c_high - c_low
            c_atr = entry.atr if entry.atr > 0 else c_range

            p1_wick_ratio = c_wick >= 1.8 * c_body
            p1_wick_range = (c_wick / c_range) >= 0.40 if c_range > 0 else False
            p1_abs_wick = (c_wick >= 0.003 * c_high) or (c_wick >= 0.5 * c_atr)
            p1_pullback = (c_close < c_open) or (current_price <= c_high * (1.0 - 0.004)) or (c_close <= c_high * (1.0 - 0.004))
            p1_fib_safe = retracement <= 0.382

            if p1_wick_ratio and p1_wick_range and p1_abs_wick and p1_pullback and p1_fib_safe:
                return False, None, ReversalTriggerResult(
                    triggered=True,
                    pattern="UPPER_WICK_REJECTION",
                    trigger_price=current_price,
                    evidence=(
                        f"15m Upper Wick Rejection confirmed on {cand_label}: wick={c_wick:.6f} ({c_wick/c_range*100:.1f}% range), "
                        f">=1.8x body ({c_body:.6f}), pullback confirmed, Fib retracement={retracement:.3f} <= 0.382."
                    ),
                    reasons=["wick_ratio_met", "wick_range_met", "abs_wick_met", "closed_pullback_met", "fib_safe"]
                )

        # ----------------------------------------------------
        # PATTERN 2: Local Break of Structure (Micro Breakdown 15m)
        # ----------------------------------------------------
        prev_1 = klines_15m[-2]
        prev_2 = klines_15m[-3]
        try:
            min_prev_low = min(float(prev_1.get("low", 0)), float(prev_2.get("low", 0)))
        except (ValueError, TypeError):
            min_prev_low = low_p

        # Volume confirmation: >= 1.3x SMA(Volume, 10)
        recent_vols = []
        for c in klines_15m[-10:]:
            try:
                recent_vols.append(float(c.get("volume", c.get("quoteVolume", 0))))
            except Exception:
                pass
        sma_vol = (sum(recent_vols) / len(recent_vols)) if recent_vols else vol

        p2_structure_break = (close_p < min_prev_low) or (current_price < min_prev_low)
        p2_volume_confirm = vol >= 1.3 * sma_vol if sma_vol > 0 else True
        p2_fib_safe = retracement <= 0.382

        if p2_structure_break and p2_volume_confirm and p2_fib_safe:
            return False, None, ReversalTriggerResult(
                triggered=True,
                pattern="MICRO_BREAKDOWN",
                trigger_price=current_price,
                evidence=(
                    f"15m Micro Breakdown confirmed: close={close_p} < min_prev_low={min_prev_low}, "
                    f"volume={vol:.1f} >= 1.3x SMA10 ({sma_vol:.1f}), Fib retracement={retracement:.3f} <= 0.382."
                ),
                reasons=["structure_break_met", "volume_confirm_met", "fib_safe"]
            )

        # ----------------------------------------------------
        # 5. Extended Dump Missed Gate (>5.0% below swing high without reversal being caught)
        # Evaluated ONLY AFTER checking reversal patterns so textbook reversals aren't prematurely evicted!
        # ----------------------------------------------------
        if entry.swing_high > 0 and current_price < entry.swing_high * 0.95:
            return True, "DUMP_MISSED", ReversalTriggerResult(triggered=False, evidence="Missed dump >5% below swing high")

        # Neither pattern triggered, keep watching
        return False, None, ReversalTriggerResult(
            triggered=False,
            evidence="Reversal confirmation criteria not yet satisfied."
        )

    def reconcile_resting_orders(
        self,
        client: BingXClient,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        [PHASE 2 FEATURE - PRE-WIRED FOR BREAKDOWN STOP-MARKET EXECUTION]
        Startup & Cycle Reconciliation:
        1. Checks status of existing resting orders on exchange.
        2. Detects filled resting orders.
        3. Cancels resting orders that have timed out (>20 min) or invalid price (>1.5% above limit).
        4. Detects and cancels orphaned zombie orders on exchange not belonging to active sessions.
        """
        now = time.time()
        report = {
            "filled_orders": [],
            "cancelled_orders": [],
            "orphans_cancelled": 0
        }

        try:
            open_orders = client.get_open_orders()
        except Exception as exc:
            AuditLogger.log_event("RECONCILIATION_ERROR", {"error": str(exc)}, session_id=session_id)
            return report

        open_order_ids = {str(o.get("orderId")) for o in open_orders if o.get("orderId")}
        open_client_order_ids = {str(o.get("clientOrderId")).lower() for o in open_orders if o.get("clientOrderId")}
        tracked_client_ids = set()

        for symbol, entry in list(self.entries.items()):
            if entry.resting_order_id or entry.resting_client_order_id:
                cid = (entry.resting_client_order_id or "").lower()
                oid = str(entry.resting_order_id or "")
                tracked_client_ids.add(cid)

                # Check if still in open orders
                is_open = (oid in open_order_ids) or (cid in open_client_order_ids)

                if is_open:
                    # Timeout check: >20 minutes (1200 seconds)
                    placed_at = entry.resting_order_placed_at or entry.entered_at
                    if now - placed_at > 1200.0:
                        self.cancel_entry_resting_order(
                            entry=entry,
                            reason="TIMEOUT_20M",
                            client=client,
                            session_id=session_id
                        )
                        report["cancelled_orders"].append(entry.symbol)
                        continue

                    # Price Invalidation check: Spot jumped >1.5% above limit price
                    if entry.resting_order_price and entry.resting_order_price > 0:
                        try:
                            # Quick depth check
                            depth = client.get_depth(entry.symbol, limit=1)
                            best_bid = float(depth.get("bids", [[0, 0]])[0][0]) if depth.get("bids") else 0
                            if best_bid > entry.resting_order_price * 1.015:
                                self.cancel_entry_resting_order(
                                    entry=entry,
                                    reason="PRICE_INVALIDATED_ABOVE_1.5PCT",
                                    client=client,
                                    session_id=session_id
                                )
                                report["cancelled_orders"].append(entry.symbol)
                                continue
                        except Exception:
                            pass
                else:
                    # Order is no longer in open orders -> assumed FILLED (or manually closed)
                    report["filled_orders"].append(entry.symbol)
                    entry.resting_order_id = None
                    entry.resting_client_order_id = None
                    entry.resting_order_price = None

        # Reconcile Orphans: Cancel open orders with clientOrderId matching our agent prefix that are NOT tracked
        for o in open_orders:
            cid = str(o.get("clientOrderId", "")).lower()
            sym = o.get("symbol", "")
            oid = o.get("orderId")
            if (cid.startswith("bx_short") or cid.startswith("bx_limit")) and cid not in tracked_client_ids:
                try:
                    client.cancel_order(symbol=sym, order_id=oid, client_order_id=cid)
                    report["orphans_cancelled"] += 1
                    AuditLogger.log_event("ORPHAN_ORDER_RECONCILED", {
                        "symbol": sym,
                        "order_id": oid,
                        "client_order_id": cid,
                        "action": "CANCELLED"
                    }, session_id=session_id)
                except Exception:
                    pass

        return report
