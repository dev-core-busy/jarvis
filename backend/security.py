"""Sicherheits-Funktionen für Jarvis."""

import subprocess
import ipaddress
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

    # 3. Alle IPs aller lokalen Netzwerk-Interfaces (via ip addr)
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip = line.split()[1].split("/")[0]
                if not ip.startswith("127."):
                    ips.add(ip)
    except Exception:
        pass

    # 4. Default Gateway (Docker Host IP)
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

    # 5. Externe IP (mehrere Dienste versuchen)
    for url in ["http://ifconfig.me", "http://api.ipify.org", "http://checkip.amazonaws.com"]:
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "3", url],
                capture_output=True, text=True, timeout=5
            )
            ext_ip = result.stdout.strip()
            if ext_ip and all(part.isdigit() for part in ext_ip.split(".")) and len(ext_ip.split(".")) == 4:
                ips.add(ext_ip)
                break
        except Exception:
            pass

    # 127.0.0.1 immer dabei
    ips.add("127.0.0.1")

    return sorted(ips)


def _collect_server_names():
    """Sammelt DNS-Namen für das SSL-Zertifikat (SAN) – inkl. System-Hostname/FQDN."""
    names = ["jarvis", "jarvis.local", "localhost"]
    try:
        hn = socket.gethostname()
        if hn:
            names.append(hn)
        fqdn = socket.getfqdn()
        # FQDN nur wenn echter Name (keine IP) und nicht schon enthalten
        if fqdn and not fqdn.replace(".", "").isdigit():
            names.append(fqdn)
    except Exception:
        pass
    # Dedup unter Beibehaltung der Reihenfolge
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


CERT_FILE = CERTS_DIR / "server.crt"
KEY_FILE = CERTS_DIR / "server.key"
CERT_DER_FILE = CERTS_DIR / "jarvis.cer"  # DER-Format für Windows


def _lokale_adressen():
    """IPv4-Adressen DIESES Rechners – rein lokal ermittelt.

    Ausdruecklich eine eigene, kleine Funktion und nicht ``_collect_server_ips``:
    * jener Schritt 5 ruft ifconfig.me/ipify/amazonaws auf. Das ist beim
      ERZEUGEN einmal vertretbar, bei JEDEM Start nicht – es waere ein
      Netzzugriff nach draussen auf dem Startpfad.
    * jener Schritt 4 nimmt das **Standard-Gateway** mit ("Docker Host IP").
      Ein Gateway ist nicht die Adresse dieses Rechners; fuer die Frage
      "nennt das Zertifikat mich?" waere es eine falsche Antwort. Genau so ein
      Fremdwert – die Gateway-Adresse zur Erzeugungszeit – steckte im
      DEV-Zertifikat, als der Fall am 2026-10-13 auffiel.
    """
    ips = set()
    server_ip = os.getenv("SERVER_IP", "")
    if server_ip and server_ip != "127.0.0.1":
        ips.add(server_ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:
        result = subprocess.run(["ip", "-4", "addr", "show", "scope", "global"],
                                capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip = line.split()[1].split("/")[0]
                if not ip.startswith("127."):
                    ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def _ist_ip(wert):
    try:
        ipaddress.ip_address(wert)
        return True
    except ValueError:
        return False


def zertifikat_adress_warnung():
    """Grund, wenn das vorhandene Zertifikat zu diesem Server nicht mehr passt.

    Leerer String = in Ordnung ODER nicht feststellbar. Eine AUSKUNFT, keine
    Sperre: ob ein Zertifikat getauscht wird, entscheidet der Betreiber.

    WARUM ES DAS GIBT (gemessen 2026-10-13): das DEV-Zertifikat stammte vom
    20.02.2026 und nannte die damalige Gateway-Adresse; der Rechner lag
    laengst auf einer anderen, per DHCP bezogenen Adresse, und die DNS-Namen
    darin waren
    ``jarvis``/``jarvis.local``/``localhost`` – also keiner, den ein fremder
    Client aufloest. ``ensure_certificates`` erzeugt ein bestehendes Zertifikat
    bewusst NIE neu (sonst bricht das hinterlegte Vertrauen), die Abweichung war
    damit **dauerhaft und unbemerkt**: Namensabweichung im Browser, kein
    brauchbares Ziel fuer die Umleitung, und ``addin.zert_deckt_basis`` meldete
    "nicht gedeckt" fuer die Adresse, die tatsaechlich benutzt wurde.

    ⚠ GEWARNT WIRD NUR, WENN BEIDES FEHLT – eigene Adresse UND aufloesbarer
    DNS-Name. Die erste Fassung meldete jede lokale Adresse, die nicht im SAN
    steht, und waere auf dem PRODUKTIONSSERVER bei jedem Start angeschlagen:
    dessen CA-Zertifikat lautet absichtlich nur auf zwei FQDNs und enthaelt
    gar keine IP. Das ist der Normalfall eines richtig ausgestellten
    Zertifikats, kein Fehler – eine Meldung, die das behauptet, ist Laerm und
    wird beim dritten Mal ueberlesen.

    Ein DNS-Name genuegt, eine fremde IP nicht: ein Name kann auf diesen Server
    zeigen, ohne dass meine Adresse im Zertifikat steht (genau der Produktions-
    fall). Eine IP im SAN, die mir NICHT gehoert, ist dagegen nur veraltet –
    deshalb zaehlt fuer die zweite Bedingung ausschliesslich ein DNS-Name.
    """
    try:
        from backend.http_umleitung import (zertifikat_namen,   # noqa: PLC0415
                                            taugt_als_rueckfall)
        namen = zertifikat_namen(CERT_FILE)
    except Exception:  # noqa: BLE001
        return ""
    if not namen:
        return ""                     # nicht ermittelbar -> nichts behaupten
    eigene = _lokale_adressen()
    if any(a in namen for a in eigene):
        return ""                     # (a) meine Adresse steht drin
    if any(taugt_als_rueckfall(n) for n in namen if not _ist_ip(n)):
        return ""                     # (b) ein aufloesbarer DNS-Name steht drin
    return ("Das Serverzertifikat passt nicht zu diesem Rechner: es nennt "
            "weder eine eigene Adresse (%s) noch einen von aussen aufloesbaren "
            "Namen - abgedeckt ist nur %s."
            % (", ".join(eigene) or "keine ermittelt", ", ".join(namen)))


def ensure_certificates():
    """Generiert selbstsignierte Zertifikate, falls nicht vorhanden.

    Idempotent: ein BESTEHENDES TLS-Cert (server.crt + server.key) wird NIEMALS neu
    erzeugt – sonst bricht bei jedem Start/Update das im Browser hinterlegte Vertrauen.
    Fehlt nur die DER-Datei (jarvis.cer), wird sie aus dem vorhandenen Cert abgeleitet.
    Voll neu generiert wird nur, wenn server.crt ODER server.key fehlt.

    Deckt das bestehende Zertifikat die eigene Adresse nicht mehr ab, wird das
    GEMELDET (siehe ``zertifikat_adress_warnung``) – nicht stillschweigend
    behoben: ein neues Zertifikat entwertet jede hinterlegte Vertrauensstellung
    und die Zertifikatspruefung der Windows-/Android-App (BSI M11).
    """
    CERTS_DIR.mkdir(parents=True, exist_ok=True)

    # Bestehendes Cert beibehalten – nur fehlende DER nachziehen.
    if CERT_FILE.exists() and KEY_FILE.exists():
        if not CERT_DER_FILE.exists():
            try:
                subprocess.run([
                    "openssl", "x509", "-in", str(CERT_FILE),
                    "-outform", "DER", "-out", str(CERT_DER_FILE),
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("🔒 DER-Zertifikat aus bestehendem Cert abgeleitet (Cert/Trust unveraendert).")
            except Exception as e:
                print(f"⚠️  DER-Ableitung fehlgeschlagen: {e}")
        grund = zertifikat_adress_warnung()
        if grund:
            # Laut, mit Grund UND naechstem Schritt - ein richtiger Hinweis,
            # der nicht sagt was zu tun ist, ist nutzlos (Register).
            print(f"⚠️  {grund}", flush=True)
            print("    Folge: Namensabweichung im Browser, keine brauchbare "
                  "Umleitung von Port 80, und Office lehnt das Add-in ab.", flush=True)
            print("    Abhilfe: ein Zertifikat hinterlegen, das diese Adresse "
                  "abdeckt - oder certs/server.crt und server.key entfernen und "
                  "neu starten (erzeugt ein neues selbstsigniertes; dabei "
                  "verlieren Browser und App ihre Vertrauensstellung).", flush=True)
        return

    print("🔒 Generiere SSL-Zertifikate (Windows 11 kompatibel)...")

    # Alle relevanten IPs sammeln
    ips = _collect_server_ips()
    print(f"   IPs im Zertifikat: {', '.join(ips)}")

    # IP-Einträge für OpenSSL SAN generieren
    ip_lines = "\n".join(f"IP.{i+1} = {ip}" for i, ip in enumerate(ips))

    # DNS-Namen für SAN (inkl. System-Hostname/FQDN)
    names = _collect_server_names()
    print(f"   DNS-Namen im Zertifikat: {', '.join(names)}")
    dns_lines = "\n".join(f"DNS.{i+1} = {n}" for i, n in enumerate(names))

    # OpenSSL Konfigurationsdatei mit allen nötigen Extensions
    ext_file = CERTS_DIR / "openssl.cnf"
    ext_file.write_text(f"""[req]
default_bits = 3072
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
{dns_lines}
{ip_lines}
""")

    # PEM-Zertifikat generieren. RSA 3072 (BSI TR-02102-1: mindestens 3000 Bit;
    # bis 2026-10-13 stand hier 2048 - Rest aus dem BSI-Abgleich zu H6).
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:3072",
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

