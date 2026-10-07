"""Security module: Direct bcrypt password hashing, JWT token handling, and Fernet encryption for API credentials."""

import os
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt
import jwt
from cryptography.fernet import Fernet

# Master key resolution
KEY_FILE = os.path.join(os.path.dirname(__file__), "data", ".master_key")

def get_or_create_master_key() -> bytes:
    env_key = os.environ.get("MASTER_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode("utf-8")
    
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    new_key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(new_key)
    return new_key

MASTER_KEY = get_or_create_master_key()
_cipher = Fernet(MASTER_KEY)

JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "bingx-agent-secret-jwt-key-2026-production-salt")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days for mobile webview convenience

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8")[:72], salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8")[:72], hashed_password.encode("utf-8"))
    except Exception:
        return False

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRATION_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

def encrypt_credential(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

def decrypt_credential(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""
