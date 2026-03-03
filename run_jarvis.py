"""Jarvis Launcher – Startet Server mit HTTPS."""

import uvicorn
from backend.config import config
from backend.security import ensure_certificates, CERT_FILE, KEY_FILE

if __name__ == "__main__":
    print("🚀 Starte Jarvis Launcher...")
    
    # Zertifikate sicherstellen
    ensure_certificates()
    
    if CERT_FILE.exists() and KEY_FILE.exists():
        print("🔐 HTTPS aktiviert.")
        ssl_cert = str(CERT_FILE)
        ssl_key = str(KEY_FILE)
        protocol = "https"
    else:
        print("⚠️  WARNUNG: Keine Zertifikate gefunden. Fallback auf HTTP.")
        ssl_cert = None
        ssl_key = None
        protocol = "http"

    print(f"🌐 Jarvis läuft unter: {protocol}://{config.SERVER_HOST}:{config.SERVER_PORT}")

    uvicorn.run(
        "backend.main:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        ssl_certfile=ssl_cert,
        ssl_keyfile=ssl_key,
        reload=True
    )
