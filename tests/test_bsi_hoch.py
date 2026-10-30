#!/usr/bin/env python3
"""Waechter: drei Hoch-Befunde aus dem BSI-Abgleich vom 2026-09-29.

  [H2]  2FA liess sich per POST /api/auth/totp/setup ohne Kennwort abschalten
        (setup schrieb totp_enabled=False und ein neues Secret).
  [H12] POST /api/feedback lief ohne Anmeldung ("anonymous") – LLM-Aufruf und
        Lernnotiz fuer jeden im Netz.
  [H14] Kundenverwaltungs-Client pruefte TLS nie (CERT_NONE) und schickte den
        API-Key an jede Gegenstelle.

Jeder Befund wird an der WIRKUNG gemessen: die Endpunkte laufen (per AST aus
main.py geholt, mit Attrappen in echter Signatur), der Client spricht mit einem
echten lokalen TLS-Server mit selbst ausgestelltem Zertifikat.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import http.server
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
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


# backend.config NUR als Stub – der echte Import schreibt die Live-settings.json.
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)

TMP = Path(tempfile.mkdtemp(prefix="waechter-bsi-hoch-"))

MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN_SRC)


def _funktionen(*namen: str) -> ast.Module:
    """Genannte Top-Level-Funktionen aus main.py, ohne Dekoratoren/Annotationen."""
    gefunden = []
    for name in namen:
        fn = next((n for n in BAUM.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == name), None)
        if fn is None:
            abbruch("%s nicht in main.py" % name)
        fn.decorator_list = []
        for a in fn.args.args + fn.args.kwonlyargs:
            a.annotation = None
        fn.returns = None
        fn.args.defaults = [ast.Constant(None) for _ in fn.args.defaults]
        gefunden.append(fn)
    mod = ast.Module(body=gefunden, type_ignores=[])
    ast.fix_missing_locations(mod)
    return mod


class _Antwort:
    def __init__(self, inhalt, status_code=200, headers=None):
        self.inhalt, self.status_code, self.headers = inhalt, status_code, headers or {}


class _Req:
    def __init__(self, body, headers=None):
        self._b = body
        self.headers = headers or {}
        # wie bei Starlette: .client gibt es immer (BSI N4 liest die IP)
        self.client = types.SimpleNamespace(host="198.51.100.9")
        self.cookies = {}    # wie Starlette: ohne Sitzungs-Cookie (BSI H4)

    async def json(self):
        if isinstance(self._b, Exception):
            raise self._b
        return self._b


# ── [H2] TOTP ────────────────────────────────────────────────────────────────
print("\n[H2] 2FA: Neu-Einrichten ersetzt/abschaltet die aktive 2FA nur mit Kennwort")

# pyotp-Attrappe in echter Signatur: random_base32(), TOTP(s).verify(code,
# valid_window=...), provisioning_uri(name=, issuer_name=). Ein Code gilt, wenn
# er "code-<secret>" lautet – deterministisch, ohne Uhr.
_zaehler = [0]
_pyotp = types.ModuleType("pyotp")


def _random_base32():
    _zaehler[0] += 1
    return "SECRET%d" % _zaehler[0]


class _TOTP:
    def __init__(self, s):
        self.s = s

    interval = 30

    def verify(self, otp, for_time=None, valid_window=0):
        return otp == "code-" + self.s

    def provisioning_uri(self, name=None, issuer_name=None):
        return "otpauth://totp/%s:%s?secret=%s" % (issuer_name, name, self.s)


_pyotp.random_base32 = _random_base32
_pyotp.TOTP = _TOTP
sys.modules["pyotp"] = _pyotp

# qrcode-Attrappe: make(uri, image_factory=, box_size=, border=).save(buf, format=)
_qr = types.ModuleType("qrcode")
_qr_img = types.ModuleType("qrcode.image")
_qr_pil = types.ModuleType("qrcode.image.pil")
_qr_pil.PilImage = object


class _Bild:
    def save(self, buf, format=None):
        buf.write(b"PNG")


_qr.make = lambda uri, image_factory=None, box_size=None, border=None: _Bild()
_qr.image = _qr_img
_qr_img.pil = _qr_pil
sys.modules.update({"qrcode": _qr, "qrcode.image": _qr_img, "qrcode.image.pil": _qr_pil})

_STATE: dict = {}


def _get_state(u):
    return dict(_STATE.get(u, {"must_change_password": True,
                               "totp_enabled": False, "totp_secret": None}))


def _set_state(u, upd):
    _STATE.setdefault(u, {"must_change_password": True,
                          "totp_enabled": False, "totp_secret": None}).update(upd)


_auth_aufrufe: list = []


def _auth(u, pw, details=None):
    _auth_aufrufe.append((u, pw))
    return pw == "richtig"


from backend import anmelde_schutz as _AS  # noqa: E402
from backend import totp_schutz as _TS     # noqa: E402
_AS.STORE_PATH = TMP / "anmelde_schutz.json"
_TS.STORE_PATH = TMP / "totp_schritte.json"
if not all(str(p).startswith(str(TMP)) for p in (_AS.STORE_PATH, _TS.STORE_PATH)):
    abbruch("Ablage zeigt aus dem Sandkasten heraus")

_ns2 = {"JSONResponse": _Antwort, "Depends": lambda x: None, "require_auth": None,
        "Request": object, "asyncio": asyncio, "__name__": "waechter",
        "_get_user_auth_state": _get_state, "_set_user_auth_state": _set_state,
        "authenticate_linux_user": _auth,
        # BSI M3: Pflicht-Pruefung in totp_disable (hier: kein Admin) und der
        # Sitzungskontext; QR-Erzeugung liegt seit M3 in _totp_vormerken.
        "_sitzung_kontext": __import__("contextvars").ContextVar("_sk", default=None),
        "_is_admin_user": lambda u: False, "_admin_2fa_pflicht": lambda: True,
        # seit b46fee6b ruft totp_verify ihn (Ruecksetz-Hinweis abraeumen)
        "_konto_hinweis_abraeumen": lambda u: None,
        # BSI N3/N4: Code nur einmal, Kennwortpruefung mit Anmeldeschutz
        "_totp_schutz": _TS, "_anmelde_schutz": _AS,
        "_norm_login": lambda n: (n or "").split("\\")[-1].strip().lower(),
        "_sicherheits_log": types.SimpleNamespace(ereignis=lambda *a, **k: {}),
        # Code-Review 2026-10-07: verify darf die Sitzung NICHT zur Sitzung
        # "mit 2FA" machen – die Attrappe zeichnet jeden Versuch auf.
        "_sitzung": types.SimpleNamespace(
            setze_mit_2fa=lambda sig, ts: _befoerdert.append((sig, ts)))}
_befoerdert: list = []
exec(compile(_funktionen("totp_setup", "_totp_vormerken", "_totp_qr_daten",
                         "totp_verify", "totp_disable",
                         "_sitzung_ist_app", "_totp_app_sperre",
                         "_totp_fehlertext", "_kennwort_schranke", "_kennwort_fehlversuch",
                         "_check_rate_limit", "_record_login_attempt",
                         "_konto_sperre_antwort"),
             "main.py", "exec"), _ns2)
_setup, _verify, _disable = _ns2["totp_setup"], _ns2["totp_verify"], _ns2["totp_disable"]


def _run(coro):
    return asyncio.run(coro)


# Positivkontrolle: frisches Konto richtet ein und aktiviert
_STATE.clear()
r = _run(_setup(_Req({}), username="anna"))
geheim1 = (r.inhalt or {}).get("secret")
check("Positivkontrolle: setup ohne aktive 2FA -> 200 mit Secret (ist %s)" % r.status_code,
      r.status_code == 200 and bool(geheim1))
if r.status_code != 200 or not geheim1:
    abbruch("setup liefert nichts – der Rest waere trivial")
r = _run(_verify(_Req({"code": "code-" + geheim1}), username="anna"))
check("Positivkontrolle: verify aktiviert mit genau diesem Secret",
      r.status_code == 200 and _STATE["anna"].get("totp_enabled") is True
      and _STATE["anna"].get("totp_secret") == geheim1)

vorher = dict(_STATE["anna"])
r = _run(_setup(_Req(ValueError("kein JSON")), username="anna"))
check("aktive 2FA: setup ohne Rumpf -> 400 (ist %s)" % r.status_code, r.status_code == 400)
check("…und die 2FA bleibt AN, Secret unveraendert",
      _STATE["anna"].get("totp_enabled") is True
      and _STATE["anna"].get("totp_secret") == geheim1)
r = _run(_setup(_Req({}), username="anna"))
check("aktive 2FA: setup ohne Kennwort -> 400 (ist %s)" % r.status_code, r.status_code == 400)
r = _run(_setup(_Req({"password": "falsch"}), username="anna"))
check("aktive 2FA: setup mit falschem Kennwort -> 401 (ist %s)" % r.status_code,
      r.status_code == 401)
check("…Zustand nach beiden Abweisungen byte-gleich", _STATE["anna"] == vorher)

r = _run(_setup(_Req({"password": "richtig"}), username="anna"))
geheim2 = (r.inhalt or {}).get("secret")
check("aktive 2FA: setup mit Kennwort -> 200 (ist %s)" % r.status_code,
      r.status_code == 200 and geheim2 and geheim2 != geheim1)
check("…die alte 2FA gilt weiter, bis das neue Secret bestaetigt ist",
      _STATE["anna"].get("totp_enabled") is True
      and _STATE["anna"].get("totp_secret") == geheim1)
r = _run(_verify(_Req({"code": "code-" + geheim1}), username="anna"))
check("verify mit Code des ALTEN Secrets aktiviert das neue nicht (ist %s)" % r.status_code,
      r.status_code == 401 and _STATE["anna"].get("totp_secret") == geheim1)
r = _run(_verify(_Req({"code": "code-" + geheim2}), username="anna"))
check("verify mit neuem Code tauscht das Secret, vorgemerktes ist weg",
      r.status_code == 200 and _STATE["anna"].get("totp_secret") == geheim2
      and _STATE["anna"].get("totp_enabled") is True
      and not _STATE["anna"].get("totp_pending_secret"))

# Altbestand: vor dem Umbau begonnenes Einrichten (Secret in totp_secret, aus)
_STATE["bert"] = {"must_change_password": False, "totp_enabled": False,
                  "totp_secret": "ALT"}
r = _run(_verify(_Req({"code": "code-ALT"}), username="bert"))
check("Altbestand: begonnenes Einrichten laesst sich noch abschliessen",
      r.status_code == 200 and _STATE["bert"].get("totp_enabled") is True)

# disable raeumt auch ein vorgemerktes Secret ab
_run(_setup(_Req({"password": "richtig"}), username="bert"))
r = _run(_disable(_Req({"password": "richtig"}), username="bert"))
check("disable raeumt ein vorgemerktes Secret mit ab",
      r.status_code == 200 and not _STATE["bert"].get("totp_pending_secret")
      and _STATE["bert"].get("totp_enabled") is False)


# ── Code-Review 2026-10-07: App-Sitzung tauscht den Faktor nicht aus ─────────
# Eine App-Anmeldung eines Admins ueberspringt die 2FA (BSI M3, ohne_admin).
# Mit setup + verify haette das Kennwort allein den Faktor ersetzt; und verify
# machte JEDE Sitzung zur Sitzung "mit 2FA" (SSO-Admin ohne 2FA -> Admin).
print("\n[Review 2026-10-07] 2FA-Aenderung aus App-Sitzung, keine Selbstbefoerderung")
_SK = _ns2["_sitzung_kontext"]
_STATE.clear()
_STATE["chef"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": "ECHT"}

# Positivkontrolle: dieselben Aufrufe aus einer BROWSER-Sitzung kommen durch
_tk = _SK.set(("chef", True, False))
try:
    r = _run(_setup(_Req({"password": "richtig"}), username="chef"))
finally:
    _SK.reset(_tk)
_pk_secret = (r.inhalt or {}).get("secret")
check("Positivkontrolle: Browser-Sitzung, setup mit Kennwort -> 200 (ist %s)" % r.status_code,
      r.status_code == 200 and bool(_pk_secret))
if r.status_code != 200 or not _pk_secret:
    abbruch("Positivkontrolle gescheitert – die App-Abweisungen waeren trivial")
_STATE["chef"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": "ECHT"}
vorher = dict(_STATE["chef"])

_tk = _SK.set(("chef", False, True))          # App-Sitzung: ohne 2FA, ohne_admin
try:
    r = _run(_setup(_Req({"password": "richtig"}), username="chef"))
    check("App-Sitzung: setup mit RICHTIGEM Kennwort -> 403 (ist %s)" % r.status_code,
          r.status_code == 403 and not (r.inhalt or {}).get("secret"))
    check("…kein Secret vorgemerkt", not _STATE["chef"].get("totp_pending_secret"))
    _STATE["chef"]["totp_pending_secret"] = "EINDRINGLING"
    r = _run(_verify(_Req({"code": "code-EINDRINGLING"}), username="chef"))
    check("App-Sitzung: verify mit gueltigem Code -> 403 (ist %s)" % r.status_code,
          r.status_code == 403)
    check("…das aktive Secret bleibt das echte", _STATE["chef"].get("totp_secret") == "ECHT")
    _STATE["chef"].pop("totp_pending_secret", None)
    r = _run(_disable(_Req({"password": "richtig"}), username="chef"))
    check("App-Sitzung: disable mit Kennwort -> 403 (ist %s)" % r.status_code,
          r.status_code == 403)
    check("…2FA bleibt an, Zustand unveraendert", _STATE["chef"] == vorher)
finally:
    _SK.reset(_tk)

# Fremdes Konto in derselben Anfrage ist nicht betroffen (Sperre gilt der SITZUNG)
_tk = _SK.set(("jemand", False, True))
try:
    _STATE["dora"] = {"must_change_password": False, "totp_enabled": False, "totp_secret": None}
    r = _run(_setup(_Req({}), username="dora"))
    check("App-Kontext eines ANDEREN Kontos sperrt dora nicht (ist %s)" % r.status_code,
          r.status_code == 200)
finally:
    _SK.reset(_tk)

# verify macht eine Sitzung ohne 2FA nicht zur Sitzung "mit 2FA"
_befoerdert.clear()
_STATE["sso"] = {"must_change_password": False, "totp_enabled": False, "totp_secret": None}
_tk = _SK.set(("sso", False, False))           # z. B. Outlook-SSO, Admin ohne 2FA
try:
    r = _run(_setup(_Req({}), username="sso"))
    s_neu = (r.inhalt or {}).get("secret")
    r = _run(_verify(_Req({"code": "code-%s" % s_neu},
                          {"Authorization": "Bearer sso:1700000000:sig"}), username="sso"))
    check("SSO-Sitzung: Einrichten selbst gelingt (Positivkontrolle, ist %s)" % r.status_code,
          r.status_code == 200 and _STATE["sso"].get("totp_enabled") is True)
    check("…aber die Sitzung wird NICHT zur Sitzung mit 2FA befoerdert (%s)" % _befoerdert,
          _befoerdert == [])
finally:
    _SK.reset(_tk)


# ── [H12] /api/feedback ──────────────────────────────────────────────────────
print("\n[H12] /api/feedback nur mit Sitzungstoken oder Agent-API-Key")

_TOKENS = {"tok-anna": "anna", "tok-gesperrt": "gesperrt"}
_llm: list = []


async def _self_improve(user_msg, bot_resp, rating, benutzer=""):
    # Signatur wie das Original (seit BSI M9 mit Herkunft ``benutzer``)
    _llm.append(rating)
    return "analyse"


class _Guard:
    @staticmethod
    def is_blocked(u):
        return u == "gesperrt"


def _agent_key_ok(k):
    return k == "agent-key"


class _ReqF(_Req):
    pass


_ns12 = {"JSONResponse": _Antwort, "Request": object, "__name__": "waechter",
         "json": json, "time": __import__("time"), "Path": Path,
         "verify_token": lambda t: _TOKENS.get(t),
         "_user_must_change": lambda u: False,
         "security_guard": _Guard, "_login_still_allowed": lambda u: True,
         "_is_valid_agent_key": _agent_key_ok,
         "_verify_agent_api_key": lambda req: _agent_key_ok(
             req.headers.get("X-API-Key", "")
             or req.headers.get("Authorization", "").replace("Bearer ", "")),
         "_feedback_self_improve": _self_improve,
         # BSI H4: der Koerper-Rueckfall laeuft ueber den ECHTEN Helfer
         "_sitzung_cookie": __import__("backend.sitzung_cookie", fromlist=["x"])}
exec(compile(_funktionen("_token_aufloesen", "api_feedback"), "main.py", "exec"), _ns12)
_feedback = _ns12["api_feedback"]

_alt_cwd = os.getcwd()
os.chdir(TMP)            # der Endpunkt schreibt relativ nach data/feedback.json
FB = TMP / "data" / "feedback.json"


def _fb(body, headers=None):
    _llm.clear()
    r = _run(_feedback(_ReqF(body, headers)))
    eintraege = json.loads(FB.read_text()) if FB.exists() else []
    return r.status_code, eintraege, list(_llm)


try:
    st, ein, llm = _fb({"token": "tok-anna", "rating": "negative",
                        "user_message": "f", "bot_response": "a"})
    check("Positivkontrolle: gueltiges Token im Rumpf -> 200, Eintrag, LLM-Analyse (%s)" % st,
          st == 200 and ein and ein[-1]["user"] == "anna" and llm == ["negative"])
    if st != 200:
        abbruch("Positivkontrolle gescheitert – die Abweisungen waeren trivial")
    anzahl = len(ein)

    for body, hdr, name in (
            ({"rating": "negative"}, None, "ohne Token"),
            ({"token": "", "rating": "wrong"}, None, "leeres Token"),
            ({"token": "geraten", "rating": "negative"}, None, "falsches Token"),
            ({"rating": "wrong"}, {"Authorization": "Bearer geraten"}, "falscher Bearer")):
        st, ein, llm = _fb(body, hdr)
        check("%s -> 401, kein Eintrag, kein LLM-Aufruf (ist %s, llm=%s)" % (name, st, llm),
              st == 401 and len(ein) == anzahl and llm == [])

    st, ein, llm = _fb({"token": "tok-gesperrt", "rating": "negative"})
    check("gesperrtes Konto -> 403, nichts geschrieben (ist %s)" % st,
          st == 403 and len(ein) == anzahl and llm == [])
    st, ein, llm = _fb("kein dict")
    check("Rumpf kein Objekt -> 400 statt Absturz (ist %s)" % st, st == 400)

    st, ein, _ = _fb({"token": "agent-key", "rating": "positive"})
    check("Agent-API-Key im Rumpf (Android/Windows-App) -> 200 als 'api' (ist %s)" % st,
          st == 200 and ein[-1]["user"] == "api")
    st, ein, _ = _fb({"rating": "positive"}, {"Authorization": "Bearer tok-anna"})
    check("Sitzungstoken im Header -> 200 (ist %s)" % st,
          st == 200 and ein[-1]["user"] == "anna")
    check("kein Eintrag traegt mehr 'anonymous'",
          all(e.get("user") != "anonymous" for e in ein))
finally:
    os.chdir(_alt_cwd)


# ── [H14] Kundenverwaltung: TLS-Pruefung ────────────────────────────────────
print("\n[H14] Kundenverwaltung prueft TLS; selbst ausgestellt nur verankert")

KV_SRC = (ROOT / "backend" / "kundenverwaltung_client.py").read_text(encoding="utf-8")
kv_baum = ast.parse(KV_SRC)
cert_none = [n.lineno for n in ast.walk(kv_baum)
             if isinstance(n, ast.Attribute) and n.attr == "CERT_NONE"]
verify_mode = [n.lineno for n in ast.walk(kv_baum)
               if isinstance(n, ast.Assign) and any(
                   isinstance(t, ast.Attribute) and t.attr == "verify_mode"
                   for t in n.targets)]
check("REGEL: kein ssl.CERT_NONE im Client-Code (Zeilen: %s)" % cert_none, not cert_none)
check("REGEL: keine Zuweisung an verify_mode (Zeilen: %s)" % verify_mode, not verify_mode)

# Selbst ausgestelltes Zertifikat fuer 127.0.0.1 (SAN IP), plus ein zweites,
# damit "anderes Zertifikat" messbar ist
def _zert(name):
    key, crt = TMP / (name + ".key"), TMP / (name + ".crt")
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(crt), "-days", "2",
                        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        abbruch("openssl req gescheitert: %s" % r.stderr[-300:])
    return key, crt


_EMPFANGEN: list = []


class _Handler(http.server.BaseHTTPRequestHandler):
    def _antwort(self):
        # Namen klein: urllib schreibt "X-api-key", nicht "X-API-Key"
        _EMPFANGEN.append({k.lower(): v for k, v in self.headers.items()})
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        roh = json.dumps({"event": [{"id": "7", "text": "Zeile"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    do_GET = do_POST = _antwort

    def log_message(self, *a):
        pass


class _Srv(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass    # abgewiesene Handshakes sind hier der Messgegenstand, kein Fehler


def _server(key, crt, port=0):
    srv = _Srv(("127.0.0.1", port), _Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(crt), str(key))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


k1, c1 = _zert("a")
k2, c2 = _zert("b")
srv = _server(k1, c1)
BASE = "https://127.0.0.1:%d/api" % srv.server_address[1]

_JIRA = {"ibs_api_url": BASE, "ibs_api_key": "GEHEIM-KEY"}
_jc = types.ModuleType("backend.jira_client")
_jc.get_jira_config = lambda: dict(_JIRA)
sys.modules["backend.jira_client"] = _jc
import backend  # noqa: E402
backend.jira_client = _jc
from backend import kundenverwaltung_client as kv  # noqa: E402
from backend import sap_cert  # noqa: E402

# Positivkontrolle: der Server spricht TLS und legt sein Zertifikat vor
try:
    zert = kv.zertifikat_pruefen(BASE)
except Exception as e:  # noqa: BLE001
    abbruch("Testserver nicht erreichbar: %s" % e)
check("Positivkontrolle: Zertifikat abrufbar, NICHT systemvertraut, verankerbar",
      zert.get("fingerprint", "").startswith("sha256:") and zert.get("system_ok") is False
      and zert.get("pin_ok") is True and "pem" not in zert)

_EMPFANGEN.clear()
erg = kv.test_connection()
check("ohne Anker: Verbindungstest scheitert mit Zertifikatsfehler",
      erg.get("reachable") is False and erg.get("zertifikat_fehler") is True)
erg = kv.tickets_by_buzzwords("drucker")
check("ohne Anker: Ticketsuche scheitert", erg.get("ok") is False)
check("…und der API-Key hat den Server NIE erreicht (%d Anfragen)" % len(_EMPFANGEN),
      not _EMPFANGEN)

try:
    kv.zertifikat_verankern(BASE, "sha256:" + "0" * 64)
    falsch_abgewiesen = False
except sap_cert.ZertFehler:
    falsch_abgewiesen = True
check("Verankern mit falschem Fingerabdruck wird abgewiesen", falsch_abgewiesen)

eintrag = kv.zertifikat_verankern(BASE, zert["fingerprint"])
_JIRA[kv.CERT_FELD] = eintrag
_EMPFANGEN.clear()
erg = kv.test_connection()
check("mit Anker: Verbindungstest erreicht den Server (%s)" % erg.get("status"),
      erg.get("reachable") is True and erg.get("status") == 200)
erg = kv.tickets_by_buzzwords("drucker")
check("mit Anker: Ticketsuche liefert das Ergebnis", erg.get("ok") is True
      and erg.get("count") == 1)
check("…mit API-Key an den verankerten Server",
      any(h.get("x-api-key") == "GEHEIM-KEY" for h in _EMPFANGEN))

# Anderes Zertifikat an derselben Adresse -> Anker haelt nicht mehr
port_alt = srv.server_address[1]
srv.shutdown()
srv.server_close()
try:
    srv_b = _server(k2, c2, port_alt)
    _EMPFANGEN.clear()
    erg = kv.test_connection()
    check("Zertifikat getauscht (gleiche Adresse): abgewiesen, Key nicht gesendet",
          erg.get("reachable") is False and erg.get("zertifikat_fehler") is True
          and not _EMPFANGEN)
    srv_b.shutdown()
except OSError as e:
    print("  (Tausch-Probe uebersprungen: Port %d nicht wieder belegbar: %s)" % (port_alt, e))

# Anker fuer anderen Host/Port gilt nicht (kein stilles Mitschleppen) –
# gemessen an der WIRKUNG: derselbe Server, dessen Zertifikat genau im Anker
# steht, wird abgewiesen, sobald der Anker auf einen anderen Port lautet.
# Dazu braucht es den urspruenglichen Server wieder.
srv_c = _server(k1, c1)
BASE_C = "https://127.0.0.1:%d/api" % srv_c.server_address[1]
_JIRA["ibs_api_url"] = BASE_C
_JIRA[kv.CERT_FELD] = dict(eintrag, port=srv_c.server_address[1])
erg = kv.test_connection()
check("Positivkontrolle: Anker auf den neuen Port -> erreichbar",
      erg.get("reachable") is True)
_JIRA[kv.CERT_FELD] = dict(eintrag, port=srv_c.server_address[1] + 1)
_EMPFANGEN.clear()
erg = kv.test_connection()
check("Anker fuer anderen Port greift NICHT (abgewiesen, Key nicht gesendet)",
      erg.get("reachable") is False and not _EMPFANGEN)
_JIRA[kv.CERT_FELD] = dict(eintrag, port=srv_c.server_address[1], host="127.0.0.2")
erg = kv.test_connection()
check("Anker fuer anderen Host greift NICHT", erg.get("reachable") is False)
srv_c.shutdown()
ctx = kv.ssl_kontext(BASE, {kv.CERT_FELD: eintrag})
check("Anker ohne gemessene Namensabweichung: Namensabgleich bleibt AN",
      eintrag.get("name_abweichung") is False and ctx.check_hostname is True
      and ctx.verify_mode == ssl.CERT_REQUIRED)
ctx = kv.ssl_kontext(BASE, {kv.CERT_FELD: dict(eintrag, pem="kaputt")})
check("unbrauchbarer Anker -> fail-closed auf gewoehnliche Pruefung",
      ctx.verify_mode == ssl.CERT_REQUIRED)
ctx = kv.ssl_kontext(BASE, {kv.CERT_FELD: dict(eintrag, name_abweichung=True)})
check("Namensabweichung: Namensabgleich aus, Pruefung bleibt CERT_REQUIRED",
      ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is False)

# Endpunkte: vorhanden, nur fuer Administratoren
_eps = {}
for n in BAUM.body:
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.args and isinstance(d.args[0], ast.Constant)
                    and str(d.args[0].value).startswith("/api/kundenverwaltung/zertifikat")):
                deps = [ast.unparse(x) for x in ast.walk(n.args) if isinstance(x, ast.Call)]
                _eps[(d.func.attr, d.args[0].value)] = deps
check("drei Zertifikats-Endpunkte (probe/trust/delete) vorhanden: %s" % sorted(_eps),
      set(_eps) == {("post", "/api/kundenverwaltung/zertifikat/probe"),
                    ("post", "/api/kundenverwaltung/zertifikat/trust"),
                    ("delete", "/api/kundenverwaltung/zertifikat")})
check("…alle hinter require_local_auth",
      _eps and all(any("require_local_auth" in x for x in v) for v in _eps.values()))

# Oberflaeche: Baustein eingebunden, Reihenfolge der Skripte stimmt
SET = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
p_cert, p_kv = SET.find("/static/js/sapcert.js?v="), SET.find("/static/js/kundenverwaltung.js?v=")
check("settings.html: Anker-Container #kv-cert vorhanden", 'id="kv-cert"' in SET)
check("settings.html: sapcert.js vor kundenverwaltung.js geladen",
      0 <= p_cert < p_kv)
KVJS = (ROOT / "frontend" / "js" / "kundenverwaltung.js").read_text(encoding="utf-8")
check("kundenverwaltung.js haengt den Baustein mit der Kundenverwaltungs-Basis ein",
      "SapCert.mount" in KVJS and "'/api/kundenverwaltung/zertifikat'" in KVJS)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
