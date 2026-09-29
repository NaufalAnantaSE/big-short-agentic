"""FastAPI backend service providing multi-tenant REST API with JWT auth,
isolated BingX management, and humanized plain Indonesian AI insights.
"""

import os
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import load_config, AppConfig
from security import (
    hash_password, verify_password,
    create_access_token, decode_access_token
)
from ai_settings import get_ai_settings, update_ai_settings
import db
from tenant_manager import TenantSessionManager

app = FastAPI(
    title="BingX Agentic Short — Multi-Tenant Mobile Webview API",
    version="1.0.0"
)

# Enable CORS for local dev / mobile webview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

base_config = load_config()
tenant_manager = TenantSessionManager(base_config)

# Request & Response models
class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""

class LoginRequest(BaseModel):
    username: str
    password: str

class CredentialsRequest(BaseModel):
    api_key: str
    secret_key: str
    is_demo: bool = True

class SessionStartRequest(BaseModel):
    margin_per_pos: float = Field(default=5.0, ge=1.0, le=500.0)
    leverage: int = Field(default=20, ge=1, le=20)
    quota: int = Field(default=10, ge=1, le=50)
    mode: str = Field(default="PUMP_GAINERS")
    is_live: bool = False

class CycleRequest(BaseModel):
    dry_run: bool = True

class UpdateAISettingsRequest(BaseModel):
    model: str

# Dependency: Auth Gate
def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi diperlukan. Silakan login terlebih dahulu."
        )
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi login kedaluwarsa atau tidak valid."
        )
    user_id = int(payload["sub"])
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pengguna tidak ditemukan.")
    return user

def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses khusus administrator.")
    return user

def require_trader(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun admin dikhususkan untuk manajemen sistem dan tidak dapat menjalankan bot trading. Silakan login dengan akun trader pribadi."
        )
    return user

# --- AUTH ENDPOINTS ---

@app.post("/api/auth/register")
def register():
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Pendaftaran mandiri dinonaktifkan. Hubungi Admin (Naufal) untuk pembuatan akun setelah pembayaran."
    )

@app.post("/api/auth/login")
def login(req: LoginRequest):
    username = req.username.strip()
    user = db.get_user_by_username(username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username atau kata sandi tidak cocok.")
    
    token = create_access_token({"sub": str(user["id"]), "role": user["role"], "username": user["username"]})
    has_keys = bool(user.get("encrypted_api_key") and user.get("encrypted_secret_key"))
    
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user.get("full_name", user["username"]),
            "role": user["role"],
            "has_keys": has_keys,
            "is_demo": bool(user.get("is_demo", 1))
        }
    }

@app.get("/api/auth/me")
def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    has_keys = bool(user.get("encrypted_api_key") and user.get("encrypted_secret_key"))
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user.get("full_name", user["username"]),
        "role": user["role"],
        "has_keys": has_keys,
        "is_demo": bool(user.get("is_demo", 1)),
        "created_at": user["created_at"]
    }

# --- CREDENTIALS MANAGEMENT (ISOLATED) ---

@app.post("/api/credentials")
def save_credentials(req: CredentialsRequest, user: Dict[str, Any] = Depends(require_trader)):
    api_k = req.api_key.strip()
    sec_k = req.secret_key.strip()
    if not api_k or not sec_k:
        raise HTTPException(status_code=400, detail="API Key dan Secret Key tidak boleh kosong.")
    
    db.update_user_credentials(user["id"], api_k, sec_k, is_demo=req.is_demo)
    tenant_manager.invalidate_user_cache(user["id"])
    
    # Preflight verification against BingX
    try:
        summary = tenant_manager.get_account_summary(user["id"])
        return {
            "success": True,
            "message": "Kunci API berhasil disimpan dan diverifikasi dengan BingX.",
            "balance": summary["balance"],
            "asset": summary["asset"],
            "is_demo": req.is_demo
        }
    except Exception as exc:
        return {
            "success": True,
            "warning": True,
            "message": f"Kunci API tersimpan, namun verifikasi awal BingX mengembalikan: {str(exc)}",
            "is_demo": req.is_demo
        }

# --- ACCOUNT & TRADING SESSIONS ---

@app.get("/api/account/summary")
def get_account_summary(user: Dict[str, Any] = Depends(require_trader)):
    has_keys = bool(user.get("encrypted_api_key") and user.get("encrypted_secret_key"))
    if not has_keys:
        return {
            "has_keys": False,
            "message": "Silakan masukkan API Key dan Secret Key BingX Anda terlebih dahulu."
        }
    try:
        summary = tenant_manager.get_account_summary(user["id"])
        summary["has_keys"] = True
        return summary
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal mengambil saldo dari BingX: {str(exc)}")

@app.post("/api/session/start")
def start_session(req: SessionStartRequest, user: Dict[str, Any] = Depends(require_trader)):
    has_keys = bool(user.get("encrypted_api_key") and user.get("encrypted_secret_key"))
    if not has_keys:
        raise HTTPException(status_code=400, detail="Kunci API belum diatur.")
    
    try:
        res = tenant_manager.start_session(
            user_id=user["id"],
            margin_per_pos=req.margin_per_pos,
            leverage=req.leverage,
            quota=req.quota,
            mode=req.mode,
            is_live=req.is_live
        )
        return {"success": True, "session": res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/session/stop")
def stop_session(user: Dict[str, Any] = Depends(require_trader)):
    res = tenant_manager.stop_session(user["id"])
    return {"success": True, "result": res}

@app.post("/api/session/cycle")
def run_cycle(req: CycleRequest, user: Dict[str, Any] = Depends(require_trader)):
    has_keys = bool(user.get("encrypted_api_key") and user.get("encrypted_secret_key"))
    if not has_keys:
        raise HTTPException(status_code=400, detail="Kunci API belum diatur.")
    
    try:
        res = tenant_manager.run_cycle_for_user(user["id"], dry_run=req.dry_run)
        return {"success": True, "data": res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/orders")
def get_orders(user: Dict[str, Any] = Depends(require_trader)):
    orders = db.get_user_orders(user["id"])
    return {"orders": orders}

class ClosePositionRequest(BaseModel):
    symbol: str
    position_side: str = "SHORT"

@app.post("/api/position/close")
def close_position_endpoint(req: ClosePositionRequest, user: Dict[str, Any] = Depends(require_trader)):
    try:
        res = tenant_manager.close_user_position(
            user_id=user["id"],
            symbol=req.symbol,
            position_side=req.position_side
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

# --- ADMIN PANEL ---

@app.get("/api/admin/ai-settings")
def get_admin_ai_settings(admin: Dict[str, Any] = Depends(require_admin)):
    return get_ai_settings()

@app.put("/api/admin/ai-settings")
def update_admin_ai_settings(req: UpdateAISettingsRequest, admin: Dict[str, Any] = Depends(require_admin)):
    try:
        return update_ai_settings(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""
    is_demo: bool = True

class AdminResetPasswordRequest(BaseModel):
    new_password: str

@app.get("/api/admin/users")
def get_all_users_admin(admin: Dict[str, Any] = Depends(require_admin)):
    users = db.list_all_users()
    return {"users": users}

@app.get("/api/admin/sessions")
def get_all_client_sessions_admin(admin: Dict[str, Any] = Depends(require_admin)):
    sessions = db.list_all_client_sessions()
    return {"sessions": sessions}

@app.post("/api/admin/users")
def create_user_by_admin(req: AdminCreateUserRequest, admin: Dict[str, Any] = Depends(require_admin)):
    username = req.username.strip()
    if not username or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Username dan password (min 6 karakter) wajib diisi.")
    
    existing = db.get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail=f"Username '{username}' sudah terdaftar.")
    
    user_id = db.create_user(username=username, password=req.password, full_name=req.full_name or username, role="user")
    if not req.is_demo:
        with db.get_db() as conn:
            conn.execute("UPDATE users SET is_demo = 0 WHERE id = ?", (user_id,))
            conn.commit()
    
    return {
        "success": True,
        "message": f"Akun klien '{username}' berhasil dibuat!",
        "user": {
            "id": user_id,
            "username": username,
            "full_name": req.full_name or username,
            "is_demo": req.is_demo
        }
    }

@app.post("/api/admin/users/{user_id}/reset-password")
def reset_user_password(user_id: int, req: AdminResetPasswordRequest, admin: Dict[str, Any] = Depends(require_admin)):
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password baru minimal 6 karakter.")
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    with db.get_db() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(req.new_password), user_id))
        conn.commit()
    return {"success": True, "message": f"Password untuk '{target['username']}' berhasil diubah."}

@app.delete("/api/admin/users/{user_id}")
def delete_user_by_admin(user_id: int, admin: Dict[str, Any] = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun admin sendiri.")
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    with db.get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    tenant_manager.invalidate_user_cache(user_id)
    return {"success": True, "message": f"Akun '{target['username']}' berhasil dihapus."}

# --- FRONTEND STATIC SERVING ---
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        index_file = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"message": "Frontend build not found. Please build frontend first."}
