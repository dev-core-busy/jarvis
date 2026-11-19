#!/usr/bin/env python3
"""Waechter: "Verbindung testen" in der Admin-Konfiguration testet den SAMMELZUGANG.

Vorfall DEV 2026-11-19: der Administrator speicherte das neue Kennwort des
gemeinsamen SAP-Zugangs und drueckte "Verbindung testen" – Ergebnis "SAP
meldet: Anmeldung fehlgeschlagen (HTTP 401)". Der Sammelzugang war in
Ordnung (direkt gemessen: 22 EntitySets). Der Knopf rief ``/api/sap/test``,
und das testet den Zugang, der beim Auswerten gilt: den PERSOENLICHEN mit
Vorrang – der trug noch das alte Kennwort. Jeder Klick war damit zusaetzlich
ein Fehlversuch gegen die Sperrgrenze des SAP-Benutzers.

Geprueft wird die WIRKUNG, nicht das Vorkommen:

  1. Positivkontrolle: die drei Funktionen lassen sich aus main.py schneiden
     und ausfuehren (sonst Exit 2).
  2. ``/api/sap/test/sammel`` haengt an ``require_local_auth`` (Admin).
  3. Ausgefuehrt: der Sammel-Test baut ``SapClient()`` OHNE Konfiguration
     (= Sammelzugang), fragt die Zugangsaufloesung NICHT, und weder Erfolg
     noch Anmeldefehler landen beim persoenlichen Zugang.
  4. Gegenrichtung: ``/api/sap/test`` testet weiter den aufgeloesten Zugang
     und zaehlt beim persoenlichen den Fehler (unveraendert).
  5. Frontend: das ECHTE ``sap.js`` ruft beim Klick ``/api/sap/test/sammel``.

Exit 2 = konnte nicht laufen, 1 = Pruefung fehlgeschlagen, 0 = bestanden.

    python3 tests/test_sap_test_sammel.py [--main <main.py>] [--sapjs <sap.js>]

Die Pfad-Argumente sind fuer die Gegenprobe (gegen_sap_test_sammel.py): sie
legt sabotierte KOPIEN vor, die echten Dateien werden nie angefasst.
"""
import argparse
import ast
import asyncio
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ap = argparse.ArgumentParser()
_ap.add_argument("--main", default=str(ROOT / "backend" / "main.py"))
_ap.add_argument("--sapjs", default=str(ROOT / "frontend" / "js" / "sap.js"))
ARGS = _ap.parse_args()

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


# ── 1. Schneiden ──────────────────────────────────────────────────────
print("\n1. Positivkontrolle: Funktionen aus main.py")
try:
    QUELLE = Path(ARGS.main).read_text(encoding="utf-8")
    BAUM = ast.parse(QUELLE)
except Exception as e:  # noqa: BLE001
    abbruch(f"main.py nicht lesbar/parsebar: {e}")

NAMEN = ("sap_test", "sap_test_sammel", "_sap_test_antwort")
FUNK = {}
for knoten in BAUM.body:
    if isinstance(knoten, ast.AsyncFunctionDef) and knoten.name in NAMEN:
        FUNK.setdefault(knoten.name, []).append(knoten)
for n in NAMEN:
    if len(FUNK.get(n, [])) != 1:
        abbruch(f"{n} nicht genau einmal als async def gefunden ({len(FUNK.get(n, []))})")
print("  OK   alle drei Funktionen genau einmal vorhanden")


def _route(fn):
    """(Pfad, Name der Dependency des Parameters ``user``) aus dem AST."""
    pfad = None
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr == "get" and d.args
                and isinstance(d.args[0], ast.Constant)):
            pfad = d.args[0].value
    dep = None
    alle = fn.args.args
    vorgaben = fn.args.defaults
    for arg, vg in zip(alle[len(alle) - len(vorgaben):], vorgaben):
        if (arg.arg == "user" and isinstance(vg, ast.Call)
                and isinstance(vg.func, ast.Name) and vg.func.id == "Depends"
                and vg.args and isinstance(vg.args[0], ast.Name)):
            dep = vg.args[0].id
    return pfad, dep


# ── 2. Route und Recht ────────────────────────────────────────────────
print("\n2. Route und Recht")
pfad, dep = _route(FUNK["sap_test_sammel"][0])
check(pfad == "/api/sap/test/sammel", "Sammel-Test liegt auf /api/sap/test/sammel", repr(pfad))
check(dep == "require_local_auth", "Sammel-Test nur fuer Administratoren", repr(dep))
pfad, dep = _route(FUNK["sap_test"][0])
check(pfad == "/api/sap/test" and dep == "require_sap_access",
      "persoenlicher Test unveraendert (/api/sap/test, require_sap_access)", f"{pfad} {dep}")


# ── Attrappen in der echten Form ──────────────────────────────────────
class SapError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


PROTOKOLL = []


class SapClientAttrappe:
    """Echte Signatur ``SapClient(cfg=None)``; ``cfg is None`` = Sammelzugang."""
    verhalten = "ok"

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.connection_type = "odata"
        self.product = ""
        self.configured = True
        PROTOKOLL.append(("SapClient", "sammel" if cfg is None else "cfg"))

    def test(self):
        PROTOKOLL.append(("test", "sammel" if self.cfg is None else "cfg"))
        if SapClientAttrappe.verhalten == "401":
            raise SapError(401, "SAP meldet: Anmeldung fehlgeschlagen (HTTP 401)")
        return {"type": "odata", "detail": "22 EntitySet(s)", "info": {}}

    def test_bericht(self):
        return {"benutzer": "PROBE"}


_sc = types.ModuleType("backend.sap_client")
_sc.SapClient = SapClientAttrappe
_sc.SapError = SapError
_sa = types.ModuleType("backend.sap_accounts")
_sa.melde_fehler = lambda user, e: PROTOKOLL.append(("melde_fehler", user))
_sa.merke_ergebnis = lambda user, ok: PROTOKOLL.append(("merke_ergebnis", user))
_sa.aufloesen = lambda *a, **k: PROTOKOLL.append(("aufloesen",)) or {}
_backend = types.ModuleType("backend")
_backend.sap_client = _sc
_backend.sap_accounts = _sa
sys.modules.update({"backend": _backend, "backend.sap_client": _sc,
                    "backend.sap_accounts": _sa})


class _App:
    def get(self, *_a, **_k):
        return lambda f: f


def _zugang(user="", trotz_aussetzer=False):
    PROTOKOLL.append(("_sap_zugang", user))
    return {"client": SapClientAttrappe({"username": "persoenlich"}),
            "quelle": "persoenlich", "hinweis": "", "benutzer": user,
            "ausgesetzt": False}


NS = {"app": _App(), "Depends": lambda f: None, "require_local_auth": None,
      "require_sap_access": None, "JSONResponse": lambda d, **k: d,
      "asyncio": asyncio, "_sap_zugang": _zugang}
modul = ast.Module(body=[FUNK[n][0] for n in NAMEN], type_ignores=[])
try:
    exec(compile(modul, "main.py(geschnitten)", "exec"), NS)  # noqa: S102
except Exception as e:  # noqa: BLE001
    abbruch(f"geschnittene Funktionen nicht ausfuehrbar: {e}")


def lauf(fn, verhalten):
    PROTOKOLL.clear()
    SapClientAttrappe.verhalten = verhalten
    return asyncio.run(NS[fn](user="probe.konto"))


# ── 3. Sammel-Test ausgefuehrt ────────────────────────────────────────
print("\n3. Sammel-Test (ausgefuehrt)")
try:
    r = lauf("sap_test_sammel", "ok")
except Exception as e:  # noqa: BLE001
    abbruch(f"sap_test_sammel wirft: {e}")
check(("test", "sammel") in PROTOKOLL, "getestet wird SapClient() ohne Konfiguration",
      str(PROTOKOLL))
check(not any(p[0] in ("_sap_zugang", "aufloesen") for p in PROTOKOLL),
      "persoenliche Zugangsaufloesung wird nicht gefragt", str(PROTOKOLL))
check(isinstance(r, dict) and r.get("ok") is True and r.get("quelle") == "sammel",
      "Antwort: ok, quelle=sammel", json.dumps(r, default=str)[:200])
check(not any(p[0] == "merke_ergebnis" for p in PROTOKOLL),
      "Erfolg wird nicht beim persoenlichen Zugang gemerkt", str(PROTOKOLL))

r = lauf("sap_test_sammel", "401")
check(isinstance(r, dict) and r.get("ok") is False and r.get("status") == 401
      and "Anmeldung fehlgeschlagen" in str(r.get("error")),
      "Fehlerfall: Status und SAP-Text kommen an", json.dumps(r, default=str)[:200])
check(not any(p[0] == "melde_fehler" for p in PROTOKOLL),
      "Anmeldefehler des Sammelzugangs zaehlt NICHT beim persoenlichen Zugang",
      str(PROTOKOLL))

# ── 4. Gegenrichtung: persoenlicher Test ──────────────────────────────
print("\n4. Persoenlicher Test (unveraendert)")
r = lauf("sap_test", "401")
check(("_sap_zugang", "probe.konto") in PROTOKOLL and ("test", "cfg") in PROTOKOLL,
      "/api/sap/test testet den aufgeloesten (persoenlichen) Zugang", str(PROTOKOLL))
check(("melde_fehler", "probe.konto") in PROTOKOLL,
      "Anmeldefehler des persoenlichen Zugangs wird gezaehlt", str(PROTOKOLL))
check(isinstance(r, dict) and r.get("quelle") == "persoenlich", "Antwort: quelle=persoenlich",
      json.dumps(r, default=str)[:200])
r = lauf("sap_test", "ok")
check(("merke_ergebnis", "probe.konto") in PROTOKOLL,
      "Erfolg des persoenlichen Zugangs wird gemerkt", str(PROTOKOLL))

# ── 5. Frontend: echtes sap.js ────────────────────────────────────────
print("\n5. Frontend: Klick-Weg in sap.js")
NODE = shutil.which("node")
if not NODE:
    abbruch("node nicht gefunden")
SKRIPT = r"""
const fs = require('fs'), vm = require('vm');
const aufrufe = [];
const ctx = {
  window: {}, console,
  document: { getElementById: () => null, querySelectorAll: () => [],
              addEventListener: () => {} },
  fetch: (url) => { aufrufe.push(String(url).split('?')[0]);
                    return new Promise(() => {}); },
};
ctx.window = ctx; ctx.self = ctx;
ctx.JarvisSitzung = { token: () => 'probe' };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
if (!ctx.SapManager || typeof ctx.SapManager.test !== 'function') {
  console.log(JSON.stringify({ fehlt: true })); process.exit(0);
}
ctx.SapManager.test();
console.log(JSON.stringify({ aufrufe }));
"""
try:
    p = subprocess.run([NODE, "-e", SKRIPT, ARGS.sapjs], capture_output=True,
                       text=True, timeout=30)
    erg = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else None
except Exception as e:  # noqa: BLE001
    abbruch(f"sap.js nicht ausfuehrbar: {e}")
if not erg or erg.get("fehlt"):
    abbruch(f"SapManager.test nicht erreichbar – {p.stderr.strip()[:300]}")
if not erg.get("aufrufe"):
    abbruch("Positivkontrolle: test() hat gar keinen Abruf ausgeloest")
check(erg["aufrufe"] == ["/api/sap/test/sammel"],
      "Admin-Knopf ruft /api/sap/test/sammel", str(erg["aufrufe"]))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
