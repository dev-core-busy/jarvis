"""Sicherheits-Funktionen für Jarvis."""

import subprocess
import os
import secrets
from pathlib import Path

CERTS_DIR = Path(__file__).parent.parent / "certs"
CERT_FILE = CERTS_DIR / "server.crt"
KEY_FILE = CERTS_DIR / "server.key"
CERT_DER_FILE = CERTS_DIR / "jarvis.cer"  # DER-Format für Windows


def ensure_certificates():
    """Generiert selbstsignierte Zertifikate, falls nicht vorhanden."""
    CERTS_DIR.mkdir(parents=True, exist_ok=True)

    if CERT_FILE.exists() and KEY_FILE.exists() and CERT_DER_FILE.exists():
        return

    print("🔒 Generiere SSL-Zertifikate (Windows 11 kompatibel)...")

    # Server-IP aus Umgebungsvariable lesen (Fallback: 127.0.0.1)
    server_ip = os.getenv("SERVER_IP", "127.0.0.1")

    # OpenSSL Konfigurationsdatei mit allen nötigen Extensions
    ext_file = CERTS_DIR / "openssl.cnf"
    ext_file.write_text(f"""[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_ca
req_extensions = v3_ca

[dn]
C = DE
ST = Berlin
L = Berlin
O = Jarvis AI
CN = Jarvis CA

[v3_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:TRUE
keyUsage = critical, digitalSignature, keyCertSign, cRLSign, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = jarvis
DNS.2 = jarvis.local
DNS.3 = localhost
IP.1 = {server_ip}
IP.2 = 127.0.0.1
""")

    # PEM-Zertifikat generieren
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(KEY_FILE),
        "-out", str(CERT_FILE),
        "-days", "3650", "-nodes",
        "-config", str(ext_file),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # DER-Format für Windows erzeugen
        subprocess.run([
            "openssl", "x509",
            "-in", str(CERT_FILE),
            "-outform", "DER",
            "-out", str(CERT_DER_FILE),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Berechtigungen einschränken
        os.chmod(KEY_FILE, 0o600)

        # Aufräumen
        ext_file.unlink(missing_ok=True)

        print(f"✅ Zertifikate erstellt:")
        print(f"   PEM: {CERT_FILE}")
        print(f"   DER: {CERT_DER_FILE} (für Windows)")
    except subprocess.CalledProcessError as e:
        print(f"❌ Fehler beim Erstellen der Zertifikate: {e}")
    except Exception as e:
        print(f"❌ Unerwarteter Fehler: {e}")


def get_certificate_path():
    """Gibt den Pfad zum DER-Zertifikat zurück (bevorzugt für Windows)."""
    if CERT_DER_FILE.exists():
        return CERT_DER_FILE
    return CERT_FILE


def get_pem_certificate_path():
    """Gibt den Pfad zum PEM-Zertifikat zurück (für Server-Nutzung)."""
    return CERT_FILE


def get_pem_key_path():
    """Gibt den Pfad zum privaten Schlüssel zurück."""
    return KEY_FILE

