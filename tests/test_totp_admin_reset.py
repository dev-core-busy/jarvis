#!/usr/bin/env python3
"""Waechter: Administrator setzt die Zwei-Faktor-Anmeldung eines ANDEREN Kontos zurueck.

Hintergrund (todo.txt, 2026-09-29): wer seinen zweiten Faktor verloren hatte, kam
nie wieder hinein – /api/auth/totp/disable setzt eine Anmeldung voraus. Ausweg
war Handarbeit in auth_state.json auf dem Server. Seit 2026-10-02:
``GET /api/admin/totp/users`` und ``POST /api/admin/totp/reset``.

Gemessen wird die WIRKUNG: Endpunkte und Helfer werden per AST aus
``backend/main.py`` geschnitten und gegen einen Zustand IM SPEICHER ausgefuehrt
(die echte auth_state.json wird nie beruehrt). Zugesagt ist:

  * nur Administratoren (``Depends(require_local_auth)``),
  * das Kennwort des ADMINS wird geprueft (nicht das des Zielkontos),
  * falsches/fehlendes Kennwort, eigenes Konto, Konto ohne 2FA: NICHTS aendert sich,
  * ein Secret taucht in keiner Antwort auf,
  * nur das Zielkonto aendert sich, und dort alle drei Felder,
  * jeder Versuch steht im Tool-Audit, die Handlung in der Anwesenheitsliste.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import copy
import json
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


try:
    QUELLE = MAIN.read_text(encoding="utf-8")
    baum = ast.parse(QUELLE)
except Exception as e:  # noqa: BLE001
    abbruch(f"main.py nicht lesbar: {e}")


def route(fn):
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                and d.args and isinstance(d.args[0], ast.Constant)):
            return d.func.attr, d.args[0].value
    return None


def funktionen(pred):
    return [n for n in baum.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and pred(n)]


liste_fn = funktionen(lambda n: route(n) == ("get", "/api/admin/totp/users"))
reset_fn = funktionen(lambda n: route(n) == ("post", "/api/admin/totp/reset"))
HELFER = ("_totp_aktive_benutzer", "_totp_protokoll", "_norm_login", "_auth_schluessel",
          "_auth_eintraege_zusammenfuehren")
helfer = funktionen(lambda n: n.name in HELFER)

print("Positivkontrolle")
check("GET /api/admin/totp/users genau einmal", len(liste_fn) == 1, str(len(liste_fn)))
check("POST /api/admin/totp/reset genau einmal", len(reset_fn) == 1, str(len(reset_fn)))
check("Helfer %s gefunden" % ", ".join(HELFER), len(helfer) == len(HELFER),
      str([h.name for h in helfer]))
if len(liste_fn) != 1 or len(reset_fn) != 1 or len(helfer) != len(HELFER):
    abbruch("Endpunkte/Helfer nicht eindeutig – keine Aussage moeglich")

print("\nBerechtigung")
for fn in (liste_fn[0], reset_fn[0]):
    vorg = fn.args.defaults + [d for d in fn.args.kw_defaults if d is not None]
    ok = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends"
             and d.args and isinstance(d.args[0], ast.Name) and d.args[0].id == "require_local_auth"
             for d in vorg)
    check(f"{fn.name} haengt an Depends(require_local_auth)", ok)

# ── Ausfuehrbar machen, Zustand im Speicher ─────────────────────────────────
for fn in liste_fn + reset_fn:
    fn.decorator_list = []
modul = ast.Module(body=helfer + liste_fn + reset_fn, type_ignores=[])
ast.fix_missing_locations(modul)

SECRET_A, SECRET_B, SECRET_P = "AAAASECRETAAAA2345", "BBBBSECRETBBBB2345", "PPPPENDINGPPPP2345"
START = {"users": {
    "jarvis": {"must_change_password": False, "totp_enabled": True, "totp_secret": SECRET_A},
    "m.muster": {"must_change_password": True, "totp_enabled": True, "totp_secret": SECRET_B,
                        "totp_pending_secret": SECRET_P},
    "e.ohne": {"must_change_password": True, "totp_enabled": False, "totp_secret": None},
    "h.halb": {"totp_enabled": True, "totp_secret": None},   # kaputter Altbestand: zaehlt nicht
}}
ZUSTAND = {}
PROT = []
AKTIV = []
KENNWORT = {"jarvis": "admin-geheim", "FIRMA\\m.muster": "ziel-geheim"}
GEPRUEFT = []
FEHLV = []


def _load_auth_state():
    # Wie der echte Lader: Schreibweisen derselben Person zusammengefuehrt
    st = copy.deepcopy(ZUSTAND)
    if isinstance(st.get("users"), dict):
        st["users"], _ = ns["_auth_eintraege_zusammenfuehren"](st["users"])
    return st


def _set_user_auth_state(username, updates):
    # Wie der echte Schreiber: Schluessel ist der normalisierte Kontoname
    ZUSTAND.setdefault("users", {}).setdefault(ns["_auth_schluessel"](username), {}).update(updates)


def authenticate_linux_user(username, password, details=None):
    GEPRUEFT.append(username)
    return KENNWORT.get(username) == password


class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class Anfrage:
    def __init__(self, body):
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


audit = types.ModuleType("backend.audit_log")
audit.log_tool = lambda user, tool, args, n, ms: PROT.append((user, tool, dict(args)))
sys.modules.setdefault("backend", types.ModuleType("backend"))
sys.modules["backend.audit_log"] = audit
sys.modules["backend"].audit_log = audit

# Jede require_*-Abhaengigkeit als Attrappe: steht im Kopf eine FALSCHE, soll
# die Berechtigungspruefung oben das melden (Exit 1) – nicht ein NameError beim
# Definieren die Messung abbrechen (Exit 2 wuerde den Befund verdecken).
_abh = {n: object() for n in set(re.findall(r"\bDepends\((require_[a-z_]+)\)", QUELLE))}
ns = {**_abh, "JSONResponse": JSONResponse, "Request": Anfrage, "Depends": lambda f: None,
      "require_local_auth": object(), "asyncio": asyncio, "re": re, "time": time,
      "_load_auth_state": _load_auth_state, "_set_user_auth_state": _set_user_auth_state,
      "authenticate_linux_user": authenticate_linux_user,
      "_display_name": lambda u: "Anzeige:" + u,
      "_note_activity": lambda u, r: AKTIV.append(u),
      "_kennwort_schranke": lambda r, u: None,
      "_kennwort_fehlversuch": lambda r, u, w: FEHLV.append((u, w))}
try:
    exec(compile(modul, str(MAIN), "exec"), ns)
except Exception as e:  # noqa: BLE001
    abbruch(f"nicht ausfuehrbar: {e}")
LISTE, RESET = ns[liste_fn[0].name], ns[reset_fn[0].name]


def frisch():
    ZUSTAND.clear()
    ZUSTAND.update(copy.deepcopy(START))
    PROT.clear(); AKTIV.clear(); GEPRUEFT.clear(); FEHLV.clear()


def reset(body, admin="jarvis"):
    return asyncio.run(RESET(Anfrage(body), user=admin))


def unveraendert():
    return ZUSTAND == START


# ── Liste ───────────────────────────────────────────────────────────────────
print("\nListe")
frisch()
r = asyncio.run(LISTE(user="jarvis"))
namen = [u.get("user") for u in r.content.get("users", [])]
check("liefert genau die Konten mit 2FA an UND Secret", sorted(namen) == ["jarvis", "m.muster"], str(namen))
check("eigenes Konto ist markiert", any(u.get("user") == "jarvis" and u.get("self") for u in r.content["users"]))
roh = json.dumps(r.content)
check("kein Secret in der Antwort", not any(s in roh for s in (SECRET_A, SECRET_B, SECRET_P)))
check("nur die Felder user/display/self", all(set(u) == {"user", "display", "self"} for u in r.content["users"]),
      str(r.content["users"]))

# ── Regelfall ───────────────────────────────────────────────────────────────
print("\nRegelfall")
frisch()
r = reset({"user": "FIRMA\\m.muster", "password": "admin-geheim"})
z = ZUSTAND["users"]["m.muster"]
check("200 ok", r.status_code == 200 and r.content.get("ok") is True, f"{r.status_code} {r.content}")
check("geprueft wurde das Kennwort des ADMINS", GEPRUEFT == ["jarvis"], str(GEPRUEFT))
check("totp_enabled aus", z.get("totp_enabled") is False)
check("totp_secret geloescht", z.get("totp_secret") is None)
check("totp_pending_secret geloescht", z.get("totp_pending_secret") is None)
check("uebrige Felder des Zielkontos bleiben", z.get("must_change_password") is True)
check("Vermerk fuer den Hinweis an den Betroffenen (von, am)",
      isinstance(z.get("totp_zurueckgesetzt"), dict) and z["totp_zurueckgesetzt"].get("von") == "Anzeige:jarvis"
      and abs(z["totp_zurueckgesetzt"].get("am", 0) - time.time()) < 10, str(z.get("totp_zurueckgesetzt")))
andere = {k: v for k, v in ZUSTAND["users"].items() if k != "m.muster"}
check("alle anderen Konten unveraendert", andere == {k: v for k, v in START["users"].items() if k != "m.muster"})
check("Audit: wer, bei wem, Ergebnis",
      PROT == [("jarvis", "totp_admin_reset", {"ziel": "m.muster", "ergebnis": "zurueckgesetzt"})], str(PROT))
check("Handlung in der Anwesenheitsliste verbucht", AKTIV == ["jarvis"], str(AKTIV))
check("kein Secret in der Antwort", not any(s in json.dumps(r.content) for s in (SECRET_A, SECRET_B, SECRET_P)))
r2 = asyncio.run(LISTE(user="jarvis"))
check("danach nicht mehr in der Liste", [u["user"] for u in r2.content["users"]] == ["jarvis"])

# ── Was NICHTS aendern darf ─────────────────────────────────────────────────
print("\nAbweisungen (Zustand bleibt unveraendert)")
FAELLE = [
    ("falsches Kennwort", {"user": "FIRMA\\m.muster", "password": "falsch"}, "jarvis", 403),
    ("Kennwort des ZIELKONTOS statt des Admins", {"user": "FIRMA\\m.muster", "password": "ziel-geheim"}, "jarvis", 403),
    ("kein Kennwort", {"user": "FIRMA\\m.muster"}, "jarvis", 400),
    ("Kennwort kein Text", {"user": "FIRMA\\m.muster", "password": ["admin-geheim"]}, "jarvis", 400),
    ("kein Zielkonto", {"password": "admin-geheim"}, "jarvis", 400),
    ("eigenes Konto (mit richtigem Kennwort)", {"user": "jarvis", "password": "admin-geheim"}, "jarvis", 400),
    ("eigenes Konto in anderer Schreibweise", {"user": "JARVIS", "password": "admin-geheim"}, "jarvis", 400),
    ("Konto ohne 2FA", {"user": "e.ohne", "password": "admin-geheim"}, "jarvis", 404),
    ("Konto ohne Secret (Altbestand)", {"user": "h.halb", "password": "admin-geheim"}, "jarvis", 404),
    ("unbekanntes Konto", {"user": "gibt.es.nicht", "password": "admin-geheim"}, "jarvis", 404),
    ("Rumpf ist eine Liste", ["FIRMA\\m.muster", "admin-geheim"], "jarvis", 400),
    ("Rumpf kein JSON", ValueError("kaputt"), "jarvis", 400),
]
for name, body, admin, code in FAELLE:
    frisch()
    try:
        r = reset(body, admin)
        st = r.status_code
    except Exception as e:  # noqa: BLE001
        st = f"Ausnahme {e!r}"
    check(f"{name} -> {code}, nichts geaendert", st == code and unveraendert(), f"{st}")
frisch()
reset({"user": "FIRMA\\m.muster", "password": "falsch"})
check("falsches Kennwort steht im Audit",
      PROT == [("jarvis", "totp_admin_reset", {"ziel": "m.muster", "ergebnis": "kennwort_falsch"})], str(PROT))
check("falsches Kennwort zaehlt als Fehlversuch (BSI N4)", FEHLV == [("jarvis", "totp_reset")], str(FEHLV))

# ── Altbestand in einer anderen Schreibweise ─────────────────────────────────
print("\nAltbestand (Schreibweise im Schluessel)")
frisch()
ZUSTAND["users"]["FIRMA\\m.muster"] = ZUSTAND["users"].pop("m.muster")
r = asyncio.run(LISTE(user="jarvis"))
check("Altschluessel FIRMA\\m.muster erscheint normalisiert",
      sorted(u["user"] for u in r.content["users"]) == ["jarvis", "m.muster"], str(r.content["users"]))
r = reset({"user": "m.muster", "password": "admin-geheim"})
check("Ruecksetzung ueber den blossen Namen greift beim Altschluessel", r.status_code == 200, str(r.status_code))

# ── Aktions-Beschriftung ────────────────────────────────────────────────────
print("\nAnwesenheitsliste")
tab = [n for n in baum.body if isinstance(n, ast.Assign) and any(
    isinstance(t, ast.Name) and t.id == "_ACTION_DETAILS" for t in n.targets) and isinstance(n.value, ast.List)]
eintraege = []
if tab:
    for el in tab[0].value.elts:
        try:
            eintraege.append(ast.literal_eval(el))
        except Exception:  # noqa: BLE001
            pass
treffer = [e for e in eintraege if e[0] == "POST" and re.fullmatch(e[1], "/api/admin/totp/reset")]
check("eigene Beschriftung fuer POST /api/admin/totp/reset", len(treffer) >= 1 and "Zwei-Faktor" in treffer[0][2],
      str(treffer))

ok = sum(res)
print(f"\n\033[1mErgebnis: {ok}/{len(res)}\033[0m")
sys.exit(0 if ok == len(res) else 1)
