"""Sicherheits-Funktionen für Jarvis."""

import subprocess
import os
import socket
import secrets
from pathlib import Path

CERTS_DIR = Path(__file__).parent.parent / "certs"


def _collect_server_ips():
    """Sammelt alle relevanten IPs für das SSL-Zertifikat (SAN)."""
    ips = set()

    # 1. Explizit gesetzte SERVER_IP
    server_ip = os.getenv("SERVER_IP", "")
    if server_ip and server_ip != "127.0.0.1":
        ips.add(server_ip)

    # 2. Alle lokalen Netzwerk-Interfaces
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass

    # 3. Externe IP ermitteln (für Docker-Container wichtig)
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "3", "http://ifconfig.me"],
            capture_output=True, text=True, timeout=5
        )
        ext_ip = result.stdout.strip()
        if ext_ip and all(part.isdigit() for part in ext_ip.split(".")) and len(ext_ip.split(".")) == 4:
            ips.add(ext_ip)
    except Exception:
        pass

    # 4. Default Gateway (Docker Host)
    try:
        result = subprocess.run(
            ["ip", "route"], capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                gw = line.split()[2]
                if not gw.startswith("127."):
                    ips.add(gw)
    except Exception:
        pass

    # 127.0.0.1 immer dabei
    ips.add("127.0.0.1")

    return sorted(ips)
CERT_FILE = CERTS_DIR / "server.crt"
KEY_FILE = CERTS_DIR / "server.key"
CERT_DER_FILE = CERTS_DIR / "jarvis.cer"  # DER-Format für Windows


def ensure_certificates():
    """Generiert selbstsignierte Zertifikate, falls nicht vorhanden."""
    CERTS_DIR.mkdir(parents=True, exist_ok=True)

    if CERT_FILE.exists() and KEY_FILE.exists() and CERT_DER_FILE.exists():
        return

    print("🔒 Generiere SSL-Zertifikate (Windows 11 kompatibel)...")

    # Alle relevanten IPs sammeln
    ips = _collect_server_ips()
    print(f"   IPs im Zertifikat: {', '.join(ips)}")

    # IP-Einträge für OpenSSL SAN generieren
    ip_lines = "\n".join(f"IP.{i+1} = {ip}" for i, ip in enumerate(ips))

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
{ip_lines}
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

