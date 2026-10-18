#!/usr/bin/env python3
"""Waechter: Hinweis "deine 2FA wurde zurueckgesetzt" an das betroffene Konto.

Kette: POST /api/admin/totp/reset vermerkt am Zielkonto ``totp_zurueckgesetzt``
(wer, wann) -> GET /api/auth/hinweise liefert ihn dem Betroffenen -> er
quittiert (POST /api/auth/hinweise/gelesen) ODER richtet die 2FA neu ein
(/api/auth/totp/verify raeumt den Vermerk ab).

⚠ auth_state.json ist nach der TIPPFORM beim Anmelden verschluesselt – dieselbe
Person steht auf DEV unter "contoso\\x.y" UND "x.y". Gemessen wird deshalb
ausdruecklich: Ruecksetzung unter der einen, Anmeldung unter der anderen
Schreibweise.

Ausgefuehrt werden die ECHTEN Funktionen (per AST aus backend/main.py) gegen
einen Zustand im Speicher. Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import contextvars
import copy
import re
import sys
import time
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = WURZEL / "backend" / "main.py"
res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abbruch(grund):
    print(f"ABBRUCH (Exit 2): {grund}")
    sys.exit(2)


QUELLE = MAIN.read_text(encoding="utf-8")
baum = ast.parse(QUELLE)


def route(fn):
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                and d.args and isinstance(d.args[0], ast.Constant)):
            return d.func.attr, d.args[0].value
    return None


ROUTEN = {("post", "/api/admin/totp/reset"): "reset", ("get", "/api/auth/hinweise"): "liste",
          ("post", "/api/auth/hinweise/gelesen"): "gelesen", ("post", "/api/auth/totp/verify"): "verify"}
HELFER = {"_totp_aktive_benutzer", "_totp_protokoll", "_norm_login", "_konto_hinweise",
          "_konto_hinweis_abraeumen", "_totp_fehlertext",
          # Code-Review 2026-10-07: verify weist App-Sitzungen ab
          "_sitzung_ist_app", "_totp_app_sperre",
          # seit 2026-10-18: ein Konto = ein Schluessel (test_auth_schreibweise)
          "_auth_schluessel", "_auth_eintraege_zusammenfuehren"}
teile, namen = [], {}
for n in baum.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        r = route(n)
        if r in ROUTEN:
            namen[ROUTEN[r]] = n.name
            teile.append(n)
        elif n.name in HELFER:
            teile.append(n)
print("Positivkontrolle")
check("vier Endpunkte gefunden", set(namen) == set(ROUTEN.values()), str(namen))
check("alle Helfer gefunden", {n.name for n in teile} >= HELFER, str([n.name for n in teile]))
if set(namen) != set(ROUTEN.values()) or not {n.name for n in teile} >= HELFER:
    abbruch("Funktionen nicht gefunden")

print("\nBerechtigung")
for art in ("liste", "gelesen"):
    fn = next(n for n in teile if n.name == namen[art])
    vorg = fn.args.defaults + [d for d in fn.args.kw_defaults if d is not None]
    check(f"{fn.name} haengt an Depends(require_auth)", any(
        isinstance(d, ast.Call) and getattr(d.func, "id", "") == "Depends" and d.args
        and getattr(d.args[0], "id", "") == "require_auth" for d in vorg))

for n in teile:
    n.decorator_list = []
modul = ast.Module(body=teile, type_ignores=[])
ast.fix_missing_locations(modul)

ZUSTAND = {}


def _load_auth_state():
    # Wie der echte Lader seit 2026-10-18: Schreibweisen derselben Person werden
    # zusammengefuehrt UND zurueckgeschrieben (Migration beim ersten Lesen).
    if isinstance(ZUSTAND.get("users"), dict):
        ZUSTAND["users"], _ = ns["_auth_eintraege_zusammenfuehren"](ZUSTAND["users"])
    return copy.deepcopy(ZUSTAND)


def _set_user_auth_state(username, updates):
    _load_auth_state()
    ZUSTAND.setdefault("users", {}).setdefault(ns["_auth_schluessel"](username), {}).update(updates)


class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


class Anfrage:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


pyotp = types.ModuleType("pyotp")


class _TOTP:
    def __init__(self, secret):
        self.s = secret

    interval = 30

    def verify(self, otp, for_time=None, valid_window=0):   # echte Signatur
        return otp == "123456"


pyotp.TOTP = _TOTP
sys.modules["pyotp"] = pyotp

# BSI N3: totp_verify prueft ueber totp_schutz – Ablage im Wegwerf-Verzeichnis
import tempfile  # noqa: E402
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)
sys.path.insert(0, str(MAIN.parent.parent))
from backend import totp_schutz as _TS  # noqa: E402
_TS.STORE_PATH = Path(tempfile.mkdtemp(prefix="waechter-konto-hinweise-")) / "totp_schritte.json"
audit = types.ModuleType("backend.audit_log")
audit.log_tool = lambda *a, **k: None
sys.modules.setdefault("backend", types.ModuleType("backend"))
sys.modules["backend.audit_log"] = audit
sys.modules["backend"].audit_log = audit

_abh = {n: object() for n in set(re.findall(r"\bDepends\((require_[a-z_]+)\)", QUELLE))}
ns = {**_abh, "JSONResponse": JSONResponse, "Request": Anfrage, "Depends": lambda f: None,
      "asyncio": asyncio, "time": time, "re": re, "_totp_schutz": _TS,
      "_load_auth_state": _load_auth_state, "_set_user_auth_state": _set_user_auth_state,
      "_get_user_auth_state": lambda u: copy.deepcopy((ZUSTAND.get("users") or {}).get(u, {})),
      "authenticate_linux_user": lambda u, p, details=None: (u, p) == ("jarvis", "admin-geheim"),
      "_display_name": lambda u: "Anzeige " + u, "_note_activity": lambda u, r: None,
      "_sitzung_kontext": contextvars.ContextVar("_sk", default=None),
      # seit 2026-10-18 auch an der Admin-Ruecksetzung (BSI N4, test_totp_admin_reset)
      "_kennwort_schranke": lambda r, u: None, "_kennwort_fehlversuch": lambda r, u, w: None}
try:
    exec(compile(modul, str(MAIN), "exec"), ns)
except Exception as e:  # noqa: BLE001
    abbruch(f"nicht ausfuehrbar: {e}")
F = {k: ns[v] for k, v in namen.items()}

START = {"users": {
    "jarvis": {"totp_enabled": True, "totp_secret": "ADMINSECRET"},
    "FIRMA\\m.muster": {"must_change_password": True, "totp_enabled": True, "totp_secret": "MSECRET"},
    "m.muster": {"must_change_password": True, "totp_enabled": False, "totp_secret": None},
    "k.andere": {"totp_enabled": True, "totp_secret": "KSECRET"},
}}


def frisch():
    ZUSTAND.clear()
    ZUSTAND.update(copy.deepcopy(START))


def hinweise(user):
    return asyncio.run(F["liste"](user=user)).content.get("hinweise")


def run(name, body, user):
    return asyncio.run(F[name](Anfrage(body), user=user) if name != "verify"
                       else F[name](Anfrage(body), username=user))


print("\nOhne Ruecksetzung")
frisch()
check("niemand hat einen Hinweis", all(hinweise(u) == [] for u in ("m.muster", "FIRMA\\m.muster", "k.andere", "jarvis")))

print("\nRuecksetzung unter 'FIRMA\\\\m.muster'")
frisch()
t0 = int(time.time())
r = run("reset", {"user": "FIRMA\\m.muster", "password": "admin-geheim"}, "jarvis")
check("(Positivkontrolle) Ruecksetzung 200", r.status_code == 200, str(r.content))
v = _load_auth_state()["users"]["m.muster"].get("totp_zurueckgesetzt") or {}   # ein Schluessel je Person
check("Vermerk am Zielkonto: von (Anzeigename) und am", v.get("von") == "Anzeige jarvis" and t0 <= v.get("am", 0) <= t0 + 5, str(v))
for schreibweise in ("FIRMA\\m.muster", "m.muster", "M.Muster@firma.local"):
    h = hinweise(schreibweise)
    check(f"Hinweis fuer Anmeldung als '{schreibweise}'",
          h == [{"art": "totp_zurueckgesetzt", "von": "Anzeige jarvis", "am": v.get("am")}], str(h))
check("kein Hinweis fuer andere Konten", hinweise("k.andere") == [] and hinweise("jarvis") == [])
check("kein Secret im Hinweis", "SECRET" not in str(hinweise("m.muster")))

print("\nQuittieren")
r = run("gelesen", {"art": "unbekannt"}, "m.muster")
check("unbekannte Art -> 400, Hinweis bleibt", r.status_code == 400 and hinweise("m.muster") != [])
r = run("gelesen", ["totp_zurueckgesetzt"], "m.muster")
check("Rumpf keine Zuordnung -> 400", r.status_code == 400)
r = run("gelesen", {"art": "totp_zurueckgesetzt"}, "k.andere")
check("ein ANDERES Konto quittiert nicht fremde Hinweise", r.status_code == 200 and hinweise("m.muster") != [])
r = run("gelesen", {"art": "totp_zurueckgesetzt"}, "m.muster")
check("Quittieren unter ANDERER Schreibweise als die Ruecksetzung: 200", r.status_code == 200)
check("Hinweis danach weg – in jeder Schreibweise",
      hinweise("m.muster") == [] and hinweise("FIRMA\\m.muster") == [])
check("Vermerk in auth_state abgeraeumt",
      not any(st.get("totp_zurueckgesetzt") for st in ZUSTAND["users"].values()))

print("\n2FA unter einer ANDEREN Schreibweise aktiv")
frisch()
run("reset", {"user": "FIRMA\\m.muster", "password": "admin-geheim"}, "jarvis")
check("(Positivkontrolle) Hinweis offen", hinweise("m.muster") != [])
# Ohne verify: unter "m.muster" steht (z.B. aus frueherer Einrichtung) eine aktive 2FA
_set_user_auth_state("m.muster", {"totp_enabled": True, "totp_secret": "ANDERSECRET"})
check("kein Hinweis, solange die Person unter irgendeiner Schreibweise 2FA hat",
      hinweise("m.muster") == [] and hinweise("FIRMA\\m.muster") == [])

print("\nNeu einrichten statt quittieren")
frisch()
run("reset", {"user": "FIRMA\\m.muster", "password": "admin-geheim"}, "jarvis")
check("(Positivkontrolle) Hinweis offen", hinweise("m.muster") != [])
_set_user_auth_state("m.muster", {"totp_pending_secret": "NEUSECRET"})
r = run("verify", {"code": "123456"}, "m.muster")
check("(Positivkontrolle) 2FA unter 'm.muster' wieder eingeschaltet", r.status_code == 200, str(r.content))
check("Hinweis ist erledigt (2FA wieder an)", hinweise("m.muster") == [] and hinweise("FIRMA\\m.muster") == [])
check("verify raeumt den Vermerk in JEDER Schreibweise ab",
      not any(st.get("totp_zurueckgesetzt") for st in ZUSTAND["users"].values()),
      str({k: st.get("totp_zurueckgesetzt") for k, st in ZUSTAND["users"].items()}))
# Der Fall, an dem ein stehengebliebener Vermerk sichtbar wuerde: die Person
# schaltet die (neu eingerichtete) 2FA spaeter SELBST wieder ab.
_set_user_auth_state("m.muster", {"totp_enabled": False, "totp_secret": None})
_set_user_auth_state("FIRMA\\m.muster", {"totp_enabled": False, "totp_secret": None})
check("2FA spaeter selbst abgeschaltet: KEIN alter Hinweis taucht wieder auf",
      hinweise("m.muster") == [], str(hinweise("m.muster")))

print("\nAnwesenheitsliste")
tab = [n for n in baum.body if isinstance(n, ast.Assign) and any(
    isinstance(t, ast.Name) and t.id == "_ACTION_DETAILS" for t in n.targets)]
eintraege = []
for el in (tab[0].value.elts if tab else []):
    try:
        eintraege.append(ast.literal_eval(el))
    except Exception:  # noqa: BLE001
        pass
check("eigene Beschriftung fuer POST /api/auth/hinweise/gelesen",
      any(e[0] == "POST" and re.fullmatch(e[1], "/api/auth/hinweise/gelesen") for e in eintraege))

ok = sum(res)
print(f"\n\033[1mErgebnis: {ok}/{len(res)}\033[0m")
sys.exit(0 if ok == len(res) else 1)
