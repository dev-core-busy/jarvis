#!/usr/bin/env python3
"""Waechter: BSI N1–N6 (Niedrig) aus dem BSI-Abgleich vom 2026-09-29.

  N1  ``/api/health`` gibt anonym nur ``{"status": "ok"}`` heraus; Details
      (Konfigurationsfehler, Auslastung, Dienste, Startzeit) nur einer
      Administrator-Sitzung. Der echte Endpunkt wird per AST geschnitten und
      ausgefuehrt; die Admin-Pruefung ist eine Attrappe mit echter Signatur.
  N2  Die Umleitung Port 80 → 443 nimmt das Ziel aus dem Serverzertifikat, nie
      aus dem Host-Kopf (``backend/http_umleitung.py`` gegen ein echtes, hier
      erzeugtes Zertifikat; der Handler laeuft ueber Starlette-Attrappen).
  N3  Ein 2FA-Code gilt EINMAL (``backend/totp_schutz.py``, echte Zeitschritte;
      pyotp, wenn installiert, sonst eine RFC-6238-Nachbildung mit derselben
      Signatur). Dazu die REGEL: in main.py prueft kein Weg mehr selbst per
      ``pyotp.TOTP(...).verify``.
  N4  Kennwortwechsel, 2FA-Abschaltung und 2FA-Neueinrichtung zaehlen
      Fehlversuche wie der Login und pruefen waehrend einer Sperre gar nicht
      erst (echte Endpunkte per AST, echter ``anmelde_schutz`` im Sandkasten).
  N5  Kein ``server: uvicorn``: jede Startstelle schaltet den Kopf ab.
  N6  Kein fester Benutzer-Schluesselpfad in einem versionierten Deploy-Skript.

``backend.config`` nur als Stub. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import base64
import contextvars
import datetime
import hashlib
import hmac
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool, detail: str = "") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)

TMP = Path(tempfile.mkdtemp(prefix="waechter-bsi-n-"))

# ── pyotp: echt, sonst Nachbildung nach RFC 6238 mit derselben Signatur ──────
try:
    import pyotp as _pyotp_echt  # noqa: F401
    PYOTP_ECHT = True
except ImportError:
    PYOTP_ECHT = False

    def _hotp(secret: str, zaehler: int) -> str:
        s = secret.upper() + "=" * (-len(secret) % 8)
        mac = hmac.new(base64.b32decode(s), struct.pack(">Q", zaehler), hashlib.sha1).digest()
        o = mac[-1] & 0x0F
        return "%06d" % ((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)

    class _TOTP:
        interval = 30

        def __init__(self, s, digits=6, digest=None, name=None, issuer=None, interval=30):
            self.secret, self.interval = s, interval

        def timecode(self, for_time: datetime.datetime) -> int:
            import calendar
            if for_time.tzinfo:
                return int(calendar.timegm(for_time.utctimetuple()) / self.interval)
            return int(time.mktime(for_time.timetuple()) / self.interval)

        def at(self, for_time, counter_offset: int = 0) -> str:
            if not isinstance(for_time, datetime.datetime):
                for_time = datetime.datetime.fromtimestamp(int(for_time))
            return _hotp(self.secret, self.timecode(for_time) + counter_offset)

        def verify(self, otp, for_time=None, valid_window: int = 0) -> bool:
            if for_time is None:
                for_time = datetime.datetime.now()
            if valid_window:
                return any(hmac.compare_digest(str(otp), self.at(for_time, i))
                           for i in range(-valid_window, valid_window + 1))
            return hmac.compare_digest(str(otp), self.at(for_time))

    _m = types.ModuleType("pyotp")
    _m.TOTP = _TOTP
    _m.random_base32 = lambda: "JBSWY3DPEHPK3PXP"
    sys.modules["pyotp"] = _m

import pyotp  # noqa: E402

from backend import anmelde_schutz as AS   # noqa: E402
from backend import totp_schutz as TS      # noqa: E402
from backend import http_umleitung as HU   # noqa: E402

AS.STORE_PATH = TMP / "anmelde_schutz.json"
TS.STORE_PATH = TMP / "totp_schritte.json"
for _p in (AS.STORE_PATH, TS.STORE_PATH):
    if not str(_p).startswith(str(TMP)):
        abbruch("Ablage zeigt aus dem Sandkasten heraus: %s" % _p)

MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN_SRC)


def _fn(name):
    fn = next((n for n in BAUM.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if fn is None:
        abbruch("%s nicht in main.py" % name)
    return fn


def _funktionen(*namen):
    teile = []
    for name in namen:
        fn = _fn(name)
        fn = ast.parse(ast.unparse(fn)).body[0]      # Kopie, BAUM bleibt unberuehrt
        fn.decorator_list = []
        for a in fn.args.args + fn.args.kwonlyargs:
            a.annotation = None
        fn.returns = None
        fn.args.defaults = [ast.Constant(None) for _ in fn.args.defaults]
        teile.append(fn)
    mod = ast.Module(body=teile, type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, "main.py<auszug>", "exec")


def _aufrufe(knoten, praedikat):
    return [k for k in ast.walk(knoten) if isinstance(k, ast.Call) and praedikat(ast.unparse(k.func))]


class _Antwort:
    def __init__(self, inhalt, status_code=200, headers=None):
        self.inhalt, self.status_code, self.headers = inhalt, status_code, headers or {}


class _HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class _Req:
    def __init__(self, body=None, token="", ip="198.51.100.1"):
        self._body = body or {}
        self.headers = {"user-agent": "Mozilla/5.0"}
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.client = types.SimpleNamespace(host=ip)
        self.scope = {}      # wie Starlette: ohne Cookie-Anmeldung (BSI H4) kein Merker

    async def json(self):
        return self._body


def _neu_schutz():
    for mod in (AS, TS):
        mod._zuruecksetzen_fuer_test()
        mod.STORE_PATH.unlink(missing_ok=True)
        mod._zuruecksetzen_fuer_test()


# ══ N1 ═══════════════════════════════════════════════════════════════════════
print("[N1] /api/health")
ADMIN_TOKEN = "admin-tok"
AUTH_GEFRAGT: list = []


async def _require_local_auth(request):
    tok = request.headers.get("Authorization", "").replace("Bearer ", "")
    AUTH_GEFRAGT.append(tok)
    if not tok:
        raise _HTTPException(401, "Nicht authentifiziert")
    if tok != ADMIN_TOKEN:
        raise _HTTPException(403, "Nur Administratoren")
    return "jarvis"


NS1 = {
    "JSONResponse": _Antwort, "HTTPException": _HTTPException, "Request": object,
    "require_local_auth": _require_local_auth, "asyncio": asyncio,
    "config": types.SimpleNamespace(validate=lambda: ["LLM-Schluessel fehlt"],
                                    active_profile={"api_key": "x"}),
    "psutil": types.SimpleNamespace(
        virtual_memory=lambda: types.SimpleNamespace(percent=41.0),
        disk_usage=lambda p: types.SimpleNamespace(percent=63.0)),
    "_wa_bridge_request_safe": lambda p: {"error": "nicht erreichbar"},
    "_cached_cpu_percent": 12.5, "_PROZESS_START": 1_700_000_000.0,
}


async def _keine_verbindung(*a, **k):
    raise OSError("kein VNC")

NS1["asyncio"] = types.SimpleNamespace(open_connection=_keine_verbindung,
                                       to_thread=asyncio.to_thread)
exec(_funktionen("health"), NS1)
health = NS1["health"]

r = asyncio.run(health(_Req(token=ADMIN_TOKEN)))
if not (r.status_code == 200 and "started_at" in r.inhalt):
    abbruch("Positivkontrolle: Admin bekommt die Details nicht (%s)" % (r.inhalt,))
check("Admin: Details mit started_at, Diensten, Auslastung",
      all(k in r.inhalt for k in ("started_at", "services", "cpu_percent", "memory_percent",
                                  "disk_percent", "errors")))
r = asyncio.run(health(_Req()))
check("anonym: genau {'status': 'ok'}", r.status_code == 200 and r.inhalt == {"status": "ok"},
      r.inhalt)
r = asyncio.run(health(_Req(token="nutzer-tok")))
check("angemeldet ohne Admin-Rechte: genau {'status': 'ok'}", r.inhalt == {"status": "ok"},
      r.inhalt)
check("die Admin-Pruefung lief bei jedem Abruf (3x)", len(AUTH_GEFRAGT) == 3, AUTH_GEFRAGT)
fh = _fn("health")
z_auth = min((k.lineno for k in _aufrufe(fh, lambda s: s == "require_local_auth")), default=None)
z_det = min((k.lineno for k in _aufrufe(fh, lambda s: s == "config.validate")), default=None)
check("Admin-Pruefung steht VOR dem ersten Detail-Abruf",
      z_auth is not None and z_det is not None and z_auth < z_det, (z_auth, z_det))

APP_JS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
m = re.search(r"const _health = async \(\) => \{(.*?)\n\s*\};", APP_JS, flags=re.S)
check("app.js: _health gefunden", m is not None)
if m:
    rumpf = re.sub(r"//[^\n]*", "", m.group(1))
    check("app.js: 'Dienst neu starten' schickt das Token an /api/health",
          "/api/health" in rumpf and re.search(r"Authorization['\"]?\s*:\s*`Bearer \$\{token\}`",
                                                rumpf) is not None, rumpf)

# ══ N2 ═══════════════════════════════════════════════════════════════════════
print("\n[N2] Umleitung Port 80")
CERT = TMP / "server.crt"
try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress as _ip
    schl = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "jarvis.beispiel.de")])
    jetzt_dt = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(schl.public_key()).serial_number(1)
            .not_valid_before(jetzt_dt).not_valid_after(jetzt_dt + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("jarvis.beispiel.de"), x509.DNSName("*.beispiel.de"),
                x509.DNSName("jarvis"), x509.IPAddress(_ip.ip_address("192.0.2.10"))]),
                critical=False)
            .sign(schl, hashes.SHA256()))
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
except Exception as e:  # noqa: BLE001
    abbruch("Testzertifikat nicht erzeugbar: %s" % e)

NAMEN = HU.zertifikat_namen(CERT)
if "jarvis.beispiel.de" not in NAMEN:
    abbruch("Positivkontrolle: Namen aus dem Zertifikat nicht gelesen (%s)" % NAMEN)
check("Namen aus dem SAN, DNS zuerst, Platzhalter ausgelassen",
      NAMEN == ["jarvis.beispiel.de", "jarvis", "192.0.2.10"], NAMEN)
check("fehlende Datei: keine Namen", HU.zertifikat_namen(TMP / "gibtsnicht.crt") == [])
check("fremder Host-Kopf → erster Zertifikatsname",
      HU.ziel_url("boese.example", "/login", "a=1", NAMEN)
      == "https://jarvis.beispiel.de/login?a=1")
check("fremder Host-Kopf mit Port → erster Zertifikatsname",
      HU.ziel_url("boese.example:80", "/", "", NAMEN) == "https://jarvis.beispiel.de/")
check("Name aus dem Zertifikat bleibt erhalten (Kurzname)",
      HU.ziel_url("JARVIS:80", "/x", "", NAMEN) == "https://jarvis/x")
check("IP aus dem Zertifikat bleibt erhalten",
      HU.ziel_url("192.0.2.10", "/", "", NAMEN) == "https://192.0.2.10/")
check("Unterdomaene, die nur der Platzhalter trifft, wird NICHT uebernommen",
      HU.ziel_url("evil.beispiel.de", "/", "", NAMEN) == "https://jarvis.beispiel.de/")
check("Host-Kopf mit @/Pfad-Tricks landet nie im Ziel",
      all(HU.ziel_url(h, "/", "", NAMEN).startswith("https://jarvis.beispiel.de/")
          for h in ("jarvis.beispiel.de@boese.example", "boese.example/jarvis.beispiel.de",
                    "boese.example#", "")))
check("'//' am Pfadanfang wird zu EINEM Schraegstrich",
      HU.ziel_url("x", "//boese.example/a", "", NAMEN) == "https://jarvis.beispiel.de/boese.example/a")
check("abweichender HTTPS-Port wird angehaengt",
      HU.ziel_url("x", "/", "", NAMEN, 8443) == "https://jarvis.beispiel.de:8443/")
check("ohne Zertifikatsnamen: kein Ziel (fail-closed)", HU.ziel_url("x", "/", "", []) is None)

# ── Rueckfall nur auf einen Namen, der beim Client ankommen kann ────────────
# VORFALL 2026-10-13 (DEV): `namen[0]` war der ERSTE Name des Zertifikats, und
# bei einer selbstsignierten Installation ist das der blanke Rechnername –
# `_collect_server_names()` beginnt mit ["jarvis", "jarvis.local", "localhost"].
# Gemessen: http://<dev-ip>/chat -> https://jarvis/chat, ein Ziel, das
# ausserhalb des Servers niemand aufloest. Der Waechter konnte das nicht sehen,
# weil SEIN Testzertifikat den punktierten Namen zuerst traegt (oben) – das
# Material war getippt, nicht vom Erzeuger.
from backend import security as _secmod                                  # noqa: E402
_ERZ = _secmod._collect_server_names()
# Drift-Schranke: das Material unten nimmt den KONSTANTEN Anfang dieser Liste.
# Aendert der Erzeuger ihn, soll das hier auffallen und nicht still veralten.
if _ERZ[:3] != ["jarvis", "jarvis.local", "localhost"]:
    abbruch("_collect_server_names() beginnt nicht mehr mit "
            "['jarvis','jarvis.local','localhost'] sondern %r" % (_ERZ[:3],))
check("Erzeuger beginnt mit Namen, die als Rueckfall nichts taugen",
      not any(HU.taugt_als_rueckfall(n) for n in _ERZ[:3]), _ERZ[:3])

check("einteiliger Rechnername taugt nicht als Rueckfall",
      HU.taugt_als_rueckfall("jarvis") is False)
check("localhost taugt nicht", HU.taugt_als_rueckfall("localhost") is False)
check("127.0.0.1 / ::1 / 0.0.0.0 taugen nicht",
      not any(HU.taugt_als_rueckfall(n) for n in ("127.0.0.1", "::1", "0.0.0.0")))
check("mDNS-Name (.local, RFC 6762) taugt nicht",
      HU.taugt_als_rueckfall("jarvis.local") is False)
check("punktierter DNS-Name taugt", HU.taugt_als_rueckfall("dp.beispiel.de") is True)
check("oeffentlich routbare IP taugt", HU.taugt_als_rueckfall("192.0.2.77") is True)

# Zertifikat in der Reihenfolge, die real entsteht: die drei unbrauchbaren
# Namen des Erzeugers zuerst, dann ein brauchbarer.
CERT2 = TMP / "server_erzeuger.crt"
try:
    name2 = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _ERZ[0])])
    cert2 = (x509.CertificateBuilder().subject_name(name2).issuer_name(name2)
             .public_key(schl.public_key()).serial_number(2)
             .not_valid_before(jetzt_dt)
             .not_valid_after(jetzt_dt + datetime.timedelta(days=1))
             .add_extension(x509.SubjectAlternativeName(
                 [x509.DNSName(n) for n in _ERZ[:3]]
                 + [x509.DNSName("dp.beispiel.de"),
                    x509.IPAddress(_ip.ip_address("192.0.2.77"))]), critical=False)
             .sign(schl, hashes.SHA256()))
    CERT2.write_bytes(cert2.public_bytes(serialization.Encoding.PEM))
except Exception as e:  # noqa: BLE001
    abbruch("Testzertifikat (Erzeuger-Reihenfolge) nicht erzeugbar: %s" % e)
NAMEN2 = HU.zertifikat_namen(CERT2)
# Positivkontrollen VOR den inhaltlichen Pruefungen: gelesen UND der Fehlerfall
# ist ueberhaupt hergestellt. Ohne die zweite waere alles Folgende trivial.
if "dp.beispiel.de" not in NAMEN2:
    abbruch("Positivkontrolle: Namen aus CERT2 nicht gelesen (%s)" % NAMEN2)
# Die zweite Kontrolle ist eine Eigenschaft des MATERIALS, nicht der gepruefen
# Funktion: der erste Name muss der einteilige Rechnername sein. Sie darf NICHT
# ueber taugt_als_rueckfall entschieden werden – sonst macht eine sabotierte
# Funktion aus einem Biss ein "konnte nicht laufen" (Register: eine Sabotage,
# die den Waechter abstuerzen laesst, hat nicht gebissen). In der Gegenprobe
# genau so passiert, bevor diese Zeile so aussah.
if NAMEN2[0] != _ERZ[0]:
    abbruch("Positivkontrolle: CERT2 stellt den Fehlerfall nicht her – erster "
            "Name ist %r, erwartet war der Rechnername %r"
            % (NAMEN2[0], _ERZ[0]))
check("Rueckfall ueberspringt Rechnername, .local und localhost",
      HU.ziel_url("fremd.example", "/chat", "", NAMEN2) == "https://dp.beispiel.de/chat",
      HU.ziel_url("fremd.example", "/chat", "", NAMEN2))
check("gewuenschter einteiliger Name bleibt trotzdem erhalten",
      HU.ziel_url("jarvis", "/chat", "", NAMEN2) == "https://jarvis/chat")
check("gewuenschtes localhost bleibt erhalten (lokaler Aufruf)",
      HU.ziel_url("localhost", "/", "", NAMEN2) == "https://localhost/")
check("taugt nur Unbrauchbares: KEINE Umleitung statt Sprung ins Leere",
      HU.ziel_url("fremd.example", "/", "", ["jarvis", "jarvis.local", "localhost",
                                             "127.0.0.1"]) is None)
check("IP als einziger brauchbarer Name wird genommen",
      HU.ziel_url("fremd.example", "/", "", ["jarvis", "192.0.2.77"])
      == "https://192.0.2.77/")

# ── Deckt das Zertifikat ueberhaupt die eigene Adresse? ────────────────────
# Dieselbe Wurzel wie oben: auf DEV nannte das Zertifikat vom 20.02.2026 eine
# Adresse, die der Rechner seit Monaten nicht mehr hatte (DHCP). Weil
# ensure_certificates ein bestehendes Zertifikat bewusst NIE neu erzeugt, war
# die Abweichung dauerhaft - und nichts sah nach. Jetzt meldet der Startpfad sie.
_SEC_SRC = (ROOT / "backend" / "security.py").read_text(encoding="utf-8")
# Eigene Namen: `_fn` ist in dieser Datei schon eine FUNKTION (Zeile 131) und
# wird weiter unten gebraucht. Eine Modulvariable, die einen vorhandenen Namen
# ueberschreibt, laesst einen spaeteren Abschnitt mit TypeError sterben - beim
# ersten Lauf genau so passiert (Register: geteilte Namen pruefen).
_sec_baum = ast.parse(_SEC_SRC)
_sec_fn = {n.name: n for n in _sec_baum.body if isinstance(n, ast.FunctionDef)}
check("security._lokale_adressen existiert", "_lokale_adressen" in _sec_fn)
check("security.zertifikat_adress_warnung existiert",
      "zertifikat_adress_warnung" in _sec_fn)
if "_lokale_adressen" not in _sec_fn or "ensure_certificates" not in _sec_fn:
    abbruch("security.py hat die erwarteten Funktionen nicht - die folgenden "
            "Pruefungen waeren trivial")


def _text_konstanten(knoten):
    """Zeichenketten-Konstanten einer Funktion, OHNE ihren Docstring.

    Gemessen wird am Syntaxbaum, nicht am unparsten Text - zwei Gruende, beide
    bezahlt:

    * ``ast.unparse`` schreibt eine Liste als ``['ip', 'route']``. Eine Suche
      nach ``"ip route"`` kann dort NIE etwas finden: die Phrase geht ueber zwei
      Listenelemente. Die erste Fassung dieser Pruefung war genau so blind - die
      Gegenprobe "Gateway wieder mit" meldete 0 FAIL und hat es gezeigt.
    * Der Docstring von ``_lokale_adressen`` NENNT ifconfig.me und ipify als
      das, was dort bewusst nicht passiert. Wer ihn mitliest, prueft die
      Begruendung statt des Codes (Register).
    """
    # ast.get_docstring WIRFT fuer alles, was keinen Docstring tragen kann
    # (z. B. einen Call). Ein Pruefwerkzeug, das wirft statt fehlzuschlagen,
    # nimmt den ganzen Waechter mit - genau so passiert, als diese Funktion
    # zum Zaehlen der print-Texte benutzt wurde.
    doc = None
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef, ast.Module)):
        doc = ast.get_docstring(knoten, clean=False)
    return {s.value for s in ast.walk(knoten)
            if isinstance(s, ast.Constant) and isinstance(s.value, str)
            and s.value != doc}


_EXTERN = ("ifconfig.me", "ipify", "amazonaws", "checkip", "curl")
_la_texte = _text_konstanten(_sec_fn["_lokale_adressen"])
# Positivkontrolle der MESSMETHODE: dieselbe Regel auf eine Funktion angewandt,
# die den Abruf nachweislich macht, muss zuschlagen. Sonst ist die Pruefung
# unten trivial wahr - ein blindes Muster saehe wie Entwarnung aus.
if "_collect_server_ips" in _sec_fn:
    _ref = _text_konstanten(_sec_fn["_collect_server_ips"])
    if not any(w in t for t in _ref for w in _EXTERN):
        abbruch("Positivkontrolle: die Regel findet den externen Abruf in "
                "_collect_server_ips nicht - das Muster ist blind")
    check("Positivkontrolle: die Regel erkennt den externen Abruf im Altbestand",
          any(w in t for t in _ref for w in _EXTERN))
    check("Positivkontrolle: die Regel erkennt die Routing-Abfrage im Altbestand",
          "route" in _ref)
# REGEL, nicht Messung: die Funktion laeuft bei JEDEM Start. Ein Netzzugriff
# nach draussen gehoert dort nicht hin (_collect_server_ips Schritt 5 ruft
# ifconfig.me/ipify/amazonaws - deshalb wird sie hier NICHT benutzt).
check("Adress-Ermittlung ohne externen Abruf",
      not any(w in t for t in _la_texte for w in _EXTERN), sorted(_la_texte))
# Und ohne das Standard-Gateway: das ist nicht die Adresse DIESES Rechners -
# genau so ein Fremdwert steckte im DEV-Zertifikat.
check("Adress-Ermittlung liest die Routing-Tabelle nicht (kein Gateway)",
      "route" not in _la_texte and "default" not in _la_texte, sorted(_la_texte))

# Drei Lagen, alle am 2026-10-13 an echten Servern GEMESSEN - das Material ist
# nicht erfunden, sondern die Gestalt der drei Zertifikate, die es wirklich gab:
#   (1) ALT-DEV   : SAN = jarvis, jarvis.local, localhost + eine FREMDE IP
#                   -> keine eigene Adresse, kein aufloesbarer Name -> WARNUNG
#   (2) NEU-DEV   : die eigene Adresse steht im SAN                  -> still
#   (3) ECHT      : CA-Zertifikat auf zwei FQDNs, GAR KEINE IP       -> still
# (3) ist der Grund, warum nicht jede fehlende IP gemeldet werden darf: die
# erste Fassung haette auf dem Produktionsserver bei jedem Start angeschlagen.
_ZERT_CERTS = {}
for _nm, _san in (("alt_dev", ["jarvis", "jarvis.local", "localhost", "192.0.2.1"]),
                  ("neu_dev", ["jarvis", "jarvis.local", "localhost", "192.0.2.77"]),
                  ("echt", ["dp.beispiel.de", "dp2.beispiel.de"])):
    try:
        _n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis CA")])
        _eintraege = []
        for _s in _san:
            try:
                _eintraege.append(x509.IPAddress(_ip.ip_address(_s)))
            except ValueError:
                _eintraege.append(x509.DNSName(_s))
        _c = (x509.CertificateBuilder().subject_name(_n).issuer_name(_n)
              .public_key(schl.public_key()).serial_number(10)
              .not_valid_before(jetzt_dt)
              .not_valid_after(jetzt_dt + datetime.timedelta(days=1))
              .add_extension(x509.SubjectAlternativeName(_eintraege), critical=False)
              .sign(schl, hashes.SHA256()))
        _p = TMP / ("zert_%s.crt" % _nm)
        _p.write_bytes(_c.public_bytes(serialization.Encoding.PEM))
        _ZERT_CERTS[_nm] = _p
    except Exception as e:  # noqa: BLE001
        abbruch("Testzertifikat %s nicht erzeugbar: %s" % (_nm, e))

from backend import security as _sec2                                    # noqa: E402
_sec_cert_vorher, _sec_la_vorher = _sec2.CERT_FILE, _sec2._lokale_adressen
try:
    # Die eigene Adresse ist in allen drei Lagen dieselbe: 192.0.2.77.
    _sec2._lokale_adressen = lambda: ["192.0.2.77"]
    _sec2.CERT_FILE = _ZERT_CERTS["alt_dev"]
    _w_alt = _sec2.zertifikat_adress_warnung()
    check("(1) veraltetes Zertifikat wird gemeldet", bool(_w_alt), _w_alt)
    check("(1) die Meldung nennt die eigene Adresse", "192.0.2.77" in _w_alt)
    _sec2.CERT_FILE = _ZERT_CERTS["neu_dev"]
    check("(2) eigene Adresse im SAN: still",
          _sec2.zertifikat_adress_warnung() == "",
          _sec2.zertifikat_adress_warnung())
    _sec2.CERT_FILE = _ZERT_CERTS["echt"]
    check("(3) CA-Zertifikat auf FQDNs ohne jede IP: still (kein Laerm auf ECHT)",
          _sec2.zertifikat_adress_warnung() == "",
          _sec2.zertifikat_adress_warnung())
    # Eine FREMDE IP im SAN rettet nichts - sie gehoert mir ja nicht. Gemessen
    # an einem Zertifikat, dessen SAN AUSSCHLIESSLICH so eine IP traegt: ohne
    # diese Unterscheidung waere (1) still, denn 192.0.2.1 ist routbar.
    _nur_fremde_ip = TMP / "zert_nur_fremde_ip.crt"
    _n2 = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis CA")])
    _c2 = (x509.CertificateBuilder().subject_name(_n2).issuer_name(_n2)
           .public_key(schl.public_key()).serial_number(11)
           .not_valid_before(jetzt_dt)
           .not_valid_after(jetzt_dt + datetime.timedelta(days=1))
           .add_extension(x509.SubjectAlternativeName(
               [x509.IPAddress(_ip.ip_address("192.0.2.1"))]), critical=False)
           .sign(schl, hashes.SHA256()))
    _nur_fremde_ip.write_bytes(_c2.public_bytes(serialization.Encoding.PEM))
    _sec2.CERT_FILE = _nur_fremde_ip
    check("nur eine fremde (routbare) IP im SAN: wird gemeldet",
          bool(_sec2.zertifikat_adress_warnung()),
          _sec2.zertifikat_adress_warnung())
    # Ohne lesbare Namen wird NICHTS behauptet - sonst meldete jeder Server mit
    # TLS-Terminierung im Rueckwaertsproxy dauerhaft einen Fehler, den es nicht
    # gibt (gleiche Haltung wie addin.zert_namen).
    _sec2.CERT_FILE = TMP / "gibtsnicht.crt"
    check("ohne lesbares Zertifikat: keine Behauptung",
          _sec2.zertifikat_adress_warnung() == "")
finally:
    _sec2.CERT_FILE, _sec2._lokale_adressen = _sec_cert_vorher, _sec_la_vorher
check("security-Modulzustand ist zurueckgestellt",
      _sec2.CERT_FILE is _sec_cert_vorher
      and _sec2._lokale_adressen is _sec_la_vorher)
# Die Meldung muss im Pfad fuer das BESTEHENDE Zertifikat stehen - im
# Erzeugungszweig waere sie wirkungslos (dort passt das Zertifikat gerade).
#
# ⚠ GEMESSEN WIRD EIN ECHTER ast.Call, NICHT DAS VORKOMMEN DES NAMENS. Die erste
# Fassung las den unparsten Quelltext - und der Docstring von
# ensure_certificates NENNT zertifikat_fehlende_adressen. Die Pruefung war damit
# trivial wahr: die Gegenprobe "Startpfad meldet die Abweichung nicht mehr"
# meldete 0 FAIL, obwohl der Aufruf durch `fehlt = []` ersetzt war.
_ec = _sec_fn["ensure_certificates"]
_bestand = next((n for n in _ec.body if isinstance(n, ast.If)), None)
if _bestand is None:
    abbruch("ensure_certificates hat keinen Bestands-Zweig mehr")
# Positivkontrolle: ist das wirklich der Zweig fuer ein VORHANDENES Zertifikat?
_bed = ast.unparse(_bestand.test)
if "CERT_FILE" not in _bed or "KEY_FILE" not in _bed:
    abbruch("der erste if-Zweig ist nicht der Bestands-Zweig, sondern %r" % _bed)
check("Positivkontrolle: Bestands-Zweig an CERT_FILE/KEY_FILE erkannt", True)
_rufe = [k for k in ast.walk(_bestand) if isinstance(k, ast.Call)
         and ast.unparse(k.func).endswith("zertifikat_adress_warnung")]
check("Bestands-Zweig ruft zertifikat_adress_warnung wirklich auf",
      len(_rufe) == 1, "%d Aufrufe" % len(_rufe))
# Und die Meldung muss den naechsten Schritt nennen, nicht nur den Zustand.
_prints = " ".join(t for k in ast.walk(_bestand) if isinstance(k, ast.Call)
                   and ast.unparse(k.func) == "print"
                   for t in _text_konstanten(k))
check("die Meldung nennt die Abhilfe", "Abhilfe" in _prints)

# Handler ueber Starlette-Attrappen (echte Signaturen, nur das Noetige)
_st = {n: types.ModuleType(n) for n in ("starlette", "starlette.applications",
                                         "starlette.responses", "starlette.routing")}


class _Route:
    def __init__(self, path, endpoint, **kw):
        self.path, self.endpoint = path, endpoint


class _Starlette:
    def __init__(self, routes=None, **kw):
        self.routes = routes or []


class _Redirect:
    def __init__(self, url, status_code=307, headers=None):
        self.url, self.status_code = url, status_code


class _Text:
    def __init__(self, content, status_code=200, **kw):
        self.content, self.status_code = content, status_code


_st["starlette.applications"].Starlette = _Starlette
_st["starlette.responses"].RedirectResponse = _Redirect
_st["starlette.responses"].PlainTextResponse = _Text
_st["starlette.routing"].Route = _Route
_alt = {n: sys.modules.get(n) for n in _st}
sys.modules.update(_st)
try:
    app = HU.app_erstellen(CERT, 443)
    ohne = HU.app_erstellen(TMP / "fehlt.crt", 443)
finally:
    for n, v in _alt.items():
        if v is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = v


def _anfrage(host, pfad="/", query=""):
    return types.SimpleNamespace(headers={"host": host},
                                 url=types.SimpleNamespace(path=pfad, query=query))


ep = app.routes[0].endpoint if app.routes else None
if ep is None:
    abbruch("app_erstellen liefert keine Route")
r = asyncio.run(ep(_anfrage("boese.example", "/portal", "x=1")))
check("Handler: fremder Host → 301 auf den Zertifikatsnamen",
      isinstance(r, _Redirect) and r.status_code == 301
      and r.url == "https://jarvis.beispiel.de/portal?x=1", getattr(r, "url", r))
r = asyncio.run(ohne.routes[0].endpoint(_anfrage("boese.example")))
check("Handler ohne lesbares Zertifikat: keine Umleitung (400)",
      isinstance(r, _Text) and r.status_code == 400, r)

fr = _fn("_start_http_redirect")
check("main: Umleitung kommt aus http_umleitung.app_erstellen",
      len(_aufrufe(fr, lambda s: s.endswith("app_erstellen"))) == 1)
check("main: der Umleitungs-Server liest request.url nicht mehr selbst",
      "request.url" not in ast.unparse(fr))

# ══ N3 ═══════════════════════════════════════════════════════════════════════
print("\n[N3] 2FA-Code nur einmal (%s)" % ("pyotp" if PYOTP_ECHT else "RFC-6238-Nachbildung"))
_neu_schutz()
GEHEIM = "JBSWY3DPEHPK3PXP"
T = pyotp.TOTP(GEHEIM)
T0 = 1_800_000_015.0                     # mitten in einem Zeitschritt
code_jetzt = T.at(int(T0))
code_vorher = T.at(int(T0) - 30)
code_danach = T.at(int(T0) + 30)
if code_jetzt == code_vorher or code_jetzt == code_danach:
    abbruch("Testzeitpunkt ungeeignet: zwei Schritte mit demselben Code")
if TS.pruefen("anna", GEHEIM, code_jetzt, jetzt=T0) != TS.OK:
    abbruch("Positivkontrolle: gueltiger Code wird nicht angenommen")
check("derselbe Code ein zweites Mal: SCHON_BENUTZT",
      TS.pruefen("anna", GEHEIM, code_jetzt, jetzt=T0 + 5) == TS.SCHON_BENUTZT)
check("…auch noch im Folgeschritt (Fenster 1)",
      TS.pruefen("anna", GEHEIM, code_jetzt, jetzt=T0 + 30) == TS.SCHON_BENUTZT)
check("der Code des VORschritts nach dem aktuellen: SCHON_BENUTZT",
      TS.pruefen("anna", GEHEIM, code_vorher, jetzt=T0 + 6) == TS.SCHON_BENUTZT)
check("der naechste Code: OK", TS.pruefen("anna", GEHEIM, code_danach, jetzt=T0 + 30) == TS.OK)
check("falscher Code: FALSCH", TS.pruefen("anna", GEHEIM, "000000"
                                          if code_danach != "000000" else "111111",
                                          jetzt=T0 + 31) == TS.FALSCH)
check("Code ausserhalb des Fensters: FALSCH",
      TS.pruefen("bert", GEHEIM, T.at(int(T0) - 120), jetzt=T0) == TS.FALSCH)
check("anderes Konto: eigener Merker", TS.pruefen("bert", GEHEIM, code_jetzt, jetzt=T0) == TS.OK)
check("ein FALSCHER Versuch verbraucht nichts",
      TS.pruefen("carl", GEHEIM, "123", jetzt=T0) == TS.FALSCH
      and TS.pruefen("carl", GEHEIM, code_jetzt, jetzt=T0) == TS.OK)
check("Leerzeichen im Code stoeren nicht",
      TS.pruefen("dora", GEHEIM, code_jetzt[:3] + " " + code_jetzt[3:], jetzt=T0) == TS.OK)
check("Ablage nicht weltlesbar",
      TS.STORE_PATH.exists() and (TS.STORE_PATH.stat().st_mode & 0o007) == 0)
TS._zuruecksetzen_fuer_test()            # "Neustart": Speicher leer, Datei bleibt
check("Sperre ueberlebt einen Neustart",
      TS.pruefen("anna", GEHEIM, code_danach, jetzt=T0 + 31) == TS.SCHON_BENUTZT)
check("Merker eines Tages verfallen (keine endlose Datei)",
      TS.pruefen("zoe", GEHEIM, T.at(int(T0) + 2 * 86400), jetzt=T0 + 2 * 86400) == TS.OK
      and not any(k.startswith("anna|") for k in json.loads(TS.STORE_PATH.read_text())))
check("das Secret selbst steht nie in der Ablage", GEHEIM not in TS.STORE_PATH.read_text())
_neu_schutz()
GEHEIM2 = "KRUGS4ZANFZSAYJA"
TS.pruefen("gina", GEHEIM, code_jetzt, jetzt=T0)
check("neues Secret desselben Kontos im selben Zeitschritt: OK (keine Wiederholung)",
      TS.pruefen("gina", GEHEIM2, pyotp.TOTP(GEHEIM2).at(int(T0)), jetzt=T0) == TS.OK)
check("…das alte Secret bleibt dabei gesperrt",
      TS.pruefen("gina", GEHEIM, code_jetzt, jetzt=T0) == TS.SCHON_BENUTZT)
_neu_schutz()
ergebnisse: list = []
sperre = threading.Barrier(12)


def _gleichzeitig():
    sperre.wait()
    ergebnisse.append(TS.pruefen("eva", GEHEIM, code_jetzt, jetzt=T0))

faeden = [threading.Thread(target=_gleichzeitig) for _ in range(12)]
for f in faeden:
    f.start()
for f in faeden:
    f.join()
check("12 gleichzeitige Anfragen mit demselben Code: genau EINE kommt durch",
      ergebnisse.count(TS.OK) == 1 and ergebnisse.count(TS.SCHON_BENUTZT) == 11, ergebnisse)
_neu_schutz()
check("ohne Zeitangabe (echte Uhr): aktueller Code OK, dann verbraucht",
      TS.pruefen("fritz", GEHEIM, T.at(int(time.time()))) == TS.OK
      and TS.pruefen("fritz", GEHEIM, T.at(int(time.time()))) == TS.SCHON_BENUTZT)

# REGEL: kein eigener pyotp-Pruefweg mehr in main.py
totp_konstrukte = []
for fn in ast.walk(BAUM):
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for k in _aufrufe(fn, lambda s: s == "pyotp.TOTP"):
            totp_konstrukte.append(fn.name)
# Seit 2026-10-30 baut _totp_qr_daten den QR fuer Einrichten UND erneutes Anzeigen.
check("REGEL: pyotp.TOTP(...) in main.py nur noch fuer den QR-Code (_totp_qr_daten)",
      set(totp_konstrukte) == {"_totp_qr_daten"}, totp_konstrukte)
check("REGEL: kein .verify(...) auf einem TOTP in main.py",
      not [k for k in ast.walk(BAUM) if isinstance(k, ast.Call)
           and isinstance(k.func, ast.Attribute) and k.func.attr == "verify"
           and "totp" in ast.unparse(k.func.value).lower()])
for name, n_min in (("_login_ablauf", 2), ("totp_verify", 1), ("geheimnis_bestaetigen", 1)):
    n = len(_aufrufe(_fn(name), lambda s: s == "_totp_schutz.pruefen"))
    check("%s prueft ueber _totp_schutz.pruefen (%dx)" % (name, n_min), n == n_min, n)

# ══ N4 ═══════════════════════════════════════════════════════════════════════
print("\n[N4] Grenze an Kennwortwechsel und 2FA-Abschaltung")
AUTH_AUFRUFE: list = []
STATE: dict = {}
LOG: list = []


def _auth(u, pw, details=None):
    AUTH_AUFRUFE.append(u)
    return pw == "richtig"


def _get_state(u):
    return dict(STATE.get(u, {"must_change_password": False, "totp_enabled": False,
                              "totp_secret": None}))


def _set_state(u, upd):
    STATE.setdefault(u, {"must_change_password": False, "totp_enabled": False,
                         "totp_secret": None}).update(upd)


NS4 = {
    "JSONResponse": _Antwort, "HTTPException": _HTTPException, "Request": object,
    "asyncio": asyncio, "hashlib": hashlib, "json": json,
    "config": types.SimpleNamespace(get_setting=lambda k, d=None: d),
    "_anmelde_schutz": AS, "_totp_schutz": TS,
    "_sicherheits_log": types.SimpleNamespace(ereignis=lambda *a, **k: LOG.append((a, k))),
    "_norm_login": lambda n: (n or "").split("@")[0].split("\\")[-1].strip().lower(),
    "authenticate_linux_user": _auth,
    "_get_user_auth_state": _get_state, "_set_user_auth_state": _set_state,
    "_sitzung_kontext": contextvars.ContextVar("_sk", default=None),
    "_is_admin_user": lambda u: False, "_admin_2fa_pflicht": lambda: True,
    "_validate_password_strength": lambda pw, u: [],
    "_DOCKER_MODE": True,
    "_load_auth_state": lambda: {}, "_save_auth_state": lambda s: None,
    "_sitzungen_nach_kennwortwechsel": lambda u, r=None: "neues-token",
    "_totp_vormerken": lambda u: {"secret": "S", "qr_code": "q", "uri": "u"},
    # BSI H4: Token-Antworten laufen ueber _sitzung_antwort – mit dem ECHTEN Modul
    "_sitzung_cookie": __import__("backend.sitzung_cookie", fromlist=["x"]),
    # Docker-Kennwortwechsel hasht ueber main._standard_zugang (Modul-Import in main.py)
    # – das ECHTE Modul, keine Attrappe: es hat keine Abhaengigkeiten auf Modulebene
    "_standard_zugang": __import__("backend.standard_zugang", fromlist=["x"]),
}
exec(_funktionen("_check_rate_limit", "_record_login_attempt", "_konto_sperre_antwort",
                 "_kennwort_schranke", "_kennwort_fehlversuch", "_sitzung_antwort",
                 "change_password", "totp_disable", "totp_setup",
                 "_sitzung_ist_app", "_totp_app_sperre"), NS4)


def _rufe(name, body, user="bert", ip="198.51.100.1"):
    return contextvars.copy_context().run(
        lambda: asyncio.run(NS4[name](_Req(body, ip=ip), user)))


WEGE = (
    ("change_password", lambda pw: {"old_password": pw, "new_password": "Neu-Kennwort-1",
                                    "confirm_password": "Neu-Kennwort-1"}, lambda r: r.inhalt.get("success")),
    ("totp_disable", lambda pw: {"password": pw}, lambda r: r.inhalt.get("success")),
    ("totp_setup", lambda pw: {"password": pw}, lambda r: bool(r.inhalt.get("secret"))),
)
for name, body, erfolg in WEGE:
    _neu_schutz()
    STATE.clear()
    if name == "totp_setup":
        _set_state("bert", {"totp_enabled": True, "totp_secret": GEHEIM})
    r = _rufe(name, body("richtig"))
    if not (r.status_code == 200 and erfolg(r)):
        abbruch("Positivkontrolle %s: richtiges Kennwort kommt nicht durch (%s %s)"
                % (name, r.status_code, r.inhalt))
    _neu_schutz()
    if name == "totp_setup":
        _set_state("bert", {"totp_enabled": True, "totp_secret": GEHEIM})
    for i in range(AS.KONTO_MAX):
        _rufe(name, body("falsch"), ip="203.0.113.%d" % i)
    AUTH_AUFRUFE.clear()
    r = _rufe(name, body("richtig"), ip="203.0.113.200")
    check("%s: nach KONTO_MAX falschen Kennwoertern (wechselnde IPs) 429" % name,
          r.status_code == 429, (r.status_code, r.inhalt))
    check("%s: …und das Kennwort geht waehrend der Sperre nicht an PAM/AD" % name,
          AUTH_AUFRUFE == [], AUTH_AUFRUFE)
    check("%s: …die Sperre ist die Konto-Sperre des Logins" % name,
          AS.konto_wartezeit("bert") > 0)
    check("%s: Fehlversuch steht im Sicherheitsprotokoll" % name,
          any(a and a[0] == "kennwort_pruefung" for a, k in LOG))
    _neu_schutz()
    if name == "totp_setup":             # Kennwort wird nur bei aktiver 2FA verlangt
        for u in ["konto%d" % i for i in range(AS.IP_MAX)] + ["neu"]:
            _set_state(u, {"totp_enabled": True, "totp_secret": GEHEIM})
    for i in range(AS.IP_MAX):
        _rufe(name, body("falsch"), user="konto%d" % i, ip="192.0.2.77")
    AUTH_AUFRUFE.clear()
    r = _rufe(name, body("richtig"), user="neu", ip="192.0.2.77")
    check("%s: IP-Grenze wie beim Login (429, kein Kennwortabgleich)" % name,
          r.status_code == 429 and AUTH_AUFRUFE == [], (r.status_code, AUTH_AUFRUFE))
    _neu_schutz()
    for i in range(AS.KONTO_MAX - 1):
        _rufe(name, body("falsch"), ip="203.0.113.%d" % i)
    _rufe(name, body("richtig"), ip="203.0.113.50")
    check("%s: Erfolg setzt den Konto-Zaehler zurueck" % name,
          "bert" not in (json.loads(AS.STORE_PATH.read_text()).get("konto") or {})
          if AS.STORE_PATH.exists() else True)

# ══ N5 ═══════════════════════════════════════════════════════════════════════
print("\n[N5] kein Server-Banner")


def _befehl(datei, anfang):
    """Die zusammengesetzte Befehlszeile ab ``anfang`` (Fortsetzungen per '\\')."""
    zeilen = (ROOT / datei).read_text(encoding="utf-8").splitlines()
    for i, z in enumerate(zeilen):
        if re.match(anfang, z.strip()):
            teile = [z]
            while teile[-1].rstrip().endswith("\\") and i + 1 < len(zeilen):
                i += 1
                teile.append(zeilen[i])
            return " ".join(t.rstrip("\\ ") for t in teile)
    return None


for datei, anfang in (("start_jarvis.sh", r"exec \./venv/bin/python -m uvicorn "),
                      ("run.sh", r"python -m uvicorn "),
                      ("docker/entrypoint.sh", r"exec /venv/bin/uvicorn ")):
    b = _befehl(datei, anfang)
    check("%s: uvicorn-Aufruf gefunden" % datei, b is not None)
    if b:
        check("%s: --no-server-header am Aufruf" % datei, "--no-server-header" in b.split(), b[-160:])

uv_aufrufe = []
for datei in ("run_jarvis.py", "backend/main.py"):
    baum = ast.parse((ROOT / datei).read_text(encoding="utf-8"))
    for k in ast.walk(baum):
        if isinstance(k, ast.Call) and ast.unparse(k.func) in ("uvicorn.run", "uvicorn.Config"):
            sh = next((kw.value for kw in k.keywords if kw.arg == "server_header"), None)
            uv_aufrufe.append((datei, k.lineno, isinstance(sh, ast.Constant) and sh.value is False))
check("Positivkontrolle: drei uvicorn.run/Config-Aufrufe gefunden", len(uv_aufrufe) == 3, uv_aufrufe)
for datei, zeile, ok in uv_aufrufe:
    check("%s:%d server_header=False" % (datei, zeile), ok)

# ══ N6 ═══════════════════════════════════════════════════════════════════════
print("\n[N6] keine festen Schluesselpfade in Deploy-Skripten")
try:
    dateien = subprocess.run(["git", "ls-files", "*.sh", "deploy/*", "deploy/**/*"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
except Exception as e:  # noqa: BLE001
    abbruch("git ls-files nicht moeglich: %s" % e)
dateien = sorted(set(d for d in dateien if (ROOT / d).is_file()))
if "deploy_instructions.sh" not in dateien or "deploy/als_dienst.sh" not in dateien:
    abbruch("Positivkontrolle: Deploy-Skripte nicht erfasst (%d Dateien)" % len(dateien))
FEST = re.compile(r"(/c/users/[a-z0-9._-]+|[a-z]:\\\\users\\\\[a-z0-9._-]+|/home/[a-z0-9._-]+/\.ssh)",
                  re.I)
check("Positivkontrolle: das Muster trifft den Altbestand",
      FEST.search('SSH_KEY_PATH="/c/users/bender/.ssh/id_rsa"') is not None
      and FEST.search(r"C:\\Users\\bender\\.ssh") is not None)
treffer = []
for d in dateien:
    try:
        text = (ROOT / d).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for nr, zeile in enumerate(text.splitlines(), 1):
        if FEST.search(zeile):
            treffer.append("%s:%d" % (d, nr))
check("kein fester Benutzer-Schluesselpfad in %d Deploy-Skripten" % len(dateien), not treffer, treffer)
DI = (ROOT / "deploy_instructions.sh").read_text(encoding="utf-8")
check("deploy_instructions.sh: Schluessel aus JARVIS_SSH_KEY",
      re.search(r'^SSH_KEY_PATH="\$\{JARVIS_SSH_KEY:-\$HOME/\.ssh/id_rsa\}"$', DI, flags=re.M)
      is not None)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
