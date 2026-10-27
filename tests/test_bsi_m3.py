#!/usr/bin/env python3
"""Waechter: BSI M3 – Anmeldeschutz je Konto (dauerhaft) und 2FA-Pflicht fuer Admins.

Befund (BSI-Abgleich 2026-09-29): Fehlversuche nur je IP und nur im Speicher;
2FA fuer Administratoren freiwillig.

Gemessen an der WIRKUNG:
  [A] ``backend/anmelde_schutz.py`` direkt (Ablage im Wegwerf-Verzeichnis):
      Sperre je Konto ueber wechselnde IPs, Ueberleben eines Neustarts, Ablauf,
      Ruecksetzen bei Erfolg, Aufheben, IP-Grenze.
  [B] der echte Login-Endpunkt (per AST aus main.py, Attrappen in echter
      Signatur, echtes ``sitzung_token``): Sperre VOR der Kennwortpruefung,
      Pflicht-Einrichtung fuer Admins (ohne Token bis zum Code), kein Zwang
      fuer Nicht-Admins und bei abgeschalteter Pflicht.
  [C] Admin-Rechte haengen an der SITZUNG: ``_user_is_admin``/``require_local_auth``
      nach ``verify_token`` – ohne 2FA kein Admin, fremde Konten unberuehrt,
      ausserhalb einer Anfrage unveraendert; Kennwortwechsel erbt das Merkmal;
      ``totp_disable`` verweigert Admins unter der Pflicht; Add-in-SSO stellt
      kein Token "mit 2FA" aus.
  [D] AI-Maus (Betreiberentscheid 2026-10-27): keine 2FA-Abfrage fuer IRGENDEIN
      Konto, dafuer gilt die Sitzung nur auf /api/ai-mouse/* und /api/generated/*
      (ohne Admin-Seiten) und nie als Admin.

``backend.config`` nur als Stub. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

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
EINST = {"admin_2fa_pflicht": True}
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
exec(_funktionen("generate_token", "verify_token", "_epoche_widerrufen", "_admin_2fa_pflicht", "_sitzung_ohne_admin",
                 "_ist_app_anmeldung", "_ist_ai_maus_anmeldung", "_user_is_admin",
                 "_is_admin_user", "_admin_verweigert_text", "require_local_auth",
                 "_check_rate_limit", "_record_login_attempt", "_konto_sperre_antwort",
                 "_totp_vormerken", "login", "_login_ablauf", "_anmeldung_protokollieren",
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
    EINST["admin_2fa_pflicht"] = True
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

# Pflicht-Einrichtung
_neu()
r = anmelden("andreas")
check("Admin ohne 2FA: kein Token, requires_totp_setup",
      not r.inhalt.get("token") and r.inhalt.get("requires_totp_setup") is True)
check("…mit QR und Schluessel", bool(r.inhalt.get("qr_code")) and bool(r.inhalt.get("secret")))
check("…und einem Hinweis fuer Clients ohne Einrichtungsmaske", "Pflicht" in str(r.inhalt.get("error")))
geheim = str(r.inhalt.get("secret") or "")
check("…Secret ist nur vorgemerkt (2FA noch aus)",
      _get_state("andreas").get("totp_pending_secret") == geheim and not _get_state("andreas").get("totp_enabled"))
r = anmelden("andreas", code="code-FALSCH")
check("falscher Einrichtungs-Code: 401, kein Token",
      r.status_code == 401 and not r.inhalt.get("token") and r.inhalt.get("requires_totp_setup"))
check("…zaehlt als Fehlversuch",
      len((json.loads(AS.STORE_PATH.read_text()) if AS.STORE_PATH.exists() else {})
          .get("konto", {}).get("andreas", [])) == 1)
r = anmelden("andreas", code="code-" + geheim)
tok = r.inhalt.get("token") or ""
check("richtiger Code: Token", r.status_code == 200 and r.inhalt.get("success") and bool(tok))
check("…2FA ist danach aktiv mit dem vorgemerkten Secret",
      _get_state("andreas").get("totp_enabled") and _get_state("andreas").get("totp_secret") == geheim
      and not _get_state("andreas").get("totp_pending_secret"))
check("…Sitzung traegt das Merkmal 'mit 2FA'", ST.mit_2fa(tok.split(":", 2)[2]) if tok else False)
r = anmelden("andreas")
check("naechste Anmeldung verlangt den Code (requires_totp)", r.inhalt.get("requires_totp") is True
      and not r.inhalt.get("token"))
r = anmelden("andreas", code="code-" + geheim)
check("…derselbe Code gleich noch einmal: abgewiesen (BSI N3)",
      r.status_code == 401 and not r.inhalt.get("token")
      and "bereits verwendet" in str(r.inhalt.get("error")))
# ein Zeitfenster spaeter (die Attrappe kennt keine Zeit – der Merker wird geleert)
TS._zuruecksetzen_fuer_test()
TS.STORE_PATH.unlink(missing_ok=True)
TS._zuruecksetzen_fuer_test()
AS.erfolg("andreas")
r = anmelden("andreas", code="code-" + geheim)
check("…mit Code: Token 'mit 2FA'", bool(r.inhalt.get("token"))
      and ST.mit_2fa(r.inhalt["token"].split(":", 2)[2]))

_neu()
r = anmelden("jarvis")
check("lokaler Admin jarvis faellt ebenfalls unter die Pflicht", r.inhalt.get("requires_totp_setup") is True)

_neu()
EINST["admin_2fa_pflicht"] = False
r = anmelden("andreas")
check("Pflicht AUS: Admin ohne 2FA bekommt ein Token",
      r.status_code == 200 and bool(r.inhalt.get("token")))
check("…aber ohne Merkmal 'mit 2FA'",
      not ST.mit_2fa(r.inhalt.get("token", "x:1:x").split(":", 2)[2]))

# ── [B2] Android-/Windows-App ───────────────────────────────────────────────
print("\n[B2] App-Anmeldung: Admin-Konto ohne Admin-Rechte")
_neu()
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "AS"}
r = anmelden("andreas")
if r.inhalt.get("requires_totp") is not True:
    abbruch("Positivkontrolle: Admin mit 2FA im Browser wird nicht nach dem Code gefragt")
for name, kw in (("client=android", {"client": "android"}),
                 ("client=windows", {"client": "windows"}),
                 ("bestehende Android-App (OkHttp)", {"ua": "okhttp/4.12.0"}),
                 ("bestehende Windows-App (Go)", {"ua": "Go-http-client/1.1"})):
    r = anmelden("andreas", **kw)
    check("App (%s): Admin mit 2FA bekommt ein Token ohne Code" % name,
          r.status_code == 200 and bool(r.inhalt.get("token")))
    check("…Sitzung 'ohne Admin', nicht 'mit 2FA'",
          ST.ohne_admin(_sig(r)) and not ST.mit_2fa(_sig(r)))
    check("…Antwort meldet is_admin false", r.inhalt.get("is_admin") is False)
STATE.pop("andreas")
r = anmelden("andreas", client="android")
check("App: Admin OHNE 2FA unter der Pflicht – keine Einrichtung, Token ohne Admin",
      bool(r.inhalt.get("token")) and "requires_totp_setup" not in r.inhalt and ST.ohne_admin(_sig(r)))
EINST["admin_2fa_pflicht"] = False
r = anmelden("andreas", client="windows")
check("App bei Pflicht AUS: trotzdem 'ohne Admin'", ST.ohne_admin(_sig(r)))
EINST["admin_2fa_pflicht"] = True
STATE["bert"] = {"totp_enabled": True, "totp_secret": "BS"}
r = anmelden("bert", client="android")
check("App: Nicht-Admin mit 2FA braucht weiter den Code (kein 2FA-Umweg)",
      r.inhalt.get("requires_totp") is True and not r.inhalt.get("token"))
r = anmelden("carla", client="android")
check("App: Nicht-Admin ohne 2FA – normales Token, kein Merkmal",
      bool(r.inhalt.get("token")) and not ST.ohne_admin(_sig(r)))
r = anmelden("andreas", ua="Mozilla/5.0 okhttp-Nachahmer")
check("Browser mit 'okhttp' irgendwo im Text gilt NICHT als App",
      r.inhalt.get("requires_totp_setup") is True)

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
mit = NS["generate_token"]("andreas", ts=_jetzt - 20, mit_2fa=True)
j_ohne = NS["generate_token"]("jarvis", ts=_jetzt - 30)
if not in_kontext(lambda: verify(mit) == "andreas" and is_admin("andreas")):
    abbruch("Positivkontrolle: Admin-Sitzung mit 2FA ist kein Admin")
check("Sitzung OHNE 2FA: _is_admin_user False",
      in_kontext(lambda: verify(ohne) == "andreas" and not is_admin("andreas")))
check("Sitzung OHNE 2FA: auch _user_is_admin False",
      in_kontext(lambda: (verify(ohne), user_is_admin("andreas"))[1]) is False)
check("lokaler jarvis OHNE 2FA: kein Admin (keine ALLOWED_USERS-Abkuerzung)",
      in_kontext(lambda: (verify(j_ohne), is_admin("jarvis"))[1]) is False)
check("Pruefung eines FREMDEN Kontos bleibt unberuehrt",
      in_kontext(lambda: (verify(ohne), is_admin("jarvis"))[1]) is True)
check("ausserhalb einer Anfrage (kein Kontext): Konto-Rechte unveraendert",
      in_kontext(lambda: is_admin("andreas")) is True)
EINST["admin_2fa_pflicht"] = False
check("Pflicht AUS: Sitzung ohne 2FA hat Admin-Rechte",
      in_kontext(lambda: (verify(ohne), is_admin("andreas"))[1]) is True)
EINST["admin_2fa_pflicht"] = True


def _local(tok):
    async def f():
        try:
            return await req_local(_Req(token=tok))
        except _HTTPException as e:
            return e
    return in_kontext(lambda: asyncio.run(f()))


e = _local(ohne)
check("require_local_auth: Sitzung ohne 2FA -> 403",
      isinstance(e, _HTTPException) and e.status_code == 403)
check("…mit einem Text, der die fehlende 2FA nennt",
      isinstance(e, _HTTPException) and "Zwei-Faktor" in str(e.detail))
check("require_local_auth: Sitzung mit 2FA -> durch", _local(mit) == "andreas")
e = _local(j_ohne)
check("require_local_auth: lokaler jarvis OHNE 2FA -> 403",
      isinstance(e, _HTTPException) and e.status_code == 403)
e = _local(NS["generate_token"]("bert", ts=_jetzt - 20, mit_2fa=True))
check("require_local_auth: Nicht-Admin -> 403 mit dem Rechte-Text",
      isinstance(e, _HTTPException) and "Zwei-Faktor" not in str(e.detail))

# App-Sitzung: nie Admin, unabhaengig von 2FA und Pflicht
app_tok = NS["generate_token"]("andreas", ts=_jetzt - 50, ohne_admin=True)
check("App-Sitzung: _is_admin_user False",
      in_kontext(lambda: (verify(app_tok), is_admin("andreas"))[1]) is False)
EINST["admin_2fa_pflicht"] = False
check("App-Sitzung bei Pflicht AUS: weiterhin kein Admin",
      in_kontext(lambda: (verify(app_tok), is_admin("andreas"))[1]) is False)
EINST["admin_2fa_pflicht"] = True
e = _local(app_tok)
check("require_local_auth: App-Sitzung -> 403 mit Hinweis auf die Weboberflaeche",
      isinstance(e, _HTTPException) and e.status_code == 403 and "App" in str(e.detail))
neu_app = NS["_sitzungen_nach_kennwortwechsel"]("andreas", _Req(token=app_tok))
check("Kennwortwechsel in der App-Sitzung: Ersatz-Token bleibt 'ohne Admin'",
      ST.ohne_admin(neu_app.split(":", 2)[2]))

# Kennwortwechsel erbt das Merkmal
neu_mit = NS["_sitzungen_nach_kennwortwechsel"]("andreas", _Req(token=mit))
neu_ohne = NS["_sitzungen_nach_kennwortwechsel"]("bert", _Req(token=NS["generate_token"]("bert", ts=_jetzt - 40)))
check("Kennwortwechsel in einer Sitzung mit 2FA: Ersatz-Token 'mit 2FA'",
      ST.mit_2fa(neu_mit.split(":", 2)[2]))
check("Kennwortwechsel ohne 2FA: Ersatz-Token ohne Merkmal",
      not ST.mit_2fa(neu_ohne.split(":", 2)[2]))

# Merkmal ueberlebt einen Neustart
ST._zuruecksetzen_fuer_test()
check("Merkmal 'mit 2FA' ueberlebt einen Neustart", ST.mit_2fa(mit.split(":", 2)[2]))
check("Merkmal 'ohne Admin' ueberlebt einen Neustart", ST.ohne_admin(app_tok.split(":", 2)[2]))

# totp_disable
STATE["andreas"] = {"totp_enabled": True, "totp_secret": "S"}
STATE["bert"] = {"totp_enabled": True, "totp_secret": "S"}
dis = NS["totp_disable"]
r = in_kontext(lambda: asyncio.run(dis(_Req({"password": "richtig"}), "andreas")))
check("totp_disable: Admin unter der Pflicht -> 403, 2FA bleibt an",
      r.status_code == 403 and _get_state("andreas").get("totp_enabled"))
r = in_kontext(lambda: asyncio.run(dis(_Req({"password": "richtig"}), "bert")))
check("totp_disable: Nicht-Admin darf weiterhin abschalten",
      r.status_code == 200 and not _get_state("bert").get("totp_enabled"))

# Add-in-SSO: Token nie "mit 2FA" (REGEL am Syntaxbaum – der Endpunkt braucht
# ein echtes Exchange-Token und ist hier nicht ausfuehrbar)
sso = _fn("_addin_sso_ablauf")
gen_aufrufe = [k for k in ast.walk(sso) if isinstance(k, ast.Call)
               and isinstance(k.func, ast.Name) and k.func.id == "generate_token"]
check("addin_sso stellt genau ein Token aus", len(gen_aufrufe) == 1)
check("…ohne mit_2fa", all(not any(kw.arg == "mit_2fa" for kw in k.keywords) for k in gen_aufrufe))

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
check("AI-Maus: Admin OHNE 2FA unter der Pflicht – keine Einrichtung, Token",
      bool(r.inhalt.get("token")) and "requires_totp_setup" not in r.inhalt)
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
check("_AnfragePfadMiddleware ist registriert und als letzte (aeusserste) Schicht",
      len(_pfad_mw) == 1 and _pfad_mw[0].lineno == _letzte)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
