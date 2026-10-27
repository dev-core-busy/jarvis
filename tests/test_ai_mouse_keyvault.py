#!/usr/bin/env python3
"""Waechter: AI-Maus signiert ueber den Azure Key Vault (zweiter Weg, 2026-10-27).

⚠ GEMESSEN WIRD DER GANZE WEG, nicht eine Attrappe davon: ein nachgebauter
Azure-Dienst (Anmeldung + Vault) laeuft auf 127.0.0.1, das ECHTE jsign
signiert eine ECHTE, kleine PE-Datei, und die Signatur wird aus der Datei
gelesen und gegen das Zertifikat des Vaults geprueft. Der echte Vault ist von
einem Entwicklungsrechner aus nicht erreichbar (Netzwerk-Freigabe) – eine
Messung, die ihn braucht, liefe nie.

Geprueft wird unter anderem:
  * erst pruefen, dann speichern – falsches Secret, Firewall, fehlende
    Signier-Berechtigung, fremder Schluessel: nichts wird geaendert;
  * der Vault ist auf ``https://<name>.vault.azure.net`` festgelegt und die
    ``kid`` muss im selben Vault liegen (das Token geht nirgends sonst hin);
  * ein gespeichertes Secret gilt nur fuer denselben Zugang;
  * das Token steht nie in der Befehlszeile, das Secret nie im Zustand;
  * fail-open, aber laut: Fehlschlag beim Bau laesst die Datei unveraendert.

Sandkasten: jedes Pfad-Attribut des Moduls liegt im Wegwerf-Verzeichnis,
sonst Exit 2. Ohne Java oder ohne jsign (Maven nicht erreichbar): Exit 2.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import http.server
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

OK = 0
FAIL = 0


def check(text: str, bedingung) -> bool:
    global OK, FAIL
    if isinstance(text, bool) or not isinstance(text, str):
        print("HARNESS-FEHLER: check(text, bedingung) – Argumente vertauscht?")
        sys.exit(2)
    if bedingung:
        OK += 1
        print("  OK   %s" % text)
        return True
    FAIL += 1
    print("  FAIL %s" % text)
    return False


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


def sicher(fn, *a, **kw):
    """Darf nicht werfen – sonst endet der Lauf ohne Bilanz (Register)."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


# ── Sandkasten ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="aimouse-kv-test-"))
(SAND / "data").mkdir()

from backend import ai_mouse_signatur as sig  # noqa: E402

sig._DATA = SAND / "data"
sig.PFX_DATEI = sig._DATA / ".aimouse_sign.pfx"
sig.SCHLUESSEL_DATEI = sig._DATA / ".aimousesignkey"
sig.KONFIG_DATEI = sig._DATA / "ai_mouse_signatur.json"
sig.JSIGN_JAR = SAND / "vendor" / "jsign.jar"
_aussen = {n: str(v) for n, v in vars(sig).items()
           if isinstance(v, Path) and not n.startswith("__")
           and not str(v).startswith(str(SAND))}
if _aussen:
    abbruch("Sandkasten nicht dicht: %s" % _aussen)

import backend.ai_mouse as am  # noqa: E402

am.branding = lambda: ("Contoso", "#123456")
am.einkompilierte_basis = lambda pfad=None: ""
am.exe_pfad = lambda: SAND / "fehlt.exe"

# ── Material: Schluessel, Zertifikate, PE ──────────────────────────────────
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs7  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402


def zert_bauen(key, cn: str, tage: int):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - datetime.timedelta(days=2))
            .not_valid_after(jetzt + datetime.timedelta(days=tage))
            .sign(key, hashes.SHA256()))


KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FREMD = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ZERT = zert_bauen(KEY, "Testhaus Code Signing", 365)
ZERT_ALT = zert_bauen(KEY, "Testhaus Code Signing", -1)       # abgelaufen
ZERT_FREMD = zert_bauen(FREMD, "Testhaus Code Signing", 365)  # passt nicht zum Schluessel

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "66666666-7777-8888-9999-aaaaaaaaaaaa"
SECRET = "geheimes~Secret.123"
ZNAME = "TesthausCodeSigning"


def pe_bauen() -> bytes:
    """Kleinste PE32+-Datei mit einer Section, die jsign annimmt."""
    fa = 0x200
    b = bytearray(fa * 2)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    lf = 0x80
    b[lf:lf + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", b, lf + 4, 0x8664, 1, 0, 0, 0, 240, 0x22)
    o = lf + 24
    struct.pack_into("<HBBIIIII", b, o, 0x20B, 14, 0, fa, 0, 0, 0x1000, 0x1000)
    struct.pack_into("<Q", b, o + 24, 0x140000000)
    struct.pack_into("<II", b, o + 32, 0x1000, fa)
    struct.pack_into("<HHHHHH", b, o + 40, 6, 0, 0, 0, 6, 0)
    struct.pack_into("<IIII", b, o + 56, 0x2000, fa, 0, 3)
    struct.pack_into("<QQQQ", b, o + 72, 0x100000, 0x1000, 0x100000, 0x1000)
    struct.pack_into("<II", b, o + 104, 0, 16)
    s = o + 240
    b[s:s + 8] = b".text\0\0\0"
    struct.pack_into("<IIIIIIHHI", b, s + 8, 0x10, 0x1000, fa, fa, 0, 0, 0, 0, 0x60000020)
    b[fa] = 0xC3
    return bytes(b)


def signatur_zertifikate(pfad: Path) -> list:
    """Die Zertifikate aus der Authenticode-Signatur der Datei (PKCS#7)."""
    daten = pfad.read_bytes()
    lf = struct.unpack_from("<I", daten, 0x3C)[0]
    dd = lf + 24 + 112
    versatz, groesse = struct.unpack_from("<II", daten, dd + 4 * 8)
    if not versatz or not groesse:
        return []
    laenge = struct.unpack_from("<I", daten, versatz)[0]
    der = daten[versatz + 8:versatz + laenge]
    import warnings
    try:
        # jsign schreibt BER (unbestimmte Laengen); cryptography liest es und
        # warnt nur – die Warnung ist hier kein Befund.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return pkcs7.load_der_pkcs7_certificates(der)
    except Exception:  # noqa: BLE001
        return []


# ── Nachgebauter Azure-Dienst ───────────────────────────────────────────────
class Azure:
    modus = "normal"     # normal | firewall | ohne_sign | fremd_kid | fremder_schluessel | abgelaufen
    log: list = []
    tokens: set = set()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _antw(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _token_ok(self):
        return (self.headers.get("Authorization") or "")[7:] in Azure.tokens

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        roh = self.rfile.read(n)
        pfad = self.path.split("?")[0]
        Azure.log.append(("POST", pfad))
        if pfad == "/%s/oauth2/v2.0/token" % TENANT:
            f = dict(urllib.parse.parse_qsl(roh.decode()))
            if f.get("client_id") != CLIENT or f.get("client_secret") != SECRET:
                return self._antw(401, {"error": "invalid_client",
                                        "error_description": "AADSTS7000215: Invalid client secret provided."})
            if f.get("scope") != "https://vault.azure.net/.default":
                return self._antw(400, {"error": "invalid_scope"})
            tok = "tok-%d" % (len(Azure.tokens) + 1)
            Azure.tokens.add(tok)
            return self._antw(200, {"access_token": tok, "token_type": "Bearer"})
        if pfad.startswith("/%s/oauth2" % "") or "/oauth2/" in pfad:
            return self._antw(400, {"error": "invalid_request",
                                    "error_description": "AADSTS90002: Tenant not found."})
        if pfad == "/keys/%s/v1/sign" % ZNAME:
            Azure.log.append(("SIGN", json.loads(roh).get("alg")))
            if not self._token_ok():
                return self._antw(401, {"error": {"code": "Unauthorized", "message": "x"}})
            if Azure.modus == "ohne_sign":
                return self._antw(403, {"error": {"code": "Forbidden", "message":
                                        "The user does not have keys sign permission"}})
            dig = base64.urlsafe_b64decode(json.loads(roh)["value"] + "==")
            s = KEY.sign(dig, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
            return self._antw(200, {"kid": "x", "value": base64.urlsafe_b64encode(s).decode().rstrip("=")})
        return self._antw(404, {"error": {"code": "NotFound", "message": pfad}})

    def do_GET(self):
        pfad = self.path.split("?")[0]
        Azure.log.append(("GET", pfad))
        # Bezugsquelle fuer jsign (interner Spiegel) – ohne Token, wie ein
        # Maven-Spiegel.
        if pfad in ("/jsign.jar", "/falsch.jar"):
            daten = JAR_BYTES[0] if pfad == "/jsign.jar" else b"kein jsign"
            self.send_response(200)
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)
            return
        if not self._token_ok():
            return self._antw(401, {"error": {"code": "Unauthorized", "message": "no token"}})
        if Azure.modus == "firewall":
            return self._antw(403, {"error": {"code": "Forbidden", "message":
                                    "Client address is not authorized and caller is not a trusted service.",
                                    "innererror": {"code": "ForbiddenByFirewall"}}})
        if pfad == "/certificates/%s" % ZNAME:
            z = {"abgelaufen": ZERT_ALT, "fremder_schluessel": ZERT_FREMD}.get(Azure.modus, ZERT)
            kid = BASIS + "/keys/%s/v1" % ZNAME
            if Azure.modus == "fremd_kid":
                kid = "http://127.0.0.1:1/keys/%s/v1" % ZNAME
            # Antwortform wie der echte Vault (CertificateBundle): jsign liest
            # ``policy.key_props.kty`` – ohne das Feld stirbt es mit einer
            # NullPointerException (erster Lauf dieses Waechters).
            return self._antw(200, {"cer": base64.b64encode(
                z.public_bytes(serialization.Encoding.DER)).decode(), "kid": kid,
                "id": BASIS + "/certificates/%s/v1" % ZNAME,
                **({} if Azure.modus == "ohne_policy" else {
                    "policy": {"key_props": {"kty": "RSA", "key_size": 2048,
                                             "exportable": False}}})})
        return self._antw(404, {"error": {"code": "CertificateNotFound", "message": pfad}})


JAR_BYTES = [b""]   # wird in Abschnitt 5 mit dem echten jsign gefuellt
SRV = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
BASIS = "http://127.0.0.1:%d" % SRV.server_address[1]

# Der Dienst steht fuer Anmeldung UND Vault. Die echte Vault-Pruefung laesst
# nur https://<name>.vault.azure.net zu – sie wird in Abschnitt 1 selbst
# gemessen und HIER fuer den nachgebauten Vault ersetzt.
# ⚠ DIE VORGABE ZEIGT INS LEERE, die Anmeldeadresse kommt aus der
#   EINSTELLUNG: so ist jede gelungene Anmeldung zugleich der Beleg, dass der
#   eingestellte Wert benutzt wird und nicht die Vorgabe.
sig.AZURE_ANMELDUNG = "http://127.0.0.1:1"
_echt_vault_normieren = sig._vault_normieren
sig._vault_normieren = lambda roh: BASIS
_echt_anmeldung_normieren = sig._anmeldung_normieren
_echt_quelle_normieren = sig._jsign_quelle_normieren
sig._anmeldung_normieren = lambda roh: (roh or "").strip().rstrip("/")


def stand() -> bytes:
    try:
        return sig.KONFIG_DATEI.read_bytes()
    except FileNotFoundError:
        return b""


def setzen(**kw):
    a = dict(vault="meinvault", tenant=TENANT, client=CLIENT, secret=SECRET,
             zertifikat=ZNAME, tsa="", anmeldung=BASIS)
    a.update(kw)
    return sicher(sig.keyvault_setzen, **a)


# ── 1. Vault-Adresse und Eingaben ───────────────────────────────────────────
print("=== 1. Vault-Adresse ist festgelegt (dorthin geht das Token) ===")
vn = _echt_vault_normieren
check("Name -> https://<name>.vault.azure.net", vn("MeinVault") == "https://meinvault.vault.azure.net")
check("volle Adresse wird angenommen",
      vn("https://meinvault.vault.azure.net/") == "https://meinvault.vault.azure.net")
for boese in ("http://meinvault.vault.azure.net", "https://meinvault.vault.azure.net.boese.de",
              "https://boese.de", "https://meinvault.vault.azure.net/pfad",
              "https://a.b.vault.azure.net", "", "x"):
    check("abgewiesen: %r" % boese, isinstance(sicher(vn, boese), sig.SignaturFehler))
an = _echt_anmeldung_normieren
check("Anmeldeadresse leer = Vorgabe", an("") == "")
check("Anmeldeadresse https ohne Pfad wird angenommen",
      an("https://login.microsoftonline.us/") == "https://login.microsoftonline.us")
for boese in ("http://login.beispiel.de", "https://login.beispiel.de/pfad", "login.beispiel.de"):
    check("Anmeldeadresse abgewiesen: %r" % boese, isinstance(sicher(an, boese), sig.SignaturFehler))
jq = _echt_quelle_normieren
check("jsign-Quelle leer = Maven Central", jq("") == "")
check("jsign-Quelle http(s) wird angenommen (interner Spiegel)",
      jq("http://spiegel.firma.local/jsign.jar") == "http://spiegel.firma.local/jsign.jar")
check("jsign-Quelle ohne Schema abgewiesen", isinstance(sicher(jq, "spiegel/jsign.jar"), sig.SignaturFehler))
check("Tenant muss eine GUID sein", isinstance(setzen(tenant="contoso"), sig.SignaturFehler))
check("Client muss eine GUID sein", isinstance(setzen(client="123"), sig.SignaturFehler))
check("Zertifikatsname ohne Sonderzeichen", isinstance(setzen(zertifikat="a/b"), sig.SignaturFehler))
check("nichts gespeichert", stand() == b"")

# ── 2. Erst pruefen, dann speichern ─────────────────────────────────────────
print("\n=== 2. Erst pruefen, dann speichern ===")
r = setzen(secret="falsch")
check("falsches Secret: abgewiesen, Grund nennt das Secret",
      isinstance(r, sig.SignaturFehler) and "Client-Secret" in str(r))
check("…nichts gespeichert", stand() == b"")
for modus, wort in (("firewall", "Netzwerk-Freigabe"), ("ohne_sign", "Berechtigung"),
                    ("fremder_schluessel", "gehoeren nicht zusammen"),
                    ("fremd_kid", "in diesem Vault")):
    Azure.modus = modus
    Azure.log.clear()
    r = setzen()
    check("%s: abgewiesen mit „%s\"" % (modus, wort),
          isinstance(r, sig.SignaturFehler) and wort in str(r))
    check("%s: nichts gespeichert" % modus, stand() == b"")
    if modus == "fremd_kid":
        check("fremd_kid: an die fremde Adresse ging KEINE Anfrage (kein SIGN)",
              not any(e[0] == "SIGN" for e in Azure.log))
Azure.modus = "normal"
Azure.log.clear()
r = setzen()
# ⚠ ZWEI URSACHEN TRENNEN (Register): ging die Anmeldung gar nicht an die
#   EINGESTELLTE Adresse, ist das ein Produktbefund (FAIL mit Bilanz) – nur ein
#   sonst kaputter Aufbau ist „konnte nicht laufen".
_ging = ("POST", "/%s/oauth2/v2.0/token" % TENANT) in Azure.log
check("die Anmeldung ging an die EINGESTELLTE Adresse (nicht an die Vorgabe)", _ging)
if not isinstance(r, dict):
    if not _ging:
        print("\n%d OK, %d FAIL" % (OK, FAIL))
        sys.exit(1)
    abbruch("Positivkontrolle: gueltiger Zugang wurde abgewiesen: %r" % r)
check("gueltiger Zugang: gespeichert, Weg = Key Vault",
      r.get("verfahren") == "keyvault" and r.get("eingerichtet") is True)
check("die Probesignatur wurde wirklich angefordert (RS256)", ("SIGN", "RS256") in Azure.log)
check("Zertifikatsdaten stehen im Zustand",
      r.get("betreff") == "Testhaus Code Signing" and bool(r.get("gueltig_bis")))
check("⚠ das Secret steht NICHT im Zustand", SECRET not in json.dumps(r)
      and "secret_enc" not in json.dumps(r))
check("…nur, OB eines gespeichert ist", r.get("keyvault", {}).get("secret_gesetzt") is True)
check("⚠ das Secret steht nicht im Klartext in der Ablage", SECRET.encode() not in stand())
check("Ablage 0640", (sig.KONFIG_DATEI.stat().st_mode & 0o777) == 0o640)
# Die Zusage im Hinweis: „wird beim Speichern des Zugangs geladen". Hier
# zeigt die Quelle ins Leere – der Versuch muss trotzdem STATTFINDEN und die
# Einrichtung darf daran nicht scheitern.
_versuche = []
_echt_bereit = sig.jsign_bereitstellen
sig.jsign_bereitstellen = lambda: _versuche.append(1) or "attrappe"
try:
    check("Speichern versucht, jsign bereitzustellen", isinstance(setzen(), dict) and _versuche)
finally:
    sig.jsign_bereitstellen = _echt_bereit

# ── 3. Gespeichertes Secret nur fuer denselben Zugang ───────────────────────
print("\n=== 3. Leeres Secret = unveraendert – nur fuer denselben Zugang ===")
check("leeres Secret, gleicher Zugang: angenommen", isinstance(setzen(secret=""), dict))
vorher = stand()
Azure.log.clear()
r = setzen(secret="", client="66666666-7777-8888-9999-bbbbbbbbbbbb")
check("leeres Secret, anderer Client: abgewiesen mit der Bitte um das Secret",
      isinstance(r, sig.SignaturFehler) and "Bitte das Client-Secret eingeben" in str(r))
# ⚠ DIE EIGENTLICHE ZUSAGE: das gespeicherte Secret geht gar nicht erst
#   hinaus. „Abgewiesen" allein waere auch wahr, wenn es an die Anmeldung
#   ginge und DIESE es ablehnte (erste Fassung dieses Waechters: stumm).
check("…und es ging KEINE Anmeldung hinaus", not any(e[0] == "POST" for e in Azure.log))
check("…nichts geaendert", stand() == vorher)
r = setzen(secret="", tenant="11111111-2222-3333-4444-666666666666")
check("leeres Secret, anderer Tenant: abgewiesen", isinstance(r, sig.SignaturFehler))
Azure.log.clear()
r = setzen(secret="", anmeldung="http://127.0.0.1:2")
check("⚠ leeres Secret, andere ANMELDEADRESSE: abgewiesen (dorthin ginge das Secret)",
      isinstance(r, sig.SignaturFehler) and "Bitte das Client-Secret eingeben" in str(r))
check("…und es ging keine Anfrage hinaus", Azure.log == [])
z = sig.zustand().get("keyvault", {})
check("Zustand nennt die eingestellte Anmeldeadresse", z.get("anmeldung") == BASIS)
check("…und die Vorgaben fuer die Platzhalter",
      z.get("anmeldung_standard") == sig.AZURE_ANMELDUNG and z.get("jsign_quelle_standard") == sig.JSIGN_URL)

# ── 4. Befehlszeile ─────────────────────────────────────────────────────────
print("\n=== 4. jsign-Aufruf: das Token steht NICHT in der Befehlszeile ===")
kvd = sig._kv(sig._laden())
befehl = sig._jsign_befehl(kvd, SAND / "x.exe", "http://ts.beispiel/tsa")
check("Positivkontrolle: es ist ein jsign-Aufruf", str(sig.JSIGN_JAR) in befehl)
paare = list(zip(befehl, befehl[1:]))
check("Token ueber die Umgebung (env:)", ("--storepass", "env:" + sig.KV_TOKEN_VAR) in paare)
check("Speichertyp Azure Key Vault", ("--storetype", "AZUREKEYVAULT") in paare)
check("SHA-256", ("--alg", "SHA-256") in paare)
check("Zeitstempel RFC 3161", ("--tsaurl", "http://ts.beispiel/tsa") in paare
      and ("--tsmode", "RFC3161") in paare)
check("vorhandene Signatur wird ersetzt (--replace)", "--replace" in befehl)
check("weder Token noch Secret im Aufruf",
      not any(x.startswith("tok-") or SECRET in x for x in befehl))
check("ohne Zeitstempel kein --tsaurl", "--tsaurl" not in sig._jsign_befehl(kvd, SAND / "x.exe", ""))

# ── 5. Werkzeug ─────────────────────────────────────────────────────────────
print("\n=== 5. Werkzeug: Java und jsign (Inhalt, nicht Name) ===")
if not shutil.which("java"):
    abbruch("Java fehlt – der Signierweg ist hier nicht messbar.")
sig.JSIGN_JAR.parent.mkdir(parents=True, exist_ok=True)
sig.JSIGN_JAR.write_bytes(b"kein jsign")
check("eine falsche Datei unter dem richtigen Namen gilt NICHT", not sig.jsign_gueltig())
sig.JSIGN_JAR.unlink()
quelle = WURZEL / "vendor" / "jsign.jar"
if quelle.is_file() and hashlib.sha256(quelle.read_bytes()).hexdigest() == sig.JSIGN_SHA256:
    shutil.copyfile(quelle, sig.JSIGN_JAR)
else:
    grund = sig.jsign_bereitstellen()
    if grund:
        abbruch("jsign nicht verfuegbar (%s)" % grund)
check("jsign liegt bereit und hat die gepinnte Pruefsumme", sig.jsign_gueltig())

# Bezugsquelle aus der EINSTELLUNG (interner Spiegel)
JAR_BYTES[0] = sig.JSIGN_JAR.read_bytes()
sig.JSIGN_JAR.rename(SAND / "jsign.sicher")
_echt_url = sig.JSIGN_URL
sig.JSIGN_URL = "http://127.0.0.1:1/jsign.jar"   # Vorgabe ins Leere
try:
    d = sig._laden()
    d["kv"]["jsign_quelle"] = BASIS + "/falsch.jar"
    sig._speichern(d)
    grund = sig.jsign_bereitstellen()
    check("eingestellte Quelle mit falscher Datei: abgewiesen (Pruefsumme)",
          "Pruefsumme" in grund and not sig.JSIGN_JAR.exists())
    d = sig._laden()
    d["kv"]["jsign_quelle"] = BASIS + "/jsign.jar"
    sig._speichern(d)
    Azure.log.clear()
    grund = sig.jsign_bereitstellen()
    check("eingestellte Quelle mit echtem jsign: geladen und gueltig",
          grund == "" and sig.jsign_gueltig())
    check("…und zwar von der EINGESTELLTEN Quelle", ("GET", "/jsign.jar") in Azure.log)
finally:
    sig.JSIGN_URL = _echt_url
    if not sig.JSIGN_JAR.exists():
        (SAND / "jsign.sicher").rename(sig.JSIGN_JAR)
    d = sig._laden()
    d["kv"]["jsign_quelle"] = ""
    sig._speichern(d)

# ── 6. Signieren, Ende zu Ende ──────────────────────────────────────────────
print("\n=== 6. Signieren ueber den nachgebauten Vault (echtes jsign, echte PE) ===")
EXE = SAND / "AiMouse.exe"
EXE.write_bytes(pe_bauen())
check("Positivkontrolle: die PE-Datei ist vorher unsigniert", not sig.ist_signiert(EXE))
befehle = []
_echt_run = sig.subprocess.run


def _run_mitschnitt(b, **kw):
    befehle.append((list(b), dict(kw.get("env") or {})))
    return _echt_run(b, **kw)


sig.subprocess.run = _run_mitschnitt
Azure.log.clear()
try:
    ok, grund = sicher(sig.signieren, EXE) or (None, None)
finally:
    sig.subprocess.run = _echt_run
check("signieren(): Erfolg ohne Hinweis", ok is True and grund == "")
if ok is not True:
    print("       Grund: %s" % grund)
check("die Datei traegt eine Signatur (PE-Header)", sig.ist_signiert(EXE))
zs = signatur_zertifikate(EXE)
check("⚠ die Signatur stammt vom Zertifikat des Vaults",
      any(z.public_bytes(serialization.Encoding.DER)
          == ZERT.public_bytes(serialization.Encoding.DER) for z in zs))
check("der Vault hat signiert (RS256)", ("SIGN", "RS256") in Azure.log)
check("jsign wurde genau einmal aufgerufen", len(befehle) == 1)
if befehle:
    argv, env = befehle[0]
    check("das Token kam ueber die Umgebung", env.get(sig.KV_TOKEN_VAR, "").startswith("tok-"))
    check("⚠ und steht NICHT in der Befehlszeile",
          env.get(sig.KV_TOKEN_VAR, "x") not in " ".join(argv))
check("keine Zwischendatei bleibt liegen", not (SAND / "AiMouse.exe.signiert").exists())
check("der Zustand meldet: signiert, kein Fehler",
      sig.zustand().get("letzter_fehler") == "" and sig.zustand().get("verfahren") == "keyvault")

# Zeitstempel-Dienst tot: zweiter Versuch ohne, und das wird gesagt
EXE.write_bytes(pe_bauen())
d = sig._laden()
d["tsa"] = "http://127.0.0.1:1/tsa"
sig._speichern(d)
ok, grund = sicher(sig.signieren, EXE) or (None, None)
check("toter Zeitstempel-Dienst: trotzdem signiert", ok is True and sig.ist_signiert(EXE))
check("…und der Hinweis sagt OHNE Zeitstempel", isinstance(grund, str) and "OHNE Zeitstempel" in grund)
d = sig._laden()
d["tsa"] = ""
sig._speichern(d)

# ── 7. Fehlschlag beim Bau: Datei unveraendert, Grund laut ─────────────────
print("\n=== 7. Fail-open, aber laut ===")
EXE.write_bytes(pe_bauen())
roh = EXE.read_bytes()
Azure.modus = "firewall"
ok, grund = sicher(sig.signieren, EXE) or (None, None)
check("Firewall beim Bau: kein Erfolg, Grund nennt die Freigabe",
      ok is False and isinstance(grund, str) and "Netzwerk-Freigabe" in grund)
check("…die Datei ist unveraendert", EXE.read_bytes() == roh)
check("…und der Zustand traegt den Grund", "Netzwerk-Freigabe" in sig.zustand().get("letzter_fehler", ""))
Azure.modus = "abgelaufen"
sig.JSIGN_JAR.rename(SAND / "jsign.weg")
_echt_url = sig.JSIGN_URL
sig.JSIGN_URL = "http://127.0.0.1:1/jsign.jar"
try:
    ok, grund = sicher(sig.signieren, EXE) or (None, None)
    check("⚠ abgelaufenes Zertifikat wird VOR fehlendem Werkzeug gemeldet",
          ok is False and isinstance(grund, str) and "abgelaufen" in grund)
    Azure.modus = "normal"
    ok, grund = sicher(sig.signieren, EXE) or (None, None)
    check("jsign fehlt und ist nicht ladbar: Grund nennt jsign",
          ok is False and isinstance(grund, str) and "jsign" in grund)
finally:
    sig.JSIGN_URL = _echt_url
    (SAND / "jsign.weg").rename(sig.JSIGN_JAR)
check("…die Datei ist weiterhin unveraendert", EXE.read_bytes() == roh)
# Ein jsign-Fehler muss die AUSNAHME nennen, nicht das Ende des Stacktrace
# (erster Lauf dieses Waechters: nur „at …JsignCLI.main" kam an).
Azure.modus = "ohne_policy"
ok, grund = sicher(sig.signieren, EXE) or (None, None)
Azure.modus = "normal"
check("jsign-Fehler: der Grund nennt die Ausnahme",
      ok is False and isinstance(grund, str) and "NullPointerException" in grund)
check("…und keinen Stacktrace", isinstance(grund, str) and "JsignCLI.main" not in grund
      and "\tat " not in grund)

# ── 8. Wege umschalten ──────────────────────────────────────────────────────
print("\n=== 8. Wege: nur auf einen eingerichteten umschalten ===")
check("kein PFX: Umschalten auf PFX abgewiesen",
      isinstance(sicher(sig.verfahren_setzen, "pfx"), sig.SignaturFehler))
check("…der Key Vault bleibt wirksam", sig.verfahren() == "keyvault")
z = sicher(sig.keyvault_entfernen)
check("Key Vault entfernt: Weg PFX, nichts eingerichtet",
      isinstance(z, dict) and z.get("verfahren") == "pfx" and z.get("eingerichtet") is False)
check("…das Secret ist aus der Ablage verschwunden", b"secret_enc" not in stand())
check("ohne Zugang: Umschalten auf Key Vault abgewiesen",
      isinstance(sicher(sig.verfahren_setzen, "keyvault"), sig.SignaturFehler))
check("unbekannter Weg abgewiesen", isinstance(sicher(sig.verfahren_setzen, "x"), sig.SignaturFehler))

SRV.shutdown()
shutil.rmtree(SAND, ignore_errors=True)
print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
