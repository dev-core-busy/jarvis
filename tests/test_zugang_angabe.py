#!/usr/bin/env python3
"""
Waechter: die Fachproben-Endpunkte sagen, MIT WELCHEM Zugang sie antworten
(Vorgabe 2026-11-16).

ANLASS: /api/confluence/spaces, /api/jira/search, /api/sap/odata/services,
/api/sap/tables und /api/vemas/query fallen still auf den gemeinsamen Zugang
zurueck, wenn der eigene nicht greift. Die Fachprobe in "Mein …-Zugang"
meldete dann "funktioniert", obwohl der eigene Zugang gar nicht benutzt
wurde. Jede Antwort traegt deshalb ``zugang`` ({quelle, hinweis}).

GEMESSEN (am Syntaxbaum bzw. ausgefuehrt, nicht am Text):
  1. Positivkontrolle: alle fuenf Endpunkte und der Helfer sind gefunden
     (sonst Exit 2 – eine Regel ueber null Funktionen waere trivial wahr).
  2. JEDE ``JSONResponse({...})`` dieser Endpunkte hat den Schluessel
     "zugang" – auch die Fehlerwege: "dein Zugang funktioniert nicht" braucht
     die Angabe gerade dort. Eine kuenftige Rueckgabe ohne ihn faellt auf.
  3. ``_zugang_angabe`` wird AUSGEFUEHRT: es gibt NUR quelle und hinweis
     heraus – kein Token, kein Client, kein Benutzer (der Wert geht an den
     Browser). Unbekanntes -> None.
  4. ``client_fuer_lauf`` in confluence_accounts UND jira_accounts haengt
     ``zugang`` an den Client (sonst bliebe das Feld bei diesen beiden still
     None, und die Oberflaeche behauptete nichts – kein Fehler, aber die
     Zusage waere weg).

Aufruf: python3 tests/test_zugang_angabe.py   Exit 0 gruen, 1 FAIL, 2 kaputt
"""
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = Path(os.environ.get("ZUGANG_MAIN") or ROOT / "backend" / "main.py")
KONTEN = {
    "confluence": Path(os.environ.get("ZUGANG_CONF") or ROOT / "backend" / "confluence_accounts.py"),
    "jira": Path(os.environ.get("ZUGANG_JIRA") or ROOT / "backend" / "jira_accounts.py"),
}
ENDPUNKTE = ["confluence_spaces_api", "jira_search_api", "sap_odata_services_api",
             "sap_tables_api", "vemas_query",
             # Die eigenen Probe-Endpunkte (2026-11-16, siehe Abschnitt 5).
             "confluence_account_bereiche", "jira_account_vorgaenge"]
PROBE = {"confluence_account_bereiche": ("/api/confluence/account/bereiche",
                                         "require_confluence_account_access"),
         "jira_account_vorgaenge": ("/api/jira/account/vorgaenge",
                                    "require_jira_assist_access")}

OK = FAIL = 0


def check(bed, name, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{info}]" if info else ""))


def funktionen(baum):
    return {n.name: n for n in ast.walk(baum)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


baum = ast.parse(MAIN.read_text(encoding="utf-8"))
fn = funktionen(baum)

print("\n═══ 1) Positivkontrolle")
# Nur fehlende ENDPUNKTE sind ein kaputter Messaufbau (Exit 2). Ein fehlender
# HELFER ist ein Produktbefund und wird als FAIL gemeldet – sonst saehe der
# Altstand wie "konnte nicht laufen" aus statt wie ein Biss (Register).
fehlt = [n for n in ENDPUNKTE if n not in fn]
if fehlt:
    print(f"ABBRUCH: Endpunkte nicht gefunden: {fehlt}")
    sys.exit(2)
check(True, f"alle {len(ENDPUNKTE)} Endpunkte gefunden")
check("_zugang_angabe" in fn, "Helfer _zugang_angabe vorhanden")

print("\n═══ 2) Jede Antwort der Endpunkte traegt 'zugang'")
for name in ENDPUNKTE:
    antworten = [c for c in ast.walk(fn[name])
                 if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "JSONResponse"
                 and c.args and isinstance(c.args[0], ast.Dict)]
    ohne = [c.lineno for c in antworten
            if not any(isinstance(k, ast.Constant) and k.value == "zugang" for k in c.args[0].keys)]
    check(len(antworten) > 0, f"{name}: hat Antworten (Positivkontrolle)", str(len(antworten)))
    check(not ohne, f"{name}: alle {len(antworten)} Antworten tragen 'zugang'",
          f"ohne in Zeile(n) {ohne}")
    # Der Wert kommt aus _zugang_angabe – nicht aus einem handgebauten dict,
    # das beim naechsten Feld (z. B. benutzer) mehr herausgaebe.
    ruft = any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_zugang_angabe"
               for c in ast.walk(fn[name]))
    check(ruft, f"{name}: Wert kommt aus _zugang_angabe")

print("\n═══ 3) _zugang_angabe gibt NUR quelle und hinweis heraus")
ns = {}
if "_zugang_angabe" in fn:
    exec(compile(ast.Module(body=[fn["_zugang_angabe"]], type_ignores=[]), str(MAIN), "exec"), ns)
f = ns.get("_zugang_angabe") or (lambda z: {"fehlt": True})
voll = {"client": object(), "quelle": "persoenlich", "hinweis": "h",
        "benutzer": "anna", "api_token": "GEHEIM", "token": "GEHEIM"}
r = f(voll)
check(isinstance(r, dict) and set(r) == {"quelle", "hinweis"},
      "nur die Schluessel quelle und hinweis", repr(r))
check(r == {"quelle": "persoenlich", "hinweis": "h"}, "Werte korrekt uebernommen", repr(r))
check("GEHEIM" not in repr(r) and "anna" not in repr(r), "kein Token, kein Benutzer in der Angabe")
check(f({"quelle": None}) == {"quelle": "", "hinweis": ""}, "None wird zu Leertext")
check(f(None) is None and f("persoenlich") is None, "Unbekanntes -> None")

print("\n═══ 4) client_fuer_lauf haengt 'zugang' an den Client")
for bereich, pfad in KONTEN.items():
    kfn = funktionen(ast.parse(pfad.read_text(encoding="utf-8"))).get("client_fuer_lauf")
    check(kfn is not None, f"{bereich}: client_fuer_lauf gefunden")
    if kfn is None:
        continue
    setzt = [n for n in ast.walk(kfn) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Attribute) and t.attr == "zugang" for t in n.targets)]
    check(bool(setzt), f"{bereich}: setzt <client>.zugang")
    ruft = any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "aufloesen"
               for c in ast.walk(kfn))
    check(ruft, f"{bereich}: Angabe stammt aus aufloesen()")

print("\n═══ 5) Probe-Endpunkte: Schranke der Konto-Routen, NUR der eigene Zugang")
# Anlass (2026-11-16, Bildschirmfoto): die Proben fragten /api/confluence/spaces
# bzw. /api/jira/search – beide require_local_auth, also nur Administratoren.
# Jeder andere Benutzer bekam "Nur Administratoren duerfen diese Aktion
# ausfuehren". Die eigenen Endpunkte duerfen KEINE neue Tuer sein: ohne
# eigenen Zugang fragen sie gar nicht, und es gibt keine frei waehlbare Abfrage.
import asyncio  # noqa: E402
import types  # noqa: E402


def _dep_namen(fdef):
    namen = []
    for d in list(fdef.args.defaults) + list(fdef.args.kw_defaults or []):
        if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "Depends" and d.args:
            namen.append(getattr(d.args[0], "id", ""))
    return namen


def _route(fdef):
    for dek in fdef.decorator_list:
        if isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute) and dek.args \
                and isinstance(dek.args[0], ast.Constant):
            return dek.func.attr, dek.args[0].value
    return None, None


for name, (pfad, dep) in PROBE.items():
    fdef = fn[name]
    check(_route(fdef) == ("get", pfad), f"{name}: Route GET {pfad}", repr(_route(fdef)))
    deps = _dep_namen(fdef)
    check(deps == [dep], f"{name}: Schranke {dep} (nicht require_local_auth)", repr(deps))
    params = [a.arg for a in fdef.args.args]
    check(params == ["user"], f"{name}: einziger Parameter ist der Benutzer (keine Abfrage)",
          repr(params))


class _Antwort:
    """JSONResponse-Attrappe mit der echten Signatur (inhalt, status_code)."""
    def __init__(self, inhalt, status_code=200):
        self.d, self.status = inhalt, status_code


class _Fehler(Exception):
    status = 0


def _fuehre(name, zugang):
    """Fuehrt den ECHTEN Funktionsrumpf aus; der Client zaehlt seine Abrufe."""
    abrufe = []

    class _Client:
        configured = True
        base = "https://beispiel.de"

        def __init__(self):
            if zugang is not None:
                self.zugang = zugang

        def spaces_detailed(self, n):
            abrufe.append(("spaces", n))
            return [{"key": "B", "name": "beta"}, {"key": "A", "name": "Alpha"}]

        def search(self, jql, limit=25):
            abrufe.append(("search", jql, limit))
            return {"issues": [{"key": "PRJA-1"}], "total": 1}

    konten = types.SimpleNamespace(QUELLE_PERSOENLICH="persoenlich")
    stubs = {
        "backend": types.SimpleNamespace(confluence_accounts=konten, jira_accounts=konten),
        "backend.confluence_client": types.SimpleNamespace(ConfluenceError=_Fehler),
        "backend.jira_client": types.SimpleNamespace(
            JiraError=_Fehler, issue_brief=lambda it, base="": {"key": it.get("key")}),
    }
    vorher = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        kopie = ast.parse(ast.unparse(fn[name]))
        kopie.body[0].decorator_list = []
        ns = {"JSONResponse": _Antwort, "asyncio": asyncio, "_zugang_angabe": f,
              "_confluence_client": lambda u: _Client(), "_jira_client": lambda u: _Client(),
              "_CF_MAX_BEREICHE": 5000, "_PROBE_NICHT_EIGEN": "Eigener Zugang nicht aktiv.",
              "Depends": lambda d: None, "require_confluence_account_access": None,
              "require_jira_assist_access": None}
        # Jede Schranke, die die Funktion nennt, als Platzhalter – sonst wirft
        # schon die Definition (Vorgabewert Depends(<name>)), und eine Gegenprobe
        # "falsche Schranke" endete als Absturz statt als FAIL (Register).
        for dep in _dep_namen(fn[name]):
            ns.setdefault(dep, None)
        exec(compile(kopie, name, "exec"), ns)
        antwort = asyncio.run(ns[name](user="anna"))
    finally:
        for k, v in vorher.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return antwort, abrufe


for name in PROBE:
    a, ab = _fuehre(name, {"quelle": "sammel", "hinweis": "Sondengrund."})
    check(ab == [], f"{name}: gemeinsamer Zugang -> KEIN Abruf", repr(ab))
    check(a.d.get("ok") is False and a.d.get("eigener_zugang") is False
          and "Sondengrund." in str(a.d.get("error")),
          f"{name}: gemeinsamer Zugang -> Absage MIT Grund", repr(a.d))
    a, ab = _fuehre(name, None)
    check(ab == [] and a.d.get("ok") is False,
          f"{name}: ohne Zugangsangabe -> KEIN Abruf (fail-closed)", repr(ab))
    a, ab = _fuehre(name, {"quelle": "persoenlich", "hinweis": ""})
    check(len(ab) == 1 and a.d.get("ok") is True,
          f"{name}: eigener Zugang -> genau EIN Abruf, ok", repr(ab))
    check((a.d.get("zugang") or {}).get("quelle") == "persoenlich",
          f"{name}: Antwort nennt den eigenen Zugang", repr(a.d.get("zugang")))
    if name == "jira_account_vorgaenge":
        check(ab == [("search", "ORDER BY updated DESC", 5)],
              "jira: feste Abfrage, hoechstens 5 Treffer", repr(ab))
    else:
        keys = [s.get("key") for s in a.d.get("spaces", [])]
        check(keys == ["A", "B"] and a.d.get("count") == 2,
              "confluence: vollstaendige Liste, nach Name sortiert", repr(keys))

print(f"\nERGEBNIS: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
