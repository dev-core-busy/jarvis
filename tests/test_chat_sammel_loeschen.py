#!/usr/bin/env python3
"""Waechter: Sammel-Loeschung von Chat-Sitzungen – Serverseite (2026-09-29).

Die Oberflaeche prueft `tests/test_chat_mehrfach_loeschen.js` (jsdom, echter
Renderer). Was die dort nicht sehen kann, steht hier:

  * Der Endpunkt existiert unter dem Pfad, den das Frontend ruft.
  * Die TYPPRUEFUNG liegt VOR der Schleife – ueber einen String zu iterieren
    ist immer erlaubt und nie gemeint (ergaebe eine Loeschung je Zeichen).
  * Teilerfolge werden BENANNT (deleted/failed), nicht gezaehlt: eine blosse
    Zahl liesse offen, welcher Chat noch da ist.
  * Jede erfolgreiche Loeschung wirft den RAM-Kontext weg – ueber denselben
    Helfer wie die Einzelloeschung, damit die Lehre von 2026-08-30 (Haupt-
    agent, nicht `agent_instance`) nicht an einer Stelle wieder verloren geht.
  * Die Handlung heisst im Audit "geloescht" und nicht "begonnen".

Gemessen wird am SYNTAXBAUM, nicht am Text: ein Teilstring ist keine
Identitaet, und ein Waechter, der seine eigene Begruendung liest, prueft
nichts. Der Audit-Teil laeuft mit den ECHTEN Mustern aus main.py und einer
Positivkontrolle an zwei Pfaden, deren Beschriftung bekannt ist.

    python3 tests/test_chat_sammel_loeschen.py
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % label)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (label, (" – %s" % detail) if detail else ""))


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def abbruch(grund):
    """"Konnte nicht laufen" ist nicht "bestanden" – Exit 2."""
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


if not MAIN.is_file():
    abbruch("backend/main.py nicht gefunden")
BAUM = ast.parse(MAIN.read_text(encoding="utf-8"))


def dekorator_pfade(fn):
    """Alle ("METHODE", "/pfad") aus @app.<methode>("/pfad") einer Funktion."""
    raus = []
    for d in fn.decorator_list:
        if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute):
            continue
        ziel = d.func.value
        if not (isinstance(ziel, ast.Name) and ziel.id == "app"):
            continue
        if d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
            raus.append((d.func.attr.upper(), d.args[0].value))
    return raus


FUNKTIONEN = {}
for n in ast.walk(BAUM):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNKTIONEN.setdefault(n.name, n)


def rufe(knoten, name):
    """Echte ast.Call auf `name` – ein Vorkommen im Text traefe auch ein `def`."""
    return [c for c in ast.walk(knoten)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name]


def attribut_rufe(knoten, name):
    """Echte ast.Call auf `<irgendwas>.name(...)`."""
    return [c for c in ast.walk(knoten)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == name]


# ── Positivkontrolle: gibt es die geprueften Funktionen ueberhaupt? ──────────
abschnitt("0. Positivkontrolle")
for name in ("chat_sessions_delete_many", "chat_sessions_delete", "_chat_kontext_vergessen"):
    if name not in FUNKTIONEN:
        abbruch("Funktion %s existiert nicht – ohne sie ist jede Pruefung "
                "darunter trivial wahr" % name)
check(True, "alle drei Funktionen im Syntaxbaum gefunden")

SAMMEL = FUNKTIONEN["chat_sessions_delete_many"]
EINZEL = FUNKTIONEN["chat_sessions_delete"]

# ── 1. Der Endpunkt, den das Frontend ruft ──────────────────────────────────
abschnitt("1. Endpunkt")
pfade = dekorator_pfade(SAMMEL)
check(("POST", "/api/chat/sessions/delete") in pfade,
      "POST /api/chat/sessions/delete ist verdrahtet", str(pfade))

# Das Frontend muss GENAU diesen Pfad rufen – zwei Enden, die nie verbunden
# werden, sind der Fehler aus dem Register (Regel in toter Funktion).
CHATJS = (ROOT / "frontend" / "js" / "chat.js").read_text(encoding="utf-8")
check("'/api/chat/sessions/delete'" in CHATJS,
      "chat.js ruft denselben Pfad (beide Enden verbunden)")

# ── 2. Typpruefung VOR der Schleife ─────────────────────────────────────────
abschnitt("2. Typpruefung vor der Schleife")
schleifen = [n for n in ast.walk(SAMMEL) if isinstance(n, (ast.For, ast.AsyncFor))]
check(len(schleifen) >= 1, "es wird ueberhaupt ueber etwas gelaufen",
      "%d Schleifen" % len(schleifen))

wachen = []
for n in ast.walk(SAMMEL):
    if not isinstance(n, ast.If):
        continue
    hat_isinstance_list = any(
        isinstance(c.args[1], ast.Name) and c.args[1].id == "list"
        for c in rufe(n.test, "isinstance") if len(c.args) == 2
    )
    kehrt_zurueck = any(isinstance(k, ast.Return) for k in ast.walk(n))
    if hat_isinstance_list and kehrt_zurueck:
        wachen.append(n)
check(bool(wachen), "es gibt eine isinstance(..., list)-Schranke mit Rueckgabe")
if wachen and schleifen:
    erste_schleife = min(s.lineno for s in schleifen)
    frueheste_wache = min(w.lineno for w in wachen)
    check(frueheste_wache < erste_schleife,
          "⚠ sie steht VOR der ersten Schleife (kein Lauf ueber einen String)",
          "Schranke Zeile %d, Schleife Zeile %d" % (frueheste_wache, erste_schleife))

# Deckel auf die Laenge: EINE Anfrage darf nicht beliebig lange laufen.
deckel = [n for n in ast.walk(SAMMEL)
          if isinstance(n, ast.Compare) and rufe(n.left, "len")]
check(bool(deckel), "die Anzahl je Aufruf ist gedeckelt (len(...)-Vergleich)")
grenze = [n for n in ast.walk(BAUM)
          if isinstance(n, ast.Assign)
          and any(isinstance(t, ast.Name) and t.id == "_CHAT_DELETE_MAX" for t in n.targets)]
check(bool(grenze) and isinstance(grenze[0].value, ast.Constant)
      and isinstance(grenze[0].value.value, int) and grenze[0].value.value > 0,
      "_CHAT_DELETE_MAX ist eine positive ganze Zahl",
      ast.dump(grenze[0].value) if grenze else "fehlt")

# ── 3. Teilerfolge werden benannt ───────────────────────────────────────────
abschnitt("3. Antwortform: Teilerfolge BENANNT, nicht gezaehlt")
schluessel = set()
for d in ast.walk(SAMMEL):
    if isinstance(d, ast.Dict):
        for k in d.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                schluessel.add(k.value)
check("deleted" in schluessel and "failed" in schluessel,
      "die Antwort nennt 'deleted' UND 'failed'", str(sorted(schluessel)))

# ── 4. RAM-Kontext: derselbe Helfer wie bei der Einzelloeschung ─────────────
abschnitt("4. RAM-Kontext der geloeschten Sitzungen")
check(bool(rufe(SAMMEL, "_chat_kontext_vergessen")),
      "die Sammel-Loeschung wirft den RAM-Kontext weg")
check(bool(rufe(EINZEL, "_chat_kontext_vergessen")),
      "die Einzel-Loeschung benutzt DENSELBEN Helfer (eine Stelle, nicht zwei)")
# ⚠ Der Aufruf muss im ERFOLGS-Zweig der Schleife stehen. Steht er daneben,
# wuerde auch fuer eine nicht geloeschte Sitzung der Kontext verworfen.
im_zweig = False
for s in schleifen:
    for n in ast.walk(s):
        if isinstance(n, ast.If) and rufe(n, "_chat_kontext_vergessen"):
            treffer = [c for c in ast.walk(ast.Module(body=n.body, type_ignores=[]))
                       if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                       and c.func.id == "_chat_kontext_vergessen"]
            if treffer:
                im_zweig = True
check(im_zweig, "⚠ und zwar nur im ERFOLGS-Zweig, nicht fuer jede Id")
check(bool(attribut_rufe(SAMMEL, "delete_session")),
      "geloescht wird ueber chat_sessions.delete_session (die Pfadpruefung dort gilt)")

# ── 5. Audit: die Handlung heisst "geloescht" ───────────────────────────────
abschnitt("5. Audit-Beschriftung")
# Die ECHTE Musterliste aus main.py holen (nicht nachbauen): die beiden
# Zuweisungen sind reine Literale und werden hier ausgefuehrt.
koepfe = []
for n in BAUM.body:
    if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in ("_ID", "_ACTION_DETAILS") for t in n.targets):
        # NUR die erste Zuweisung von _ACTION_DETAILS (die zweite kompiliert
        # die Muster und braeuchte re) – erkennbar am Listen-Literal.
        if any(isinstance(t, ast.Name) and t.id == "_ACTION_DETAILS" for t in n.targets) \
                and not isinstance(n.value, (ast.List, ast.Tuple)):
            continue
        koepfe.append(n)
raum = {}
try:
    exec(compile(ast.Module(body=koepfe, type_ignores=[]), "<audit>", "exec"), raum)
except Exception as e:                                          # noqa: BLE001
    abbruch("Musterliste liess sich nicht auslesen: %s" % e)
muster = raum.get("_ACTION_DETAILS") or []
if not muster:
    abbruch("_ACTION_DETAILS leer – ohne Muster ist jede Aussage darunter wertlos")


def label(pfad, methode):
    """Dieselbe Reihenfolge und dasselbe fullmatch wie _action_label."""
    for meth, mus, lab in muster:
        if (meth == "*" or meth == methode) and re.fullmatch(mus, pfad):
            return lab
    return "Aktion"


# Positivkontrolle der Sonde an zwei Pfaden, deren Beschriftung feststeht.
check(label("/api/chat/sessions", "POST") == "Chat · Unterhaltung begonnen",
      "Sonde geeicht: POST /api/chat/sessions -> 'Unterhaltung begonnen'",
      label("/api/chat/sessions", "POST"))
check(label("/api/chat/sessions/abc123", "DELETE") == "Chat · Unterhaltung gelöscht",
      "Sonde geeicht: DELETE einer Sitzung -> 'Unterhaltung gelöscht'",
      label("/api/chat/sessions/abc123", "DELETE"))

lab = label("/api/chat/sessions/delete", "POST")
check("gelöscht" in lab, "die Sammel-Loeschung wird als Loeschung verbucht", lab)
check(lab != "Chat · Unterhaltung begonnen",
      "⚠ sie wird NICHT als 'Unterhaltung begonnen' verbucht", lab)
check(lab != "Aktion", "sie faellt nicht auf das neutrale 'Aktion' zurueck", lab)

print("\n\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (_ok, _fail))
sys.exit(1 if _fail else 0)
