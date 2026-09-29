"""Production server launcher for BingX Agentic Short Mobile Webview."""

import uvicorn
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8088))
    print(f"Starting BingX Agent API on http://127.0.0.1:{port}")
    uvicorn.run("api:app", host="127.0.0.1", port=port, log_level="info")
