"""Multi-Tenant Session Manager: Enforces absolute tenant isolation by maintaining
isolated BingXClient and SessionOrchestrator instances per user.
No API credentials or session states are ever shared between tenants.
Includes autonomous background runner for persistent scanning when frontend is closed.
"""

import time
import json
import threading
from typing import Dict, Any, Optional, List, Set
from config import AppConfig
from client import BingXClient, BingXAPIError
from orchestrator import SessionOrchestrator, SessionState
from plain_explainer import humanize_ai_decision
from audit_logger import AuditLogger
from ai_settings import get_ai_settings
from contracts import ExecutionMode, Environment, DirectionMode
import db

class TenantSessionManager:
    def __init__(self, base_config: AppConfig):
        self.base_config = base_config
        # In-memory tenant orchestrator pool: user_id -> SessionOrchestrator
        self._orchestrator_pool: Dict[int, SessionOrchestrator] = {}
        # In-memory tenant client pool: user_id -> BingXClient
        self._client_pool: Dict[int, BingXClient] = {}
        # Cached latest evaluations: user_id -> list of evaluations
        self._latest_evaluations: Dict[int, list] = {}
        # Concurrency guard: track which user_id is currently executing a cycle
        self._currently_scanning: Set[int] = set()
        self._scan_state_lock = threading.Lock()
        self._last_scan_times: Dict[int, float] = {}
        
        # Autonomous background worker state
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_running: bool = False
        self._worker_lock = threading.Lock()

    def start_background_worker(self):
        """Starts the autonomous background worker thread if not already running."""
        with self._worker_lock:
            if self._worker_running:
                return
            self._worker_running = True
            self._worker_thread = threading.Thread(
                target=self._autonomous_worker_loop,
                daemon=True,
                name="BingX-Autonomous-Scanner"
            )
            self._worker_thread.start()

    def stop_background_worker(self):
        """Stops the autonomous background worker thread."""
        with self._worker_lock:
            self._worker_running = False
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=2.0)
                self._worker_thread = None

    def _autonomous_worker_loop(self):
        while self._worker_running:
            try:
                self._run_autonomous_tick()
            except Exception as e:
                time.sleep(2)
            time.sleep(3)

    def _run_autonomous_tick(self):
        active_sessions = db.get_active_searching_sessions()
        now = time.time()
        for sess in active_sessions:
            user_id = sess["user_id"]
            with self._scan_state_lock:
                if user_id in self._currently_scanning:
                    continue
                # Reserve before spawning the thread. Checking here and
                # adding inside the worker is racy on a fast scheduler tick.
                if not db.claim_due_session(sess["session_id"], now=now):
                    continue
                self._currently_scanning.add(user_id)

            # Spawn scheduled cycle in a background thread so one user does not block others
            t = threading.Thread(
                target=self._execute_scheduled_cycle,
                args=(user_id, sess),
                daemon=True,
                name=f"Worker-Scan-User-{user_id}"
            )
            t.start()

    def _execute_scheduled_cycle(self, user_id: int, sess: Dict[str, Any]):
        try:
            # 1. Sync positions first
            client = self.get_client(user_id)
            pos_data = client.get_positions()
            active_count = len([p for p in pos_data if float(p.get("positionAmt", p.get("initialMargin", 0))) != 0])
            quota = int(sess.get("quota", 10))

            orch = self.get_orchestrator(user_id)
            sess_mode = sess.get("mode", "PUMP_GAINERS")
            orch.config.universe_mode = sess_mode
            if not orch.current_session:
                orch.current_session = SessionState(
                    session_id=sess["session_id"],
                    status=sess["status"],
                    margin_per_pos=sess["margin_per_pos"],
                    leverage=sess["leverage"],
                    quota=quota,
                    environment=sess.get("environment", "BINGX_VST"),
                    execution_mode=sess.get("execution_mode", "EXCHANGE_DEMO"),
                    direction_mode=sess.get("direction_mode", "SHORT"),
                    exit_policy=sess.get("exit_policy", "MANUAL_ONLY"),
                    universe_mode=sess_mode,
                    filled_count=active_count,
                    started_at=sess["started_at"]
                )
            else:
                orch.current_session.universe_mode = sess_mode
                orch.current_session.filled_count = active_count

            # If quota is already filled:
            if active_count >= quota:
                orch.current_session.status = "EXHAUSTED"
                db.update_session_status(sess["session_id"], "EXHAUSTED", active_count)
                return

            if orch.current_session.status == "EXHAUSTED" and active_count < quota:
                orch.current_session.status = "ACTIVE_SEARCHING"
                db.update_session_status(sess["session_id"], "ACTIVE_SEARCHING", active_count)

            # 2. Run the cycle
            # An exchange session (EXCHANGE_DEMO or EXCHANGE_LIVE) executes orders to the exchange.
            # Only LOCAL_PAPER runs in dry_run mode.
            exec_mode = sess.get("execution_mode") or ExecutionMode.EXCHANGE_DEMO.value
            is_local = (exec_mode == ExecutionMode.LOCAL_PAPER.value)
            self.run_cycle_for_user(user_id, dry_run=is_local)
        except Exception as exc:
            AuditLogger.log_event("BACKGROUND_SCAN_ERROR", {"user_id": user_id, "error": str(exc)}, session_id=sess.get("session_id"))
        finally:
            self._last_scan_times[user_id] = time.time()
            with self._scan_state_lock:
                self._currently_scanning.discard(user_id)

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
        """Fetches live balance, positions, and current dynamic session state for this tenant."""
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

        active_count = len(active_positions)

        # Check in-memory or persisted session
        orch = self._orchestrator_pool.get(user_id)
        current_sess = orch.current_session if orch else None
        latest_db_sess = db.get_latest_user_session(user_id)

        # Sync filled_count and status with actual active positions from BingX
        current_status = "IDLE"
        sess_id = None
        quota = 10
        margin_per_pos = 5.0
        leverage = 20
        auto_scan = True
        scan_interval = 60
        last_scan_at = None
        environment = "BINGX_VST"
        execution_mode = "EXCHANGE_DEMO"
        direction_mode = "SHORT"
        exit_policy = "MANUAL_ONLY"
        universe_mode = "PUMP_GAINERS"

        if current_sess:
            current_sess.filled_count = active_count
            quota = current_sess.quota
            margin_per_pos = current_sess.margin_per_pos
            leverage = current_sess.leverage
            sess_id = current_sess.session_id
            if active_count >= quota:
                current_sess.status = "EXHAUSTED"
            elif current_sess.status == "EXHAUSTED" and active_count < quota:
                current_sess.status = "ACTIVE_SEARCHING"
            current_status = current_sess.status
            environment = current_sess.environment
            execution_mode = current_sess.execution_mode
            direction_mode = current_sess.direction_mode
            exit_policy = current_sess.exit_policy
            universe_mode = getattr(current_sess, "universe_mode", "PUMP_GAINERS")
            db.update_session_status(current_sess.session_id, current_status, active_count)
        elif latest_db_sess:
            sess_id = latest_db_sess["session_id"]
            quota = latest_db_sess["quota"]
            margin_per_pos = latest_db_sess["margin_per_pos"]
            leverage = latest_db_sess["leverage"]
            current_status = latest_db_sess["status"]
            environment = latest_db_sess.get("environment", "BINGX_VST")
            execution_mode = latest_db_sess.get("execution_mode", "EXCHANGE_DEMO")
            direction_mode = latest_db_sess.get("direction_mode", "SHORT")
            exit_policy = latest_db_sess.get("exit_policy", "MANUAL_ONLY")
            universe_mode = latest_db_sess.get("mode", "PUMP_GAINERS")
            if current_status in ("ACTIVE_SEARCHING", "EXHAUSTED"):
                if active_count >= quota:
                    current_status = "EXHAUSTED"
                elif current_status == "EXHAUSTED" and active_count < quota:
                    current_status = "ACTIVE_SEARCHING"
                db.update_session_status(sess_id, current_status, active_count)

        if latest_db_sess:
            auto_scan = bool(latest_db_sess.get("auto_scan", 1))
            scan_interval = int(latest_db_sess.get("scan_interval", 60))
            last_scan_at = latest_db_sess.get("last_scan_at")

        # Calculate countdown
        now = time.time()
        next_scan_in = 0
        if auto_scan and current_status == "ACTIVE_SEARCHING":
            last_t = last_scan_at or self._last_scan_times.get(user_id) or 0.0
            if last_t > 0:
                next_scan_in = max(0, int(scan_interval - (now - last_t)))
            else:
                next_scan_in = 0

        # Retrieve cached latest evaluations
        latest_evals = self._latest_evaluations.get(user_id)
        if latest_evals is None and latest_db_sess and latest_db_sess.get("latest_evaluations"):
            try:
                latest_evals = json.loads(latest_db_sess["latest_evaluations"])
            except Exception:
                latest_evals = []
        if latest_evals is None:
            latest_evals = []

        session_info = {
            "status": current_status,
            "session_id": sess_id,
            "quota": quota,
            "filled_count": active_count,
            "margin_per_pos": margin_per_pos,
            "leverage": leverage,
            "environment": environment,
            "execution_mode": execution_mode,
            "direction_mode": direction_mode,
            "exit_policy": exit_policy,
            "mode": universe_mode,
            "universe_mode": universe_mode,
            "auto_scan": auto_scan,
            "scan_interval": scan_interval,
            "last_scan_at": last_scan_at,
            "next_scan_in": next_scan_in,
            "is_scanning": (user_id in self._currently_scanning),
            "watchlist": [entry.model_dump() for entry in orch.watchlist.get_all_entries()] if orch else [],
            "resting_orders_count": orch.watchlist.count_resting_orders() if orch else 0
        }

        return {
            "asset": asset_name,
            "balance": balance,
            "equity": equity,
            "available_margin": available_margin,
            "used_margin": used_margin,
            "unrealized_pnl": unrealized_pnl,
            "active_positions_count": active_count,
            "active_positions": active_positions,
            "session": session_info,
            "latest_evaluations": latest_evals,
            "last_sync_at": now,
            "has_keys": True
        }

    def start_session(
        self,
        user_id: int,
        margin_per_pos: float = 5.0,
        leverage: int = 20,
        quota: int = 10,
        mode: str = "PUMP_GAINERS",
        is_live: bool = False,
        auto_scan: bool = True,
        scan_interval: int = 60,
        environment: str = "BINGX_VST",
        execution_mode: str = "EXCHANGE_DEMO",
        direction_mode: str = "SHORT",
        exit_policy: str = "MANUAL_ONLY"
    ) -> Dict[str, Any]:
        """Initializes and persists a new trading session for this user."""
        orch = self.get_orchestrator(user_id)
        validated_mode = str(mode or "PUMP_GAINERS").upper()
        if validated_mode not in ("PUMP_GAINERS", "MEME_ONLY"):
            validated_mode = "PUMP_GAINERS"
        orch.config.universe_mode = validated_mode
        session_state = orch.start_session(
            margin_per_pos=margin_per_pos,
            leverage=leverage,
            quota=quota,
            environment=environment,
            execution_mode=execution_mode,
            direction_mode=direction_mode,
            exit_policy=exit_policy,
            universe_mode=validated_mode
        )
        
        now = time.time()
        # Persist to database
        db.save_session(
            session_id=session_state.session_id,
            user_id=user_id,
            status=session_state.status,
            margin=margin_per_pos,
            leverage=leverage,
            quota=quota,
            filled_count=0,
            mode=validated_mode,
            is_live=is_live,
            started_at=session_state.started_at,
            auto_scan=auto_scan,
            scan_interval=scan_interval,
            last_scan_at=None,
            latest_evaluations="[]",
            environment=environment,
            execution_mode=execution_mode,
            direction_mode=direction_mode,
            exit_policy=exit_policy
        )

        # Reserve the first scan before spawning it. Without this claim, the
        # daemon could see the newly inserted session at the same time and
        # launch a duplicate first cycle.
        if auto_scan:
            initial_session = {
                    "session_id": session_state.session_id,
                    "status": session_state.status,
                    "margin_per_pos": margin_per_pos,
                    "leverage": leverage,
                    "quota": quota,
                    "mode": mode,
                    "is_live": 1 if is_live else 0,
                    "started_at": session_state.started_at,
                    "auto_scan": 1,
                    "scan_interval": scan_interval
            }
            if db.claim_due_session(session_state.session_id, now=now):
                with self._scan_state_lock:
                    self._currently_scanning.add(user_id)
                threading.Thread(
                    target=self._execute_scheduled_cycle,
                    args=(user_id, initial_session),
                    daemon=True,
                    name=f"Initial-Scan-User-{user_id}"
                ).start()

        return {
            "session_id": session_state.session_id,
            "status": session_state.status,
            "margin_per_pos": margin_per_pos,
            "leverage": leverage,
            "quota": quota,
            "mode": validated_mode,
            "universe_mode": validated_mode,
            "is_live": is_live,
            "environment": environment,
            "execution_mode": execution_mode,
            "direction_mode": direction_mode,
            "exit_policy": exit_policy,
            "auto_scan": auto_scan,
            "scan_interval": scan_interval
        }

    def update_session_params(
        self,
        user_id: int,
        margin_per_pos: Optional[float] = None,
        quota: Optional[int] = None,
        auto_scan: Optional[bool] = None,
        scan_interval: Optional[int] = None
    ) -> Dict[str, Any]:
        """Allows dynamically updating margin, quota, and auto_scan for active user session."""
        orch = self.get_orchestrator(user_id)
        if not orch.current_session:
            latest = db.get_latest_user_session(user_id)
            if latest and latest["status"] in ("ACTIVE_SEARCHING", "EXHAUSTED"):
                u_mode = latest.get("mode", "PUMP_GAINERS")
                orch.config.universe_mode = u_mode
                orch.current_session = SessionState(
                    session_id=latest["session_id"],
                    status=latest["status"],
                    margin_per_pos=latest["margin_per_pos"],
                    leverage=latest["leverage"],
                    quota=latest["quota"],
                    environment=latest.get("environment", "BINGX_VST"),
                    execution_mode=latest.get("execution_mode", "EXCHANGE_DEMO"),
                    direction_mode=latest.get("direction_mode", "SHORT"),
                    exit_policy=latest.get("exit_policy", "MANUAL_ONLY"),
                    universe_mode=u_mode,
                    filled_count=latest["filled_count"],
                    started_at=latest["started_at"]
                )

        latest_db = db.get_latest_user_session(user_id)
        if orch.current_session:
            sess_id = orch.current_session.session_id
            if margin_per_pos is not None:
                orch.current_session.margin_per_pos = float(margin_per_pos)
            if quota is not None:
                orch.current_session.quota = int(quota)
                if orch.current_session.status == "EXHAUSTED" and orch.current_session.filled_count < orch.current_session.quota:
                    orch.current_session.status = "ACTIVE_SEARCHING"
            cur_status = orch.current_session.status
            cur_margin = orch.current_session.margin_per_pos
            cur_quota = orch.current_session.quota
            cur_filled = orch.current_session.filled_count
        elif latest_db:
            sess_id = latest_db["session_id"]
            cur_status = latest_db["status"]
            cur_margin = float(margin_per_pos) if margin_per_pos is not None else latest_db["margin_per_pos"]
            cur_quota = int(quota) if quota is not None else latest_db["quota"]
            cur_filled = latest_db["filled_count"]
        else:
            return {"status": "NO_ACTIVE_SESSION", "message": "Tidak ada sesi aktif untuk diperbarui."}

        db.update_session_params(
            session_id=sess_id,
            margin_per_pos=cur_margin,
            quota=cur_quota,
            status=cur_status,
            auto_scan=auto_scan,
            scan_interval=scan_interval
        )

        res = {
            "session_id": sess_id,
            "status": cur_status,
            "margin_per_pos": cur_margin,
            "quota": cur_quota,
            "filled_count": cur_filled
        }
        if auto_scan is not None:
            res["auto_scan"] = auto_scan
        if scan_interval is not None:
            res["scan_interval"] = scan_interval
        return res

    def set_user_auto_scan(self, user_id: int, auto_scan: bool, scan_interval: Optional[int] = None) -> Dict[str, Any]:
        """Toggles the autonomous background scanner for this user's active session."""
        latest = db.get_latest_user_session(user_id)
        if not latest or latest["status"] not in ("ACTIVE_SEARCHING", "EXHAUSTED"):
            raise ValueError("Tidak ada sesi aktif yang berjalan. Silakan mulai bot terlebih dahulu.")

        db.update_session_auto_scan(latest["session_id"], auto_scan, scan_interval)
        
        # If toggled ON, kick off one claimed cycle immediately if due.
        if auto_scan and user_id not in self._currently_scanning:
            now = time.time()
            if db.claim_due_session(latest["session_id"], now=now):
                with self._scan_state_lock:
                    self._currently_scanning.add(user_id)
                threading.Thread(
                    target=self._execute_scheduled_cycle,
                    args=(user_id, {**latest, "auto_scan": 1}),
                    daemon=True,
                    name=f"Manual-Trigger-Scan-{user_id}"
                ).start()

        return {
            "session_id": latest["session_id"],
            "auto_scan": auto_scan,
            "scan_interval": scan_interval or latest.get("scan_interval", 60),
            "status": latest["status"]
        }

    def stop_session(self, user_id: int) -> Dict[str, Any]:
        """Stops searching session without closing existing positions."""
        orch = self._orchestrator_pool.get(user_id)
        if orch and orch.current_session:
            sess = orch.stop_session()
            if sess:
                db.update_session_status(sess.session_id, "TERMINATED", sess.filled_count, stopped_at=time.time())
                db.update_session_auto_scan(sess.session_id, False)
                return {"status": "TERMINATED", "session_id": sess.session_id}
        
        latest_db_sess = db.get_latest_user_session(user_id)
        if latest_db_sess and latest_db_sess["status"] in ("ACTIVE_SEARCHING", "EXHAUSTED"):
            db.update_session_status(latest_db_sess["session_id"], "TERMINATED", latest_db_sess["filled_count"], stopped_at=time.time())
            db.update_session_auto_scan(latest_db_sess["session_id"], False)
            return {"status": "TERMINATED", "session_id": latest_db_sess["session_id"]}
        
        return {"status": "IDLE", "message": "Tidak ada sesi aktif yang sedang berjalan."}

    def reload_ai_settings(self):
        """Propagates updated AI settings to all active orchestrator instances."""
        ai_cfg = get_ai_settings()
        for orch in self._orchestrator_pool.values():
            orch.config.ai_model_name = ai_cfg["model"]
            orch.ai.config.ai_model_name = ai_cfg["model"]

    def run_cycle_for_user(self, user_id: int, dry_run: bool = False) -> Dict[str, Any]:
        """Executes one scan-evaluate-execute cycle for this user."""
        orch = self.get_orchestrator(user_id)
        # Always synchronize dynamic AI model setting configured by admin
        ai_cfg = get_ai_settings()
        orch.config.ai_model_name = ai_cfg["model"]
        orch.ai.config.ai_model_name = ai_cfg["model"]
        if not orch.current_session:
            latest = db.get_latest_user_session(user_id)
            if latest and latest["status"] in ("ACTIVE_SEARCHING", "EXHAUSTED"):
                u_mode = latest.get("mode", "PUMP_GAINERS")
                orch.config.universe_mode = u_mode
                # Restore session into orchestrator
                orch.current_session = SessionState(
                    session_id=latest["session_id"],
                    status=latest["status"],
                    margin_per_pos=latest["margin_per_pos"],
                    leverage=latest["leverage"],
                    quota=latest["quota"],
                    environment=latest.get("environment", "BINGX_VST"),
                    execution_mode=latest.get("execution_mode", "EXCHANGE_DEMO"),
                    direction_mode=latest.get("direction_mode", "SHORT"),
                    exit_policy=latest.get("exit_policy", "MANUAL_ONLY"),
                    universe_mode=u_mode,
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
            mf = ev.get("market_features", {}) or {}
            fib = mf.get("fibonacci")
            imp = mf.get("impulse_wave")
            f_sent = mf.get("funding_sentiment")
            fr = mf.get("funding_rate")
            sl_price = ev.get("stop_loss_price") or sizing.get("stop_loss_price")
            tp_price = ev.get("take_profit_price") or sizing.get("take_profit_price")
            sl_pct = ev.get("sl_percent") or sizing.get("sl_percent")
            tp_pct = ev.get("tp_percent") or sizing.get("tp_percent")
            risk_usdt = ev.get("risk_amount_usdt") or sizing.get("risk_amount_usdt")
            profit_usdt = ev.get("potential_profit_usdt") or sizing.get("potential_profit_usdt")
            rsi_data = mf.get("rsi")
            bb_data = mf.get("bollinger")
            ema_data = mf.get("ema_trend")
            playbook_data = ev.get("playbook")

            session_dir = orch.current_session.direction_mode if orch.current_session else "SHORT"
            raw_dir = (
                ev.get("direction")
                or ev.get("suggested_direction")
                or (playbook_data.get("direction") if isinstance(playbook_data, dict) else None)
                or session_dir
            )
            # Never force BOTH-mode candidates into a SHORT narrative: pass BOTH
            # through so the explainer can use direction-neutral wording.
            cand_dir = str(raw_dir).upper() if str(raw_dir).upper() in ("LONG", "SHORT", "BOTH") else session_dir

            h = humanize_ai_decision(
                symbol=ev.get("symbol", ""),
                decision=ev.get("ai_decision", "SKIP"),
                confidence=ev.get("ai_confidence", 0),
                evidence=ev.get("ai_evidence", ""),
                risk_factors=ev.get("risk_factors", ""),
                price=ev.get("price", 0.0),
                change_24h=mf.get("timeframes", {}).get("15m", {}).get("change_pct", 0.0) or 0.0,
                spread_pct=mf.get("spread_pct", 0.0) or 0.0,
                margin_per_pos=orch.current_session.margin_per_pos if orch.current_session else 5.0,
                leverage=orch.current_session.leverage if orch.current_session else 20,
                executed=executed,
                order_id=str(order_id) if order_id else None,
                dry_run=dry_run_flag,
                sizing_valid=sizing_valid,
                is_quota_full=is_quota_full,
                fibonacci=fib,
                impulse_wave=imp,
                funding_sentiment=f_sent,
                funding_rate=fr,
                take_profit_price=tp_price,
                stop_loss_price=sl_price,
                tp_percent=tp_pct,
                sl_percent=sl_pct,
                risk_amount_usdt=risk_usdt,
                potential_profit_usdt=profit_usdt,
                rsi=rsi_data,
                bollinger=bb_data,
                ema_trend=ema_data,
                playbook=playbook_data,
                sizing_rejection=sizing.get("rejection_reason"),
                direction=cand_dir
            )
            # Add execution information
            h["executed"] = executed
            h["order_id"] = order_id
            h["client_order_id"] = ev.get("client_order_id")
            h["dry_run"] = dry_run_flag
            h["quantity"] = sizing.get("quantity", 0)
            h["notional"] = sizing.get("notional_value", 0)
            h["stop_loss_price"] = sl_price
            h["take_profit_price"] = tp_price
            h["playbook"] = playbook_data
            h["sl_percent"] = sl_pct
            h["tp_percent"] = tp_pct
            
            # Record order to DB if executed
            if executed and order_id:
                is_long_order = (ev.get("ai_decision") == "ENTER_LONG")
                pos_side = "LONG" if is_long_order else "SHORT"
                ord_side = "BUY" if is_long_order else "SELL"
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
                    status="FILLED",
                    side=ord_side,
                    position_side=pos_side,
                    stop_loss_price=sl_price,
                    take_profit_price=tp_price
                )

            humanized_evals.append(h)

        res["evaluations"] = humanized_evals
        
        # Cache evaluations and persist them into SQLite so frontend refresh retains the cards
        self._latest_evaluations[user_id] = humanized_evals
        now_ts = time.time()
        self._last_scan_times[user_id] = now_ts
        if orch.current_session:
            db.save_latest_evaluations(orch.current_session.session_id, json.dumps(humanized_evals), now_ts)

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
