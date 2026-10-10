"""Database module using SQLite for user isolation, encrypted credential storage, and session auditing."""

import os
import sqlite3
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from security import hash_password, encrypt_credential, decrypt_credential

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            encrypted_api_key TEXT DEFAULT '',
            encrypted_secret_key TEXT DEFAULT '',
            is_demo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            margin_per_pos REAL NOT NULL,
            leverage INTEGER NOT NULL,
            quota INTEGER NOT NULL,
            filled_count INTEGER NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'PUMP_GAINERS',
            is_live INTEGER NOT NULL DEFAULT 0,
            auto_scan INTEGER NOT NULL DEFAULT 1,
            scan_interval INTEGER NOT NULL DEFAULT 60,
            environment TEXT NOT NULL DEFAULT 'BINGX_VST',
            execution_mode TEXT NOT NULL DEFAULT 'EXCHANGE_DEMO',
            direction_mode TEXT NOT NULL DEFAULT 'SHORT',
            exit_policy TEXT NOT NULL DEFAULT 'MANUAL_ONLY',
            last_scan_at REAL,
            latest_evaluations TEXT DEFAULT '[]',
            started_at REAL NOT NULL,
            stopped_at REAL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS order_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL DEFAULT 'SELL',
            position_side TEXT NOT NULL DEFAULT 'SHORT',
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            notional REAL NOT NULL,
            leverage INTEGER NOT NULL,
            client_order_id TEXT NOT NULL,
            order_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # Safe schema evolution for existing tables
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sessions)")
        existing_cols = {r[1] for r in cursor.fetchall()}
        if "auto_scan" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN auto_scan INTEGER NOT NULL DEFAULT 1")
        if "scan_interval" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN scan_interval INTEGER NOT NULL DEFAULT 60")
        if "last_scan_at" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_scan_at REAL")
        if "latest_evaluations" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN latest_evaluations TEXT DEFAULT '[]'")
        if "environment" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN environment TEXT NOT NULL DEFAULT 'BINGX_VST'")
        if "execution_mode" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'EXCHANGE_DEMO'")
        if "direction_mode" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN direction_mode TEXT NOT NULL DEFAULT 'SHORT'")
        if "exit_policy" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN exit_policy TEXT NOT NULL DEFAULT 'MANUAL_ONLY'")

        # Safe schema evolution for order_records
        cursor.execute("PRAGMA table_info(order_records)")
        existing_order_cols = {r[1] for r in cursor.fetchall()}
        if "stop_loss_price" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN stop_loss_price REAL")
        if "take_profit_price" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN take_profit_price REAL")
        if "quote_ts" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN quote_ts INTEGER")
        if "request_price" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN request_price REAL")
        if "avg_fill_price" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN avg_fill_price REAL")
        if "effective_leverage" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN effective_leverage INTEGER")
        if "entry_fee" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN entry_fee REAL DEFAULT 0.0")
        if "exit_price" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN exit_price REAL")
        if "exit_time" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN exit_time TEXT")
        if "exit_reason" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN exit_reason TEXT")
        if "exit_fee" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN exit_fee REAL DEFAULT 0.0")
        if "funding_fee" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN funding_fee REAL DEFAULT 0.0")
        if "realized_pnl" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN realized_pnl REAL DEFAULT 0.0")
        if "realized_r" not in existing_order_cols:
            cursor.execute("ALTER TABLE order_records ADD COLUMN realized_r REAL DEFAULT 0.0")

        # Safe schema evolution for sessions table (equity snapshot)
        if "initial_equity" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN initial_equity REAL")
        if "final_equity" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN final_equity REAL")
        if "daily_realized_pnl" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN daily_realized_pnl REAL DEFAULT 0.0")
        if "consecutive_losses" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN consecutive_losses INTEGER DEFAULT 0")
        if "cooldown_until" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN cooldown_until REAL DEFAULT 0.0")
        if "last_pnl_date" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_pnl_date TEXT")
        if "processed_income_ids" not in existing_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN processed_income_ids TEXT DEFAULT '[]'")

        conn.commit()

        # Ensure default admin account exists
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        row = cursor.fetchone()
        if not row:
            now = datetime.now(timezone.utc).isoformat()
            default_pass = "naufal2026admin"
            cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, is_demo, created_at)
            VALUES (?, ?, ?, 'admin', 1, ?)
            """, ("admin", hash_password(default_pass), "Naufal Ananta (Admin)", now))
            conn.commit()

        # Ensure default personal trader account exists for Naufal
        cursor.execute("SELECT id FROM users WHERE username = 'naufal' LIMIT 1")
        row_naufal = cursor.fetchone()
        if not row_naufal:
            now = datetime.now(timezone.utc).isoformat()
            default_pass = "naufal2026trader"
            cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, is_demo, created_at)
            VALUES (?, ?, ?, 'user', 1, ?)
            """, ("naufal", hash_password(default_pass), "Naufal Ananta (Personal Trader)", now))
            conn.commit()

init_db()

# User repository functions
def create_user(username: str, password: str, full_name: str = "", role: str = "user") -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO users (username, password_hash, full_name, role, is_demo, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        """, (username, hash_password(password), full_name, role, now))
        conn.commit()
        return cursor.lastrowid or 0

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_user_credentials(user_id: int, api_key: str, secret_key: str, is_demo: bool = True) -> bool:
    enc_api = encrypt_credential(api_key.strip())
    enc_sec = encrypt_credential(secret_key.strip())
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE users
        SET encrypted_api_key = ?, encrypted_secret_key = ?, is_demo = ?
        WHERE id = ?
        """, (enc_api, enc_sec, 1 if is_demo else 0, user_id))
        conn.commit()
        return cursor.rowcount > 0

def get_decrypted_user_credentials(user_id: int) -> Optional[Dict[str, Any]]:
    user = get_user_by_id(user_id)
    if not user:
        return None
    api_key = decrypt_credential(user.get("encrypted_api_key", ""))
    secret_key = decrypt_credential(user.get("encrypted_secret_key", ""))
    return {
        "user_id": user["id"],
        "username": user["username"],
        "api_key": api_key,
        "secret_key": secret_key,
        "is_demo": bool(user.get("is_demo", 1)),
        "has_keys": bool(api_key and secret_key)
    }

def list_all_users() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, full_name, role, is_demo, created_at, (encrypted_api_key != '') as has_api_key FROM users")
        return [dict(r) for r in cursor.fetchall()]

# Session persistence
def save_session(
    session_id: str,
    user_id: int,
    status: str,
    margin: float,
    leverage: int,
    quota: int,
    filled_count: int,
    mode: str,
    is_live: bool,
    started_at: float,
    auto_scan: bool = True,
    scan_interval: int = 60,
    last_scan_at: Optional[float] = None,
    latest_evaluations: str = "[]",
    environment: str = "BINGX_VST",
    execution_mode: str = "EXCHANGE_DEMO",
    direction_mode: str = "SHORT",
    exit_policy: str = "MANUAL_ONLY"
):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO sessions (
            session_id, user_id, status, margin_per_pos, leverage, quota, filled_count,
            mode, is_live, started_at, auto_scan, scan_interval, last_scan_at, latest_evaluations,
            environment, execution_mode, direction_mode, exit_policy
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, user_id, status, margin, leverage, quota, filled_count,
            mode, 1 if is_live else 0, started_at, 1 if auto_scan else 0, scan_interval,
            last_scan_at, latest_evaluations,
            environment, execution_mode, direction_mode, exit_policy
        ))
        conn.commit()

def update_session_equity(session_id: str, initial_equity: Optional[float] = None, final_equity: Optional[float] = None):
    """P1-4: Records initial or final session equity snapshots."""
    with get_db() as conn:
        cursor = conn.cursor()
        if initial_equity is not None:
            cursor.execute("UPDATE sessions SET initial_equity = ? WHERE session_id = ?", (initial_equity, session_id))
        if final_equity is not None:
            cursor.execute("UPDATE sessions SET final_equity = ? WHERE session_id = ?", (final_equity, session_id))
        conn.commit()


def update_session_pnl_state(
    session_id: str,
    daily_realized_pnl: float,
    consecutive_losses: int,
    cooldown_until: float,
    last_pnl_date: str,
    processed_income_ids: str = "[]"
):
    """F-06: Persists daily realized PnL, loss streaks, cooldown, and processed income IDs."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE sessions
            SET daily_realized_pnl = ?,
                consecutive_losses = ?,
                cooldown_until = ?,
                last_pnl_date = ?,
                processed_income_ids = ?
            WHERE session_id = ?
        """, (daily_realized_pnl, consecutive_losses, cooldown_until, last_pnl_date, processed_income_ids, session_id))
        conn.commit()


def update_session_status(session_id: str, status: str, filled_count: int, stopped_at: Optional[float] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        if stopped_at:
            cursor.execute("UPDATE sessions SET status = ?, filled_count = ?, stopped_at = ? WHERE session_id = ?",
                           (status, filled_count, stopped_at, session_id))
        else:
            cursor.execute("UPDATE sessions SET status = ?, filled_count = ? WHERE session_id = ?",
                           (status, filled_count, session_id))
        conn.commit()

def update_session_params(
    session_id: str,
    margin_per_pos: Optional[float] = None,
    quota: Optional[int] = None,
    status: Optional[str] = None,
    auto_scan: Optional[bool] = None,
    scan_interval: Optional[int] = None
):
    with get_db() as conn:
        cursor = conn.cursor()
        fields = []
        vals = []
        if margin_per_pos is not None:
            fields.append("margin_per_pos = ?")
            vals.append(float(margin_per_pos))
        if quota is not None:
            fields.append("quota = ?")
            vals.append(int(quota))
        if status is not None:
            fields.append("status = ?")
            vals.append(status)
        if auto_scan is not None:
            fields.append("auto_scan = ?")
            vals.append(1 if auto_scan else 0)
        if scan_interval is not None:
            fields.append("scan_interval = ?")
            vals.append(int(scan_interval))
        if fields:
            vals.append(session_id)
            cursor.execute(f"UPDATE sessions SET {', '.join(fields)} WHERE session_id = ?", tuple(vals))
            conn.commit()

def update_session_auto_scan(session_id: str, auto_scan: bool, scan_interval: Optional[int] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        if scan_interval is not None:
            cursor.execute("UPDATE sessions SET auto_scan = ?, scan_interval = ? WHERE session_id = ?",
                           (1 if auto_scan else 0, int(scan_interval), session_id))
        else:
            cursor.execute("UPDATE sessions SET auto_scan = ? WHERE session_id = ?",
                           (1 if auto_scan else 0, session_id))
        conn.commit()

def save_latest_evaluations(session_id: str, evaluations_json: str, last_scan_at: float):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET latest_evaluations = ?, last_scan_at = ? WHERE session_id = ?",
                       (evaluations_json, last_scan_at, session_id))
        conn.commit()

def claim_due_session(session_id: str, now: Optional[float] = None) -> bool:
    """Atomically reserve one scan slot for a persisted session."""
    now = float(now if now is not None else time.time())
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE sessions
            SET last_scan_at = ?
            WHERE session_id = ?
              AND auto_scan = 1
              AND status IN ('ACTIVE_SEARCHING', 'EXHAUSTED')
              AND (last_scan_at IS NULL OR last_scan_at <= (? - scan_interval))
        """, (now, session_id, now))
        conn.commit()
        return cursor.rowcount == 1

def get_active_searching_sessions() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM sessions
            WHERE status IN ('ACTIVE_SEARCHING', 'EXHAUSTED') AND auto_scan = 1
            ORDER BY started_at ASC
        """)
        return [dict(r) for r in cursor.fetchall()]

def get_latest_user_session(user_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY started_at DESC LIMIT 1", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def record_order(
    user_id: int,
    session_id: str,
    symbol: str,
    quantity: float,
    price: float,
    notional: float,
    leverage: int,
    client_order_id: str,
    order_id: Optional[str],
    status: str,
    side: str = "SELL",
    position_side: str = "SHORT",
    stop_loss_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    effective_leverage: Optional[int] = None,
    quote_ts: Optional[int] = None,
    request_price: Optional[float] = None,
    avg_fill_price: Optional[float] = None,
    entry_fee: float = 0.0
):
    now = datetime.now(timezone.utc).isoformat()
    eff_lev = effective_leverage if effective_leverage is not None else leverage
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO order_records (
            user_id, session_id, symbol, side, position_side, quantity, price,
            notional, leverage, effective_leverage, client_order_id, order_id,
            status, created_at, stop_loss_price, take_profit_price,
            quote_ts, request_price, avg_fill_price, entry_fee
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, session_id, symbol, side, position_side, quantity, price,
            notional, leverage, eff_lev, client_order_id, order_id,
            status, now, stop_loss_price, take_profit_price,
            quote_ts, request_price or price, avg_fill_price or price, entry_fee
        ))
        conn.commit()

def record_trade_entry(
    user_id: int,
    session_id: str,
    symbol: str,
    side: str,
    position_side: str,
    quantity: float,
    price: float,
    notional: float,
    effective_leverage: int,
    client_order_id: str,
    order_id: Optional[str] = None,
    status: str = "FILLED",
    stop_loss_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
    quote_ts: Optional[int] = None,
    request_price: Optional[float] = None,
    avg_fill_price: Optional[float] = None,
    entry_fee: float = 0.0
):
    """P1-4: Records complete trade entry in the attribution ledger."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO order_records (
            user_id, session_id, symbol, side, position_side, quantity, price,
            notional, leverage, effective_leverage, client_order_id, order_id,
            status, created_at, stop_loss_price, take_profit_price, quote_ts,
            request_price, avg_fill_price, entry_fee
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, session_id, symbol, side, position_side, quantity, price,
            notional, effective_leverage, effective_leverage, client_order_id,
            order_id, status, now, stop_loss_price, take_profit_price, quote_ts,
            request_price, avg_fill_price or price, entry_fee
        ))
        conn.commit()


def record_trade_exit(
    client_order_id: str,
    exit_price: float,
    exit_reason: str,
    exit_fee: float = 0.0,
    funding_fee: float = 0.0,
    realized_pnl: Optional[float] = None,
    realized_r: Optional[float] = None
):
    """P1-4: Records trade exit fill, reason, fees, and realized R in the ledger."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE order_records
        SET status = 'CLOSED',
            exit_price = ?,
            exit_time = ?,
            exit_reason = ?,
            exit_fee = ?,
            funding_fee = ?,
            realized_pnl = ?,
            realized_r = ?
        WHERE client_order_id = ? OR order_id = ?
        """, (
            exit_price, now, exit_reason, exit_fee, funding_fee,
            realized_pnl or 0.0, realized_r or 0.0, client_order_id, client_order_id
        ))
        conn.commit()


def get_closed_trade_attribution(order_identifier: str) -> Optional[Dict[str, Any]]:
    """
    P1-4: Single-query attribution answering:
    - R berapa? (realized_r)
    - fee berapa? (total_fee = entry_fee + exit_fee + funding_fee)
    - kenapa exit? (exit_reason)
    - leverage efektif berapa? (effective_leverage)
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT symbol, side, position_side, quantity, price as entry_price,
               avg_fill_price, effective_leverage, leverage, stop_loss_price,
               take_profit_price, exit_price, exit_reason, exit_time,
               entry_fee, exit_fee, funding_fee,
               (COALESCE(entry_fee, 0.0) + COALESCE(exit_fee, 0.0) + COALESCE(funding_fee, 0.0)) as total_fee,
               realized_pnl, realized_r, client_order_id, order_id, session_id
        FROM order_records
        WHERE client_order_id = ? OR order_id = ?
        ORDER BY id DESC LIMIT 1
        """, (order_identifier, order_identifier))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def get_user_orders(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM order_records WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return [dict(r) for r in cursor.fetchall()]

def list_all_client_sessions() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, u.username, u.full_name, u.is_demo, (u.encrypted_api_key != '') as has_api_key
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            ORDER BY s.started_at DESC
            LIMIT 50
        """)
        return [dict(r) for r in cursor.fetchall()]
