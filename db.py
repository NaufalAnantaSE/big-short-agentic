"""Database module using SQLite for user isolation, encrypted credential storage, and session auditing."""

import os
import sqlite3
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
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

        # Ensure default admin account exists
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        row = cursor.fetchone()
        if not row:
            now = datetime.utcnow().isoformat()
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
            now = datetime.utcnow().isoformat()
            default_pass = "naufal2026trader"
            cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, is_demo, created_at)
            VALUES (?, ?, ?, 'user', 1, ?)
            """, ("naufal", hash_password(default_pass), "Naufal Ananta (Personal Trader)", now))
            conn.commit()

init_db()

# User repository functions
def create_user(username: str, password: str, full_name: str = "", role: str = "user") -> int:
    now = datetime.utcnow().isoformat()
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
def save_session(session_id: str, user_id: int, status: str, margin: float, leverage: int, quota: int, filled_count: int, mode: str, is_live: bool, started_at: float):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO sessions (session_id, user_id, status, margin_per_pos, leverage, quota, filled_count, mode, is_live, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, user_id, status, margin, leverage, quota, filled_count, mode, 1 if is_live else 0, started_at))
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

def get_latest_user_session(user_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY started_at DESC LIMIT 1", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def record_order(user_id: int, session_id: str, symbol: str, quantity: float, price: float, notional: float, leverage: int, client_order_id: str, order_id: Optional[str], status: str):
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO order_records (user_id, session_id, symbol, side, position_side, quantity, price, notional, leverage, client_order_id, order_id, status, created_at)
        VALUES (?, ?, ?, 'SELL', 'SHORT', ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, session_id, symbol, quantity, price, notional, leverage, client_order_id, order_id, status, now))
        conn.commit()

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
