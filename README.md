# Big Short Agentic — BingX Automated Perpetual Shorting & Management System

Platform otomatisasi perdagangan berjangka (perpetual futures short-only) di BingX dengan integrasi multi-tenant, evaluasi pasar adversarial AI berbasis 9Router, dan antarmuka mobile webview yang ramah pengguna.

---

## 🌟 Fitur Utama

- **Short-Only Engine**: Dirancang spesifik untuk mendeteksi pump exhaustion, buyer dry-up, dan pembalikan harga pada token volatil/memecoin.
- **AI Adversarial Evaluation**: Analisis pasar berbasis LLM via 9Router (Short Hunter, Squeeze Defender, Risk Arbiter) dengan model terpusat (default: `ag/gemini-3.8-flash`).
- **Senior-Friendly Explainer**: Menerjemahkan metrik kuantitatif dan sinyal teknis ke dalam bahasa Indonesia yang awam, tenang, dan transparan beserta estimasi modal Rupiah.
- **Pemisahan Peran Mutlak (Role Separation)**:
  - **Admin**: Khusus mengelola lisensi pengguna berbayar dan konfigurasi model AI (diblokir dari eksekusi trading bot).
  - **Trader / Client**: Menjalankan bot trading mandiri dengan enkripsi simetris (Fernet AES) untuk kunci API masing-masing (isolasi multi-tenant penuh).
- **Mobile Webview-First Frontend**: Dibangun dengan Vue 3, Vite, dan Tailwind CSS (dark mode restrained, strictly no emoji, target sentuh >= 48px).
- **One-Tap Close Position**: Pengguna dapat menutup posisi (Take Profit) kapan saja langsung dari tampilan webview.

---

## 📂 Struktur Repositori

```
big-short-agentic/
├── api.py                    # Backend FastAPI REST service & middleware
├── tenant_manager.py         # Multi-tenant isolated orchestrator pool
├── orchestrator.py           # Core bot lifecycle & cycle execution
├── client.py                 # BingX Swap V2 REST client (Hedge mode)
├── scanner.py                # Market scanner (volatility & meme filtration)
├── market_features.py        # Feature extractor & candle aggregator
├── ai_evaluator.py           # LLM integration via 9Router gateway
├── plain_explainer.py        # Senior-friendly Indonesian narrative translator
├── security.py               # Bcrypt password hashing & Fernet encryption
├── db.py                     # SQLite database repository & schema migrations
├── ai_settings.py            # Dynamic AI settings persistence
├── start_server.py           # Uvicorn production server launcher
├── requirements.txt          # Python backend dependencies
├── tests/                    # Comprehensive unit & integration tests
└── frontend/                 # Vue 3 + Tailwind CSS mobile webview
    ├── src/
    │   ├── App.vue
    │   ├── main.js
    │   ├── style.css
    │   └── components/
    │       ├── Navbar.vue
    │       ├── AuthView.vue
    │       ├── AdminDashboard.vue
    │       ├── TraderDashboard.vue
    │       ├── AccountSummaryCard.vue
    │       ├── BotControlCard.vue
    │       ├── CandidateRadarCard.vue
    │       ├── ActivePositionsCard.vue
    │       ├── AdminUsersModal.vue
    │       └── ApiKeyOnboardingModal.vue
    ├── package.json
    ├── tailwind.config.js
    └── vite.config.js
```

---

## 🚀 Panduan Menjalankan Sistem

### 1. Persiapan Backend (Python 3.12+)

```bash
# Buat virtual environment & instal dependensi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Jalankan pengujian backend
pytest tests/
```

### 2. Persiapan Frontend (Node.js 18+)

```bash
cd frontend
npm install
npm run build
cd ..
```

### 3. Menjalankan Server Terpadu

```bash
# Menjalankan server backend yang otomatis menyajikan frontend
python3 start_server.py
```
Akses aplikasi melalui browser / mobile webview di: `http://127.0.0.1:8088`

---

## 🛡️ Keamanan & Privasi

- Kunci API dan Secret Key BingX setiap pengguna dienkripsi secara simetris menggunakan Fernet sebelum disimpan ke database SQLite terisolasi.
- Pendaftaran mandiri (registrasi publik) dinonaktifkan secara default. Akun hanya dapat diaktifkan oleh Administrator setelah verifikasi lisensi/pembayaran.
- File basis data lokal (`data/bot.db`) dan riwayat audit diabaikan oleh `.gitignore` untuk mencegah kebocoran kredensial atau informasi sensitif.
