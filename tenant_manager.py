"""Multi-Tenant Session Manager: Enforces absolute tenant isolation by maintaining
isolated BingXClient and SessionOrchestrator instances per user.
No API credentials or session states are ever shared between tenants.
"""

import time
from typing import Dict, Any, Optional, List
from config import AppConfig
from client import BingXClient, BingXAPIError
from orchestrator import SessionOrchestrator, SessionState
from plain_explainer import humanize_ai_decision
from audit_logger import AuditLogger
from ai_settings import get_ai_settings
import db

class TenantSessionManager:
    def __init__(self, base_config: AppConfig):
        self.base_config = base_config
        # In-memory tenant orchestrator pool: user_id -> SessionOrchestrator
        self._orchestrator_pool: Dict[int, SessionOrchestrator] = {}
        # In-memory tenant client pool: user_id -> BingXClient
        self._client_pool: Dict[int, BingXClient] = {}

    def _build_tenant_config(self, user_id: int) -> AppConfig:
        user = db.get_user_by_id(user_id)
        if not user:
            raise ValueError("Pengguna tidak ditemukan.")
        if user.get("role") != "user":
            raise ValueError("Akun admin tidak memiliki izin trading bot. Silakan gunakan akun pengguna trader.")

        creds = db.get_decrypted_user_credentials(user_id)
        if not creds or not creds.get("has_keys"):
            raise ValueError("Kunci API BingX belum dimasukkan. Silakan simpan API Key & Secret Key Anda terlebih dahulu.")
        
        # Clone base config with tenant credentials, dynamic AI model, and environment target
        tenant_cfg = self.base_config.model_copy(deep=True)
        tenant_cfg.api_key = creds["api_key"]
        tenant_cfg.secret_key = creds["secret_key"]
        
        # Apply persisted AI settings configured by admin
        ai_cfg = get_ai_settings()
        tenant_cfg.ai_model_name = ai_cfg["model"]
        tenant_cfg.ai_gateway_url = ai_cfg["gateway_url"]
        
        # If user marked is_demo=True, point to VST demo endpoint
        if creds.get("is_demo", True):
            tenant_cfg.bingx_host = "https://open-api-vst.bingx.com"
        else:
            tenant_cfg.bingx_host = "https://open-api.bingx.com"
            
        return tenant_cfg

    def get_client(self, user_id: int, force_refresh: bool = False) -> BingXClient:
        if force_refresh or user_id not in self._client_pool:
            cfg = self._build_tenant_config(user_id)
            self._client_pool[user_id] = BingXClient(cfg)
        return self._client_pool[user_id]

    def get_orchestrator(self, user_id: int, force_refresh: bool = False) -> SessionOrchestrator:
        if force_refresh or user_id not in self._orchestrator_pool:
            cfg = self._build_tenant_config(user_id)
            orch = SessionOrchestrator(cfg)
            self._orchestrator_pool[user_id] = orch
        return self._orchestrator_pool[user_id]

    def invalidate_user_cache(self, user_id: int):
        """Called when user updates their API keys or settings."""
        self._client_pool.pop(user_id, None)
        self._orchestrator_pool.pop(user_id, None)

    def get_account_summary(self, user_id: int) -> Dict[str, Any]:
        """Fetches live balance and account metrics for the specific tenant."""
        client = self.get_client(user_id)
        bal_data = client.get_balance()
        pos_data = client.get_positions()

        # Parse balances (support list or dict BingX response)
        balance = 0.0
        equity = 0.0
        available_margin = 0.0
        used_margin = 0.0
        unrealized_pnl = 0.0
        asset_name = "USDT"

        if isinstance(bal_data, list) and bal_data:
            # Prefer VST if present, or USDT
            target = next((x for x in bal_data if x.get("asset") in {"VST", "USDT"}), bal_data[0])
            asset_name = target.get("asset", "USDT")
            balance = float(target.get("balance", 0.0))
            equity = float(target.get("equity", balance))
            available_margin = float(target.get("availableMargin", balance))
            used_margin = float(target.get("usedMargin", 0.0))
            unrealized_pnl = float(target.get("unrealizedProfit", 0.0))
        elif isinstance(bal_data, dict):
            asset_name = bal_data.get("asset", "USDT")
            balance = float(bal_data.get("balance", 0.0))
            equity = float(bal_data.get("equity", balance))
            available_margin = float(bal_data.get("availableMargin", balance))
            used_margin = float(bal_data.get("usedMargin", 0.0))
            unrealized_pnl = float(bal_data.get("unrealizedProfit", 0.0))

        # Filter active open positions
        active_positions = []
        for p in pos_data:
            amt = float(p.get("positionAmt", p.get("initialMargin", 0)))
            if amt != 0:
                active_positions.append({
                    "symbol": p.get("symbol"),
                    "position_side": p.get("positionSide", "SHORT"),
                    "amount": amt,
                    "entry_price": float(p.get("avgPrice", p.get("entryPrice", 0))),
                    "mark_price": float(p.get("markPrice", 0)),
                    "initial_margin": float(p.get("initialMargin", 0)),
                    "leverage": int(p.get("leverage", 20)),
                    "unrealized_pnl": float(p.get("unrealizedProfit", 0)),
                    "pnl_pct": float(p.get("unrealizedProfit", 0)) / max(float(p.get("initialMargin", 1)), 0.0001) * 100
                })

        # Check in-memory or persisted session
        orch = self._orchestrator_pool.get(user_id)
        current_sess = orch.current_session if orch else None
        latest_db_sess = db.get_latest_user_session(user_id)

        session_info = {
            "status": current_sess.status if current_sess else (latest_db_sess["status"] if latest_db_sess else "IDLE"),
            "session_id": current_sess.session_id if current_sess else (latest_db_sess["session_id"] if latest_db_sess else None),
            "quota": current_sess.quota if current_sess else (latest_db_sess["quota"] if latest_db_sess else 10),
            "filled_count": current_sess.filled_count if current_sess else (latest_db_sess["filled_count"] if latest_db_sess else 0),
            "margin_per_pos": current_sess.margin_per_pos if current_sess else (latest_db_sess["margin_per_pos"] if latest_db_sess else 5.0),
            "leverage": current_sess.leverage if current_sess else (latest_db_sess["leverage"] if latest_db_sess else 20),
        }

        return {
            "asset": asset_name,
            "balance": balance,
            "equity": equity,
            "available_margin": available_margin,
            "used_margin": used_margin,
            "unrealized_pnl": unrealized_pnl,
            "active_positions_count": len(active_positions),
            "active_positions": active_positions,
            "session": session_info
        }

    def start_session(
        self,
        user_id: int,
        margin_per_pos: float = 5.0,
        leverage: int = 20,
        quota: int = 10,
        mode: str = "PUMP_GAINERS",
        is_live: bool = False
    ) -> Dict[str, Any]:
        """Initializes and persists a new trading session for this user."""
        orch = self.get_orchestrator(user_id)
        session_state = orch.start_session(margin_per_pos=margin_per_pos, leverage=leverage, quota=quota)
        
        # Persist to database
        db.save_session(
            session_id=session_state.session_id,
            user_id=user_id,
            status=session_state.status,
            margin=margin_per_pos,
            leverage=leverage,
            quota=quota,
            filled_count=0,
            mode=mode,
            is_live=is_live,
            started_at=session_state.started_at
        )

        return {
            "session_id": session_state.session_id,
            "status": session_state.status,
            "margin_per_pos": margin_per_pos,
            "leverage": leverage,
            "quota": quota,
            "mode": mode,
            "is_live": is_live
        }

    def update_session_params(
        self,
        user_id: int,
        margin_per_pos: Optional[float] = None,
        quota: Optional[int] = None
    ) -> Dict[str, Any]:
        """Allows dynamically updating margin and quota for active user session."""
        orch = self.get_orchestrator(user_id)
        if not orch.current_session:
            latest = db.get_latest_user_session(user_id)
            if latest and latest["status"] in ("ACTIVE_SEARCHING", "EXHAUSTED"):
                orch.current_session = SessionState(
                    session_id=latest["session_id"],
                    status=latest["status"],
                    margin_per_pos=latest["margin_per_pos"],
                    leverage=latest["leverage"],
                    quota=latest["quota"],
                    filled_count=latest["filled_count"],
                    started_at=latest["started_at"]
                )

        if orch.current_session:
            if margin_per_pos is not None:
                orch.current_session.margin_per_pos = float(margin_per_pos)
            if quota is not None:
                orch.current_session.quota = int(quota)
                if orch.current_session.status == "EXHAUSTED" and orch.current_session.filled_count < orch.current_session.quota:
                    orch.current_session.status = "ACTIVE_SEARCHING"
            db.update_session_params(
                session_id=orch.current_session.session_id,
                margin_per_pos=orch.current_session.margin_per_pos,
                quota=orch.current_session.quota,
                status=orch.current_session.status
            )
            return {
                "session_id": orch.current_session.session_id,
                "status": orch.current_session.status,
                "margin_per_pos": orch.current_session.margin_per_pos,
                "quota": orch.current_session.quota,
                "filled_count": orch.current_session.filled_count
            }
        return {"status": "NO_ACTIVE_SESSION", "message": "Tidak ada sesi aktif untuk diperbarui."}

    def stop_session(self, user_id: int) -> Dict[str, Any]:
        """Stops searching session without closing existing positions."""
        orch = self._orchestrator_pool.get(user_id)
        if orch and orch.current_session:
            sess = orch.stop_session()
            if sess:
                db.update_session_status(sess.session_id, "TERMINATED", sess.filled_count, stopped_at=time.time())
                return {"status": "TERMINATED", "session_id": sess.session_id}
        
        latest_db_sess = db.get_latest_user_session(user_id)
        if latest_db_sess and latest_db_sess["status"] == "ACTIVE_SEARCHING":
            db.update_session_status(latest_db_sess["session_id"], "TERMINATED", latest_db_sess["filled_count"], stopped_at=time.time())
            return {"status": "TERMINATED", "session_id": latest_db_sess["session_id"]}
        
        return {"status": "IDLE", "message": "Tidak ada sesi aktif yang sedang berjalan."}

    def run_cycle_for_user(self, user_id: int, dry_run: bool = False) -> Dict[str, Any]:
        """Executes one scan-evaluate-execute cycle for this user."""
        orch = self.get_orchestrator(user_id)
        if not orch.current_session:
            latest = db.get_latest_user_session(user_id)
            if latest and latest["status"] in ("ACTIVE_SEARCHING", "EXHAUSTED"):
                # Restore session into orchestrator
                orch.current_session = SessionState(
                    session_id=latest["session_id"],
                    status=latest["status"],
                    margin_per_pos=latest["margin_per_pos"],
                    leverage=latest["leverage"],
                    quota=latest["quota"],
                    filled_count=latest["filled_count"],
                    started_at=latest["started_at"]
                )
            else:
                return {"status": "NO_ACTIVE_SESSION", "message": "Sesi belum dimulai. Tekan tombol Mulai Bot terlebih dahulu."}

        res = orch.run_cycle(dry_run=dry_run)
        
        # Update database session state
        if orch.current_session:
            db.update_session_status(
                orch.current_session.session_id,
                orch.current_session.status,
                orch.current_session.filled_count
            )

        # Humanize each candidate evaluation for senior/non-technical users
        is_quota_full = (orch.current_session.filled_count >= orch.current_session.quota) if orch.current_session else False
        humanized_evals = []
        for ev in res.get("evaluations", []):
            sizing = ev.get("sizing", {})
            executed = bool(ev.get("executed", False))
            order_id = ev.get("order_id")
            dry_run_flag = bool(ev.get("dry_run", dry_run))
            sizing_valid = bool(sizing.get("is_valid", True))
            h = humanize_ai_decision(
                symbol=ev.get("symbol", ""),
                decision=ev.get("ai_decision", "SKIP"),
                confidence=ev.get("ai_confidence", 0),
                evidence=ev.get("ai_evidence", ""),
                risk_factors=ev.get("risk_factors", ""),
                price=ev.get("price", 0.0),
                change_24h=ev.get("market_features", {}).get("timeframes", {}).get("15m", {}).get("change_pct", 0.0) or 0.0,
                spread_pct=ev.get("market_features", {}).get("spread_pct", 0.0) or 0.0,
                margin_per_pos=orch.current_session.margin_per_pos if orch.current_session else 5.0,
                leverage=orch.current_session.leverage if orch.current_session else 20,
                executed=executed,
                order_id=str(order_id) if order_id else None,
                dry_run=dry_run_flag,
                sizing_valid=sizing_valid,
                is_quota_full=is_quota_full
            )
            # Add execution information
            h["executed"] = executed
            h["order_id"] = order_id
            h["client_order_id"] = ev.get("client_order_id")
            h["dry_run"] = dry_run_flag
            h["quantity"] = sizing.get("quantity", 0)
            h["notional"] = sizing.get("notional_value", 0)
            
            # Record order to DB if executed
            if executed and order_id:
                db.record_order(
                    user_id=user_id,
                    session_id=orch.current_session.session_id,
                    symbol=ev.get("symbol"),
                    quantity=sizing.get("quantity", 0),
                    price=ev.get("price", 0.0),
                    notional=sizing.get("notional_value", 0),
                    leverage=orch.current_session.leverage,
                    client_order_id=ev.get("client_order_id", ""),
                    order_id=str(order_id),
                    status="FILLED"
                )

            humanized_evals.append(h)

        res["evaluations"] = humanized_evals
        return res

    def close_user_position(self, user_id: int, symbol: str, position_side: str = "SHORT") -> Dict[str, Any]:
        import uuid
        client = self.get_client(user_id)
        positions = client.get_positions()
        target_pos = None
        for p in positions:
            amt = float(p.get("positionAmt", 0))
            p_side = p.get("positionSide", "SHORT")
            if p.get("symbol") == symbol and p_side == position_side and abs(amt) > 0:
                target_pos = p
                break

        if not target_pos:
            raise ValueError(f"Tidak ditemukan posisi aktif untuk simbol {symbol}.")

        qty = abs(float(target_pos.get("positionAmt", 0)))
        client_order_id = f"bx_cls_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        res = client.close_position(
            symbol=symbol,
            position_side=position_side,
            quantity=qty,
            client_order_id=client_order_id
        )
        return {
            "success": True,
            "symbol": symbol,
            "quantity": qty,
            "order_id": res.get("orderId"),
            "message": f"Posisi {symbol} berhasil ditutup di pasar BingX."
        }
