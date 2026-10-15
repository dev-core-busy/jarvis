#!/usr/bin/env python3
"""Waechter: E-Mail-TLS – Pruefung IMMER an, Anker per Fingerabdruck (BSI-Abgleich).

Befund (Abschnitt 5, Skill ``email``, Schwere hoch): "TLS-Pruefung je Konto
abschaltbar". Massnahme ``backend/mail_tls.py`` (Betreiberentscheid 2026-10-12,
"wie H14"). Gemessen wird gegen ECHTE lokale TLS-Server mit selbst
ausgestelltem Zertifikat – direktes TLS (HTTPS), SMTP-STARTTLS, IMAP-STARTTLS:

  [1] Regel: kein Schalter mehr (mail_client/addin_sso/Manifest/Oberflaeche)
  [2] ziele(): welcher Kanal mit welchem Port und welchem TLS-Weg
  [3] Positivkontrolle: der Testserver ist ohne Anker WIRKLICH unvertraut –
      sonst waeren alle folgenden Pruefungen trivial wahr (Exit 2)
  [4] pruefen/bestaetigen: drei Handshakes, auch hinter STARTTLS; ein falscher
      Fingerabdruck verankert nichts
  [5] ssl_kontext: Anker wirkt nur fuer genau Host+Port; nie CERT_NONE
  [6] Bestand: alter Schalter AUS -> einmalige Uebernahme genau der damals
      eingetragenen Ziele; die Liste waechst nie; ein spaeteres verify_ssl:false
      hat keine Wirkung
  [7] EWS-Adapter (requests): verify kommt aus dem Anker, auch gegen
      ``Session.verify=False``
  [8] Add-in-SSO: das Metadaten-Dokument wird geprueft geholt
  [9] mail_client: IMAP ohne STARTTLS meldet sich NICHT im Klartext an;
      SMTP ohne Verschluesselung wird abgelehnt

``backend.config`` wird NIE echt importiert (Stub mit Exit 2 bei Verstoss),
das Anker-Buendel (``sap_cert.CERT_DIR``) liegt im Sandkasten.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import datetime
import http.server
import ipaddress
import json
import socket
import ssl
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (" – " + str(detail) if detail else ""))


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


def abschnitt(t):
    print("\n── " + t)


# ── Sandkasten: Konfigurations-Stub ─────────────────────────────────────────
_STATES: dict = {}


class _Cfg:
    def get_setting(self, key, vorgabe=None):
        return vorgabe

    def get_skill_states(self):
        return json.loads(json.dumps(_STATES))   # Kopie wie die echte Ablage

    def save_skill_state(self, name, state):
        _STATES[name] = json.loads(json.dumps(state))


_stub = types.ModuleType("backend.config")
_stub.config = _Cfg()
sys.modules["backend.config"] = _stub


def cfg_setzen(**felder):
    _STATES.clear()
    _STATES["email"] = {"enabled": True, "config": dict(felder)}


def cfg():
    return (_STATES.get("email") or {}).get("config") or {}


try:
    from backend import mail_tls, sap_cert, mail_client as mc  # noqa: E402
except Exception as e:  # noqa: BLE001
    abbruch("Module nicht ladbar: %s" % e)
if getattr(sys.modules.get("backend.config"), "__file__", None):
    abbruch("das ECHTE backend.config wurde geladen")
_SAND = Path(tempfile.mkdtemp(prefix="mail_tls_"))
sap_cert.CERT_DIR = _SAND / "certs"

# ── Zertifikat (selbst ausgestellt, wie ein interner Exchange) ──────────────
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402


def _zert(cn):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    z = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(jetzt - datetime.timedelta(days=1))
         .not_valid_after(jetzt + datetime.timedelta(days=30))
         .add_extension(x509.SubjectAlternativeName([
             x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
             critical=False)
         .sign(key, hashes.SHA256()))
    d = _SAND / cn
    d.mkdir()
    (d / "c.pem").write_bytes(z.public_bytes(serialization.Encoding.PEM))
    (d / "k.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(d / "c.pem"), str(d / "k.pem"))
    fp = "sha256:" + z.fingerprint(hashes.SHA256()).hex()
    return ctx, fp


SRV_CTX, FP = _zert("mail.test.local")
SRV_CTX2, FP2 = _zert("anderer.test.local")   # anderes Zertifikat, gleicher Name

H = "127.0.0.1"


# ── Testserver ──────────────────────────────────────────────────────────────
class _Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def https_server(ctx):
    srv = http.server.ThreadingHTTPServer((H, 0), _Ok)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    # Reine Handshake-Proben schliessen ohne HTTP – kein Traceback ins Protokoll
    srv.handle_error = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def _zeilen_server(handler):
    s = socket.socket()
    s.bind((H, 0))
    s.listen(8)

    def lauf():
        while True:
            try:
                c, _a = s.accept()
            except OSError:
                return
            threading.Thread(target=handler, args=(c,), daemon=True).start()
    threading.Thread(target=lauf, daemon=True).start()
    return s.getsockname()[1]


def smtp_server(ctx):
    def h(c):
        try:
            f = c.makefile("rb")
            c.sendall(b"220 test ESMTP\r\n")
            tls = None
            while True:
                z = f.readline()
                if not z:
                    return
                cmd = z.strip().upper()
                ziel = tls or c
                if cmd.startswith(b"EHLO") or cmd.startswith(b"HELO"):
                    ziel.sendall(b"250-test\r\n250 STARTTLS\r\n" if tls is None else b"250 test\r\n")
                elif cmd == b"STARTTLS":
                    c.sendall(b"220 go\r\n")
                    tls = ctx.wrap_socket(c, server_side=True)
                    f = tls.makefile("rb")
                elif cmd == b"QUIT":
                    ziel.sendall(b"221 bye\r\n")
                    return
                else:
                    ziel.sendall(b"250 ok\r\n")
        except Exception:  # noqa: BLE001
            return
    return _zeilen_server(h)


IMAP_LOG: list = []


def imap_server(ctx, mit_starttls=True):
    def h(c):
        try:
            f = c.makefile("rb")
            c.sendall(b"* OK IMAP4rev1 bereit\r\n")
            tls = None
            while True:
                z = f.readline()
                if not z:
                    return
                teile = z.strip().split(b" ", 2)
                tag, cmd = teile[0], (teile[1].upper() if len(teile) > 1 else b"")
                ziel = tls or c
                IMAP_LOG.append((cmd.decode(), tls is not None))
                if cmd == b"CAPABILITY":
                    cap = b"IMAP4rev1 AUTH=PLAIN" + (b" STARTTLS" if mit_starttls and tls is None else b"")
                    ziel.sendall(b"* CAPABILITY " + cap + b"\r\n" + tag + b" OK erledigt\r\n")
                elif cmd == b"STARTTLS" and mit_starttls:
                    c.sendall(tag + b" OK los\r\n")
                    tls = ctx.wrap_socket(c, server_side=True)
                    f = tls.makefile("rb")
                elif cmd == b"LOGOUT":
                    ziel.sendall(b"* BYE\r\n" + tag + b" OK erledigt\r\n")
                    return
                else:
                    ziel.sendall(tag + b" OK erledigt\r\n")
        except Exception:  # noqa: BLE001
            return
    return _zeilen_server(h)


P_HTTPS = https_server(SRV_CTX)
P_HTTPS2 = https_server(SRV_CTX2)
P_SMTP = smtp_server(SRV_CTX)
P_IMAP = imap_server(SRV_CTX)
P_IMAP_OHNE = imap_server(SRV_CTX, mit_starttls=False)


def handshake(ctx, port):
    try:
        with socket.create_connection((H, port), timeout=5) as roh:
            with ctx.wrap_socket(roh, server_hostname=H):
                return True
    except (ssl.SSLError, OSError):
        return False


def _ohne_kommentar(quelle):
    """Quelltext ohne #-Kommentare und Docstrings (Waechter liest nicht seine Begruendung)."""
    baum = ast.parse(quelle)
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(
                    getattr(n.body[0], "value", None), ast.Constant) and isinstance(
                    n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(baum)


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. Regel: es gibt keinen Schalter mehr")
MC_SRC = _ohne_kommentar((ROOT / "backend/mail_client.py").read_text(encoding="utf-8"))
SSO_SRC = _ohne_kommentar((ROOT / "backend/addin_sso.py").read_text(encoding="utf-8"))
MA_SRC = _ohne_kommentar((ROOT / "backend/mail_accounts.py").read_text(encoding="utf-8"))
check("Bis 2026-10-12 stand" in (ROOT / "backend/mail_client.py").read_text(encoding="utf-8")
      and "Bis 2026-10-12 stand" not in MC_SRC,
      "Positivkontrolle: der Docstring-Filter entfernt eine Begruendung")
check("verify_ssl" not in MC_SRC and "CERT_NONE" not in MC_SRC and "NoVerifyHTTPAdapter" not in MC_SRC,
      "mail_client kennt kein verify_ssl und kein CERT_NONE mehr")
check("verify_ssl" not in MA_SRC,
      "mail_accounts reicht kein verify_ssl ans Konto")
check("verify_ssl" not in SSO_SRC,
      "addin_sso liest keinen Pruef-Schalter mehr")
check("mail_tls.ssl_kontext" in SSO_SRC,
      "addin_sso holt die Metadaten ueber mail_tls")
_manifest = json.loads((ROOT / "skills/email/skill.json").read_text(encoding="utf-8"))
check("verify_ssl" not in json.dumps(_manifest),
      "das Skill-Manifest bietet den Schalter nicht mehr an")
_html = (ROOT / "frontend/settings.html").read_text(encoding="utf-8")
check('id="em-verify-ssl"' not in _html
      and all('class="sapcert" id="em-cert-%s"' % k in _html for k in mail_tls.KANAELE),
      "die Oberflaeche hat keinen Haken mehr, aber je Kanal einen Baustein")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("2. ziele(): Kanal, Port, TLS-Weg")
z = mail_tls.ziele({"ews_url": "mail.firma.local", "imap_host": "imap.firma.local",
                    "imap_ssl": True, "smtp_host": "smtp.firma.local", "smtp_port": 587,
                    "smtp_starttls": True})
check(z.get("ews") == ("mail.firma.local", 443, None),
      "EWS: Hostname wird zur https-Adresse, Port 443, direktes TLS", z.get("ews"))
check(z.get("imap") == ("imap.firma.local", 993, None),
      "IMAP mit TLS: 993, direktes TLS", z.get("imap"))
check(z.get("smtp") == ("smtp.firma.local", 587, "smtp"),
      "SMTP 587: STARTTLS", z.get("smtp"))
z = mail_tls.ziele({"imap_host": "i", "imap_ssl": False, "smtp_host": "s", "smtp_port": 465})
check(z.get("imap") == ("i", 143, "imap"),
      "IMAP ohne TLS-Haken: 143 mit STARTTLS", z.get("imap"))
check(z.get("smtp") == ("s", 465, None),
      "SMTP 465: direktes TLS", z.get("smtp"))
z = mail_tls.ziele({"smtp_host": "s", "smtp_port": 25, "smtp_starttls": False})
check("smtp" not in z,
      "SMTP ohne Verschluesselung: kein Ziel (es gibt kein Zertifikat)", z)
check("ews" not in mail_tls.ziele({}),
      "ohne EWS-Adresse (Autodiscover): kein EWS-Ziel")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. Positivkontrolle: der Testserver ist ohne Anker unvertraut")
cfg_setzen()
# Die Kontrolle misst mit dem SYSTEMSPEICHER, nicht mit dem Produktcode: eine
# Sabotage in mail_tls muss als FAIL erscheinen, nicht als "Messaufbau kaputt"
# (so in der ersten Fassung – zwei Gegenproben endeten im Abbruch statt im Biss).
_ohne = handshake(ssl.create_default_context(), P_HTTPS)
_roh = ssl.create_default_context()
_roh.check_hostname = False
_roh.verify_mode = ssl.CERT_NONE
_erreichbar = handshake(_roh, P_HTTPS)
if _ohne or not _erreichbar:
    abbruch("Messaufbau traegt nicht (geprueft=%s, ungeprueft erreichbar=%s)" % (_ohne, _erreichbar))
print("  (ohne Anker abgewiesen, ungeprueft erreichbar – die Messung kann unterscheiden)")
for _k in mail_tls.KANAELE:
    check(not handshake(mail_tls.ssl_kontext(_k, H, P_HTTPS), P_HTTPS),
          "%s ohne Anker und ohne Vormerkung: der Server wird abgewiesen" % _k)

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. pruefen / bestaetigen – direkt und hinter STARTTLS")
for kanal, port, st in (("ews", P_HTTPS, None), ("smtp", P_SMTP, "smtp"), ("imap", P_IMAP, "imap")):
    try:
        e = mail_tls.pruefen(kanal, H, port, st)
    except Exception as ex:  # noqa: BLE001
        check(False, "%s: Zertifikat abholbar" % kanal, ex)
        continue
    check(e["fingerprint"] == FP, "%s: Fingerabdruck des Servers stimmt" % kanal, e["fingerprint"])
    check(e["system_ok"] is False and e["pin_ok"] is True,
          "%s: Systempruefung scheitert, Anker wuerde wirken (gemessen)" % kanal,
          (e["system_ok"], e["system_grund"], e["pin_ok"], e["pin_grund"]))
try:
    mail_tls.bestaetigen("imap", H, P_IMAP, "imap", FP2)
    check(False, "falscher Fingerabdruck wird abgewiesen")
except sap_cert.ZertFehler:
    check(True, "falscher Fingerabdruck wird abgewiesen")
try:
    mail_tls.bestaetigen("imap", H, P_IMAP, "imap", "sha256:" + "0" * 63)
    check(False, "ungueltiger Fingerabdruck wird abgewiesen")
except sap_cert.ZertFehler:
    check(True, "ungueltiger Fingerabdruck wird abgewiesen")
E_IMAP = mail_tls.bestaetigen("imap", H, P_IMAP, "imap", FP)
check(E_IMAP["fingerprint"] == FP and E_IMAP["kanal"] == "imap" and E_IMAP["port"] == P_IMAP,
      "richtiger Fingerabdruck ergibt einen Eintrag mit Host, Port und Kanal")
try:
    mail_tls.ziel_aus_angabe("ews", {}, {})
    check(False, "ohne EWS-Adresse: Klartext-Grund statt Ziel")
except sap_cert.ZertFehler as ex:
    check("Autodiscover" in str(ex), "ohne EWS-Adresse: Klartext-Grund statt Ziel", ex)
check(mail_tls.ziel_aus_angabe("smtp", {"host": H, "port": str(P_SMTP), "starttls": True}, {})
      == (H, P_SMTP, "smtp"), "Ziel aus den Formularfeldern (vor dem Speichern)")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("5. ssl_kontext: Anker wirkt genau fuer Host+Port")
E_EWS = mail_tls.bestaetigen("ews", H, P_HTTPS, None, FP)
cfg_setzen(zert_anker={"ews": E_EWS})
k = mail_tls.ssl_kontext("ews", H, P_HTTPS)
check(k.verify_mode == ssl.CERT_REQUIRED, "der Kontext prueft (CERT_REQUIRED)")
check(handshake(k, P_HTTPS), "mit Anker: Handshake gelingt")
check(not handshake(mail_tls.ssl_kontext("ews", H, P_HTTPS2), P_HTTPS2),
      "anderes Ziel (anderer Port) bekommt den Anker NICHT")
check(not handshake(mail_tls.ssl_kontext("imap", H, P_HTTPS), P_HTTPS),
      "anderer Kanal bekommt den Anker NICHT")
cfg_setzen(zert_anker={"ews": dict(E_EWS, pem="kaputt")})
k = mail_tls.ssl_kontext("ews", H, P_HTTPS)
check(k.verify_mode == ssl.CERT_REQUIRED and not handshake(k, P_HTTPS),
      "unbrauchbarer Anker: gewoehnliche Pruefung, nie CERT_NONE")
cfg_setzen(verify_ssl=False, tls_bestand={"am": 1})
k = mail_tls.ssl_kontext("imap", H, P_IMAP)
check(k.verify_mode == ssl.CERT_REQUIRED and k.check_hostname,
      "ein (spaeter wieder gesetztes) verify_ssl:false hat keine Wirkung")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("6. Bestand: einmalige Uebernahme der damals eingetragenen Ziele")
cfg_setzen(verify_ssl=False, imap_host=H, imap_port=P_IMAP, imap_ssl=False,
           smtp_host=H, smtp_port=P_SMTP, smtp_starttls=True)
offen = mail_tls.bestand_festschreiben()
check(sorted(offen or []) == sorted(["imap|%s|%d" % (H, P_IMAP), "smtp|%s|%d" % (H, P_SMTP)]),
      "die eingetragenen Ziele sind vorgemerkt", offen)
check(cfg().get("verify_ssl") is True and cfg().get("tls_bestand", {}).get("pruefung_war_aus") is True,
      "der Altschalter ist abgeloest und die Marke geschrieben")
check(mail_tls.bestand_festschreiben() is None, "ein zweiter Lauf tut nichts")
# Ein spaeter eingetragener Server bekommt die Ausnahme nicht
cfg()["imap_port"] = P_IMAP_OHNE
check("imap|%s|%d" % (H, P_IMAP_OHNE) not in (cfg().get("tls_uebernahme_offen") or []),
      "die Liste waechst nicht mit der Konfiguration")
k = mail_tls.ssl_kontext("smtp", H, P_SMTP, "smtp")
import smtplib  # noqa: E402
try:
    s = smtplib.SMTP(H, P_SMTP, timeout=5)
    s.starttls(context=k)
    s.quit()
    _smtp_ok = True
except Exception as ex:  # noqa: BLE001
    _smtp_ok = ex
check(_smtp_ok is True, "erster Aufbau: das vorgelegte Zertifikat wird uebernommen, Verbindung geprueft",
      _smtp_ok)
_anker = (cfg().get("zert_anker") or {}).get("smtp") or {}
check(_anker.get("fingerprint") == FP and _anker.get("uebernommen") is True,
      "der Anker steht in der Konfiguration (als Uebernahme gekennzeichnet)")
check("smtp|%s|%d" % (H, P_SMTP) not in (cfg().get("tls_uebernahme_offen") or []),
      "das Ziel ist aus der Liste gestrichen (genau einmal)")
check("imap|%s|%d" % (H, P_IMAP) in (cfg().get("tls_uebernahme_offen") or []),
      "das noch nicht benutzte Ziel bleibt vorgemerkt")
cfg_setzen(imap_host=H, imap_port=P_IMAP)
check(mail_tls.bestand_festschreiben() == [], "Bestand MIT Pruefung: nichts vorgemerkt")
check(not handshake(mail_tls.ssl_kontext("ews", H, P_HTTPS), P_HTTPS),
      "ohne Vormerkung wird nichts uebernommen")
check(not (cfg().get("zert_anker") or {}), "und nichts verankert")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("7. EWS-Adapter (requests)")
import requests  # noqa: E402
cfg_setzen(zert_anker={"ews": E_EWS})
Adapter = mc._anker_adapter_klasse()
sitzung = requests.Session()
sitzung.mount("https://", Adapter())
sitzung.verify = False          # der Adapter muss das UEBERSTIMMEN
try:
    r = sitzung.get("https://%s:%d/" % (H, P_HTTPS), timeout=5)
    check(r.status_code == 200, "mit Anker: Anfrage gelingt")
except Exception as ex:  # noqa: BLE001
    check(False, "mit Anker: Anfrage gelingt", ex)
try:
    sitzung.get("https://%s:%d/" % (H, P_HTTPS2), timeout=5)
    check(False, "fremdes Zertifikat wird abgewiesen – auch bei Session.verify=False")
except requests.exceptions.SSLError:
    check(True, "fremdes Zertifikat wird abgewiesen – auch bei Session.verify=False")
v = mail_tls.requests_verify("https://%s:%d/EWS/Exchange.asmx" % (H, P_HTTPS))
check(isinstance(v, str) and Path(v).read_text().strip() == E_EWS["pem"].strip()
      and str(v).startswith(str(_SAND)),
      "verify ist das Buendel mit GENAU dem Anker (im Sandkasten)", v)
check(mail_tls.requests_verify("https://anders.local/") is True
      and mail_tls.requests_verify("http://x/") is True, "ohne Anker: True, nie False")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("8. Add-in-SSO: Metadaten-Dokument geprueft")
from backend import addin_sso  # noqa: E402
import httpx  # noqa: E402
# Der ECHTE Abruf muss den Kontext benutzen – sonst prueft der Rest nur eine
# Funktion, die niemand ruft.
_sso_baum = ast.parse((ROOT / "backend/addin_sso.py").read_text(encoding="utf-8"))
_abruf = [n for n in ast.walk(_sso_baum)
          if isinstance(n, ast.FunctionDef) and n.name == "_signaturschluessel"]
_verify = [kw.value for f in _abruf for c in ast.walk(f) if isinstance(c, ast.Call)
           and getattr(c.func, "attr", "") == "Client" for kw in c.keywords if kw.arg == "verify"]
check(len(_verify) == 1 and isinstance(_verify[0], ast.Call)
      and getattr(_verify[0].func, "id", "") == "_tls_kontext",
      "der Metadaten-Abruf (_signaturschluessel) nimmt verify=_tls_kontext(...)",
      [ast.unparse(v) for v in _verify])
cfg_setzen(zert_anker={"ews": E_EWS}, verify_ssl=False)
try:
    with httpx.Client(verify=addin_sso._tls_kontext("https://%s:%d/x" % (H, P_HTTPS)), timeout=5) as c:
        check(c.get("https://%s:%d/x" % (H, P_HTTPS)).status_code == 200,
              "mit verankertem Exchange-Zertifikat: Abruf gelingt")
except Exception as ex:  # noqa: BLE001
    check(False, "mit verankertem Exchange-Zertifikat: Abruf gelingt", ex)
try:
    with httpx.Client(verify=addin_sso._tls_kontext("https://%s:%d/x" % (H, P_HTTPS2)), timeout=5) as c:
        c.get("https://%s:%d/x" % (H, P_HTTPS2))
    check(False, "fremdes Zertifikat: Abruf scheitert (auch mit Altwert verify_ssl:false)")
except httpx.HTTPError:
    check(True, "fremdes Zertifikat: Abruf scheitert (auch mit Altwert verify_ssl:false)")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("9. mail_client: kein Klartext-Kennwort")
cfg_setzen(zert_anker={"imap": E_IMAP})
IMAP_LOG.clear()
konto = mc.MailKonto(adresse="a@b.de", passwort="geheim", kanal="imap",
                     imap_host=H, imap_port=P_IMAP, imap_ssl=False, zeitlimit=5)
try:
    mc._Imap(konto)._verbinden()
    check(True, "IMAP mit STARTTLS und Anker: Anmeldung gelingt")
except Exception as ex:  # noqa: BLE001
    check(False, "IMAP mit STARTTLS und Anker: Anmeldung gelingt", ex)
check(("LOGIN", True) in IMAP_LOG and ("LOGIN", False) not in IMAP_LOG,
      "LOGIN kam verschluesselt an", IMAP_LOG)
IMAP_LOG.clear()
konto = mc.MailKonto(adresse="a@b.de", passwort="geheim", kanal="imap",
                     imap_host=H, imap_port=P_IMAP_OHNE, imap_ssl=False, zeitlimit=5)
try:
    mc._Imap(konto)._verbinden()
    check(False, "Server ohne STARTTLS: die Verbindung scheitert")
except mc.MailFehler as ex:
    check(ex.kategorie != "auth", "Server ohne STARTTLS: die Verbindung scheitert (kein Anmeldefehler)",
          ex.kategorie)
check(not any(c == "LOGIN" for c, _t in IMAP_LOG), "und das Kennwort ging NICHT im Klartext hinaus",
      IMAP_LOG)
check(any(c == "CAPABILITY" for c, _t in IMAP_LOG),
      "Positivkontrolle: der Server wurde wirklich angesprochen", IMAP_LOG)
konto = mc.MailKonto(adresse="a@b.de", passwort="geheim", kanal="imap",
                     smtp_host=H, smtp_port=P_SMTP, smtp_starttls=False, zeitlimit=5)
try:
    mc._Imap(konto)._smtp()
    check(False, "SMTP ohne Verschluesselung wird abgelehnt")
except mc.MailFehler as ex:
    check("Klartext" in str(ex), "SMTP ohne Verschluesselung wird abgelehnt", ex)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
