#!/usr/bin/env python3
"""Waechter: vorhandenen 2FA-Schluessel fuer eine ZWEITE Authenticator-App zeigen.

POST /api/auth/totp/show (2026-10-30). Fuer Administratoren ist die 2FA Pflicht –
Abschalten und Neu-Einrichten ist dort kein Weg, und /totp/setup TAUSCHT das
Secret (die erste App waere danach wertlos). Der neue Weg zeigt das AKTIVE
Secret noch einmal und aendert nichts.

Gemessen an der WIRKUNG: der Endpunkt laeuft (per AST aus main.py geholt) mit
dem ECHTEN Code-Schutz (totp_schutz) und dem ECHTEN Anmeldeschutz
(anmelde_schutz) im Sandkasten; pyotp/qrcode als Attrappen in echter Signatur.

Zusagen:
  * Herausgabe nur mit Kennwort UND aktuellem Code, nie aus einer App-Sitzung.
  * Der Zustand bleibt byte-gleich (kein neues Secret, nichts vorgemerkt).
  * Ein falscher Code zaehlt wie ein Fehlversuch – nach genug davon sperrt das
    Konto auch fuer diesen Weg (sonst waeren die Codes hier ungedrosselt
    durchprobierbar).
  * Liegt das Secret im Root-Broker, gibt es nichts heraus (409 mit Weg), und
    der eingegebene Code wird dabei NICHT verbraucht.
  * Einrichten und Anzeigen bauen den QR an EINER Stelle (_totp_qr_daten).

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import sys
import tempfile
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

TMP = Path(tempfile.mkdtemp(prefix="waechter-totp-zweit-"))
BAUM = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))


def _fn(name: str):
    fn = next((n for n in BAUM.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
              None)
    if fn is None:
        abbruch("%s nicht in main.py" % name)
    return fn


def _funktionen(*namen: str) -> ast.Module:
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
    return mod


class _Antwort:
    def __init__(self, inhalt, status_code=200, headers=None):
        self.inhalt, self.status_code, self.headers = inhalt, status_code, headers or {}


class _Req:
    def __init__(self, body):
        self._b = body
        self.headers = {}
        self.client = types.SimpleNamespace(host="198.51.100.9")
        self.cookies = {}

    async def json(self):
        if isinstance(self._b, Exception):
            raise self._b
        return self._b


# pyotp-Attrappe in echter Signatur: TOTP(s).verify(code, for_time=, valid_window=),
# provisioning_uri(name=, issuer_name=), .interval. Ein Code gilt, wenn er
# "code-<secret>" lautet – deterministisch, ohne Uhr.
_pyotp = types.ModuleType("pyotp")


class _TOTP:
    interval = 30

    def __init__(self, s):
        self.s = s

    def verify(self, otp, for_time=None, valid_window=0):
        return otp == "code-" + self.s

    def provisioning_uri(self, name=None, issuer_name=None):
        return "otpauth://totp/%s:%s?secret=%s&issuer=%s" % (issuer_name, name, self.s,
                                                             issuer_name)


_pyotp.TOTP = _TOTP
_pyotp.random_base32 = lambda: "NEUESGEHEIMNIS"
sys.modules["pyotp"] = _pyotp

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

from backend import anmelde_schutz as _AS  # noqa: E402
from backend import totp_schutz as _TS     # noqa: E402
_AS.STORE_PATH = TMP / "anmelde_schutz.json"
_TS.STORE_PATH = TMP / "totp_schritte.json"
if not all(str(p).startswith(str(TMP)) for p in (_AS.STORE_PATH, _TS.STORE_PATH)):
    abbruch("Ablage zeigt aus dem Sandkasten heraus")

_STATE: dict = {}
_LOG: list = []


def _get_state(u):
    return dict(_STATE.get(u, {"must_change_password": True,
                               "totp_enabled": False, "totp_secret": None}))


def _set_state(u, upd):
    _STATE.setdefault(u, {"must_change_password": True,
                          "totp_enabled": False, "totp_secret": None}).update(upd)


def _ereignis(art, *, benutzer="", ip="", ergebnis="", **details):
    _LOG.append((art, benutzer, ergebnis, details))
    return {}


_SK = contextvars.ContextVar("_sk", default=None)
NS = {"JSONResponse": _Antwort, "Depends": lambda x: None, "require_auth": None,
      "Request": object, "asyncio": asyncio, "time": __import__("time"),
      "__name__": "waechter",
      "_get_user_auth_state": _get_state, "_set_user_auth_state": _set_state,
      "authenticate_linux_user": lambda u, pw, details=None: pw == "richtig",
      "_sitzung_kontext": _SK,
      "_totp_schutz": _TS, "_anmelde_schutz": _AS,
      "_norm_login": lambda n: (n or "").split("\\")[-1].strip().lower(),
      "_sicherheits_log": types.SimpleNamespace(ereignis=_ereignis)}
exec(compile(_funktionen("totp_show", "totp_setup", "_totp_vormerken", "_totp_qr_daten",
                         "_sitzung_ist_app", "_totp_app_sperre", "_totp_fehlertext",
                         "_kennwort_schranke", "_kennwort_fehlversuch",
                         "_check_rate_limit", "_record_login_attempt",
                         "_konto_sperre_antwort", "_totp_im_broker", "_totp_secret_lesbar"),
             "main.py", "exec"), NS)
_show = NS["totp_show"]


def _run(coro):
    return asyncio.run(coro)


def _neu():
    _STATE.clear()
    _LOG.clear()
    for p in (_AS.STORE_PATH, _TS.STORE_PATH):
        if p.exists():
            p.unlink()
    for mod in (_AS, _TS):
        rs = getattr(mod, "_zuruecksetzen_fuer_test", None) or getattr(mod, "_reset_fuer_tests", None)
        if rs:
            rs()


def _ohne_secret(r) -> bool:
    i = r.inhalt or {}
    return not i.get("secret") and not i.get("qr_code") and "GEHEIM" not in str(i)


GEHEIM = "GEHEIMANNA"

# ── 1. Positivkontrolle ─────────────────────────────────────────────────────
print("\n[1] Positivkontrolle: Kennwort + Code geben das AKTIVE Secret heraus")
_neu()
_STATE["anna"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": GEHEIM}
vorher = dict(_STATE["anna"])
r = _run(_show(_Req({"password": "richtig", "code": "code-" + GEHEIM}), username="anna"))
i = r.inhalt or {}
check("200 mit genau dem aktiven Secret (ist %s)" % r.status_code,
      r.status_code == 200 and i.get("secret") == GEHEIM)
if r.status_code != 200 or i.get("secret") != GEHEIM:
    abbruch("der Gutfall liefert nichts – alle Abweisungen waeren trivial wahr")
check("QR-Code als PNG-Daten-URL", str(i.get("qr_code", "")).startswith("data:image/png;base64,"))
check("URI traegt Secret und Aussteller 'Jarvis'",
      "secret=" + GEHEIM in str(i.get("uri")) and "Jarvis" in str(i.get("uri")))
check("Zustand byte-gleich (kein neues Secret, nichts vorgemerkt)", _STATE["anna"] == vorher)
check("Sicherheitsprotokoll: 'totp_angezeigt' mit Konto",
      any(e[0] == "totp_angezeigt" and e[1] == "anna" for e in _LOG))

# Dieselbe Anzeige wie beim Einrichten: gleicher Name, gleicher Aussteller
r_setup = _run(NS["totp_setup"](_Req({}), username="bert"))
uri_setup = (r_setup.inhalt or {}).get("uri", "")
check("Einrichten und Anzeigen bauen die URI gleich (nur das Secret unterscheidet)",
      bool(uri_setup) and uri_setup.replace("NEUESGEHEIMNIS", GEHEIM).replace("bert", "anna")
      == i.get("uri"))

# ── 2. Abweisungen ──────────────────────────────────────────────────────────
print("\n[2] Ohne Kennwort UND Code kein Secret")
r = _run(_show(_Req({"password": "richtig", "code": "code-" + GEHEIM}), username="anna"))
check("derselbe Code ein zweites Mal -> 401, kein Secret (ist %s)" % r.status_code,
      r.status_code == 401 and _ohne_secret(r))
for body, name in (({"password": "richtig"}, "ohne Code"),
                   ({"code": "code-" + GEHEIM}, "ohne Kennwort"),
                   (ValueError("kein JSON"), "ohne Rumpf"),
                   (["x"], "Rumpf keine Abbildung")):
    r = _run(_show(_Req(body), username="anna"))
    check("%s -> 400, kein Secret (ist %s)" % (name, r.status_code),
          r.status_code == 400 and _ohne_secret(r))

_neu()
_STATE["anna"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": GEHEIM}
r = _run(_show(_Req({"password": "falsch", "code": "code-" + GEHEIM}), username="anna"))
check("falsches Kennwort -> 401, kein Secret (ist %s)" % r.status_code,
      r.status_code == 401 and _ohne_secret(r))
check("…als Kennwort-Fehlversuch protokolliert",
      any(e[0] == "kennwort_pruefung" for e in _LOG))
r = _run(_show(_Req({"password": "richtig", "code": "code-" + GEHEIM}), username="anna"))
check("…und der Code wurde dabei NICHT verbraucht (gleicher Code geht danach)",
      r.status_code == 200 and (r.inhalt or {}).get("secret") == GEHEIM)

_neu()
_STATE["anna"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": GEHEIM}
r = _run(_show(_Req({"password": "richtig", "code": "code-ANDERES"}), username="anna"))
check("falscher Code -> 401, kein Secret (ist %s)" % r.status_code,
      r.status_code == 401 and _ohne_secret(r))
check("…unter eigener Art protokolliert ('totp_pruefung', nicht 'falsches Kennwort')",
      any(e[0] == "totp_pruefung" for e in _LOG)
      and not any(e[0] == "kennwort_pruefung" for e in _LOG))

_neu()
_STATE["carl"] = {"must_change_password": False, "totp_enabled": False, "totp_secret": None}
r = _run(_show(_Req({"password": "richtig", "code": "code-x"}), username="carl"))
check("2FA nicht eingeschaltet -> 400 (ist %s)" % r.status_code, r.status_code == 400)

_neu()
_STATE["anna"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": GEHEIM}
tok = _SK.set(("anna", False, True))      # App-Sitzung (ohne_admin)
try:
    r = _run(_show(_Req({"password": "richtig", "code": "code-" + GEHEIM}), username="anna"))
finally:
    _SK.reset(tok)
check("App-Sitzung -> 403, kein Secret (ist %s)" % r.status_code,
      r.status_code == 403 and _ohne_secret(r))

# ── 3. Drossel: falsche Codes sperren das Konto ─────────────────────────────
print("\n[3] Falsche Codes laufen in den Anmeldeschutz")
_neu()
_STATE["anna"] = {"must_change_password": False, "totp_enabled": True, "totp_secret": GEHEIM}
grenze = max(int(getattr(_AS, "KONTO_MAX", 5)), int(getattr(_AS, "IP_MAX", 5))) + 1
stati = []
for n in range(grenze):
    stati.append(_run(_show(_Req({"password": "richtig", "code": "code-FALSCH%d" % n}),
                            username="anna")).status_code)
r = _run(_show(_Req({"password": "richtig", "code": "code-" + GEHEIM}), username="anna"))
check("nach %d falschen Codes: auch der RICHTIGE Code gibt nichts heraus (429, ist %s; Folge %s)"
      % (grenze, r.status_code, stati), r.status_code == 429 and _ohne_secret(r))

# ── 4. Secret im Root-Broker / nicht lesbar ─────────────────────────────────
print("\n[4] Secret, das das Backend nicht kennt")
from backend.broker import freigabe as _F  # noqa: E402
from backend import geheimnis_tresor as _GT  # noqa: E402
_neu()
_STATE["jarvis"] = {"must_change_password": False, "totp_enabled": True,
                    "totp_secret": _F.MARKE_IM_BROKER}
r = _run(_show(_Req({"password": "richtig", "code": "code-" + _F.MARKE_IM_BROKER}),
               username="jarvis"))
check("Secret im Broker -> 409 (ist %s)" % r.status_code, r.status_code == 409)
check("…die Meldung nennt den Weg (jarvis-broker-admin totp-zeigen <konto>)",
      "jarvis-broker-admin totp-zeigen jarvis" in str((r.inhalt or {}).get("error")))
check("…gibt den Verweis nicht als Secret heraus", _ohne_secret(r)
      and _F.MARKE_IM_BROKER not in str((r.inhalt or {}).get("secret") or ""))
# Die Ablage fuehrt "<konto>|<hash>" je verbrauchtem Schritt
check("…und verbraucht keinen Code (kein Eintrag fuer das Konto in der Ablage)",
      not _TS.STORE_PATH.exists() or '"jarvis|' not in _TS.STORE_PATH.read_text())

_neu()
_STATE["dora"] = {"must_change_password": False, "totp_enabled": True,
                  "totp_secret": _GT.PRAEFIX_WERT + "verpackt"}
r = _run(_show(_Req({"password": "richtig", "code": "code-x"}), username="dora"))
check("Secret noch verpackt (Hauptschluessel fehlt) -> 503, kein Secret (ist %s)"
      % r.status_code, r.status_code == 503 and _ohne_secret(r))

# ── 5. Regeln am Syntaxbaum ─────────────────────────────────────────────────
print("\n[5] Regeln")


def _ruft(fn_name: str, ziel: str) -> bool:
    return any(isinstance(k, ast.Call) and ast.unparse(k.func) == ziel
               for k in ast.walk(_fn(fn_name)))


check("totp_show baut den QR ueber _totp_qr_daten", _ruft("totp_show", "_totp_qr_daten"))
check("_totp_vormerken baut den QR ueber _totp_qr_daten",
      _ruft("_totp_vormerken", "_totp_qr_daten"))
check("_totp_qr_daten schreibt keinen Zustand",
      not _ruft("_totp_qr_daten", "_set_user_auth_state"))
check("totp_show schreibt keinen Zustand", not _ruft("totp_show", "_set_user_auth_state"))
check("Route POST /api/auth/totp/show haengt an totp_show",
      any(isinstance(d, ast.Call) and ast.unparse(d.func) == "app.post"
          and d.args and isinstance(d.args[0], ast.Constant)
          and d.args[0].value == "/api/auth/totp/show"
          for d in next(n for n in ast.parse((ROOT / "backend" / "main.py").read_text(
              encoding="utf-8")).body if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "totp_show").decorator_list))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
