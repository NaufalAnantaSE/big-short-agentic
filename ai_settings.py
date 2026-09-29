"""AI Settings management module for BingX Agentic Short System.
Persists model selection in SQLite for new sessions while preserving
server-configured gateway URL and system security defaults.
"""

from typing import Dict, Any
from config import load_config
import db

def _ensure_settings_table():
    with db.get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.commit()

def get_ai_settings() -> Dict[str, Any]:
    _ensure_settings_table()
    cfg = load_config()
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = 'ai_model_name'")
        row = cursor.fetchone()
        model_name = row["value"] if row else cfg.ai_model_name
    
    return {
        "model": model_name,
        "gateway_url": cfg.ai_gateway_url,
        "applies_to": "new_sessions"
    }

def update_ai_settings(model: str) -> Dict[str, Any]:
    clean_model = model.strip()
    if not clean_model:
        raise ValueError("Nama model AI tidak boleh kosong.")
    
    _ensure_settings_table()
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO system_settings (key, value)
            VALUES ('ai_model_name', ?)
        """, (clean_model,))
        conn.commit()
    
    cfg = load_config()
    return {
        "model": clean_model,
        "gateway_url": cfg.ai_gateway_url,
        "applies_to": "new_sessions"
    }
