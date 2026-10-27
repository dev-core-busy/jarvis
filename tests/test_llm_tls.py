#!/usr/bin/env python3
"""Waechter: Zertifikatsanker per Fingerabdruck fuer LLM-Profile (backend/llm_tls.py).

Gemessen gegen ZWEI echte lokale TLS-Server mit je einem selbst signierten
Zertifikat (``localhost``, verschiedene Ports) – kein Netz, keine Attrappe am
TLS-Weg. ``backend.config`` ist nur eine Attrappe (der echte Import schreibt
die Live-settings.json zurueck).

Zusagen:
  1. Fingerabdruck-Schreibweisen werden normiert, SHA-1 mit Grund abgelehnt.
  2. Verankert wird nur bei gleichem Fingerabdruck; das PEM holt der Server.
  3. Ein Anker gilt fuer GENAU Host:Port – nicht fuer einen anderen Port
     desselben Rechners (httpx-``mounts`` taeten genau das, siehe Modul-Docstring).
  4. Ohne Anker entstehen die Clients unveraendert (``client_args() == {}``).
  5. Der gemeinsame LLM-Client wird neu gebaut, wenn sich ein Anker aendert.
  6. Ein Anker kommt nie aus einem Request (Whitelist von update_profile).

Positivkontrolle vorab: ohne Anker MUSS der Abruf am Zertifikat scheitern –
sonst waeren alle Pruefungen trivial wahr (Exit 2).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""

from __future__ import annotations

import ast
import asyncio
import datetime
import http.server
import ipaddress
import os
import socketserver
import ssl
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def pruef(bed: bool, text: str) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


def abbruch(text: str) -> None:
    print("ABBRUCH: " + text)
    sys.exit(2)


# ── Attrappe fuer backend.config ────────────────────────────────────────────

class _Cfg:
    profiles: list = []
    LLM_TIMEOUT = 180
    LLM_PROVIDER = "openai_compatible"


_stub = types.ModuleType("backend.config")
_stub.config = _Cfg()
sys.modules["backend.config"] = _stub

try:
    import httpx
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from backend import llm_tls
except Exception as e:  # noqa: BLE001
    abbruch(f"Import fehlgeschlagen: {e}")


# ── Zwei lokale TLS-Server ──────────────────────────────────────────────────

def _zert(verz: Path, name: str) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - datetime.timedelta(minutes=5))
            .not_valid_after(jetzt + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    c, k = verz / f"{name}.crt", verz / f"{name}.key"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return str(c), str(k)


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        daten = b'{"data":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)

    def log_message(self, *a):  # noqa: D401
        pass


class _S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Abgewiesene Handshakes sind hier gewollt (Positivkontrolle, falscher
        # Anker) – ohne das stuende je Fall ein Stacktrace in der Ausgabe.
        pass


def _server(cert: str, key: str) -> tuple[_S, int]:
    s = _S(("127.0.0.1", 0), _H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    s.socket = ctx.wrap_socket(s.socket, server_side=True)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]


TMP = Path(tempfile.mkdtemp(prefix="llm_tls_"))
c1, k1 = _zert(TMP, "eins")
c2, k2 = _zert(TMP, "zwei")
S1, P1 = _server(c1, k1)
S2, P2 = _server(c2, k2)
# Dritter Port mit DEMSELBEN Zertifikat wie Server 1: nur hier unterscheidet
# sich "Anker gilt fuer Host:Port" von "Anker gilt fuer den Host" – gegen
# Server 2 (anderes Zertifikat) scheitern beide Fassungen gleich.
S3, P3 = _server(c1, k1)
URL1 = f"https://localhost:{P1}/v1"
URL2 = f"https://localhost:{P2}/v1"
URL3 = f"https://localhost:{P3}/v1"


def _fp(pfad: str) -> str:
    der = ssl.PEM_cert_to_DER_cert(Path(pfad).read_text())
    import hashlib
    return "sha256:" + hashlib.sha256(der).hexdigest()


FP1, FP2 = _fp(c1), _fp(c2)


async def _abruf(url: str, **kw) -> str:
    """'ok' oder der Fehlertyp."""
    try:
        async with httpx.AsyncClient(timeout=5.0, **kw) as c:
            r = await c.get(url + "/models")
            return "ok" if r.status_code == 200 else f"http{r.status_code}"
    except httpx.ConnectError as e:
        return "zert" if "CERTIFICATE_VERIFY_FAILED" in str(e) else f"connect:{e}"
    except Exception as e:  # noqa: BLE001
        return f"anders:{type(e).__name__}:{e}"


async def main() -> None:
    # ── Positivkontrolle ────────────────────────────────────────────────
    print("Positivkontrolle")
    _stub.config.profiles = []
    ohne = await _abruf(URL1)
    if ohne != "zert":
        abbruch(f"ohne Anker muss der Abruf am Zertifikat scheitern, war: {ohne}")
    print(f"  OK   ohne Anker scheitert der Abruf am Zertifikat ({P1})")
    mit_cafile = await _abruf(URL1, verify=ssl.create_default_context(cafile=c1))
    if mit_cafile != "ok":
        abbruch(f"der Testserver antwortet auch mit seinem Zertifikat nicht: {mit_cafile}")
    print("  OK   der Testserver antwortet, wenn sein Zertifikat vertraut ist")

    # ── 1. Normierung ───────────────────────────────────────────────────
    print("1. Fingerabdruck-Schreibweisen")
    hexwert = FP1.split(":", 1)[-1] if ":" in FP1 else ""
    paare = ":".join(hexwert[i:i + 2] for i in range(0, len(hexwert), 2)).upper()
    for roh, was in ((FP1, "sha256:-Form"), (FP1.upper(), "Grossschreibung"),
                     (paare, "Paare mit Doppelpunkt"),
                     ("SHA256 Fingerprint=" + paare, "openssl-Ausgabe"),
                     (" ".join(paare.split(":")), "Leerzeichen")):
        try:
            pruef(llm_tls.fingerabdruck_normieren(roh) == FP1, f"{was} wird normiert")
        except llm_tls.AnkerFehler as e:
            pruef(False, f"{was} wird normiert ({e})")
    for roh, muss, was in (("ab" * 20, "SHA-1", "SHA-1 mit Grund abgelehnt"),
                           ("ab" * 31, "64", "falsche Laenge abgelehnt"),
                           ("zz" * 32, "Hexadezimal", "Nicht-Hex abgelehnt"),
                           ("", "Kein", "leer abgelehnt")):
        try:
            llm_tls.fingerabdruck_normieren(roh)
            pruef(False, was)
        except llm_tls.AnkerFehler as e:
            pruef(muss in str(e), f"{was} ({str(e)[:50]})")

    # ── 2. Verankern ────────────────────────────────────────────────────
    print("2. Verankern nur bei gleichem Fingerabdruck")
    try:
        e1 = await asyncio.to_thread(llm_tls.anker_bauen, URL1, FP1)
        pruef(e1.get("fingerprint") == FP1 and "BEGIN CERTIFICATE" in e1.get("pem", ""),
              "richtiger Fingerabdruck -> Eintrag mit selbst geholtem PEM")
        pruef(e1.get("host") == "localhost" and e1.get("port") == P1,
              "Eintrag traegt Host UND Port")
    except Exception as e:  # noqa: BLE001
        abbruch(f"Verankern mit richtigem Fingerabdruck scheitert: {e}")
    try:
        await asyncio.to_thread(llm_tls.anker_bauen, URL1, FP2)
        pruef(False, "fremder Fingerabdruck wird abgelehnt")
    except llm_tls.AnkerFehler as e:
        pruef("anderes Zertifikat" in str(e) and FP1 in str(e),
              "fremder Fingerabdruck wird abgelehnt und nennt den gefundenen")
    try:
        await asyncio.to_thread(llm_tls.anker_bauen, f"http://localhost:{P1}/v1", FP1)
        pruef(False, "http-Adresse abgelehnt")
    except llm_tls.AnkerFehler as e:
        pruef("HTTPS" in str(e), "http-Adresse abgelehnt")
    # Name passt nicht (IP statt localhost): Bindung trotzdem moeglich, gemessen
    url_ip = f"https://127.0.0.1:{P1}/v1"
    try:
        e_ip = await asyncio.to_thread(llm_tls.anker_bauen, url_ip, FP1)
        pruef(e_ip.get("name_abweichung") is True, "IP-Adresse: Namensabweichung vermerkt")
    except Exception as e:  # noqa: BLE001
        e_ip = None
        pruef(False, f"IP-Adresse: Verankern moeglich ({e})")

    # ── 4. ohne Anker unveraendert ──────────────────────────────────────
    print("4. Ohne Anker byte-gleich")
    _stub.config.profiles = [{"id": "a", "api_url": URL1}]
    pruef(llm_tls.client_args() == {}, "client_args() ohne Anker ist leer")

    # ── 3. Wirkung, exakt nach Host:Port ────────────────────────────────
    print("3. Wirkung nach Host UND Port")
    _stub.config.profiles = [{"id": "a", "api_url": URL1, "cert": e1}]
    pruef(await _abruf(URL1, **llm_tls.client_args()) == "ok",
          "mit Anker gelingt der Abruf am verankerten Port")
    pruef(await _abruf(URL2, **llm_tls.client_args()) == "zert",
          "anderer Port desselben Rechners bleibt bei der normalen Pruefung")
    pruef(await _abruf(URL3, **llm_tls.client_args()) == "zert",
          "anderer Port mit GLEICHEM Zertifikat: Anker greift dort nicht")
    # Anker von Server 1 auf den Port von Server 2 umgeschrieben: das
    # Zertifikat ist das falsche, also muss es scheitern (keine Namensbindung)
    falsch = dict(e1, port=P2)
    _stub.config.profiles = [{"id": "a", "api_url": URL2, "cert": falsch}]
    pruef(await _abruf(URL2, **llm_tls.client_args()) == "zert",
          "Anker gilt nur fuer das Zertifikat, nicht fuer den Ort")
    if e_ip:
        _stub.config.profiles = [{"id": "a", "api_url": url_ip, "cert": e_ip}]
        pruef(await _abruf(url_ip, **llm_tls.client_args()) == "ok",
              "IP-Adresse mit Namensabweichung: Abruf gelingt mit Anker")
        pruef(await _abruf(url_ip) == "zert", "IP-Adresse ohne Anker scheitert")
    # Formular-Zusatz (ungespeichert)
    _stub.config.profiles = []
    zus = await asyncio.to_thread(llm_tls.zusatz_fuer, URL1, FP1)
    pruef(await _abruf(URL1, **llm_tls.client_args(zus)) == "ok",
          "ungespeicherter Formular-Anker wirkt im Test")
    pruef(await asyncio.to_thread(llm_tls.zusatz_fuer, URL1, "") == {},
          "leeres Formularfeld -> kein Zusatz")

    # ── 5. gemeinsamer Client ───────────────────────────────────────────
    print("5. Gemeinsamer LLM-Client folgt den Ankern")
    try:
        from backend import llm
    except Exception as e:  # noqa: BLE001
        abbruch(f"backend.llm nicht importierbar: {e}")
    _stub.config.profiles = []
    c_a = await llm._get_shared_client()
    c_b = await llm._get_shared_client()
    pruef(c_a is c_b, "ohne Aenderung derselbe Client")
    _stub.config.profiles = [{"id": "a", "api_url": URL1, "cert": e1}]
    c_c = await llm._get_shared_client()
    pruef(c_c is not c_a, "neuer Anker -> neuer Client")
    try:
        r = await c_c.get(URL1 + "/models", timeout=5.0)
        pruef(r.status_code == 200, "der neue gemeinsame Client traegt den Anker")
    except Exception as e:  # noqa: BLE001
        pruef(False, f"der neue gemeinsame Client traegt den Anker ({e})")
    await c_c.aclose()
    await c_a.aclose()

    # ── 6. Anker nie aus dem Request ────────────────────────────────────
    print("6. Kein Anker ueber die Profil-Whitelist")
    baum = ast.parse((ROOT / "backend" / "config.py").read_text(encoding="utf-8"))
    gefunden = False
    for f in ast.walk(baum):
        if isinstance(f, ast.FunctionDef) and f.name in ("update_profile", "create_profile"):
            texte = {n.value for n in ast.walk(f)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            gefunden = True
            pruef("cert" not in texte, f"{f.name} kennt das Feld 'cert' nicht")
    if not gefunden:
        abbruch("update_profile/create_profile nicht gefunden")


try:
    asyncio.run(main())
finally:
    S1.shutdown()
    S2.shutdown()
    S3.shutdown()

print(f"\nErgebnis: {OK} OK, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
