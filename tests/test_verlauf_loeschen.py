#!/usr/bin/env python3
"""Waechter: der Benutzer loescht EINZELNE Eintraege seines Such-Verlaufs.

Bis 2026-08-30 gab es nur "Leeren" – alles oder nichts. Dieser Test sichert die
neue Haelfte: ``DELETE /api/support/history/entry``.

Laeuft OHNE fastapi: der Endpunkt wird per ``ast`` aus ``backend/main.py``
GESCHNITTEN und WIRKLICH AUSGEFUEHRT. Eine reine Quelltext-Suche wuerde die
eigene Begruendung im Docstring mitlesen (im Projekt inzwischen der zehnte
Fall), und ein Import zoege den halben Server nach.

Geprueft wird die REGEL, nicht ein Wortlaut:
  1. es faellt GENAU EIN Eintrag weg, die uebrigen bleiben in ihrer Reihenfolge
  2. der Verlauf FREMDER Benutzer wird nicht angefasst
  3. DER BENUTZER KOMMT AUS DER ANMELDUNG, nie aus dem Rumpf
  4. verglichen wird wie beim Anlegen (getrimmt, Gross/Klein egal) – sonst
     entfernte "loeschen" etwas anderes, als eine gleiche Suche ersetzen wuerde
  5. ein misslungener Schreibvorgang meldet einen FEHLER, kein "ok"
  6. die Oberflaechen von /support, /sap und /vemas bieten den Knopf ueberhaupt an

SANDKASTEN mit Exit 2: zeigt die Verlaufsdatei nicht ins Wegwerf-Verzeichnis,
bricht der Lauf ab – ein Test, der den echten Verlauf der Benutzer loescht,
waere teurer als der Fehler, den er sucht.
"""
import ast
import asyncio
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen "
              "(erst Beschreibung, dann Bedingung)\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


# ── Schnitt aus backend/main.py ────────────────────────────────────────────
MAIN = ROOT / "backend" / "main.py"
QUELL = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)

FUNKTIONEN, ZUWEISUNGEN = {}, {}
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNKTIONEN[n.name] = n
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name):
                ZUWEISUNGEN[t.id] = n

GESCHNITTEN = ["_get_hist_lock", "_load_support_history", "_record_support_history",
               "support_history_get", "support_history_clear",
               "support_history_delete_entry"]
KONSTANTEN = ["_SUPPORT_HIST_MAX", "_support_hist_lock"]

for name in GESCHNITTEN:
    if name not in FUNKTIONEN:
        abbruch("Funktion %s nicht in backend/main.py gefunden" % name)
for name in KONSTANTEN:
    if name not in ZUWEISUNGEN:
        abbruch("Konstante %s nicht in backend/main.py gefunden" % name)


# ── Attrappen ──────────────────────────────────────────────────────────────
class Antwort:
    """Steht fuer JSONResponse – haelt Status und Rumpf zum Nachsehen fest."""

    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class Anfrage:
    """Steht fuer Request. `roh` = Rumpf, der kein JSON ist."""

    def __init__(self, body=None, roh=False):
        self._body = body
        self._roh = roh

    async def json(self):
        if self._roh:
            raise ValueError("kein JSON")
        return self._body


SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis-verlauf-test-"))
HIST_DATEI = SANDKASTEN / "support_history.json"

NS = {
    "json": json, "print": print, "Path": Path, "time": time,
    "threading": threading,
    "Request": Anfrage, "JSONResponse": Antwort,
    "Depends": lambda x: None, "require_auth": None,
    "app": type("App", (), {"get": staticmethod(lambda *a, **k: (lambda f: f)),
                            "delete": staticmethod(lambda *a, **k: (lambda f: f))})(),
    "_SUPPORT_HIST_FILE": HIST_DATEI,
}

# Die Dekoratoren fallen weg: `@app.delete(...)` registriert eine Route, hier
# wird die FUNKTION geprueft. Der Pfad selbst wird weiter unten am Quelltext
# geprueft, damit er nicht unbemerkt wandert.
knoten = []
for k in KONSTANTEN:
    knoten.append(ZUWEISUNGEN[k])
for k in GESCHNITTEN:
    n = FUNKTIONEN[k]
    kopie = ast.parse(ast.unparse(n)).body[0]
    kopie.decorator_list = []
    knoten.append(kopie)
exec(compile(ast.fix_missing_locations(ast.Module(body=knoten, type_ignores=[])),
             "<main-schnitt>", "exec"), NS)

# SANDKASTEN-WAECHTER: sonst schreibt der Test in den echten Datenbestand.
if not str(NS["_SUPPORT_HIST_FILE"]).startswith(str(SANDKASTEN)):
    abbruch("Verlaufsdatei zeigt nicht in den Sandkasten: %s" % NS["_SUPPORT_HIST_FILE"])

loeschen = NS["support_history_delete_entry"]
lesen = NS["support_history_get"]
merken = NS["_record_support_history"]
leeren = NS["support_history_clear"]


_LOOP = asyncio.new_event_loop()


def lauf(coro):
    return _LOOP.run_until_complete(coro)


def stand():
    return json.loads(HIST_DATEI.read_text(encoding="utf-8")) if HIST_DATEI.exists() else {}


def setze(daten):
    HIST_DATEI.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")


DREI = [
    {"query": "Drucker klemmt", "ts": 1756520000, "total": 4},
    {"query": "VPN geht nicht", "ts": 1756510000, "total": 7},
    {"query": "Passwort zuruecksetzen", "ts": 1756500000, "total": 2},
]


# ══ 1. Ein Eintrag, nicht der Verlauf ══════════════════════════════════════
abschnitt("1 – Es faellt genau EIN Eintrag weg")

setze({"anna": [dict(e) for e in DREI]})
antwort = lauf(loeschen(Anfrage({"query": "VPN geht nicht"}), "anna"))
check("Antwort ist 200/ok", antwort.status_code == 200 and antwort.content.get("ok") is True,
      antwort.content)
check("gemeldet wird EIN entfernter Eintrag", antwort.content.get("removed") == 1,
      antwort.content)
rest = stand().get("anna", [])
check("zwei Eintraege bleiben", len(rest) == 2, rest)
check("der angeklickte ist weg", all(e["query"] != "VPN geht nicht" for e in rest))
check("die uebrigen stehen in unveraenderter Reihenfolge",
      [e["query"] for e in rest] == ["Drucker klemmt", "Passwort zuruecksetzen"], rest)
check("die uebrigen Felder sind unangetastet",
      rest[0]["ts"] == 1756520000 and rest[0]["total"] == 4, rest[0])

# ══ 2. Fremde Verlaeufe ════════════════════════════════════════════════════
abschnitt("2 – Fremde Verlaeufe bleiben unberuehrt")

setze({"anna": [dict(e) for e in DREI], "bob": [dict(e) for e in DREI]})
lauf(loeschen(Anfrage({"query": "VPN geht nicht"}), "anna"))
d = stand()
check("beim Anfragenden ist der Eintrag weg", len(d["anna"]) == 2)
check("bei bob steht er unveraendert", len(d["bob"]) == 3,
      [e["query"] for e in d["bob"]])

# Der Benutzer aus dem Rumpf darf NICHTS bewirken – sonst waere der Endpunkt
# ein Weg in fremde Verlaeufe.
setze({"anna": [dict(e) for e in DREI], "bob": [dict(e) for e in DREI]})
lauf(loeschen(Anfrage({"query": "VPN geht nicht", "user": "bob",
                       "username": "bob", "owner": "bob"}), "anna"))
d = stand()
check("ein 'user' im Rumpf trifft NICHT den fremden Verlauf", len(d["bob"]) == 3,
      [e["query"] for e in d["bob"]])
check("...sondern weiter den Angemeldeten", len(d["anna"]) == 2)

# ══ 3. Vergleich wie beim Anlegen ══════════════════════════════════════════
abschnitt("3 – Verglichen wird wie beim Anlegen (getrimmt, Gross/Klein egal)")

setze({"anna": [dict(e) for e in DREI]})
antwort = lauf(loeschen(Anfrage({"query": "  vpn GEHT nicht \n"}), "anna"))
check("Leerraum und Gross/Klein spielen keine Rolle",
      antwort.content.get("removed") == 1 and len(stand()["anna"]) == 2, antwort.content)

# Gegenprobe: dieselbe Schreibweise, die _record_support_history als "dieselbe
# Anfrage" behandelt, muss auch geloescht werden – und nur die.
setze({"anna": []})
merken("anna", "Drucker klemmt", 4)
merken("anna", "VPN geht nicht", 7)
merken("anna", "  drucker KLEMMT  ", 9)   # ersetzt den ersten Eintrag
check("Dedup beim Anlegen greift wie erwartet", len(stand()["anna"]) == 2,
      [e["query"] for e in stand()["anna"]])
lauf(loeschen(Anfrage({"query": "Drucker klemmt"}), "anna"))
check("und genau dieser Eintrag ist loeschbar",
      [e["query"] for e in stand()["anna"]] == ["VPN geht nicht"],
      [e["query"] for e in stand()["anna"]])

# ══ 4. Randfaelle ══════════════════════════════════════════════════════════
abschnitt("4 – Randfaelle, fail-closed")

setze({"anna": [dict(e) for e in DREI]})
for rumpf, was in [({}, "kein query"), ({"query": ""}, "leeres query"),
                   ({"query": "   "}, "nur Leerraum"), ({"query": None}, "query None")]:
    a = lauf(loeschen(Anfrage(rumpf), "anna"))
    check("%s wird mit 400 abgewiesen" % was, a.status_code == 400, a.content)
check("...und der Verlauf ist dabei unangetastet geblieben", len(stand()["anna"]) == 3)

a = lauf(loeschen(Anfrage(None, roh=True), "anna"))
check("unlesbarer Rumpf wird abgewiesen, nicht durchgereicht", a.status_code == 400)

a = lauf(loeschen(Anfrage({"query": "gab es nie"}), "anna"))
check("unbekannte Anfrage: ok mit removed=0",
      a.status_code == 200 and a.content.get("removed") == 0, a.content)
check("...und nichts wurde entfernt", len(stand()["anna"]) == 3)

a = lauf(loeschen(Anfrage({"query": "Drucker klemmt"}), "niemand"))
check("Benutzer ohne Verlauf: ok mit removed=0", a.content.get("removed") == 0)
check("...und fremde Verlaeufe bleiben stehen", len(stand()["anna"]) == 3)

# Letzter Eintrag: der Benutzerschluessel verschwindet mit, sonst waechst die
# Datei mit Karteileichen.
setze({"anna": [{"query": "einziger", "ts": 1, "total": 0}], "bob": [dict(DREI[0])]})
lauf(loeschen(Anfrage({"query": "einziger"}), "anna"))
d = stand()
check("nach dem letzten Eintrag ist der Benutzer aus der Datei", "anna" not in d, d)
check("...und bob steht weiter drin", "bob" in d)

# ══ 5. Ein misslungener Schreibvorgang ist ein FEHLER ══════════════════════
abschnitt("5 – Schreibfehler meldet 500, kein 'ok'")

setze({"anna": [dict(e) for e in DREI]})
_echt = Path.write_text


def _kaputt(self, *a, **k):
    if str(self) == str(HIST_DATEI):
        raise OSError("Platte voll")
    return _echt(self, *a, **k)


Path.write_text = _kaputt
try:
    a = lauf(loeschen(Anfrage({"query": "VPN geht nicht"}), "anna"))
finally:
    Path.write_text = _echt
check("Schreibfehler wird als 500 gemeldet", a.status_code == 500, a.content)
check("...und nicht als Erfolg", a.content.get("ok") is False, a.content)
check("die Datei steht unveraendert da", len(stand()["anna"]) == 3)

# ══ 6. Lesen und Leeren funktionieren weiter ═══════════════════════════════
abschnitt("6 – Der Bestand bleibt heil")

setze({"anna": [dict(e) for e in DREI]})
a = lauf(lesen("anna"))
check("GET liefert weiter alle Eintraege", len(a.content["entries"]) == 3)
lauf(leeren("anna"))
check("Leeren raeumt weiterhin ganz auf", stand().get("anna") in (None, []))

# ══ 7. Der Pfad und die Anmeldung am Endpunkt ══════════════════════════════
abschnitt("7 – Route, Anmeldung, Benutzerherkunft")

# `get_source_segment` einer FunctionDef laesst die Dekoratoren AUSSEN vor –
# deshalb wird der Dekorator einzeln geschnitten.
_ep = FUNKTIONEN["support_history_delete_entry"]
deko = [ast.get_source_segment(QUELL, d) for d in _ep.decorator_list]
quelle = ast.get_source_segment(QUELL, _ep)
check("Route ist DELETE /api/support/history/entry",
      any('app.delete("/api/support/history/entry")' in (d or "") for d in deko), deko)
check("Anmeldung ueber require_auth", "Depends(require_auth)" in quelle)

# DIE EIGENSCHAFT, nicht die Schreibweise: im Rumpf des Endpunkts darf kein
# Benutzername aus dem Request gelesen werden.
rumpf_knoten = ast.parse(ast.unparse(FUNKTIONEN["support_history_delete_entry"])).body[0]
rumpf_knoten.decorator_list = []
schluessel = set()
for n in ast.walk(rumpf_knoten):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
        for arg in n.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                schluessel.add(arg.value)
check("aus dem Rumpf wird NUR 'query' gelesen", schluessel <= {"query"}, sorted(schluessel))
check("der Benutzer ist ein Parameter, kein Rumpf-Feld",
      "user" in [a.arg for a in rumpf_knoten.args.args])

# ══ 8. Die Oberflaechen bieten den Knopf an ════════════════════════════════
abschnitt("8 – /support, /sap und /vemas bieten den Muelleimer an")

FRONT = [
    ("support", "frontend/js/support.js", "frontend/support.html", "sup"),
    ("sap", "frontend/js/sap_portal.js", "frontend/sap.html", "sp"),
    ("vemas", "frontend/js/vemas_portal.js", "frontend/vemas.html", "vm"),
]
for bereich, js, html, p in FRONT:
    q = (ROOT / js).read_text(encoding="utf-8")
    h = (ROOT / html).read_text(encoding="utf-8")
    # Kommentare raus – ein Waechter, der seine eigene Begruendung liest,
    # prueft nichts.
    nur_code = "\n".join(z for z in q.splitlines() if not z.strip().startswith("//"))
    check("%s: der Verlauf zeichnet einen Loeschknopf (%s-hist-del)" % (bereich, p),
          "%s-hist-del" % p in nur_code)
    check("%s: das Symbol kommt aus icons.js (kein Emoji)" % bereich,
          "JarvisIcons.trash()" in nur_code and "🗑" not in nur_code)
    check("%s: der Klick stoppt die Weitergabe (Zeile darunter + Panel)" % bereich,
          "stopPropagation" in nur_code)
    check("%s: CSS fuer den Knopf vorhanden" % bereich, ".%s-hist-del" % p in h)
    # min-width: 0 – ohne das schiebt eine lange Anfrage den Knopf aus dem
    # Panel. GEPRUEFT WIRD DIE REGEL SELBST, nicht das Vorkommen irgendwo in
    # der Datei: die erste Fassung dieses Waechters suchte "min-width: 0" im
    # ganzen Dokument und blieb in der Gegenprobe gruen.
    import re as _re
    m = _re.search(r"\.%s-hist-text\s*\{([^}]*)\}" % p, h)
    check("%s: es gibt eine Regel .%s-hist-text" % (bereich, p), m is not None)
    check("%s: und sie setzt min-width: 0" % bereich,
          m is not None and _re.search(r"min-width:\s*0", m.group(1)) is not None,
          m.group(1) if m else "")
    m2 = _re.search(r"\.%s-hist-item\s*\{([^}]*)\}" % p, h)
    check("%s: der Eintrag ist eine Flex-Zeile (Text + Knopf nebeneinander)" % bereich,
          m2 is not None and "display: flex" in m2.group(1),
          m2.group(1) if m2 else "")

check("nur /support ruft den Server (die beiden anderen liegen im Browser)",
      "/api/support/history/entry" in (ROOT / FRONT[0][1]).read_text(encoding="utf-8")
      and "/api/support/history/entry" not in (ROOT / FRONT[1][1]).read_text(encoding="utf-8")
      and "/api/support/history/entry" not in (ROOT / FRONT[2][1]).read_text(encoding="utf-8"))

# ── Aufraeumen ─────────────────────────────────────────────────────────────
import shutil
_LOOP.close()
shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n\033[1mErgebnis: %d/%d\033[0m%s" % (ok, ok + fail,
      ("  ·  \033[31m%d FEHLER\033[0m" % fail) if fail else ""))
sys.exit(1 if fail else 0)
