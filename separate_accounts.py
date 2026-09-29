"""Separate personal trading account from administrative account.
Atomically transfers BingX credentials, sessions, and order records to a dedicated
user role trader account. Stops any active session in the process.
"""

from typing import Dict, Any, Optional
import db
from security import hash_password

def separate_admin_account(
    admin_username: str,
    trader_username: str,
    trader_password: str,
    trader_full_name: str = "Naufal Ananta (Pribadi)"
) -> Dict[str, Any]:
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (admin_username,))
        admin = cursor.fetchone()
        if not admin:
            raise ValueError(f"Admin account '{admin_username}' not found.")
        
        cursor.execute("SELECT * FROM users WHERE username = ?", (trader_username,))
        existing_trader = cursor.fetchone()
        if existing_trader:
            raise ValueError(f"Target trader account '{trader_username}' already exists.")
        
        # Create trader user
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, encrypted_api_key, encrypted_secret_key, is_demo, created_at)
            VALUES (?, ?, ?, 'user', ?, ?, ?, ?)
        """, (
            trader_username,
            hash_password(trader_password),
            trader_full_name,
            admin["encrypted_api_key"],
            admin["encrypted_secret_key"],
            admin["is_demo"],
            admin["created_at"]
        ))
        trader_id = cursor.lastrowid

        # Transfer sessions and set them to TERMINATED so bot doesn't resume blindly
        cursor.execute("""
            UPDATE sessions
            SET user_id = ?,
                status = CASE WHEN status = 'ACTIVE_SEARCHING' THEN 'TERMINATED' ELSE status END
            WHERE user_id = ?
        """, (trader_id, admin["id"]))

        # Transfer order records
        cursor.execute("UPDATE order_records SET user_id = ? WHERE user_id = ?", (trader_id, admin["id"]))

        # Clear credentials on admin account
        cursor.execute("""
            UPDATE users
            SET encrypted_api_key = '', encrypted_secret_key = ''
            WHERE id = ?
        """, (admin["id"],))

        conn.commit()
        return {
            "user_id": trader_id,
            "username": trader_username,
            "full_name": trader_full_name,
            "role": "user"
        }
