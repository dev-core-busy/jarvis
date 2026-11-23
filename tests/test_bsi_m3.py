#!/usr/bin/env python3
"""Waechter: BSI M3 – Anmeldeschutz je Konto (dauerhaft) und Admin-Rechte nur mit 2FA.

Befund (BSI-Abgleich 2026-09-29): Fehlversuche nur je IP und nur im Speicher;
2FA fuer Administratoren freiwillig.

Gemessen an der WIRKUNG:
  [A] ``backend/anmelde_schutz.py`` direkt (Ablage im Wegwerf-Verzeichnis):
      Sperre je Konto ueber wechselnde IPs, Ueberleben eines Neustarts, Ablauf,
      Ruecksetzen bei Erfolg, Aufheben, IP-Grenze.
  [B] der echte Login-Endpunkt (per AST aus main.py, Attrappen in echter
      Signatur, echtes ``sitzung_token``): Sperre VOR der Kennwortpruefung;
      seit dem Zahnrad (Betreiberentscheid 2026-11-20) fragt die Anmeldung
      Administratoren NICHT nach der 2FA (auch keine Einrichtung), Nicht-Admins
      mit eigener 2FA weiterhin; jede Sitzung beginnt ohne Admin-Rechte.
  [C] Admin-Rechte haengen an der SITZUNG: ``_user_is_admin``/``require_local_auth``
      nach ``verify_token`` – ohne Erhoehung am Zahnrad kein Admin (auch nicht
      mit IdP-MFA), fremde Konten unberuehrt, ausserhalb einer Anfrage
      unveraendert; Kennwortwechsel erbt die Merkmale; ``totp_disable``
      verweigert Admin-Konten; Add-in-SSO stellt nur Tokens "ohne Admin" aus.
  [E] die Erhoehung selbst (``admin_erhoehen``/``admin_erhoehung_beenden``):
      Code, Einrichtung mit Kennwort, IdP-MFA ohne Code, App/AI-Maus/Nicht-Admin
      abgewiesen, Fehlversuche zaehlen, Beenden nimmt nur DIESER Sitzung die Rechte.
  [D] AI-Maus (Betreiberentscheid 2026-10-27): keine 2FA-Abfrage fuer IRGENDEIN
      Konto, dafuer gilt die Sitzung nur auf /api/ai-mouse/* und /api/generated/*
      (ohne Admin-Seiten) und nie als Admin.

``backend.config`` nur als Stub. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations
import sys as _sys_jo, pathlib as _pl_jo  # noqa: E401
_sys_jo.path.insert(0, str(_pl_jo.Path(__file__).resolve().parent / "lib"))
# Das ECHTE main._json_objekt fuer geschnittene Endpunkte (tests/lib/json_objekt.py)
from json_objekt import json_objekt_aus_main as _json_objekt_aus_main  # noqa: E402

import ast
import asyncio
import contextvars
import hashlib
import hmac
import json
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)

TMP = Path(tempfile.mkdtemp(prefix="waechter-bsi-m3-"))

from backend import anmelde_schutz as AS   # noqa: E402
from backend import sitzung_token as ST    # noqa: E402
from backend import totp_schutz as TS      # noqa: E402

AS.STORE_PATH = TMP / "anmelde_schutz.json"
# Zeitbremsen aus: dieser Waechter misst Sperren, Tokens und 2FA, keine Dauer.
# Mit den Vorgaben wartete jeder Fehlversuch >= 1 s (angleichen) und jeder
# weitere Versuch derselben IP 2 s (bremse) - 24 der 28 s Laufzeit (Profil
# 2026-11-22). Die Zeitzusagen selbst misst test_anmelde_spruehen.py, und
# test_pentest_anmeldung.py stellt sie fuer seinen uebrigen Ablauf genauso ab.
AS.FEHL_MINDESTDAUER_S, AS.FEHL_STREUUNG_S, AS.SPRUEH_ABSTAND_S = 0.0, 0.0, 0.0
ST.STORE_PATH = TMP / "auth_sitzungen.json"
TS.STORE_PATH = TMP / "totp_schritte.json"
for _p in (AS.STORE_PATH, ST.STORE_PATH, TS.STORE_PATH):
    if not str(_p).startswith(str(TMP)):
        abbruch("Ablage zeigt aus dem Sandkasten heraus: %s" % _p)

# ── [A] Modul ────────────────────────────────────────────────────────────────
print("[A] anmelde_schutz")
AS._zuruecksetzen_fuer_test()
T0 = 1_000_000.0
for i in range(AS.KONTO_MAX - 1):
    AS.fehlversuch("10.0.0.%d" % i, "anna", jetzt=T0 + i)
check("%d Fehlversuche: noch nicht gesperrt" % (AS.KONTO_MAX - 1),
      AS.konto_wartezeit("anna", jetzt=T0 + 10) == 0)
gesperrt = AS.fehlversuch("10.0.0.99", "anna", jetzt=T0 + 10)
check("%d. Fehlversuch (jede IP eine andere) sperrt das Konto" % AS.KONTO_MAX,
      gesperrt and AS.konto_wartezeit("anna", jetzt=T0 + 11) > 0)
check("Sperrdauer = KONTO_SPERRE_S",
      abs(AS.konto_wartezeit("anna", jetzt=T0 + 10) - AS.KONTO_SPERRE_S) <= 1)
check("anderes Konto unberuehrt", AS.konto_wartezeit("bert", jetzt=T0 + 11) == 0)
check("Ablage nicht weltlesbar", AS.STORE_PATH.exists()
      and (AS.STORE_PATH.stat().st_mode & 0o007) == 0)
AS._zuruecksetzen_fuer_test()          # "Neustart": Speicher leer, Datei bleibt
check("Sperre ueberlebt einen Neustart", AS.konto_wartezeit("anna", jetzt=T0 + 12) > 0)
check("Sperre laeuft von selbst ab",
      AS.konto_wartezeit("anna", jetzt=T0 + 10 + AS.KONTO_SPERRE_S + 1) == 0)
check("aufheben: True bei laufender Sperre", AS.aufheben("anna"))
check("aufheben: danach frei", AS.konto_wartezeit("anna", jetzt=T0 + 13) == 0)
check("aufheben ohne Sperre: False", not AS.aufheben("anna"))

AS._zuruecksetzen_fuer_test()
AS.STORE_PATH.unlink(missing_ok=True)
AS._zuruecksetzen_fuer_test()
for i in range(AS.KONTO_MAX - 1):
    AS.fehlversuch("", "carl", jetzt=T0 + i)
AS.erfolg("carl")
AS.fehlversuch("", "carl", jetzt=T0 + 20)
check("Erfolg setzt den Konto-Zaehler zurueck", AS.konto_wartezeit("carl", jetzt=T0 + 21) == 0)
check("…und gesperrt wird erst wieder nach KONTO_MAX neuen",
      not any(AS.fehlversuch("", "carl", jetzt=T0 + 21 + i) for i in range(AS.KONTO_MAX - 2)))
check("Fehlversuche ausserhalb des Fensters zaehlen nicht",
      not AS.fehlversuch("", "carl", jetzt=T0 + 21 + AS.KONTO_FENSTER_S + 5))

AS._zuruecksetzen_fuer_test()
AS.STORE_PATH.unlink(missing_ok=True)
AS._zuruecksetzen_fuer_test()
for i in range(AS.IP_MAX):
    AS.fehlversuch("192.0.2.7", "konto%d" % i, jetzt=T0 + i)
check("IP-Grenze: nach IP_MAX Fehlversuchen wartet die IP",
      AS.ip_wartezeit("192.0.2.7", jetzt=T0 + AS.IP_MAX) > 0)
check("IP-Grenze: andere IP frei", AS.ip_wartezeit("192.0.2.8", jetzt=T0 + AS.IP_MAX) == 0)
check("IP-Grenze: nach dem Fenster wieder frei",
      AS.ip_wartezeit("192.0.2.7", jetzt=T0 + AS.IP_MAX + AS.IP_FENSTER_S + 1) == 0)
check("Konten aus dem IP-Durchlauf je nur 1 Fehlversuch – nicht gesperrt",
      all(AS.konto_wartezeit("konto%d" % i, jetzt=T0 + 10) == 0 for i in range(AS.IP_MAX)))

# ── Attrappen fuer [B]/[C] ───────────────────────────────────────────────────
_pyotp = types.ModuleType("pyotp")
_zaehler = [0]


def _random_base32():
    _zaehler[0] += 1
    return "SECRET%d" % _zaehler[0]


class _TOTP:
    """Echte Signatur von pyotp.TOTP.verify; der Code gilt zu JEDER Zeit (die
    Zeitschritt-Sperre aus BSI N3 hat test_bsi_n.py mit dem echten pyotp)."""
    interval = 30

    def __init__(self, s):
        self.s = s

    def verify(self, otp, for_time=None, valid_window=0):
        return otp == "code-" + self.s

    def provisioning_uri(self, name=None, issuer_name=None):
        return "otpauth://totp/%s:%s?secret=%s" % (issuer_name, name, self.s)


_pyotp.random_base32, _pyotp.TOTP = _random_base32, _TOTP
sys.modules["pyotp"] = _pyotp
_qr = types.ModuleType("qrcode")
_qr_img = types.ModuleType("qrcode.image")
_qr_pil = types.ModuleType("qrcode.image.pil")
_qr_pil.PilImage = object


class _Bild:
    def save(self, buf, format=None):
        buf.write(b"PNG")


_qr.make = lambda uri, image_factory=None, box_size=None, border=None: _Bild()
_qr.image, _qr_img.pil = _qr_img, _qr_pil
sys.modules.update({"qrcode": _qr, "qrcode.image": _qr_img, "qrcode.image.pil": _qr_pil})


class _Antwort:
    def __init__(self, inhalt, status_code=200, headers=None):
        self.inhalt, self.status_code, self.headers = inhalt, status_code, headers or {}


class _HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class _Req:
    def __init__(self, body=None, token="", ip="198.51.100.1", ua="Mozilla/5.0 (X11; Linux x86_64)"):
        self._body = body or {}
        # Starlette-Header sind gross/klein-unabhaengig; der Code liest "user-agent"
        self.headers = {"user-agent": ua}
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.client = types.SimpleNamespace(host=ip)
        self.scope = {}      # wie Starlette: ohne Cookie-Anmeldung (BSI H4) kein Merker
        # wie Starlette: request.state (Ablage der Anmelde-Reservierung, A1)
        self.state = types.SimpleNamespace()

    async def json(self):
        return self._body


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
        fn.decorator_list = []
        for a in fn.args.args + fn.args.kwonlyargs:
            a.annotation = None
        fn.returns = None
        fn.args.defaults = [ast.Constant(None) for _ in fn.args.defaults]
        teile.append(fn)
    mod = ast.Module(body=teile, type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, "main.py<auszug>", "exec")


ADMINS = {"jarvis", "andreas"}
EINST: dict = {}
STATE: dict = {}
AUTH_AUFRUFE: list = []


def _auth(u, pw, details=None):
    AUTH_AUFRUFE.append(u)
    return pw == "richtig"


def _get_state(u):
    return dict(STATE.get(u, {"must_change_password": False, "totp_enabled": False,
                              "totp_secret": None}))


def _set_state(u, upd):
    STATE.setdefault(u, {"must_change_password": False, "totp_enabled": False,
                         "totp_secret": None}).update(upd)


NS = {
    "JSONResponse": _Antwort, "HTTPException": _HTTPException, "Request": object,
    "asyncio": asyncio, "time": time, "hmac": hmac, "hashlib": hashlib, "json": json,
    "config": types.SimpleNamespace(SECRET_KEY="k" * 64,
                                    get_setting=lambda k, d=None: EINST.get(k, d)),
    "_sitzung": ST, "_anmelde_schutz": AS, "_totp_schutz": TS,
    "_sitzung_kontext": contextvars.ContextVar("_sk", default=None),
    # BSI M2: Protokoll-Halter (verify_token) und Sicherheitsprotokoll (Anmeldung)
    "_admin_anfrage": contextvars.ContextVar("_aa", default=None),
    "_sicherheits_log": types.SimpleNamespace(ereignis=lambda *a, **k: {}),
    "_revoked_logins": {}, "_save_revocations": lambda: None, "_WIDERRUF_ALLE": "*",
    "_sitzung_herkunft": contextvars.ContextVar("_sh", default=None),
    "ALLOWED_USERS": {"jarvis"}, "DESKTOP_USER": "jarvis", "_DOCKER_MODE": True,
    "_norm_login": lambda n: (n or "").split("@")[0].split("\\")[-1].strip().lower(),
    "_display_name": lambda u: u,
    "authenticate_linux_user": _auth,
    "_get_user_auth_state": _get_state, "_set_user_auth_state": _set_state,
    # BSI M5: die Anmeldung prueft vor pyotp, ob das 2FA-Secret geoeffnet ist
    # (gleiche Regel wie main._totp_secret_lesbar)
    "_totp_secret_lesbar": lambda s: isinstance(s, str) and bool(s) and not s.startswith("JGS1:"),
    "_user_must_change": lambda u: False,
    "_standard_zugang": types.SimpleNamespace(ist_standardkennwort=lambda pw, u: False),
    "_user_sessions": types.SimpleNamespace(record_login=lambda *a, **k: None),
    "security_guard": types.SimpleNamespace(get_block=lambda u: None, is_blocked=lambda u: False),
    "switch_desktop_session": lambda u: None,
    "_konto_hinweis_abraeumen": lambda u: None,
    "_login_still_allowed": lambda u: True,
    "_admin_access_cache": {},
    # AD-Admins ueber die Liste; jarvis ist lokal Admin
    "_gruppe_trifft": lambda plain, grp, cache: False,
}
EINST.update({"ad_admins": "andreas", "ad_server": "dc.firma.local", "ad_domain": "firma.local"})
# BSI H4: Token-Antworten laufen ueber _sitzung_antwort – mit dem ECHTEN Modul
NS["_sitzung_cookie"] = __import__("backend.sitzung_cookie", fromlist=["x"])
NS.setdefault("_json_objekt", _json_objekt_aus_main(NS.get("HTTPException")))
exec(_funktionen("generate_token", "verify_token", "_epoche_widerrufen", "_konto_ist_admin",
                 "_sitzung_ohne_admin", "_abruf_sitzung", "_totp_code_pruefen",
                 "admin_erhoehen", "admin_erhoehung_beenden", "_erhoehung_protokoll",
                 "_ist_app_anmeldung", "_ist_ai_maus_anmeldung", "_user_is_admin",
                 "_is_admin_user", "_admin_verweigert_text", "require_local_auth",
                 "_check_rate_limit", "_record_login_attempt", "_konto_sperre_antwort",
                 # A1/A2 (2026-11-05): Reservierung vor der Pruefung, Bremsen-Ueberlauf
                 "_anmelde_reservierung", "_bremse_ueberlauf_antwort",
                 "_totp_vormerken", "_totp_qr_daten", "login", "_login_ablauf", "_anmeldung_protokollieren",
                 # Seit 2026-10-20 kann das 2FA-Geheimnis im ROOT-BROKER liegen
                 # (ein Authenticator-Eintrag fuer Anmeldung UND Freigaben). Die
                 # ECHTEN Funktionen mitschneiden, nicht nachbauen: eine Attrappe
                 # haette den neuen Zweig dauerhaft unmessbar gemacht. Die Konten
                 # hier tragen kein Broker-Geheimnis, der Zweig wird also nicht
                 # betreten - fehlt er aber, stirbt der Lauf an einem NameError,
                 # und der Folgefehler nennt eine voellig andere Zeile.
                 "_totp_im_broker", "_totp_broker_pruefen", "_totp_broker_fehlertext",
                 "_antwort_json", "totp_disable", "_totp_fehlertext",
                 "_sitzung_ist_app", "_totp_app_sperre",
                 "_kennwort_schranke", "_kennwort_fehlversuch",
                 "_sitzungen_nach_kennwortwechsel", "_sitzung_antwort"), NS)
login = NS["login"]


def _neu():
    AS._zuruecksetzen_fuer_test()
    AS.STORE_PATH.unlink(missing_ok=True)
    AS._zuruecksetzen_fuer_test()
    ST._zuruecksetzen_fuer_test()
    ST.STORE_PATH.unlink(missing_ok=True)
    ST._zuruecksetzen_fuer_test()
    STATE.clear()
    AUTH_AUFRUFE.clear()
    TS._zuruecksetzen_fuer_test()
    TS.STORE_PATH.unlink(missing_ok=True)
    TS._zuruecksetzen_fuer_test()


def anmelden(user, pw="richtig", code=None, ip="198.51.100.1", client=None,
             ua="Mozilla/5.0 (X11; Linux x86_64)"):
    body = {"username": user, "password": pw}
    if code is not None:
        body["totp_code"] = code
    if client is not None:
        body["client"] = client
    return contextvars.copy_context().run(lambda: asyncio.run(login(_Req(body, ip=ip, ua=ua))))


def _sig(r):
    return (r.inhalt.get("token") or "x:1:x").split(":", 2)[2]


# ── [B] Login ────────────────────────────────────────────────────────────────
print("\n[B] Login-Endpunkt")
_neu()
r = anmelden("bert")
if not (r.status_code == 200 and r.inhalt.get("success") and r.inhalt.get("token")):
    abbruch("Positivkontrolle: Nicht-Admin mit richtigem Kennwort kommt nicht durch (%s %s)"
            % (r.status_code, r.inhalt))
check("Nicht-Admin ohne 2FA: Anmeldung ohne Einrichtungszwang", "requires_totp_setup" not in r.inhalt)

_neu()
for i in range(AS.KONTO_MAX):
    anmelden("bert", pw="falsch", ip="203.0.113.%d" % i)
AUTH_AUFRUFE.clear()
r = anmelden("bert", ip="203.0.113.200")
check("Konto nach KONTO_MAX Fehlversuchen (wechselnde IPs) gesperrt: 429", r.status_code == 429)
check("…und das Kennwort wird dabei gar nicht erst geprueft", AUTH_AUFRUFE == [])
check("…Antwort nennt Retry-After", int(r.headers.get("Retry-After", "0")) > 0)
r = anmelden("carla", ip="203.0.113.201")
check("anderes Konto von neuer IP: kommt durch", r.status_code == 200 and r.inhalt.get("success"))

_neu()
for i in range(AS.KONTO_MAX - 1):
    anmelden("bert", pw="falsch", ip="203.0.113.%d" % i)
anmelden("bert", ip="203.0.113.50")
for i in range(AS.KONTO_MAX - 1):
    anmelden("bert", pw="falsch", ip="203.0.113.%d" % (60 + i))
r = anmelden("bert", ip="203.0.113.99")
check("erfolgreiche Anmeldung setzt den Konto-Zaehler zurueck", r.status_code == 200)

_neu()
STATE["bert"] = {"totp_enabled": True, "totp_secret": "BS"}
for i in range(AS.KONTO_MAX):
    anmelden("bert", code="falsch", ip="203.0.113.%d" % i)
check("falsche 2FA-Codes zaehlen fuer das Konto", AS.konto_wartezeit("bert") > 0)

# Zahnrad (2026-11-20): Administratoren werden bei der Anmeldung nicht gefragt
_neu()
r = anmelden("andreas")
tok = r.inhalt.get("token") or ""
check("Admin ohne 2FA: Token ohne Einrichtung",
      r.status_code == 200 and bool(tok) and "requires_totp_setup" not in r.inhalt)
check("…Antwort: is_admin false, admin_konto true (das Zahnrad wird angeboten)",
      r.inhalt.get("is_admin") is False and r.inhalt.get("admin_konto") is True)
check("…Sitzung beginnt OHNE Admin-Rechte", bool(tok) and not ST.admin_erhoeht(tok.split(":", 2)[2]))
check("…bei der Anmeldung wird nichts vorgemerkt",
      not _get_state("andreas").get("totp_pending_secret"))
_neu()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
r = anmelden("andreas")
check("Admin MIT 2FA: kein Code verlangt, Token",
      bool(r.inhalt.get("token")) and "requires_totp" not in r.inhalt)
r = anmelden("andreas", code="code-FALSCH")
check("…ein mitgeschickter falscher Code wird nicht ausgewertet (kein Fehlversuch)",
      bool(r.inhalt.get("token"))
      and not (json.loads(AS.STORE_PATH.read_text()) if AS.STORE_PATH.exists() else {})
      .get("konto", {}).get("andreas"))
check("…Sitzung ohne Merkmal 'mit 2FA' und ohne Admin-Rechte",
      not ST.mit_2fa(_sig(r)) and not ST.admin_erhoeht(_sig(r)))
_neu()
r = anmelden("jarvis")
check("lokaler Admin jarvis: ebenfalls ohne 2FA-Abfrage, Zahnrad angeboten",
      bool(r.inhalt.get("token")) and r.inhalt.get("admin_konto") is True)

# Nicht-Admins mit eigener 2FA: weiterhin der Code bei der Anmeldung
_neu()
STATE["bert"] = {"totp_enabled": True, "totp_secret": "BS"}
r = anmelden("bert")
check("Nicht-Admin mit 2FA: Code verlangt, kein Token",
      r.inhalt.get("requires_totp") is True and not r.inhalt.get("token"))
r = anmelden("bert", code="code-BS")
check("…mit Code: Token 'mit 2FA', aber ohne Zahnrad", bool(r.inhalt.get("token"))
      and ST.mit_2fa(_sig(r)) and r.inhalt.get("admin_konto") is False)
r = anmelden("bert", code="code-BS")
check("…derselbe Code gleich noch einmal: abgewiesen (BSI N3)",
      r.status_code == 401 and not r.inhalt.get("token")
      and "bereits verwendet" in str(r.inhalt.get("error")))

# ── [B2] Android-/Windows-App ───────────────────────────────────────────────
print("\n[B2] App-Anmeldung: Admin-Konto ohne Admin-Rechte")
_neu()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
r = anmelden("andreas")
# Positivkontrolle als PRUEFUNG, nicht als Abbruch: faellt sie, ist das eine
# Produktaenderung (z. B. Admins werden wieder nach dem Code gefragt) – ein
# Abbruch wuerde sie als "konnte nicht laufen" verstecken (Register).
check("Positivkontrolle: Admin-Konto im Browser bekommt ein Token mit Zahnrad (admin_konto)",
      r.inhalt.get("admin_konto") is True and bool(r.inhalt.get("token"))
      and not ST.ohne_admin(_sig(r)))
for name, kw in (("client=android", {"client": "android"}),
                 ("client=windows", {"client": "windows"}),
                 ("bestehende Android-App (OkHttp)", {"ua": "okhttp/4.12.0"}),
                 ("bestehende Windows-App (Go)", {"ua": "Go-http-client/1.1"})):
    r = anmelden("andreas", **kw)
    check("App (%s): Admin mit 2FA bekommt ein Token ohne Code" % name,
          r.status_code == 200 and bool(r.inhalt.get("token")))
    check("…Sitzung 'ohne Admin', nicht 'mit 2FA'",
          ST.ohne_admin(_sig(r)) and not ST.mit_2fa(_sig(r)))
    check("…Antwort meldet is_admin false und KEIN Zahnrad",
          r.inhalt.get("is_admin") is False and r.inhalt.get("admin_konto") is False)
STATE.pop("andreas")
r = anmelden("andreas", client="android")
check("App: Admin OHNE 2FA – keine Einrichtung, Token ohne Admin",
      bool(r.inhalt.get("token")) and "requires_totp_setup" not in r.inhalt and ST.ohne_admin(_sig(r)))
STATE["bert"] = {"totp_enabled": True, "totp_secret": "BS"}
r = anmelden("bert", client="android")
check("App: Nicht-Admin mit 2FA braucht weiter den Code (kein 2FA-Umweg)",
      r.inhalt.get("requires_totp") is True and not r.inhalt.get("token"))
r = anmelden("carla", client="android")
check("App: Nicht-Admin ohne 2FA – normales Token, kein Merkmal",
      bool(r.inhalt.get("token")) and not ST.ohne_admin(_sig(r)))
# Eine Sekunde Abstand: die App-Anmeldungen darueber haben fuer "andreas" in
# derselben Sekunde ein IDENTISCHES Token ausgestellt – samt Merkmal "ohne Admin".
time.sleep(1.1)
r = anmelden("andreas", ua="Mozilla/5.0 okhttp-Nachahmer")
check("Browser mit 'okhttp' irgendwo im Text gilt NICHT als App",
      bool(r.inhalt.get("token")) and not ST.ohne_admin(_sig(r))
      and r.inhalt.get("admin_konto") is True)

# ── [C] Admin-Rechte an der Sitzung ─────────────────────────────────────────
print("\n[C] Admin-Rechte haengen an der Sitzung")
_neu()
verify, is_admin, user_is_admin = NS["verify_token"], NS["_is_admin_user"], NS["_user_is_admin"]
req_local = NS["require_local_auth"]


def in_kontext(fn):
    """Jede Anfrage hat ihren eigenen Kontext – wie unter uvicorn."""
    return contextvars.copy_context().run(fn)


# Getrennte Zeitstempel: zwei Tokens desselben Benutzers aus derselben Sekunde
# sind IDENTISCH (gleiche Signatur) – das Merkmal des einen gaelte fuer beide.
_jetzt = int(time.time())
ohne = NS["generate_token"]("andreas", ts=_jetzt - 30)
idp = NS["generate_token"]("andreas", ts=_jetzt - 25, mit_2fa=True)
erh = NS["generate_token"]("andreas", ts=_jetzt - 20, admin_erhoeht=True)
j_ohne = NS["generate_token"]("jarvis", ts=_jetzt - 30)
check("Positivkontrolle: am Zahnrad erhoehte Admin-Sitzung ist Admin",
      in_kontext(lambda: verify(erh) == "andreas" and is_admin("andreas")))
check("Sitzung OHNE Erhoehung: _is_admin_user False",
      in_kontext(lambda: verify(ohne) == "andreas" and not is_admin("andreas")))
check("Sitzung OHNE Erhoehung: auch _user_is_admin False",
      in_kontext(lambda: (verify(ohne), user_is_admin("andreas"))[1]) is False)
check("Sitzung mit IdP-MFA ('mit 2FA'), aber nicht erhoeht: kein Admin",
      in_kontext(lambda: (verify(idp), is_admin("andreas"))[1]) is False)
check("lokaler jarvis ohne Erhoehung: kein Admin (keine ALLOWED_USERS-Abkuerzung)",
      in_kontext(lambda: (verify(j_ohne), is_admin("jarvis"))[1]) is False)
check("Pruefung eines FREMDEN Kontos bleibt unberuehrt",
      in_kontext(lambda: (verify(ohne), is_admin("jarvis"))[1]) is True)
check("ausserhalb einer Anfrage (kein Kontext): Konto-Rechte unveraendert",
      in_kontext(lambda: is_admin("andreas")) is True)
check("_konto_ist_admin fragt das KONTO, nicht die Sitzung",
      in_kontext(lambda: (verify(ohne), NS["_konto_ist_admin"]("andreas"))[1]) is True)
check("…und laesst den Sitzungskontext danach unveraendert",
      in_kontext(lambda: (verify(ohne), NS["_konto_ist_admin"]("andreas"),
                          is_admin("andreas"))[2]) is False)


def _local(tok):
    async def f():
        try:
            return await req_local(_Req(token=tok))
        except _HTTPException as e:
            return e
    return in_kontext(lambda: asyncio.run(f()))


e = _local(ohne)
check("require_local_auth: Sitzung ohne Erhoehung -> 403",
      isinstance(e, _HTTPException) and e.status_code == 403)
check("…mit einem Text, der den Weg ueber das Zahnrad nennt",
      isinstance(e, _HTTPException) and "Zahnrad" in str(e.detail))
check("require_local_auth: erhoehte Sitzung -> durch", _local(erh) == "andreas")
e = _local(idp)
check("require_local_auth: Sitzung mit IdP-MFA, nicht erhoeht -> 403",
      isinstance(e, _HTTPException) and e.status_code == 403)
e = _local(j_ohne)
check("require_local_auth: lokaler jarvis ohne Erhoehung -> 403",
      isinstance(e, _HTTPException) and e.status_code == 403)
e = _local(NS["generate_token"]("bert", ts=_jetzt - 20, admin_erhoeht=True))
check("require_local_auth: Nicht-Admin (selbst mit Merkmal) -> 403 mit dem Rechte-Text",
      isinstance(e, _HTTPException) and "Zahnrad" not in str(e.detail))

# App-Sitzung: nie Admin, auch nicht mit dem Merkmal
app_tok = NS["generate_token"]("andreas", ts=_jetzt - 50, ohne_admin=True)
check("App-Sitzung: _is_admin_user False",
      in_kontext(lambda: (verify(app_tok), is_admin("andreas"))[1]) is False)
app_erh = NS["generate_token"]("andreas", ts=_jetzt - 55, ohne_admin=True, admin_erhoeht=True)
check("App-Sitzung mit erbetenem Merkmal: wird NICHT erhoeht",
      not ST.admin_erhoeht(app_erh.split(":", 2)[2])
      and in_kontext(lambda: (verify(app_erh), is_admin("andreas"))[1]) is False)
e = _local(app_tok)
check("require_local_auth: App-Sitzung -> 403 mit Hinweis auf die Weboberflaeche",
      isinstance(e, _HTTPException) and e.status_code == 403 and "App" in str(e.detail))
neu_app = NS["_sitzungen_nach_kennwortwechsel"]("andreas", _Req(token=app_tok))
check("Kennwortwechsel in der App-Sitzung: Ersatz-Token bleibt 'ohne Admin'",
      ST.ohne_admin(neu_app.split(":", 2)[2]))

# Kennwortwechsel erbt die Merkmale. Eine Sekunde Abstand zum Wechsel in der
# App-Sitzung darueber: beide stellen das Ersatz-Token fuer "andreas" mit
# ts = Epoche + 1 aus, in derselben Sekunde waeren sie IDENTISCH (Register).
time.sleep(1.1)
neu_erh = NS["_sitzungen_nach_kennwortwechsel"]("andreas", _Req(token=erh))
neu_idp = NS["_sitzungen_nach_kennwortwechsel"]("jarvis", _Req(token=NS["generate_token"](
    "jarvis", ts=_jetzt - 45, mit_2fa=True)))
neu_ohne = NS["_sitzungen_nach_kennwortwechsel"]("bert", _Req(token=NS["generate_token"]("bert", ts=_jetzt - 40)))
check("Kennwortwechsel in einer erhoehten Sitzung: Ersatz-Token bleibt erhoeht",
      ST.admin_erhoeht(neu_erh.split(":", 2)[2]))
check("Kennwortwechsel in einer Sitzung 'mit 2FA': Ersatz-Token 'mit 2FA', nicht erhoeht",
      ST.mit_2fa(neu_idp.split(":", 2)[2]) and not ST.admin_erhoeht(neu_idp.split(":", 2)[2]))
check("Kennwortwechsel ohne Merkmale: Ersatz-Token ohne Merkmale",
      not ST.mit_2fa(neu_ohne.split(":", 2)[2]) and not ST.admin_erhoeht(neu_ohne.split(":", 2)[2]))

# Merkmale ueberleben einen Neustart
ST._zuruecksetzen_fuer_test()
check("Merkmal 'Admin erhoeht' ueberlebt einen Neustart", ST.admin_erhoeht(erh.split(":", 2)[2]))
check("Merkmal 'mit 2FA' ueberlebt einen Neustart", ST.mit_2fa(idp.split(":", 2)[2]))
check("Merkmal 'ohne Admin' ueberlebt einen Neustart", ST.ohne_admin(app_tok.split(":", 2)[2]))
ST.widerrufe(erh.split(":", 2)[2], _jetzt - 20)
check("Abmelden nimmt das Merkmal 'Admin erhoeht' mit", not ST.admin_erhoeht(erh.split(":", 2)[2]))

# totp_disable
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "S"}
STATE["bert"] = {"totp_enabled": True, "totp_secret": "S"}
dis = NS["totp_disable"]
r = in_kontext(lambda: asyncio.run(dis(_Req({"password": "richtig"}), "andreas")))
check("totp_disable: Admin-Konto -> 403, 2FA bleibt an",
      r.status_code == 403 and _get_state("andreas").get("totp_enabled"))
r = in_kontext(lambda: asyncio.run(dis(_Req({"password": "richtig"}), "bert")))
check("totp_disable: Nicht-Admin darf weiterhin abschalten",
      r.status_code == 200 and not _get_state("bert").get("totp_enabled"))

# Add-in-SSO: Token nie Admin (REGEL am Syntaxbaum – der Endpunkt braucht ein
# echtes Exchange-Token und ist hier nicht ausfuehrbar)
sso = _fn("_addin_sso_ablauf")
gen_aufrufe = [k for k in ast.walk(sso) if isinstance(k, ast.Call)
               and isinstance(k.func, ast.Name) and k.func.id == "generate_token"]
check("addin_sso stellt genau ein Token aus", len(gen_aufrufe) == 1)
check("…ohne mit_2fa und ohne admin_erhoeht",
      all(not any(kw.arg in ("mit_2fa", "admin_erhoeht") for kw in k.keywords) for k in gen_aufrufe))
check("…und ausdruecklich 'ohne Admin' (Zahnrad-Erhoehung dort abgewiesen)",
      all(any(kw.arg == "ohne_admin" and isinstance(kw.value, ast.Constant) and kw.value.value is True
              for kw in k.keywords) for k in gen_aufrufe))

# ── [D] AI-Maus: ohne 2FA, nur eigene Schnittstellen ────────────────────────
print("\n[D] AI-Maus-Anmeldung")
_neu()
# [C] hat bei totp_disable die Sitzungs-Epoche von bert gesetzt (Widerruf aller
# Tokens) – fuer die Tokens unten mit Zeitstempel davor waere sonst jedes ungueltig
NS["_revoked_logins"].clear()
STATE["bert"] = {"totp_enabled": True, "totp_secret": "BS"}
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
r = anmelden("bert")
if r.inhalt.get("requires_totp") is not True:
    abbruch("Positivkontrolle: Nicht-Admin mit 2FA im Browser wird nicht nach dem Code gefragt")
for wer in ("bert", "andreas"):
    r = anmelden(wer, client="ai-mouse")
    check("AI-Maus: %s mit 2FA bekommt ein Token ohne Code" % wer,
          r.status_code == 200 and bool(r.inhalt.get("token")) and "requires_totp" not in r.inhalt)
    check("…Sitzung 'nur AI-Maus' und 'ohne Admin', nicht 'mit 2FA'",
          ST.nur_ai_maus(_sig(r)) and ST.ohne_admin(_sig(r)) and not ST.mit_2fa(_sig(r)))
    check("…Antwort meldet is_admin false", r.inhalt.get("is_admin") is False)
r = anmelden("bert", client="AI-Mouse ")
check("Kennung unabhaengig von Gross/Klein und Leerraum", ST.nur_ai_maus(_sig(r)))
r = anmelden("bert", client="ai-mouse", pw="falsch")
check("AI-Maus: falsches Kennwort bleibt 401 ohne Token",
      r.status_code == 401 and not r.inhalt.get("token"))
STATE.pop("andreas")
r = anmelden("andreas", client="ai-mouse")
check("AI-Maus: Admin OHNE 2FA – keine Einrichtung, Token, nicht erhoeht",
      bool(r.inhalt.get("token")) and "requires_totp_setup" not in r.inhalt
      and not ST.admin_erhoeht(_sig(r)))
r = anmelden("bert", client="android")
check("andere App: Nicht-Admin mit 2FA braucht weiter den Code",
      r.inhalt.get("requires_totp") is True and not r.inhalt.get("token"))
r = anmelden("carla")
check("Browser-Anmeldung traegt KEIN Merkmal 'nur AI-Maus'",
      bool(r.inhalt.get("token")) and not ST.nur_ai_maus(_sig(r)))

_jetzt = int(time.time())
maus = NS["generate_token"]("bert", ts=_jetzt - 60, ohne_admin=True, nur_ai_maus=True)
normal = NS["generate_token"]("bert", ts=_jetzt - 70)
maus_admin = NS["generate_token"]("andreas", ts=_jetzt - 80, ohne_admin=True, nur_ai_maus=True)


def auf_pfad(tok, pfad, fn=None):
    """verify_token (und danach ``fn``) mit gesetztem Anfrage-Pfad, wie die Middleware."""
    def lauf():
        if pfad is not None:
            ST.ANFRAGE_PFAD.set(pfad)
        u = verify(tok)
        return (u, fn()) if fn else u
    return in_kontext(lauf)


if auf_pfad(normal, "/api/chat") != "bert":
    abbruch("Positivkontrolle: normales Token gilt auf /api/chat nicht")
for pfad in ("/api/ai-mouse/analyze", "/api/ai-mouse/health", "/api/ai-mouse/paket",
             "/api/ai-mouse/fragen", "/api/generated/abc.png"):
    check("AI-Maus-Sitzung gilt auf %s" % pfad, auf_pfad(maus, pfad) == "bert")
for pfad in ("/api/chat", "/api/me", "/api/auth/totp/setup", "/api/change-password",
             "/api/ai-mouse/admin/areas", "/api/ai-mousex/analyze", "/ws", ""):
    check("AI-Maus-Sitzung gilt NICHT auf %r" % pfad, auf_pfad(maus, pfad) is None)
check("AI-Maus-Sitzung ohne bekannten Pfad: ungueltig (fail-closed)", auf_pfad(maus, None) is None)
check("normales Token ohne bekannten Pfad: unveraendert gueltig", auf_pfad(normal, None) == "bert")
check("AI-Maus-Sitzung eines Admins: auf ihrem Pfad kein Admin",
      auf_pfad(maus_admin, "/api/ai-mouse/analyze", lambda: is_admin("andreas"))
      == ("andreas", False))
ST._zuruecksetzen_fuer_test()
check("Merkmal 'nur AI-Maus' ueberlebt einen Neustart", ST.nur_ai_maus(maus.split(":", 2)[2])
      and auf_pfad(maus, "/api/chat") is None)
ST.widerrufe(maus.split(":", 2)[2], _jetzt - 60)
check("abgemeldete AI-Maus-Sitzung gilt auch auf ihrem Pfad nicht mehr",
      auf_pfad(maus, "/api/ai-mouse/analyze") is None)

# Client: die AI-Maus muss sich ausweisen, sonst greift nichts davon
CS = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Vision" / "JarvisClient.cs").read_text(encoding="utf-8")
check("JarvisClient.cs schickt client=ai-mouse bei der Anmeldung",
      '["client"] = "ai-mouse"' in CS)

# Middleware: muss AEUSSERSTE Schicht sein (zuletzt registriert), sonst sieht
# eine aeussere Schicht, die verify_token ruft, keinen Pfad
_reg = [n for n in BAUM.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "add_middleware"]
_dek = [n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr == "middleware" for d in n.decorator_list)]
_letzte = max([n.lineno for n in _reg] + [n.lineno for n in _dek], default=0)
_pfad_mw = [n for n in _reg if n.value.args and isinstance(n.value.args[0], ast.Name)
            and n.value.args[0].id == "_AnfragePfadMiddleware"]
# Die eigentliche Zusage: jede Schicht, die die Sitzung befragt, liegt INNEN.
# Aeusser ihr darf nur liegen, was nachweislich nichts von der Sitzung weiss –
# seit c0a24600 die KompressionsWeiche, die selbst aeusserste Schicht sein muss
# (no_cache_static schreibt HTML um, test_kompression.py). Gemessen wird am
# QUELLTEXT der spaeter registrierten Schichten, nicht an einer Namensliste.
_SITZUNGS_NAMEN = {"verify_token", "_sitzung", "ANFRAGE_PFAD", "_token_aufloesen"}
def _quelle_der_schicht(ausdruck):
    """Quelltext einer registrierten Schicht: Klasse/Funktion in main.py oder
    das ganze Modul bei ``modul.Klasse`` (``from backend import modul as alias``)."""
    if isinstance(ausdruck, ast.Name):
        for n in BAUM.body:
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and n.name == ausdruck.id:
                return n
        return None
    if isinstance(ausdruck, ast.Attribute) and isinstance(ausdruck.value, ast.Name):
        alias = ausdruck.value.id
        for n in ast.walk(BAUM):
            if isinstance(n, ast.ImportFrom) and n.module == "backend":
                for a in n.names:
                    if (a.asname or a.name) == alias:
                        datei = ROOT / "backend" / (a.name + ".py")
                        return ast.parse(datei.read_text(encoding="utf-8")) if datei.exists() else None
    return None
def _fragt_sitzung(knoten):
    return any((isinstance(x, ast.Name) and x.id in _SITZUNGS_NAMEN)
               or (isinstance(x, ast.Attribute) and x.attr in _SITZUNGS_NAMEN)
               or (isinstance(x, ast.alias) and (x.asname or x.name) in _SITZUNGS_NAMEN)
               for x in ast.walk(knoten))
# Positivkontrolle: die Sonde erkennt die Pfad-Middleware selbst als sitzungsnah
_pk = _quelle_der_schicht(ast.Name(id="_AnfragePfadMiddleware"))
if _pk is None or not _fragt_sitzung(_pk):
    print("ABBRUCH: die Sitzungs-Sonde erkennt _AnfragePfadMiddleware nicht")
    sys.exit(2)
_aussen = [n for n in _reg if _pfad_mw and n.lineno > _pfad_mw[0].lineno]
_aussen_q = [(ast.unparse(n.value.args[0]) if n.value.args else "?",
              _quelle_der_schicht(n.value.args[0]) if n.value.args else None) for n in _aussen]
_aussen_dek = [n.name for n in _dek if _pfad_mw and n.lineno > _pfad_mw[0].lineno]
check("_AnfragePfadMiddleware ist genau einmal registriert (%d)" % len(_pfad_mw),
      len(_pfad_mw) == 1)
check("ausserhalb von ihr liegt keine dekorierte Middleware (@app.middleware) %s" % _aussen_dek,
      not _aussen_dek)
check("jede Schicht ausserhalb ist auffindbar und fragt die Sitzung NICHT %s"
      % [(name, "unauffindbar" if q is None else _fragt_sitzung(q)) for name, q in _aussen_q],
      all(q is not None and not _fragt_sitzung(q) for _, q in _aussen_q))

shutil.rmtree(TMP, ignore_errors=True)
# ── [E] Admin-Rechte am Zahnrad ─────────────────────────────────────────────
print("\n[E] Erhoehung am Zahnrad")
EREIGNISSE: list = []
NS["_sicherheits_log"] = types.SimpleNamespace(
    ereignis=lambda art, **k: (EREIGNISSE.append((art, k)), {})[1])


def zahnrad(tok, body=None, beenden=False):
    """Eine Anfrage wie unter uvicorn: require_auth (verify_token) setzt den
    Sitzungskontext, dann der Endpunkt."""
    async def f():
        u = verify(tok)
        if not u:
            return None
        fn = NS["admin_erhoehung_beenden"] if beenden else NS["admin_erhoehen"]
        return await (fn(_Req(token=tok), u) if beenden else fn(_Req(body or {}, token=tok), u))
    return in_kontext(lambda: asyncio.run(f()))


def admin_in(tok, wer="andreas"):
    return in_kontext(lambda: (verify(tok), is_admin(wer))[1])


def _versuche(konto):
    return len((json.loads(AS.STORE_PATH.read_text()) if AS.STORE_PATH.exists() else {})
               .get("konto", {}).get(konto, []))


_neu()
NS["_revoked_logins"].clear()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
_jetzt = int(time.time())
t1 = NS["generate_token"]("andreas", ts=_jetzt - 10)
t2 = NS["generate_token"]("andreas", ts=_jetzt - 9)
check("Positivkontrolle: frische Sitzung hat KEINE Admin-Rechte (sonst waere die "
      "Erhoehung nicht messbar)", not admin_in(t1))
r = zahnrad(t1)
check("Zahnrad ohne Code: requires_totp, keine Rechte",
      r is not None and r.inhalt.get("requires_totp") is True and not admin_in(t1))
r = zahnrad(t1, {"code": "code-FALSCH"})
check("falscher Code: 401, keine Rechte", r.status_code == 401 and not admin_in(t1))
check("…zaehlt als Fehlversuch des Kontos", _versuche("andreas") == 1)
check("…und steht im Sicherheitsprotokoll",
      ("admin_erhoehung", "fehlgeschlagen") in [(a, k.get("ergebnis")) for a, k in EREIGNISSE])
r = zahnrad(t1, {"code": "code-AS"})
check("richtiger Code: ok, erhoeht", r.status_code == 200 and r.inhalt.get("erhoeht") is True)
check("…die Sitzung hat danach Admin-Rechte (naechste Anfrage)", admin_in(t1))
check("…require_local_auth laesst sie durch", _local(t1) == "andreas")
check("…eine ANDERE Sitzung desselben Kontos bleibt ohne Rechte", not admin_in(t2))
check("…Protokoll: admin_erhoehung ok, weg=code",
      any(a == "admin_erhoehung" and k.get("ergebnis") == "ok" and k.get("weg") == "code"
          for a, k in EREIGNISSE))
r = zahnrad(t2, {"code": "code-AS"})
check("derselbe Code in der zweiten Sitzung: abgewiesen (BSI N3)",
      r.status_code == 401 and "bereits verwendet" in str(r.inhalt.get("error")) and not admin_in(t2))
r = zahnrad(t1, beenden=True)
check("Administration beenden: ok", r.status_code == 200 and r.inhalt.get("erhoeht") is False)
check("…danach keine Admin-Rechte mehr, die Sitzung gilt weiter",
      not admin_in(t1) and in_kontext(lambda: verify(t1)) == "andreas")
check("…Protokoll: admin_beendet", any(a == "admin_beendet" for a, _ in EREIGNISSE))
_n = len(EREIGNISSE)
zahnrad(t1, beenden=True)
check("zweites Beenden ohne Rechte: kein weiterer Protokolleintrag", len(EREIGNISSE) == _n)

# Fehlversuche am Zahnrad sperren wie an der Anmeldung
_neu()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
t3 = NS["generate_token"]("andreas", ts=int(time.time()) - 5)
for i in range(AS.KONTO_MAX):
    zahnrad(t3, {"code": "code-FALSCH%d" % i})
r = zahnrad(t3, {"code": "code-AS"})
check("nach KONTO_MAX falschen Codes: 429, auch der richtige Code hilft nicht",
      r.status_code == 429 and not admin_in(t3))

# Einrichtung am Zahnrad: QR, dann Code UND Kennwort
_neu()
t4 = NS["generate_token"]("andreas", ts=int(time.time()) - 5)
r = zahnrad(t4)
geheim = str(r.inhalt.get("secret") or "")
check("ohne 2FA: requires_totp_setup mit QR und Schluessel",
      r.inhalt.get("requires_totp_setup") is True and bool(r.inhalt.get("qr_code")) and bool(geheim))
check("…Secret ist nur vorgemerkt (2FA noch aus)",
      _get_state("andreas").get("totp_pending_secret") == geheim
      and not _get_state("andreas").get("totp_enabled"))
r = zahnrad(t4, {"code": "code-" + geheim})
check("Code OHNE Kennwort: 400, nichts eingerichtet, keine Rechte",
      r.status_code == 400 and not _get_state("andreas").get("totp_enabled") and not admin_in(t4))
r = zahnrad(t4, {"code": "code-" + geheim, "password": "falsch"})
check("falsches Kennwort: 401, nichts eingerichtet, keine Rechte",
      r.status_code == 401 and not _get_state("andreas").get("totp_enabled") and not admin_in(t4))
r = zahnrad(t4, {"code": "code-FALSCH", "password": "richtig"})
check("falscher Code mit richtigem Kennwort: 401, nichts eingerichtet",
      r.status_code == 401 and not _get_state("andreas").get("totp_enabled"))
r = zahnrad(t4, {"code": "code-" + geheim, "password": "richtig"})
check("richtiger Code + Kennwort: eingerichtet und erhoeht",
      r.status_code == 200 and r.inhalt.get("erhoeht") is True and admin_in(t4)
      and _get_state("andreas").get("totp_enabled")
      and _get_state("andreas").get("totp_secret") == geheim
      and not _get_state("andreas").get("totp_pending_secret"))

# IdP-MFA ersetzt den Code NICHT (Vorfall DEV 2026-11-20: ein Admin ohne 2FA
# kam nach der Firmenkonto-Anmeldung mit einem Klick an die Rechte – das Token
# trug keinen MFA-Nachweis, die Sitzung galt trotzdem als "mit 2FA").
_neu()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
t5 = NS["generate_token"]("andreas", ts=int(time.time()) - 5, mit_2fa=True)
r = zahnrad(t5)
check("Sitzung mit IdP-MFA, 2FA eingerichtet: Zahnrad verlangt trotzdem den Code",
      r.inhalt.get("requires_totp") is True and not admin_in(t5))
r = zahnrad(t5, {"code": "code-AS"})
check("…mit dem Code: erhoeht", r.inhalt.get("erhoeht") is True and admin_in(t5))
_neu()
t6 = NS["generate_token"]("andreas", ts=int(time.time()) - 5, mit_2fa=True)
r = zahnrad(t6)
check("Sitzung mit IdP-MFA, KEINE 2FA (der DEV-Fall): Einrichtung statt Rechte",
      r.inhalt.get("requires_totp_setup") is True and not admin_in(t6))
check("REGEL: kein Weg 'idp_mfa' mehr in admin_erhoehen",
      "idp_mfa" not in ast.unparse(_fn("admin_erhoehen")))

# Wer NIE erhoeht wird
_neu()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
STATE["bert"] = {"totp_enabled": True, "totp_secret": "BS"}
t_app = NS["generate_token"]("andreas", ts=int(time.time()) - 5, ohne_admin=True)
r = zahnrad(t_app, {"code": "code-AS"})
check("App-/SSO-Sitzung: 403 auch mit richtigem Code", r.status_code == 403 and not admin_in(t_app))
_sig_app = t_app.split(":", 2)[2]
check("setze_admin_erhoeht verweigert eine App-/SSO-Sitzung auch direkt",
      ST.setze_admin_erhoeht(ST.schluessel(_sig_app), int(time.time()), True) is False
      and not ST.admin_erhoeht(_sig_app))
t_maus = NS["generate_token"]("andreas", ts=int(time.time()) - 6, ohne_admin=True, nur_ai_maus=True)
r = zahnrad(t_maus, {"code": "code-AS"})
check("AI-Maus-Sitzung: erreicht das Zahnrad gar nicht (Pfad) und wird nie erhoeht",
      (r is None or r.status_code == 403) and not ST.admin_erhoeht(t_maus.split(":", 2)[2]))
t_bert = NS["generate_token"]("bert", ts=int(time.time()) - 5)
r = zahnrad(t_bert, {"code": "code-BS"})
check("Nicht-Admin: 403, Code wird nicht verbraucht",
      r.status_code == 403 and not admin_in(t_bert, "bert"))
check("…Protokoll: abgewiesen (kein_admin)",
      any(a == "admin_erhoehung" and k.get("grund") == "kein_admin" for a, k in EREIGNISSE))
t_j = NS["generate_token"]("jarvis", ts=int(time.time()) - 5)
STATE["jarvis"] = {"totp_enabled": True, "totp_secret": "JS"}
r = zahnrad(t_j, {"code": "code-JS"})
check("lokaler jarvis: gleiche Regel, mit Code erhoeht", r.inhalt.get("erhoeht") is True
      and admin_in(t_j, "jarvis"))

# Den Schalter gibt es nicht mehr
check("REGEL: kein _admin_2fa_pflicht / admin_2fa_pflicht mehr in main.py",
      "admin_2fa_pflicht" not in MAIN_SRC)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
