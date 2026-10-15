"""Jarvis Launcher – Startet Server mit HTTPS."""

import uvicorn
from backend.config import config
from backend.security import ensure_certificates, CERT_FILE, KEY_FILE
from backend.tls_richtlinie import TLS12_SUITES, konfig_fuer_start

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

    konfig_fuer_start()  # BSI H6-Rest: TLS 1.3-Suiten (erbt der Reload-Worker)
    uvicorn.run(
        "backend.main:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        ssl_certfile=ssl_cert,
        ssl_keyfile=ssl_key,
        ssl_ciphers=TLS12_SUITES,  # BSI H6
        server_header=False,       # BSI N5: kein "server: uvicorn"
        reload=True
    )
