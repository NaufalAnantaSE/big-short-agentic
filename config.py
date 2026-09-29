"""Configuration module for BingX Agentic Short System."""

import os
from pathlib import Path
from pydantic import BaseModel, Field

class AppConfig(BaseModel):
    # API endpoints
    bingx_host: str = Field(default="https://open-api-vst.bingx.com", description="BingX API Base URL")
    ai_gateway_url: str = Field(default="http://127.0.0.1:20128/v1", description="9Router OpenAI-Compatible URL")
    ai_model_name: str = Field(default="ag/gemini-3.8-flash", description="AI Model alias in 9Router")
    
    # Credentials (kept in memory, never logged)
    api_key: str = ""
    secret_key: str = ""
    
    # Trading Defaults
    default_margin_per_pos: float = 5.0
    default_leverage: int = 20
    default_quota: int = 2
    max_spread_pct: float = 0.25
    min_volume_24h_usdt: float = 50000.0

    # Universe & Mode Settings
    universe_mode: str = Field(default="PUMP_GAINERS", description="Scanner mode: PUMP_GAINERS or MEME_ONLY")
    min_pump_percent: float = Field(default=0.0, description="Minimum 24h price change percentage to consider")
    majors_blacklist: list = Field(
        default_factory=lambda: [
            "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
            "USDC-USDT", "FDUSD-USDT", "USDE-USDT", "EUR-USDT"
        ],
        description="Blacklisted major pairs and stablecoins"
    )

    @property
    def masked_api_key(self) -> str:
        if not self.api_key:
            return "UNSET"
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"

def load_config() -> AppConfig:
    """Loads configuration with fallback to local secure credential file."""
    api_key = os.getenv("BINGX_API_KEY", "")
    secret_key = os.getenv("BINGX_SECRET_KEY", "")
    
    secret_path = Path("/home/naufal-ananta/Documents/asecret/bingx-testing.txt")
    if not (api_key and secret_key) and secret_path.exists():
        for line in secret_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip().upper()
                v = v.strip().strip("'\"")
                if k in ("API_KEY", "BINGX_API_KEY"):
                    api_key = v
                elif k in ("SECRET_KEY", "BINGX_SECRET_KEY"):
                    secret_key = v

    return AppConfig(
        api_key=api_key,
        secret_key=secret_key,
        bingx_host=os.getenv("BINGX_HOST", "https://open-api-vst.bingx.com"),
        ai_gateway_url=os.getenv("AI_GATEWAY_URL", "http://127.0.0.1:20128/v1"),
    )
